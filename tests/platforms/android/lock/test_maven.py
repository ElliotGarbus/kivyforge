"""Maven channel resolution (android/02 channel 4) — hermetic via fake backend."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from kivyforge.config.model import AndroidGradleConfig
from kivyforge.platforms.android.lock import maven as maven_mod
from kivyforge.platforms.android.lock.maven import (
    GradleMavenResolver,
    MavenResolverError,
    ScratchProjectResolver,
    parse_verification_metadata,
    resolve_gradle_pins,
)
from kivyforge.platforms.android.lock.model import (
    GradleArtifact,
    GradleResolvedModule,
)


def _streaming(fake_run):
    """Adapt a ``subprocess.run``-shaped fake to the Gradle step's streaming seam."""

    def run_streaming(cmd, *, on_segment, cwd=None, on_quiet=None, **_kw):
        result = fake_run(
            cmd, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
        return result.returncode, "\n".join(
            p for p in (result.stdout, result.stderr) if isinstance(p, str)
        )

    return run_streaming


class FakeGradle:
    def __init__(self, modules):
        self.modules = modules
        self.calls = 0

    def resolve(self, gradle, *, offline=False):
        self.calls += 1
        return self.modules


class TestResolveGradlePins:
    def test_no_deps_skips_gradle(self):
        backend = FakeGradle(())
        pins = resolve_gradle_pins(AndroidGradleConfig(), resolver=backend)
        assert not pins.declared
        assert backend.calls == 0  # never invoked without coordinates

    def test_declared_deps_resolved(self):
        modules = (
            GradleResolvedModule(
                coordinate="com.google.zxing:core:3.5.3",
                artifacts=(GradleArtifact(name="core-3.5.3.jar", sha256="a" * 64),),
            ),
        )
        backend = FakeGradle(modules)
        config = AndroidGradleConfig(
            dependencies=("com.google.zxing:core:3.5.3",),
            repositories=("https://maven.example/releases",),
        )
        pins = resolve_gradle_pins(config, resolver=backend)
        assert pins.declared
        assert pins.dependencies == ("com.google.zxing:core:3.5.3",)
        assert pins.repositories == ("https://maven.example/releases",)
        assert pins.resolved == modules
        assert backend.calls == 1

    def test_declared_boms_recorded(self):
        config = AndroidGradleConfig(
            dependencies=("com.google.firebase:firebase-analytics",),
            platforms=("com.google.firebase:firebase-bom:34.0.0",),
        )
        pins = resolve_gradle_pins(config, resolver=FakeGradle(()))
        assert pins.platforms == ("com.google.firebase:firebase-bom:34.0.0",)

    def test_protocol_shape(self):
        # A fake satisfies the protocol without inheritance.
        backend: GradleMavenResolver = FakeGradle(())
        assert backend.resolve(AndroidGradleConfig()) == ()


_SAMPLE_METADATA = textwrap.dedent(
    """\
    <?xml version="1.0" encoding="UTF-8"?>
    <verification-metadata xmlns="https://schema.gradle.org/dependency-verification">
      <components>
        <component group="com.google.zxing" name="core" version="3.5.3">
          <artifact name="core-3.5.3.jar">
            <sha256 value="b" />
          </artifact>
          <artifact name="core-3.5.3.pom">
            <sha256 value="a" />
          </artifact>
        </component>
        <component group="androidx.annotation" name="annotation" version="1.7.0">
          <artifact name="annotation-1.7.0.aar">
            <sha256 value="c" />
          </artifact>
          <artifact name="no-hash.jar" />
        </component>
      </components>
    </verification-metadata>
    """
)


class TestParseVerificationMetadata:
    def test_parses_components_sorted_by_coordinate(self):
        modules = parse_verification_metadata(_SAMPLE_METADATA)
        assert [m.coordinate for m in modules] == [
            "androidx.annotation:annotation:1.7.0",
            "com.google.zxing:core:3.5.3",
        ]

    def test_artifacts_sorted_by_name_within_component(self):
        modules = parse_verification_metadata(_SAMPLE_METADATA)
        zxing = next(m for m in modules if "zxing" in m.coordinate)
        assert [a.name for a in zxing.artifacts] == [
            "core-3.5.3.jar",
            "core-3.5.3.pom",
        ]

    def test_artifact_without_sha256_value_is_dropped(self):
        modules = parse_verification_metadata(_SAMPLE_METADATA)
        annotation = next(m for m in modules if "annotation" in m.coordinate)
        assert [a.name for a in annotation.artifacts] == ["annotation-1.7.0.aar"]

    def test_invalid_xml_raises(self):
        with pytest.raises(MavenResolverError, match="could not parse"):
            parse_verification_metadata("<not-xml")


class TestScratchProjectResolverCommandSelection:
    def test_explicit_executable_used_verbatim(self, tmp_path):
        resolver = ScratchProjectResolver(gradle_executable="/opt/gradle/bin/gradle")
        assert resolver._gradle_command(tmp_path) == ["/opt/gradle/bin/gradle"]

    def test_standalone_gradle_on_path_preferred(self, tmp_path, monkeypatch):
        monkeypatch.setattr(maven_mod.shutil, "which", lambda name: "/usr/bin/gradle")
        resolver = ScratchProjectResolver()
        assert resolver._gradle_command(tmp_path) == ["/usr/bin/gradle"]

    def test_vendored_wrapper_staged_when_no_standalone(self, tmp_path, monkeypatch):
        monkeypatch.setattr(maven_mod.shutil, "which", lambda name: None)
        resolver = ScratchProjectResolver()
        cmd = resolver._gradle_command(tmp_path)
        assert (tmp_path / "gradle" / "wrapper" / "gradle-wrapper.jar").is_file()
        assert (tmp_path / "gradle" / "wrapper" / "gradle-wrapper.properties").is_file()
        expected_script = "gradlew.bat" if os.name == "nt" else "gradlew"
        assert cmd == [str(tmp_path / expected_script)]
        assert Path(cmd[0]).is_file()

    def test_missing_vendored_wrapper_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(maven_mod.shutil, "which", lambda name: None)
        monkeypatch.setattr(
            ScratchProjectResolver, "_WRAPPER_DIR", tmp_path / "no-such-dir"
        )
        resolver = ScratchProjectResolver()
        with pytest.raises(MavenResolverError, match="neither a standalone"):
            resolver._gradle_command(tmp_path / "root")


class TestScratchProjectResolverResolve:
    def _config(self):
        return AndroidGradleConfig(
            dependencies=("com.google.zxing:core:3.5.3",),
            repositories=("https://maven.example/releases",),
        )

    def test_success_writes_project_and_parses_metadata(self, tmp_path, monkeypatch):
        captured = {}

        def fake_run(cmd, cwd, capture_output, text, stdin=None):
            captured["cmd"] = cmd
            captured["cwd"] = Path(cwd)
            settings = (Path(cwd) / "settings.gradle").read_text(encoding="utf-8")
            build = (Path(cwd) / "build.gradle").read_text(encoding="utf-8")
            captured["settings"] = settings
            captured["build"] = build
            metadata_dir = Path(cwd) / "gradle"
            metadata_dir.mkdir(parents=True, exist_ok=True)
            (metadata_dir / "verification-metadata.xml").write_text(
                _SAMPLE_METADATA, encoding="utf-8"
            )
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        monkeypatch.setattr(maven_mod, "run_streaming", _streaming(fake_run))
        resolver = ScratchProjectResolver(gradle_executable="fake-gradle")
        modules = resolver.resolve(self._config())

        assert len(modules) == 2
        assert "maven.example/releases" in captured["settings"]
        assert "com.google.zxing:core:3.5.3" in captured["build"]
        assert "--write-verification-metadata" in captured["cmd"]
        assert "--offline" not in captured["cmd"]

    def test_boms_imported_as_platforms_before_dependencies(self, monkeypatch):
        captured = {}

        def fake_run(cmd, cwd, capture_output, text, stdin=None):
            captured["build"] = (Path(cwd) / "build.gradle").read_text(encoding="utf-8")
            metadata_dir = Path(cwd) / "gradle"
            metadata_dir.mkdir(parents=True, exist_ok=True)
            (metadata_dir / "verification-metadata.xml").write_text(
                _SAMPLE_METADATA, encoding="utf-8"
            )
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(maven_mod, "run_streaming", _streaming(fake_run))
        config = AndroidGradleConfig(
            dependencies=("com.google.firebase:firebase-analytics",),
            platforms=("com.google.firebase:firebase-bom:34.0.0",),
        )
        ScratchProjectResolver(gradle_executable="fake-gradle").resolve(config)
        build = captured["build"]
        bom = "kivyforgeLock platform('com.google.firebase:firebase-bom:34.0.0')"
        dep = "kivyforgeLock 'com.google.firebase:firebase-analytics'"
        assert bom in build and dep in build
        assert build.index(bom) < build.index(dep)

    def test_offline_flag_appended(self, tmp_path, monkeypatch):
        def fake_run(cmd, cwd, capture_output, text, stdin=None):
            metadata_dir = Path(cwd) / "gradle"
            metadata_dir.mkdir(parents=True, exist_ok=True)
            (metadata_dir / "verification-metadata.xml").write_text(
                _SAMPLE_METADATA, encoding="utf-8"
            )
            return subprocess.CompletedProcess(cmd, 0)

        seen_cmds = []

        def recording_run(cmd, cwd, capture_output, text, stdin=None):
            seen_cmds.append(cmd)
            return fake_run(cmd, cwd, capture_output, text)

        monkeypatch.setattr(maven_mod, "run_streaming", _streaming(recording_run))
        resolver = ScratchProjectResolver(gradle_executable="fake-gradle")
        resolver.resolve(self._config(), offline=True)
        assert "--offline" in seen_cmds[0]

    def test_nonzero_exit_raises_with_stderr(self, monkeypatch):
        def fake_run(cmd, cwd, capture_output, text, stdin=None):
            return subprocess.CompletedProcess(
                cmd, 1, stdout="", stderr="could not resolve dependency"
            )

        monkeypatch.setattr(maven_mod, "run_streaming", _streaming(fake_run))
        resolver = ScratchProjectResolver(gradle_executable="fake-gradle")
        with pytest.raises(MavenResolverError, match="could not resolve dependency"):
            resolver.resolve(self._config())

    def test_missing_metadata_file_raises(self, monkeypatch):
        def fake_run(cmd, cwd, capture_output, text, stdin=None):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(maven_mod, "run_streaming", _streaming(fake_run))
        resolver = ScratchProjectResolver(gradle_executable="fake-gradle")
        with pytest.raises(MavenResolverError, match="wrote no verification"):
            resolver.resolve(self._config())


class TestProgress:
    """The Gradle step is quiet by nature; say what it is doing (#84)."""

    def test_the_step_is_announced(self):
        lines = []
        gradle = AndroidGradleConfig(dependencies=("com.google.zxing:core:3.5.3",))
        resolve_gradle_pins(gradle, resolver=FakeGradle(()), on_progress=lines.append)
        assert lines and "1 Maven dependencies with Gradle" in lines[0]

    def test_nothing_to_announce_without_dependencies(self):
        lines = []
        resolve_gradle_pins(AndroidGradleConfig(), on_progress=lines.append)
        assert lines == []

    def test_wrapper_download_and_silence_are_reported(self):
        lines = []
        resolver = ScratchProjectResolver(on_progress=lines.append)
        shown = resolver._announce_wrapper_download(
            "Downloading https://services.gradle.org/distributions/gradle-8.11.1-bin.zip"
        )
        assert shown is True
        assert resolver._announce_wrapper_download("> Task :x") is False
        resolver._still_resolving(30)
        assert lines == [
            "[lock] Gradle: Downloading "
            "https://services.gradle.org/distributions/gradle-8.11.1-bin.zip",
            "[lock] Gradle: still resolving (30s)",
        ]

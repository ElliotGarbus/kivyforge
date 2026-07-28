"""Android lock engine unit tests (android/02) — hermetic, fake-injected."""

from __future__ import annotations

import dataclasses
import shutil
import tempfile
from pathlib import Path

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.lock.model import LockedPackage, LockedWheel
from kivyforge.platforms.android.lock import builder as builder_mod
from kivyforge.platforms.android.lock import reader, writer
from kivyforge.platforms.android.lock.builder import BuildError, build_lockfile
from kivyforge.platforms.android.lock.maven import parse_verification_metadata
from kivyforge.platforms.android.lock.model import (
    AndroidLockfile,
    GradleArtifact,
    GradlePins,
    GradleResolvedModule,
    LockedAndroidLib,
    LockedIncludeFile,
    PythonAndroidRuntime,
)
from kivyforge.platforms.android.lock.python_meta import (
    PythonAndroidError,
    PythonAndroidInfo,
)
from kivyforge.platforms.android.lock.resolver import (
    ResolvedPackage,
    ResolvedWheel,
    ResolverError,
)

PYPROJECT = """
[project]
name = "lockapp"
version = "1.0.0"
dependencies = ["pyjnius"]

[tool.kivy]
app_dir = "src"

[tool.kivy.android]
schema_version = 1
package = "org.example.lockapp"

[tool.kivy.android.python]
version = "3.14.6"
"""


class FakeProvider:
    def __init__(self, min_api: int = 24):
        self.min_api = min_api

    def get(self, version, abi, *, offline=False):
        arch = "aarch64" if abi == "arm64_v8a" else "x86_64"
        return PythonAndroidInfo(
            version=version,
            abi=abi,
            url=f"https://example.org/python-{version}-{arch}.tar.gz",
            sha256="0" * 64,
            min_api=self.min_api,
        )


class FakeResolver:
    def __init__(self, packages):
        self.packages = packages
        self.calls = []

    def resolve(self, requirements, **kwargs):
        self.calls.append((tuple(requirements), kwargs))
        return self.packages


def _pkg(name="pyjnius", version="1.7.0", abis=("arm64_v8a", "x86_64"), api=24):
    wheels = [
        ResolvedWheel(
            filename=f"{name}-{version}-cp314-cp314-android_{api}_{abi}.whl",
            url=f"https://files.example/{name}-{version}-android_{api}_{abi}.whl",
            sha256="a" * 64,
        )
        for abi in abis
    ]
    return ResolvedPackage(name=name, version=version, wheels=wheels)


def _config(text=PYPROJECT):
    return load_config_from_text(text, require_ios=False, require_android=True)


def _build(config_text=PYPROJECT, packages=None, min_api=24, **kwargs):
    return build_lockfile(
        _config(config_text),
        config_text,
        project_root=Path.cwd(),
        resolver=FakeResolver(packages if packages is not None else [_pkg()]),
        python_provider=FakeProvider(min_api=min_api),
        **kwargs,
    )


class TestBuilder:
    def test_minimal_lock(self):
        lock = _build()
        assert [r.abi for r in lock.python_android] == ["arm64_v8a", "x86_64"]
        assert lock.kivy_generation == 2
        assert lock.tool_kivy_android_schema_version == 1
        pkg = lock.packages[0]
        assert pkg.direct_requirement is True
        assert len(pkg.wheels) == 2

    def test_find_links_diagnostics_talk_about_android(self, tmp_path):
        """The shared find_links helpers default to platform="ios"; an Android
        caller that forgets to pass its own platform tells the user to build
        iOS wheels."""
        text = PYPROJECT.replace(
            "[tool.kivy.android.python]",
            'find_links = ["wheelhouse"]\n\n[tool.kivy.android.python]',
        )
        with pytest.raises(BuildError) as excinfo:
            build_lockfile(
                _config(text),
                text,
                project_root=tmp_path,  # no wheelhouse/ here
                resolver=FakeResolver([_pkg()]),
                python_provider=FakeProvider(),
            )
        message = str(excinfo.value)
        assert "[tool.kivy.android].find_links" in message
        assert "ios" not in message

    def test_min_sdk_below_runtime_floor_rejected(self):
        with pytest.raises(BuildError, match="minimum API"):
            _build(min_api=26)

    def test_missing_abi_rejected(self):
        with pytest.raises(BuildError, match="missing Android wheel slice"):
            _build(packages=[_pkg(abis=("arm64_v8a",))])

    def test_lower_tag_api_accepted_as_floor(self):
        # android_21 wheels satisfy min_sdk = 24 (tag is a floor, android/01).
        lock = _build(packages=[_pkg(api=21)])
        assert len(lock.packages[0].wheels) == 2

    def test_higher_tag_api_not_counted(self):
        with pytest.raises(BuildError, match="missing Android wheel slice"):
            _build(packages=[_pkg(api=28)])

    def test_pure_python_single_wheel_complete(self):
        pure = ResolvedPackage(
            name="certifi",
            version="2026.6.17",
            wheels=[
                ResolvedWheel(
                    filename="certifi-2026.6.17-py3-none-any.whl",
                    url="https://files.example/certifi-2026.6.17-py3-none-any.whl",
                    sha256="b" * 64,
                )
            ],
        )
        lock = _build(packages=[_pkg(), pure])
        assert len(lock.packages) == 2

    def test_exclude_prunes_transitives_but_not_direct(self):
        text = PYPROJECT.replace(
            'package = "org.example.lockapp"',
            'package = "org.example.lockapp"\nexclude = ["docutils", "pyjnius"]',
        )
        docutils = ResolvedPackage(
            name="docutils",
            version="0.21",
            wheels=[
                ResolvedWheel(
                    filename="docutils-0.21-py3-none-any.whl",
                    url="https://files.example/docutils-0.21-py3-none-any.whl",
                    sha256="c" * 64,
                )
            ],
        )
        lock = _build(config_text=text, packages=[_pkg(), docutils])
        names = [p.name for p in lock.packages]
        # docutils pruned; pyjnius survives (direct requirements win).
        assert names == ["pyjnius"]

    def test_include_files_hashed_and_dir_expanded(self, tmp_path):
        (tmp_path / "src").mkdir()
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "a.json").write_text("{}", encoding="utf-8")
        (cfg_dir / "sub").mkdir()
        (cfg_dir / "sub" / "b.xml").write_text("<x/>", encoding="utf-8")
        text = PYPROJECT.replace(
            "[tool.kivy.android.python]",
            "[[tool.kivy.android.include_files]]\n"
            'dest = "app"\n'
            'sources = ["config"]\n\n'
            "[tool.kivy.android.python]",
        )
        config = load_config_from_text(
            text,
            require_ios=False,
            require_android=True,
            project_root=tmp_path,
        )
        lock = build_lockfile(
            config,
            text,
            project_root=tmp_path,
            resolver=FakeResolver([_pkg()]),
            python_provider=FakeProvider(),
        )
        sources = [p.source for p in lock.include_files]
        assert sources == ["config/a.json", "config/sub/b.xml"]
        assert all(len(p.sha256) == 64 for p in lock.include_files)


class TestBuilderErrorPaths:
    """Domain errors from each collaborator surface as an actionable BuildError."""

    def test_no_android_table_rejected(self):
        text = "[project]\nname = 'x'\nversion = '1'\n[tool.kivy]\napp_dir = 'src'\n"
        config = load_config_from_text(text, require_ios=False, require_android=False)
        with pytest.raises(BuildError, match=r"no \[tool\.kivy\.android\] table"):
            build_lockfile(config, text, project_root=Path.cwd())

    def test_resolver_error_without_find_links_wrapped_plainly(self):
        class ErrorResolver:
            def resolve(self, *a, **kw):
                raise ResolverError("boom")

        with pytest.raises(BuildError, match="boom"):
            build_lockfile(
                _config(),
                PYPROJECT,
                project_root=Path.cwd(),
                resolver=ErrorResolver(),
                python_provider=FakeProvider(),
            )

    def test_resolver_error_with_find_links_gets_hint(self, tmp_path):
        wheelhouse = tmp_path / "wheelhouse"
        wheelhouse.mkdir()
        (wheelhouse / "foo-1.0-py3-none-any.whl").write_bytes(b"x")
        text = PYPROJECT.replace(
            "[tool.kivy.android.python]",
            'find_links = ["wheelhouse"]\n\n[tool.kivy.android.python]',
        )

        class ErrorResolver:
            def resolve(self, *a, **kw):
                raise ResolverError("No matching distribution found for pyjnius")

        with pytest.raises(BuildError, match="find_links check"):
            build_lockfile(
                _config(text),
                text,
                project_root=tmp_path,
                resolver=ErrorResolver(),
                python_provider=FakeProvider(),
            )

    def test_archive_resolver_error_wrapped(self, monkeypatch):
        from kivyforge.platforms.android.lock.archives import ArchiveResolverError

        def boom(*a, **kw):
            raise ArchiveResolverError("bad aar")

        monkeypatch.setattr(builder_mod, "resolve_android_libs", boom)
        with pytest.raises(BuildError, match="bad aar"):
            _build()

    def test_maven_resolver_error_wrapped(self, monkeypatch):
        from kivyforge.platforms.android.lock.maven import MavenResolverError

        def boom(*a, **kw):
            raise MavenResolverError("bad maven graph")

        monkeypatch.setattr(builder_mod, "resolve_gradle_pins", boom)
        with pytest.raises(BuildError, match="bad maven graph"):
            _build()

    def test_python_provider_error_wrapped(self):
        class ErrorProvider:
            def get(self, version, abi, *, offline=False):
                raise PythonAndroidError("network down")

        with pytest.raises(BuildError, match="network down"):
            build_lockfile(
                _config(),
                PYPROJECT,
                project_root=Path.cwd(),
                resolver=FakeResolver([_pkg()]),
                python_provider=ErrorProvider(),
            )


class TestIncludeFilesEdgeCases:
    def _single_file_config(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "google-services.json").write_text("{}", encoding="utf-8")
        text = PYPROJECT.replace(
            "[tool.kivy.android.python]",
            "[[tool.kivy.android.include_files]]\n"
            'dest = "app"\n'
            'sources = ["google-services.json"]\n\n'
            "[tool.kivy.android.python]",
        )
        return text

    def test_single_file_source_hashed(self, tmp_path):
        text = self._single_file_config(tmp_path)
        config = load_config_from_text(
            text, require_ios=False, require_android=True, project_root=tmp_path
        )
        lock = build_lockfile(
            config,
            text,
            project_root=tmp_path,
            resolver=FakeResolver([_pkg()]),
            python_provider=FakeProvider(),
        )
        assert [p.source for p in lock.include_files] == ["google-services.json"]

    def test_missing_source_rejected(self, tmp_path):
        # The loader itself already validates include_files sources exist at
        # parse time; _hash_include_files' own check is a defensive second
        # line of defense, exercised directly here (a hand-built AndroidConfig
        # bypasses the loader's earlier, stricter guard).
        from kivyforge.config.model import AndroidConfig, AndroidIncludeFile

        android = AndroidConfig(
            schema_version=1,
            package="org.example.x",
            include_files=(AndroidIncludeFile(dest="app", sources=("nope.json",)),),
        )
        with pytest.raises(BuildError, match="does not exist"):
            builder_mod._hash_include_files(android, tmp_path)


class TestWheelSourceNormalization:
    _SINGLE_ABI = 'abis = ["arm64_v8a"]\n\n[tool.kivy.android.python]'

    def test_sha256_computed_from_local_wheel_path(self, tmp_path):
        wheel = tmp_path / "pyjnius-1.7.0-cp314-cp314-android_24_arm64_v8a.whl"
        wheel.write_bytes(b"fake-wheel-bytes")
        text = PYPROJECT.replace("[tool.kivy.android.python]", self._SINGLE_ABI)
        pkg = ResolvedPackage(
            name="pyjnius",
            version="1.7.0",
            wheels=[ResolvedWheel(filename=wheel.name, url=str(wheel), sha256="")],
        )
        lock = build_lockfile(
            _config(text),
            text,
            project_root=tmp_path,
            resolver=FakeResolver([pkg]),
            python_provider=FakeProvider(),
        )
        assert len(lock.packages[0].wheels[0].sha256) == 64

    def test_missing_sha256_without_local_path_rejected(self, tmp_path):
        text = PYPROJECT.replace("[tool.kivy.android.python]", self._SINGLE_ABI)
        pkg = ResolvedPackage(
            name="pyjnius",
            version="1.7.0",
            wheels=[
                ResolvedWheel(
                    filename="pyjnius-1.7.0-cp314-cp314-android_24_arm64_v8a.whl",
                    url="https://files.example/pyjnius.whl",
                    sha256="",
                )
            ],
        )
        with pytest.raises(BuildError, match="could not determine SHA-256"):
            build_lockfile(
                _config(text),
                text,
                project_root=tmp_path,
                resolver=FakeResolver([pkg]),
                python_provider=FakeProvider(),
            )

    def test_wheel_outside_find_links_scope_rejected(self, tmp_path):
        outside = Path(tempfile.mkdtemp())
        try:
            wheel = outside / "pyjnius-1.7.0-cp314-cp314-android_24_arm64_v8a.whl"
            wheel.write_bytes(b"x")
            text = PYPROJECT.replace("[tool.kivy.android.python]", self._SINGLE_ABI)
            pkg = ResolvedPackage(
                name="pyjnius",
                version="1.7.0",
                wheels=[
                    ResolvedWheel(filename=wheel.name, url=str(wheel), sha256="a" * 64)
                ],
            )
            with pytest.raises(BuildError, match="outside the allowed"):
                build_lockfile(
                    _config(text),
                    text,
                    project_root=tmp_path,
                    resolver=FakeResolver([pkg]),
                    python_provider=FakeProvider(),
                )
        finally:
            shutil.rmtree(outside, ignore_errors=True)


class TestReqName:
    def test_valid_requirement_returns_bare_name(self):
        assert builder_mod._req_name("pyjnius>=1.7,<1.8") == "pyjnius"

    def test_invalid_requirement_falls_back_to_raw_string(self):
        garbage = "not a valid requirement!!"
        assert builder_mod._req_name(garbage) == garbage


class TestDiffSummary:
    def test_added_removed_and_changed_packages(self):
        old = _sample_lockfile()
        new_pkgs = (
            dataclasses.replace(old.packages[0], version="1.7.1"),
            LockedPackage(
                name="certifi",
                version="2026.6.17",
                wheels=(
                    LockedWheel(
                        name="certifi-2026.6.17-py3-none-any.whl",
                        url="https://files.example/certifi.whl",
                        sha256="9" * 64,
                    ),
                ),
            ),
        )
        new = dataclasses.replace(old, packages=new_pkgs)
        summary = "\n".join(builder_mod.diff_summary(old, new))
        assert "+ certifi 2026.6.17 (added)" in summary
        assert "~ pyjnius: 1.7.0 -> 1.7.1" in summary

    def test_removed_package_and_runtime_change(self):
        old = _sample_lockfile()
        new = dataclasses.replace(
            old,
            packages=(),
            python_android=tuple(
                dataclasses.replace(r, version="3.14.7") for r in old.python_android
            ),
        )
        summary = "\n".join(builder_mod.diff_summary(old, new))
        assert "- pyjnius 1.7.0 (removed)" in summary
        assert "python.org Android runtime" in summary

    def test_no_changes_is_empty(self):
        old = _sample_lockfile()
        assert builder_mod.diff_summary(old, old) == []


def _sample_lockfile() -> AndroidLockfile:
    return AndroidLockfile(
        requires_python=">=3.14",
        packages=(
            LockedPackage(
                name="pyjnius",
                version="1.7.0",
                wheels=(
                    LockedWheel(
                        name="pyjnius-1.7.0-cp314-cp314-android_24_arm64_v8a.whl",
                        path="wheels/pyjnius-1.7.0-cp314-cp314-android_24_arm64_v8a.whl",
                        sha256="a" * 64,
                    ),
                    LockedWheel(
                        name="pyjnius-1.7.0-cp314-cp314-android_24_x86_64.whl",
                        url="https://files.example/pyjnius.whl",
                        sha256="b" * 64,
                    ),
                ),
                direct_requirement=True,
            ),
        ),
        python_android=(
            PythonAndroidRuntime(
                version="3.14.6",
                abi="arm64_v8a",
                url="https://example.org/py-aarch64.tar.gz",
                sha256="c" * 64,
                min_api=24,
            ),
            PythonAndroidRuntime(
                version="3.14.6",
                abi="x86_64",
                url="https://example.org/py-x86_64.tar.gz",
                sha256="d" * 64,
                min_api=24,
            ),
        ),
        kivyforge_version="3.0.0.dev0",
        generated_at="2026-07-24T00:00:00Z",
        pyproject_sha256="e" * 64,
        tool_kivy_android_schema_version=1,
        kivy_generation=2,
        android_libs=(
            LockedAndroidLib(
                name="Sdk",
                kind="aar",
                version="3.1.0",
                url="https://vendor.example/Sdk-3.1.0.aar",
                sha256="f" * 64,
            ),
        ),
        gradle=GradlePins(
            dependencies=("com.google.zxing:core:3.5.3",),
            repositories=(),
            resolved=(
                GradleResolvedModule(
                    coordinate="com.google.zxing:core:3.5.3",
                    artifacts=(GradleArtifact(name="core-3.5.3.jar", sha256="1" * 64),),
                ),
            ),
        ),
        include_files=(
            LockedIncludeFile(
                source="config/google-services.json", dest="app", sha256="2" * 64
            ),
        ),
    )


class TestWriterReader:
    def test_round_trip(self):
        lock = _sample_lockfile()
        text = writer.dumps(lock)
        parsed = reader.loads(text)
        assert builder_mod.semantic_equal(parsed, lock)
        assert parsed == lock  # full equality incl. generated_at

    def test_deterministic_output(self):
        lock = _sample_lockfile()
        assert writer.dumps(lock) == writer.dumps(lock)

    def test_reader_rejects_future_lock_version(self):
        text = writer.dumps(_sample_lockfile()).replace(
            'lock-version = "1.0"', 'lock-version = "2.0"'
        )
        with pytest.raises(reader.LockError, match="newer"):
            reader.loads(text)

    def test_reader_rejects_missing_runtime(self):
        text = "\n".join(
            line
            for line in writer.dumps(_sample_lockfile()).splitlines()
            if "python_android" not in line
            and not line.startswith(("version =", "abi =", "min_api ="))
        )
        with pytest.raises(reader.LockError):
            reader.loads(text)

    def test_reader_rejects_bad_toml(self):
        with pytest.raises(reader.LockError, match="not valid TOML"):
            reader.loads("this is not toml [")


class TestMavenParser:
    XML = """<?xml version="1.0" encoding="UTF-8"?>
<verification-metadata xmlns="https://schema.gradle.org/dependency-verification">
   <configuration><verify-metadata>true</verify-metadata></configuration>
   <components>
      <component group="com.google.zxing" name="core" version="3.5.3">
         <artifact name="core-3.5.3.jar">
            <sha256 value="deadbeef"/>
         </artifact>
         <artifact name="core-3.5.3.pom">
            <sha256 value="cafebabe"/>
         </artifact>
      </component>
      <component group="androidx.work" name="work-runtime" version="2.9.1">
         <artifact name="work-runtime-2.9.1.aar">
            <sha256 value="0123abcd"/>
         </artifact>
      </component>
   </components>
</verification-metadata>
"""

    def test_parse(self):
        modules = parse_verification_metadata(self.XML)
        assert [m.coordinate for m in modules] == [
            "androidx.work:work-runtime:2.9.1",
            "com.google.zxing:core:3.5.3",
        ]
        zxing = modules[1]
        assert [a.name for a in zxing.artifacts] == [
            "core-3.5.3.jar",
            "core-3.5.3.pom",
        ]
        assert zxing.artifacts[0].sha256 == "deadbeef"

    def test_parse_rejects_malformed(self):
        from kivyforge.platforms.android.lock.maven import MavenResolverError

        with pytest.raises(MavenResolverError):
            parse_verification_metadata("<unclosed")

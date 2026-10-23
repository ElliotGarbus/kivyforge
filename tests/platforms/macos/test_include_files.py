"""``[[tool.kivy.macos.include_files]]`` (include-files-proposal §4.5, #170)."""

from __future__ import annotations

import dataclasses
import subprocess
import sys

import pytest

from kivyforge.artifacts import include_files
from kivyforge.cli.lock import _lock_ops
from kivyforge.config import ConfigError
from kivyforge.config.loader import load_config_from_text
from kivyforge.lock.inputs import lock_inputs_sha256
from kivyforge.lock.model import LockedIncludeFile
from kivyforge.lock.wheelruntime.serialize import dumps, loads
from kivyforge.platforms.macos import AppBundleError, bundle
from kivyforge.platforms.macos.includes import check_includes, verify_bundle
from kivyforge.report import diagnostics, exit_codes
from tests.platforms.macos.test_bundle import _PYPROJECT, _lock, _project


def _include(dest: str, *sources: str) -> str:
    listed = ", ".join(f"'{s}'" for s in sources)
    return f"[[tool.kivy.macos.include_files]]\ndest='{dest}'\nsources=[{listed}]\n"


def _config(extra: str = ""):
    text = _PYPROJECT.replace(
        "[tool.kivy.macos.python]", extra + "[tool.kivy.macos.python]"
    )
    return load_config_from_text(text, require_ios=False, require_macos=True)


@pytest.fixture
def root(tmp_path):
    (tmp_path / "proj").mkdir()
    root = _project(tmp_path / "proj")
    (root / "data").mkdir()
    (root / "data" / "words.txt").write_text("hello")
    (root / "data" / "nested").mkdir()
    (root / "data" / "nested" / "more.txt").write_text("more")
    return root


def _pinned(config, root):
    return dataclasses.replace(
        _lock(),
        include_files=tuple(
            include_files.hash_pins(config.macos_required.include_files, root)
        ),
    )


class TestConfig:
    @pytest.mark.parametrize(
        "dest", ["Resources", "Resources/data", "SharedSupport", "Resources/./x"]
    )
    def test_resources_and_shared_support_are_accepted(self, dest):
        [entry] = _config(_include(dest, "data")).macos_required.include_files
        assert entry.dest == dest

    @pytest.mark.parametrize(
        "dest", ["Library", "Library/LoginItems", "MacOS", ".", "Resources/../MacOS"]
    )
    def test_any_other_root_is_refused(self, dest):
        with pytest.raises(ConfigError, match="Resources or SharedSupport"):
            _config(_include(dest, "data"))

    def test_the_entries_are_a_lock_input(self):
        assert lock_inputs_sha256(_config(), "macos") != lock_inputs_sha256(
            _config(_include("Resources", "data")), "macos"
        )

    def test_pins_round_trip_through_the_lock(self):
        pins = (LockedIncludeFile("data/words.txt", "Resources", "ab" * 32),)
        lock = dataclasses.replace(_lock(), include_files=pins)
        assert loads(dumps(lock), platform="macos").include_files == pins

    def test_lock_refreshes_the_pins_without_resolving(self, root):
        config = _config(_include("Resources/data", "data"))
        refresh = _lock_ops("macos").refresh
        assert refresh is not None
        refreshed = refresh(_lock(), config, project_root=root)
        assert refreshed.include_files == tuple(
            include_files.hash_pins(config.macos_required.include_files, root)
        )
        assert refresh(refreshed, config, project_root=root) is refreshed


class TestPlacement:
    @pytest.mark.parametrize(
        ("dest", "source", "taken"),
        [
            ("Resources/app", "data/words.txt", "Resources/app"),
            ("resources/LIB", "data/words.txt", "Resources/lib"),
            ("Resources", "myapp.icns", "Resources/myapp.icns"),
            ("Resources/python/lib", "data/words.txt", "Resources/python"),
            ("Resources/bin", "data/words.txt", "Resources/bin"),
        ],
    )
    def test_a_path_the_bundler_writes_is_refused(self, root, dest, source, taken):
        (root / source).touch()
        # The loader's root check is exact, so a casefolded dest is built by hand.
        config = _config(_include("Resources", source))
        entry = dataclasses.replace(config.macos_required.include_files[0], dest=dest)
        config = dataclasses.replace(
            config,
            macos=dataclasses.replace(config.macos_required, include_files=(entry,)),
        )
        with pytest.raises(AppBundleError, match=f"Contents/{taken}") as info:
            check_includes(config, root, None)
        assert info.value.code == diagnostics.INCLUDE_RESERVED
        assert info.value.exit_code == exit_codes.CONFIG_ERROR

    def test_native_code_is_pointed_at_native_binaries(self, root):
        (root / "helper").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 12)
        config = _config(_include("Resources", "helper"))
        with pytest.raises(AppBundleError, match="native.binaries") as info:
            check_includes(config, root, None)
        assert info.value.code == diagnostics.INCLUDE_NATIVE_CODE

    def test_drift_is_lock_drift(self, root):
        config = _config(_include("Resources/data", "data"))
        pins = _pinned(config, root).include_files
        (root / "data" / "words.txt").write_text("edited")
        with pytest.raises(AppBundleError, match="has changed") as info:
            check_includes(config, root, pins)
        assert info.value.exit_code == exit_codes.LOCK_DRIFT


class TestBuild:
    def test_includes_land_under_contents(self, faked, root, tmp_path):
        config = _config(
            _include("Resources/data", "data")
            + _include("SharedSupport", "data/words.txt")
        )
        app = bundle.build_app_bundle(
            config,
            _pinned(config, root),
            root,
            staging_dir=tmp_path / "out",
            echo=lambda *a: None,
        )
        contents = app / "Contents"
        assert (contents / "Resources" / "data" / "words.txt").read_text() == "hello"
        assert (contents / "Resources" / "data" / "nested" / "more.txt").exists()
        assert (contents / "SharedSupport" / "words.txt").exists()

    def test_includes_are_staged_before_signing(
        self, faked, root, tmp_path, monkeypatch
    ):
        config = _config(_include("Resources/data", "data"))
        seen = []

        def sign(app):
            seen.append(
                (app / "Contents" / "Resources" / "data" / "words.txt").exists()
            )
            return 1

        monkeypatch.setattr(bundle, "sign_bundle_adhoc", sign)
        bundle.build_app_bundle(
            config,
            _pinned(config, root),
            root,
            staging_dir=tmp_path / "out",
            echo=lambda *a: None,
        )
        assert seen == [True]

    def test_drift_fails_before_anything_is_assembled(self, faked, root, tmp_path):
        config = _config(_include("Resources/data", "data"))
        with pytest.raises(AppBundleError, match="records no hash"):
            bundle.build_app_bundle(
                config, _lock(), root, staging_dir=tmp_path / "out", echo=print
            )
        assert faked["runtime"] == []

    def test_no_verify_lock_skips_the_pins(self, faked, root, tmp_path):
        config = _config(_include("Resources/data", "data"))
        app = bundle.build_app_bundle(
            config,
            _lock(),
            root,
            staging_dir=tmp_path / "out",
            verify_lock=False,
            echo=lambda *a: None,
        )
        assert (app / "Contents" / "Resources" / "data" / "words.txt").exists()

    @pytest.mark.skipif(sys.platform != "darwin", reason="com.apple.quarantine")
    def test_quarantine_does_not_reach_the_bundle(self, faked, root, tmp_path):
        source = root / "data" / "words.txt"
        subprocess.run(
            ["xattr", "-w", "com.apple.quarantine", "0081;0;Safari;", str(source)],
            check=True,
        )
        config = _config(_include("Resources/data", "data"))
        app = bundle.build_app_bundle(
            config,
            _pinned(config, root),
            root,
            staging_dir=tmp_path / "out",
            echo=lambda *a: None,
        )
        staged = app / "Contents" / "Resources" / "data" / "words.txt"
        attrs = subprocess.run(
            ["xattr", str(staged)], check=True, capture_output=True, text=True
        ).stdout
        assert "com.apple.quarantine" not in attrs


class TestVerifyBundle:
    def test_an_intact_bundle_passes(self, root, tmp_path):
        config = _config(_include("Resources/data", "data"))
        app = tmp_path / "My App.app"
        include_files.copy_items(
            include_files.expand(config.macos_required.include_files, root),
            app / "Contents",
        )
        verify_bundle(config, root, app, artifact="build/macos/My App.app")

    def test_a_missing_include_is_artifact_content(self, root, tmp_path):
        config = _config(_include("Resources/data", "data"))
        app = tmp_path / "My App.app"
        (app / "Contents").mkdir(parents=True)
        with pytest.raises(AppBundleError) as info:
            verify_bundle(config, root, app, artifact="build/macos/My App.app")
        assert info.value.code == diagnostics.ARTIFACT_CONTENT
        assert info.value.exit_code == exit_codes.BUILD_FAILURE
        assert info.value.context["artifact"] == "build/macos/My App.app"

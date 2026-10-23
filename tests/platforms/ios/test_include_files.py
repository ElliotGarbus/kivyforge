"""``[[tool.kivy.ios.include_files]]`` (include-files-proposal §4.4, #170)."""

from __future__ import annotations

import dataclasses
import zipfile
from pathlib import Path
from typing import Any

import pytest
from pbxproj import XcodeProject

from kivyforge.artifacts import include_files
from kivyforge.artifacts.include_files import ArtifactContentMismatch
from kivyforge.config import ConfigError
from kivyforge.lock.inputs import lock_inputs_sha256
from kivyforge.lock.model import LockedIncludeFile
from kivyforge.platforms.ios.includes import (
    INCLUDE_DIR,
    stage_includes,
    verify_app,
    verify_ipa,
)
from kivyforge.platforms.ios.lock.reader import loads
from kivyforge.platforms.ios.lock.writer import dumps
from kivyforge.platforms.ios.materialize import materialize_project
from kivyforge.platforms.ios.staging import StagingError, create_staging
from kivyforge.report import diagnostics, exit_codes

from .lock.test_reader import VALID

pytestmark = pytest.mark.requires_symlinks


def _include(dest: str, *sources: str) -> str:
    listed = ", ".join(f'"{s}"' for s in sources)
    return f'[[tool.kivy.ios.include_files]]\ndest = "{dest}"\nsources = [{listed}]\n'


@pytest.fixture
def files(project_root: Path) -> Path:
    (project_root / "config").mkdir()
    (project_root / "config" / "GoogleService-Info.plist").write_bytes(b"<plist/>")
    sounds = project_root / "assets" / "sounds"
    sounds.mkdir(parents=True)
    for name in ("ding.caf", "hook.py", "Helper.swift", "native.c"):
        (sounds / name).write_bytes(name.encode())
    return project_root


def _pins(config, root):
    return tuple(include_files.hash_pins(config.ios.include_files, root))


class TestConfig:
    def test_entries_parse(self, make_config):
        config = make_config(_include(".", "config/GoogleService-Info.plist"))
        [entry] = config.ios.include_files
        assert entry.dest == "."
        assert entry.sources == ("config/GoogleService-Info.plist",)

    def test_none_by_default(self, config):
        assert config.ios.include_files == ()

    def test_dest_must_stay_inside_the_app(self, make_config):
        with pytest.raises(ConfigError, match=r"stay inside the \.app"):
            make_config(_include("../outside", "config/a.json"))

    def test_the_entries_are_a_lock_input(self, make_config):
        bare = make_config()
        added = make_config(_include(".", "config/GoogleService-Info.plist"))
        assert lock_inputs_sha256(bare, "ios") != lock_inputs_sha256(added, "ios")


class TestLockfile:
    def test_pins_round_trip(self):
        lock = loads(VALID)
        pins = (
            LockedIncludeFile("config/GoogleService-Info.plist", ".", "cd" * 32),
            LockedIncludeFile("assets/sounds/ding.caf", "Sounds", "ab" * 32),
        )
        text = dumps(dataclasses.replace(lock, include_files=pins))
        assert "[[tool.kivyforge.include_files]]" in text
        assert loads(text).include_files == pins

    def test_a_lock_without_pins_reads_as_none(self):
        assert loads(VALID).include_files == ()


class TestReserved:
    @pytest.mark.parametrize(
        ("dest", "source", "why"),
        [
            (".", "Info.plist", "Info.plist kivyforge generates"),
            (".", "info.PLIST", "Info.plist kivyforge generates"),
            ("python", "config/a.json", "Python runtime"),
            ("app", "config/a.json", "app_dir"),
            (".", "AppIcon60x60@2x.png", "icon image"),
            ("AppClips", "config/a.json", "App Clips"),
            ("Watch", "config/a.json", "watchOS"),
            ("PlugIns", "config/a.json", "app extensions"),
            (".", "touchtracer", "executable"),
        ],
    )
    def test_a_generated_name_is_refused(
        self, make_config, project_root, dest, source, why
    ):
        (project_root / source).parent.mkdir(parents=True, exist_ok=True)
        (project_root / source).write_bytes(b"x")
        config = make_config(_include(dest, source))
        layout = create_staging(config, project_root)
        with pytest.raises(StagingError, match=why) as info:
            stage_includes(config, project_root, layout, None)
        assert info.value.code == diagnostics.INCLUDE_RESERVED
        assert info.value.exit_code == exit_codes.CONFIG_ERROR
        assert not (layout.root / INCLUDE_DIR).exists()

    @pytest.mark.parametrize("bundle", ["Data.framework", "Share.appex", "X.app"])
    def test_a_code_bundle_name_is_refused(self, make_config, files, bundle):
        config = make_config(_include(bundle, "config/GoogleService-Info.plist"))
        layout = create_staging(config, files)
        with pytest.raises(StagingError, match="code-bundle name") as info:
            stage_includes(config, files, layout, None)
        assert info.value.code == diagnostics.INCLUDE_RESERVED

    def test_a_bundle_folder_is_data(self, make_config, files):
        config = make_config(
            _include("Settings.bundle", "config/GoogleService-Info.plist")
        )
        layout = create_staging(config, files)
        assert stage_includes(config, files, layout, None) == [
            "Settings.bundle/GoogleService-Info.plist"
        ]

    def test_native_code_is_pointed_at_xcframeworks(self, make_config, files):
        (files / "libx.a").write_bytes(b"!<arch>\nx.o/")
        config = make_config(_include(".", "libx.a"))
        layout = create_staging(config, files)
        with pytest.raises(StagingError, match="native.xcframeworks") as info:
            stage_includes(config, files, layout, None)
        assert info.value.code == diagnostics.INCLUDE_NATIVE_CODE

    def test_a_string_catalog_is_refused(self, make_config, files):
        (files / "Localizable.xcstrings").write_text("{}")
        config = make_config(_include(".", "Localizable.xcstrings"))
        layout = create_staging(config, files)
        with pytest.raises(StagingError, match="String Catalog") as info:
            stage_includes(config, files, layout, None)
        assert info.value.code == diagnostics.INCLUDE_SOURCE_FORMAT


class TestStaging:
    def test_stages_into_include_laid_out_as_in_the_app(self, make_config, files):
        config = make_config(
            _include(".", "config/GoogleService-Info.plist")
            + _include("Sounds", "assets/sounds")
        )
        layout = create_staging(config, files)
        staged = stage_includes(config, files, layout, _pins(config, files))
        include = layout.root / INCLUDE_DIR
        assert "GoogleService-Info.plist" in staged
        assert (include / "GoogleService-Info.plist").read_bytes() == b"<plist/>"
        assert (include / "Sounds" / "ding.caf").read_bytes() == b"ding.caf"

    def test_a_removed_include_leaves_nothing_behind(self, make_config, files):
        config = make_config(_include("Sounds", "assets/sounds"))
        layout = create_staging(config, files)
        stage_includes(config, files, layout, None)
        assert stage_includes(make_config(), files, layout, None) == []
        assert not (layout.root / INCLUDE_DIR).exists()

    def test_drift_is_refused_before_anything_is_copied(self, make_config, files):
        config = make_config(_include("Sounds", "assets/sounds"))
        pins = _pins(config, files)
        (files / "assets" / "sounds" / "ding.caf").write_bytes(b"edited")
        layout = create_staging(config, files)
        with pytest.raises(StagingError, match="has changed") as info:
            stage_includes(config, files, layout, pins)
        assert info.value.code == diagnostics.LOCK_DRIFT
        assert info.value.exit_code == exit_codes.LOCK_DRIFT
        assert not (layout.root / INCLUDE_DIR).exists()

    def test_no_verify_lock_stages_unpinned_files(self, make_config, files):
        config = make_config(_include("Sounds", "assets/sounds"))
        layout = create_staging(config, files)
        assert stage_includes(config, files, layout, None)


def _resource_refs(layout, name: str) -> dict[str, str]:
    """``path -> explicitFileType`` of each Copy Bundle Resources member."""
    project: Any = XcodeProject.load(str(layout.xcodeproj / "project.pbxproj"))
    objects = project.objects
    target = project.get_target_by_name(name)
    phase = next(
        objects[p]
        for p in target.buildPhases
        if objects[p].isa == "PBXResourcesBuildPhase"
    )
    out = {}
    for build_file_id in phase.files:
        ref = objects[objects[build_file_id].fileRef]
        if str(ref.path).startswith(f"{INCLUDE_DIR}/"):
            out[str(ref.path)] = str(ref["explicitFileType"])
    return out


class TestXcodeProject:
    def test_each_top_level_entry_is_a_typed_resource(self, make_config, files):
        config = make_config(
            _include(".", "config/GoogleService-Info.plist")
            + _include(".", "assets/sounds/hook.py", "assets/sounds/Helper.swift")
            + _include(".", "assets/sounds/native.c", "assets/sounds/ding.caf")
            + _include("Sounds", "assets/sounds")
        )
        layout = materialize_project(config, files)
        assert _resource_refs(layout, "touchtracer") == {
            "Include/GoogleService-Info.plist": "file",
            "Include/hook.py": "file",
            "Include/Helper.swift": "file",
            "Include/native.c": "file",
            "Include/ding.caf": "file",
            "Include/Sounds": "folder",
        }
        text = (layout.xcodeproj / "project.pbxproj").read_text()
        # Nothing an include brings in is compiled.
        sources = text.split("PBXSourcesBuildPhase section")[1]
        assert "hook.py" not in sources
        assert "Helper.swift" not in sources

    def test_a_removed_include_loses_its_reference(self, make_config, files):
        both = make_config(
            _include(".", "config/GoogleService-Info.plist")
            + _include("Sounds", "assets/sounds")
        )
        materialize_project(both, files)
        layout = materialize_project(
            make_config(_include("Sounds", "assets/sounds")), files
        )
        assert _resource_refs(layout, "touchtracer") == {"Include/Sounds": "folder"}
        text = (layout.xcodeproj / "project.pbxproj").read_text()
        assert "GoogleService-Info.plist" not in text

    def test_regenerating_adds_no_duplicates(self, make_config, files):
        config = make_config(_include("Sounds", "assets/sounds"))
        materialize_project(config, files)
        layout = materialize_project(config, files)
        text = (layout.xcodeproj / "project.pbxproj").read_text()
        assert text.count("Include/Sounds") == 1

    def test_drift_fails_materialize_with_pins(self, make_config, files):
        config = make_config(_include("Sounds", "assets/sounds"))
        with pytest.raises(StagingError, match="records no hash"):
            materialize_project(config, files, include_pins=())


class TestProductCheck:
    @pytest.fixture
    def config(self, make_config, files):
        return make_config(
            _include(".", "config/GoogleService-Info.plist")
            + _include("Sounds", "assets/sounds")
        )

    @pytest.fixture
    def app(self, config, files, tmp_path):
        app = tmp_path / "out" / "touchtracer.app"
        include_files.copy_items(
            include_files.expand(config.ios.include_files, files), app
        )
        return app

    def test_an_intact_app_passes(self, config, files, app):
        verify_app(config, files, app)

    def test_a_converted_plist_fails_with_the_artifact_named(self, config, files, app):
        (app / "GoogleService-Info.plist").write_bytes(b"bplist00")
        with pytest.raises(ArtifactContentMismatch) as info:
            verify_app(config, files, app)
        assert info.value.code == diagnostics.ARTIFACT_CONTENT
        assert info.value.exit_code == exit_codes.BUILD_FAILURE
        assert info.value.context["path"] == "GoogleService-Info.plist"

    def test_the_ipa_is_read_under_payload(self, config, files, app, tmp_path):
        ipa = tmp_path / "touchtracer.ipa"
        with zipfile.ZipFile(ipa, "w") as zf:
            for f in app.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(app).as_posix()
                    zf.write(f, f"Payload/touchtracer.app/{rel}")
        verify_ipa(config, files, ipa)
        with zipfile.ZipFile(ipa, "w") as zf:
            zf.writestr("Payload/touchtracer.app/Info.plist", b"x")
        with pytest.raises(ArtifactContentMismatch, match="missing"):
            verify_ipa(config, files, ipa)

    def test_no_includes_reads_nothing(self, make_config, files, tmp_path):
        verify_app(make_config(), files, tmp_path / "absent.app")
        verify_ipa(make_config(), files, tmp_path / "absent.ipa")

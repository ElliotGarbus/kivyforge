"""Native xcframework link/embed wiring + stale-ref pruning in project gen."""

from __future__ import annotations

import plistlib
from unittest.mock import MagicMock

import pytest
from pbxproj import XcodeProject
from pbxproj.pbxextensions.ProjectFiles import TreeType

from kivyforge.platforms.ios import xcframeworks as xcframeworks_mod
from kivyforge.platforms.ios.generator import XcodeProjectGenerator
from kivyforge.platforms.ios.lock.model import LockedXcframework
from kivyforge.platforms.ios.materialize import materialize_project

# Materialization builds the iOS staging tree (symlinked app dir); skip where
# symlinks are unavailable (stock Windows). iOS builds only on macOS regardless.
pytestmark = pytest.mark.requires_symlinks

EMBED_DST = "10"  # PBXCopyFilesBuildPhase dstSubfolderSpec for Embed Frameworks


def _make_xcframework(frameworks_dir, name):
    xc = frameworks_dir / f"{name}.xcframework"
    (xc / "ios-arm64").mkdir(parents=True)
    (xc / "ios-arm64" / name).write_text("binary")
    with open(xc / "Info.plist", "wb") as fh:
        plistlib.dump({"AvailableLibraries": [{"LibraryIdentifier": "ios-arm64"}]}, fh)
    return xc


def _locked(name, *, link, embed):
    return LockedXcframework(
        name=name,
        version="1.0.0",
        sha256="a" * 64,
        slices=("ios-arm64",),
        path=f"{name}.zip",
        link=link,
        embed=embed,
    )


def _ref_id(project, name):
    refs = project.get_files_by_path(
        f"Frameworks/{name}.xcframework", tree=TreeType.SOURCE_ROOT
    )
    return refs[0].get_id() if refs else None


def _phase_refs(project, target_name, isa, *, dst=None):
    target = project.get_target_by_name(target_name)
    out = []
    for pid in target.buildPhases:
        phase = project.get_object(pid)
        if phase.isa != isa:
            continue
        if dst is not None and getattr(phase, "dstSubfolderSpec", None) != dst:
            continue
        for bf_id in phase["files"]:
            bf = project.objects[bf_id]
            ref = bf["fileRef"] if "fileRef" in bf else None
            if ref:
                out.append(ref)
    return out


def _link_refs(project, target_name):
    return _phase_refs(project, target_name, "PBXFrameworksBuildPhase")


def _embed_refs(project, target_name):
    return _phase_refs(project, target_name, "PBXCopyFilesBuildPhase", dst=EMBED_DST)


def _regenerate(config, layout, xcframeworks=()):
    XcodeProjectGenerator(config, layout, xcframeworks=xcframeworks).generate()
    return XcodeProject.load(str(layout.xcodeproj / "project.pbxproj"))


class TestLinkEmbedIntent:
    def test_link_and_embed(self, config, project_root):
        layout = materialize_project(config, project_root)
        _make_xcframework(layout.frameworks, "Both")
        project = _regenerate(config, layout, (_locked("Both", link=True, embed=True),))
        ref = _ref_id(project, "Both")
        assert ref in _link_refs(project, "touchtracer")
        assert ref in _embed_refs(project, "touchtracer")

    def test_link_only(self, config, project_root):
        layout = materialize_project(config, project_root)
        _make_xcframework(layout.frameworks, "LinkOnly")
        project = _regenerate(
            config, layout, (_locked("LinkOnly", link=True, embed=False),)
        )
        ref = _ref_id(project, "LinkOnly")
        assert ref in _link_refs(project, "touchtracer")
        assert ref not in _embed_refs(project, "touchtracer")

    def test_embed_only(self, config, project_root):
        layout = materialize_project(config, project_root)
        _make_xcframework(layout.frameworks, "EmbedOnly")
        project = _regenerate(
            config, layout, (_locked("EmbedOnly", link=False, embed=True),)
        )
        ref = _ref_id(project, "EmbedOnly")
        assert ref not in _link_refs(project, "touchtracer")
        assert ref in _embed_refs(project, "touchtracer")

    def test_neither(self, config, project_root):
        layout = materialize_project(config, project_root)
        _make_xcframework(layout.frameworks, "RefOnly")
        project = _regenerate(
            config, layout, (_locked("RefOnly", link=False, embed=False),)
        )
        ref = _ref_id(project, "RefOnly")
        assert ref is not None  # still referenced in the navigator
        assert ref not in _link_refs(project, "touchtracer")
        assert ref not in _embed_refs(project, "touchtracer")

    def test_wheel_embedded_default_is_embed_and_sign(self, config, project_root):
        # No lock entry (SDL3/ANGLE ride inside wheels) -> Embed & Sign default.
        layout = materialize_project(config, project_root)
        _make_xcframework(layout.frameworks, "SDL3")
        project = _regenerate(config, layout, xcframeworks=())
        ref = _ref_id(project, "SDL3")
        assert ref in _link_refs(project, "touchtracer")
        assert ref in _embed_refs(project, "touchtracer")


class TestReconcileAndPrune:
    def test_flip_embed_off_removes_embed_build_file(self, config, project_root):
        layout = materialize_project(config, project_root)
        _make_xcframework(layout.frameworks, "Flip")
        project = _regenerate(config, layout, (_locked("Flip", link=True, embed=True),))
        assert _ref_id(project, "Flip") in _embed_refs(project, "touchtracer")

        # Re-lock with embed=False; the stale embed build file must be removed.
        project = _regenerate(
            config, layout, (_locked("Flip", link=True, embed=False),)
        )
        ref = _ref_id(project, "Flip")
        assert ref in _link_refs(project, "touchtracer")
        assert ref not in _embed_refs(project, "touchtracer")

    def test_stale_framework_pruned(self, config, project_root):
        import shutil

        layout = materialize_project(config, project_root)
        xc = _make_xcframework(layout.frameworks, "Gone")
        project = _regenerate(config, layout, (_locked("Gone", link=True, embed=True),))
        assert _ref_id(project, "Gone") is not None

        # Framework removed from disk -> reference and build files pruned.
        shutil.rmtree(xc)
        project = _regenerate(config, layout, xcframeworks=())
        assert _ref_id(project, "Gone") is None
        assert _embed_refs(project, "touchtracer") == []
        assert _link_refs(project, "touchtracer") == []

    def test_python_xcframework_not_pruned(self, config, project_root):
        # Pruning only targets Frameworks/*.xcframework, never the root
        # Python.xcframework reference.
        layout = materialize_project(config, project_root)
        layout.python_xcframework.mkdir(exist_ok=True)
        project = _regenerate(config, layout, xcframeworks=())
        assert project.get_files_by_name("Python.xcframework")

    def test_missing_frameworks_dir_still_prunes(self, config, project_root):
        # A framework removed along with the whole Frameworks/ dir (not just
        # its own subfolder) must still be pruned; sync_native_frameworks must
        # not crash when frameworks_dir.is_dir() is False.
        import shutil

        layout = materialize_project(config, project_root)
        _make_xcframework(layout.frameworks, "Gone")
        project = _regenerate(config, layout, (_locked("Gone", link=True, embed=True),))
        assert _ref_id(project, "Gone") is not None

        shutil.rmtree(layout.frameworks)
        project = _regenerate(config, layout, xcframeworks=())
        assert _ref_id(project, "Gone") is None
        assert _embed_refs(project, "touchtracer") == []
        assert _link_refs(project, "touchtracer") == []

    def test_reenabling_link_and_embed_creates_fresh_build_files(
        self, config, project_root
    ):
        # After a round with neither link nor embed (both build files
        # removed), re-enabling both must create brand-new build files
        # rather than assume stale ones still exist.
        layout = materialize_project(config, project_root)
        _make_xcframework(layout.frameworks, "Revive")
        project = _regenerate(
            config, layout, (_locked("Revive", link=False, embed=False),)
        )
        ref = _ref_id(project, "Revive")
        assert ref not in _link_refs(project, "touchtracer")
        assert ref not in _embed_refs(project, "touchtracer")

        project = _regenerate(
            config, layout, (_locked("Revive", link=True, embed=True),)
        )
        ref = _ref_id(project, "Revive")
        assert ref in _link_refs(project, "touchtracer")
        assert ref in _embed_refs(project, "touchtracer")

    def test_unlinking_one_of_two_frameworks_skips_the_other(
        self, config, project_root
    ):
        # _remove_build_files must skip past the still-linked framework's
        # build file (a non-matching entry) before finding & removing the
        # unlinked one's.
        layout = materialize_project(config, project_root)
        _make_xcframework(layout.frameworks, "StaysLinked")
        _make_xcframework(layout.frameworks, "GetsUnlinked")
        project = _regenerate(
            config,
            layout,
            (
                _locked("StaysLinked", link=True, embed=True),
                _locked("GetsUnlinked", link=True, embed=True),
            ),
        )
        stays = _ref_id(project, "StaysLinked")
        unlinked = _ref_id(project, "GetsUnlinked")
        assert stays in _link_refs(project, "touchtracer")
        assert unlinked in _link_refs(project, "touchtracer")

        project = _regenerate(
            config,
            layout,
            (
                _locked("StaysLinked", link=True, embed=True),
                _locked("GetsUnlinked", link=False, embed=True),
            ),
        )
        stays = _ref_id(project, "StaysLinked")
        unlinked = _ref_id(project, "GetsUnlinked")
        assert stays in _link_refs(project, "touchtracer")
        assert unlinked not in _link_refs(project, "touchtracer")
        assert unlinked in _embed_refs(project, "touchtracer")

    def test_two_frameworks_linked_together(self, config, project_root):
        # A second framework's build-file lookup must skip past the first
        # framework's (non-matching) build file already in the phase.
        layout = materialize_project(config, project_root)
        _make_xcframework(layout.frameworks, "First")
        _make_xcframework(layout.frameworks, "Second")
        project = _regenerate(
            config,
            layout,
            (
                _locked("First", link=True, embed=True),
                _locked("Second", link=True, embed=True),
            ),
        )
        first = _ref_id(project, "First")
        second = _ref_id(project, "Second")
        assert first in _link_refs(project, "touchtracer")
        assert second in _link_refs(project, "touchtracer")
        assert first in _embed_refs(project, "touchtracer")
        assert second in _embed_refs(project, "touchtracer")


class TestPhaseHelpersDirect:
    """Directly exercise the private phase/group helpers against a real
    (already-generated) project object for branches too awkward to reach
    through a full regenerate cycle."""

    def test_link_phase_returns_none_for_missing_target(self, config, project_root):
        layout = materialize_project(config, project_root)
        project = _regenerate(config, layout)
        assert xcframeworks_mod._link_phase(project, "NoSuchTarget") is None

    def test_embed_phase_raises_for_missing_target(self, config, project_root):
        layout = materialize_project(config, project_root)
        project = _regenerate(config, layout)
        with pytest.raises(RuntimeError, match="NoSuchTarget"):
            xcframeworks_mod._embed_phase(project, "NoSuchTarget")

    def test_ensure_under_group_moves_ref_from_other_group(self, config, project_root):
        layout = materialize_project(config, project_root)
        _make_xcframework(layout.frameworks, "Movable")
        project = _regenerate(
            config, layout, (_locked("Movable", link=True, embed=True),)
        )
        ref = project.get_files_by_path(
            "Frameworks/Movable.xcframework", tree=TreeType.SOURCE_ROOT
        )[0]
        stray_group = project.get_or_create_group("Stray", "Stray")
        frameworks_group = project.get_or_create_group("Frameworks", "Frameworks")
        frameworks_group.remove_child(ref)
        stray_group.add_child(ref)
        assert stray_group.has_child(ref)

        xcframeworks_mod._ensure_under_group(project, ref, frameworks_group)
        assert frameworks_group.has_child(ref)
        assert not stray_group.has_child(ref)

    def test_ensure_file_ref_returns_none_when_add_file_leaves_no_ref(self):
        # Defensive fallback: if pbxproj's add_file somehow leaves no
        # resolvable reference behind, _ensure_file_ref must report None
        # rather than crash.
        project = MagicMock()
        project.get_files_by_path.return_value = []
        ref = xcframeworks_mod._ensure_file_ref(
            project, "Frameworks/Ghost.xcframework", "touchtracer", MagicMock()
        )
        assert ref is None
        project.add_file.assert_called_once()

    def test_sync_skips_framework_when_file_ref_could_not_be_created(
        self, config, project_root, monkeypatch
    ):
        layout = materialize_project(config, project_root)
        _make_xcframework(layout.frameworks, "Ghost")
        monkeypatch.setattr(xcframeworks_mod, "_ensure_file_ref", lambda *a, **k: None)
        # Must not raise even though every framework's ref resolves to None.
        project = _regenerate(config, layout, xcframeworks=())
        assert project is not None

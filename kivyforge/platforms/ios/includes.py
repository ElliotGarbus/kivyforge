"""``[[tool.kivy.ios.include_files]]``: user files in the ``.app`` (#170).

``dest`` is relative to the ``.app`` root. ``build`` stages the includes into
``<app>-ios/Include/``, laid out as they will be in the bundle, and makes each
*top-level* entry of ``Include/`` a member of Copy Bundle Resources: a file as
a file reference, a directory as a folder reference, which Xcode copies whole
(include-files-proposal §4.4).

Every reference has an explicit type (``file`` or ``folder``). Xcode otherwise
picks the build action from the extension even in the Resources phase, and
compiles a ``.storyboard``, converts a ``.plist`` to binary, or drops a
``.swift`` with a warning. With the type set, each include reaches the bundle
byte for byte, which is what lets ``build`` check the product against the pins.
"""

from __future__ import annotations

import fnmatch
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pbxproj.pbxextensions.ProjectFiles import TreeType
from pbxproj.pbxsections.PBXBuildFile import PBXBuildFile
from pbxproj.pbxsections.PBXFileReference import PBXFileReference

from kivyforge.artifacts import include_files
from kivyforge.artifacts.include_files import IncludeItem
from kivyforge.config.model import Config, IncludeFile
from kivyforge.lock.model import LockedIncludeFile
from kivyforge.report.failures import reclassify

from .buildsettings import APP_ICON_NAME, BUILD_PYTHON_OUTPUTS
from .staging import StagingError, StagingLayout

INCLUDE_DIR = "Include"

NATIVE_KEY = "[tool.kivy.ios.native.xcframeworks]"

#: A top-level name with one of these extensions is a code bundle to Xcode:
#: given a data-only ``X.framework``, it compiles a stub binary into it.
_CODE_BUNDLE_SUFFIXES = (".framework", ".xcframework", ".appex", ".app")


def _reserved(config: Config) -> dict[str, str]:
    """Top-level names in the ``.app`` the build owns, casefolded, with why."""
    python_outputs = {out.rsplit("/", 1)[1] for out in BUILD_PYTHON_OUTPUTS}
    owned = {
        name: "where the build puts the Python runtime and dependencies"
        for name in python_outputs
    }
    owned.update(
        {
            "app": "where the build puts app_dir",
            config.app_slug: "the app's executable",
            "Info.plist": (
                "the Info.plist kivyforge generates; set keys with "
                "[tool.kivy.ios.info_plist]"
            ),
            "PkgInfo": "written by Xcode with the Info.plist",
            "PrivacyInfo.xcprivacy": (
                "the privacy manifest; set it with [tool.kivy.ios.privacy_manifest]"
            ),
            "Assets.car": (
                "the compiled asset catalog; set the icon with [tool.kivy.ios.icons]"
            ),
            "LaunchScreen.storyboardc": (
                "the launch screen; set it with [tool.kivy.ios.splash]"
            ),
            "PlugIns": "where Apple puts app extensions",
            "AppClips": "where Apple puts App Clips",
            "Watch": "where Apple puts a watchOS app",
            "_CodeSignature": "written by code signing",
            "embedded.mobileprovision": "written by code signing",
        }
    )
    return {name.casefold(): why for name, why in owned.items()}


def reserved_check(config: Config) -> Callable[[IncludeItem], str | None]:
    """The message for an include the generated build would collide with."""
    owned = _reserved(config)
    icon_pattern = f"{APP_ICON_NAME}*.png".casefold()

    def check(item: IncludeItem) -> str | None:
        top = item.path.split("/", 1)[0]
        folded = top.casefold()
        why = owned.get(folded)
        if why is None and fnmatch.fnmatchcase(folded, icon_pattern):
            why = "an icon image actool writes; set the icon with [tool.kivy.ios.icons]"
        if why is not None:
            return (
                f"include_files: {item.source} would land at {item.path} in the "
                f".app, and {top} is {why}."
            )
        if folded.endswith(_CODE_BUNDLE_SUFFIXES):
            return (
                f"include_files: {item.source} would land at {item.path}, and "
                f"{top} is a code-bundle name: Xcode treats it as code, and gives "
                "a data-only framework a stub binary.\n"
                f"  Native frameworks go in {NATIVE_KEY}; a folder of data can be "
                "named *.bundle, as Settings.bundle is."
            )
        return None

    return check


def stage_includes(
    config: Config,
    project_root: Path,
    layout: StagingLayout,
    pins: tuple[LockedIncludeFile, ...] | None,
) -> list[str]:
    """Stage the includes into ``Include/``, checking *pins* unless ``None``.

    ``Include/`` is kivyforge's own and rebuilt each time, so an include taken
    out of the table leaves nothing behind for the generator to reference.
    Returns the staged paths.
    """
    include = layout.root / INCLUDE_DIR
    if include.exists():
        shutil.rmtree(include)
    entries = _entries(config)
    if not entries:
        return []
    try:
        items = include_files.expand(entries, project_root)
        include_files.refuse_reserved(items, reserved_check(config))
        include_files.refuse_unprocessed(items, native_key=NATIVE_KEY)
        if pins is not None:
            include_files.verify_pins(items, pins, platform="ios")
    except include_files.IncludeFilesError as exc:
        raise StagingError(str(exc), **reclassify(exc)) from exc
    return include_files.copy_items(items, include)


# -- the Xcode project ---------------------------------------------------------- #


def sync_include_references(project: Any, target_name: str, include_dir: Path) -> None:
    """Make each top-level entry of ``Include/`` a Copy Bundle Resources member.

    A reference is created directly, not through ``add_file``, because
    ``add_file`` picks the build phase from the extension: ``.py`` and ``.c``
    go to Sources, where Xcode builds them and leaves them out of the bundle,
    and an extension it does not know (``.caf``) raises.
    """
    names = (
        sorted(p.name for p in include_dir.iterdir()) if include_dir.is_dir() else []
    )
    wanted = {f"{INCLUDE_DIR}/{name}" for name in names}
    _prune(project, wanted)
    if not names:
        return
    target = project.get_target_by_name(target_name)
    if target is None:
        raise RuntimeError(f"target {target_name!r} not found in Xcode project")
    phase = target.get_or_create_build_phase("PBXResourcesBuildPhase")[0]
    group = project.get_or_create_group(INCLUDE_DIR)
    for name in names:
        rel = f"{INCLUDE_DIR}/{name}"
        refs = project.get_files_by_path(rel, tree=TreeType.SOURCE_ROOT)
        ref: Any
        if refs:
            ref = refs[0]
        else:
            ref = PBXFileReference.create(rel, tree=TreeType.SOURCE_ROOT)
            project.objects[ref.get_id()] = ref
            group.add_child(ref)
        ref.set_explicit_file_type(
            "folder" if (include_dir / name).is_dir() else "file"
        )
        if not any(
            _file_ref(project.objects[bf]) == ref.get_id() for bf in phase["files"]
        ):
            build_file: Any = PBXBuildFile.create(ref)
            project.objects[build_file.get_id()] = build_file
            phase.add_build_file(build_file)


def _prune(project: Any, wanted: set[str]) -> None:
    """Drop the references for top-level includes that are no longer staged."""
    prefix = f"{INCLUDE_DIR}/"
    for ref in list(project.objects.get_objects_in_section("PBXFileReference")):
        path = ref["path"] if "path" in ref else None
        if not path or not path.startswith(prefix) or "/" in path[len(prefix) :]:
            continue
        if path in wanted:
            continue
        ref_id = ref.get_id()
        for phase in project.objects.get_objects_in_section("PBXResourcesBuildPhase"):
            for build_file_id in list(phase["files"]):
                build_file = project.objects[build_file_id]
                if _file_ref(build_file) == ref_id:
                    phase.remove_build_file(build_file)
        for group in project.objects.get_objects_in_section("PBXGroup"):
            if ref_id in group.children:
                group.remove_child(ref)
        del project.objects[ref_id]


def _file_ref(build_file: Any) -> str | None:
    return build_file["fileRef"] if "fileRef" in build_file else None


# -- the built product (§4.8) ----------------------------------------------------- #


def expected(config: Config, project_root: Path) -> dict[str, tuple[str, str]]:
    """What each include should be in the bundle, from the files on disk."""
    entries = _entries(config)
    if not entries:
        return {}
    return include_files.expected_contents(include_files.expand(entries, project_root))


def verify_app(config: Config, project_root: Path, app: Path) -> None:
    """Refuse a built ``.app`` that lacks an include or holds a different copy."""
    contents = expected(config, project_root)
    if not contents:
        return
    include_files.raise_for_mismatches(
        include_files.tree_mismatches(contents, app),
        artifact=_rel(app, project_root),
    )


def verify_ipa(config: Config, project_root: Path, ipa: Path) -> None:
    """As :func:`verify_app`, over ``Payload/<app>.app/`` in the IPA."""
    contents = expected(config, project_root)
    if not contents:
        return
    include_files.raise_for_mismatches(
        include_files.zip_mismatches(contents, ipa, f"Payload/{config.app_slug}.app/"),
        artifact=_rel(ipa, project_root),
    )


def _entries(config: Config) -> tuple[IncludeFile, ...]:
    return config.ios.include_files if config.ios else ()


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)

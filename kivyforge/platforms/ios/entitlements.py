"""Generate ``<app>.entitlements`` from ``[tool.kivy.ios.entitlements]`` (spec 06).

Also reads the pinned provisioning profile -- an installed profile found by name
or UUID, or a ``.mobileprovision`` path -- so ``build`` and ``doctor`` can check
declared entitlements against what the profile actually grants: ``codesign``
requires the app's entitlements to be a *subset* of the profile's, and a
mismatch otherwise fails deep inside ``xcodebuild`` naming neither the pyproject
key nor the App ID capability that fixes it (spec 05).
"""

from __future__ import annotations

import plistlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from kivyforge.config.model import Config

from .xcode.commands import SigningError


def has_entitlements(config: Config) -> bool:
    return bool(config.ios and config.ios.entitlements)


def build_entitlements(config: Config) -> dict:
    if not config.ios:
        return {}
    return dict(config.ios.entitlements)


def write_entitlements(config: Config, path: str | Path) -> Path | None:
    """Write the entitlements plist; returns None when there are none.

    When no entitlements are configured, any previously generated file is
    removed so a stale ``<app>.entitlements`` (from a since-deleted config
    table) is not left referenced in the bundle.
    """
    path = Path(path)
    if not has_entitlements(config):
        path.unlink(missing_ok=True)
        return None
    with open(path, "wb") as f:
        plistlib.dump(build_entitlements(config), f, sort_keys=True)
    return path


# ---- provisioning-profile comparison ------------------------------------

_PLIST_START = b"<?xml"
_PLIST_END = b"</plist>"


class ProfileError(Exception):
    """A provisioning profile could not be read or parsed."""


@dataclass(frozen=True)
class ProvisioningProfile:
    name: str
    app_id: str
    entitlements: dict
    uuid: str = ""


PROFILE_SUFFIX = ".mobileprovision"


def installed_profile_dirs() -> tuple[Path, ...]:
    """Where Xcode installs provisioning profiles, newest location first.

    Xcode 16 moved them to ``UserData``; older Xcodes and double-clicking a
    profile in Finder still use ``MobileDevice``. Both are searched.
    """
    home = Path.home()
    return (
        home / "Library" / "Developer" / "Xcode" / "UserData" / "Provisioning Profiles",
        home / "Library" / "MobileDevice" / "Provisioning Profiles",
    )


def is_profile_path(value: str) -> bool:
    """True when ``provisioning_profile`` names a file rather than a profile.

    The contract is Xcode's: a profile *name or UUID*. A value ending in
    ``.mobileprovision`` is accepted as a path to a downloaded profile instead.
    """
    return value.lower().endswith(PROFILE_SUFFIX)


def find_installed_profile(
    specifier: str, search_dirs: tuple[Path, ...] | None = None
) -> Path | None:
    """The installed profile whose UUID or Name matches *specifier*, or None.

    A UUID match wins (case-insensitive). Several profiles can share a Name --
    a regenerated profile keeps its name but gets a new UUID -- so among Name
    matches the most recently modified file wins. Unreadable files are skipped.
    """
    dirs = installed_profile_dirs() if search_dirs is None else search_dirs
    wanted = specifier.strip()
    by_name: list[Path] = []
    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob(f"*{PROFILE_SUFFIX}")):
            try:
                profile = read_profile(path)
            except ProfileError:
                continue
            if profile.uuid and profile.uuid.lower() == wanted.lower():
                return path
            if profile.name == wanted:
                by_name.append(path)
    if not by_name:
        return None
    return max(by_name, key=lambda p: p.stat().st_mtime)


def resolve_profile_path(
    config: Config, project_root: Path, *, search_dirs: tuple[Path, ...] | None = None
) -> Path | None:
    """The file behind the pinned profile, or None.

    None when no profile is pinned, or when a name/UUID matches no installed
    profile. A path value is returned as-is (relative to *project_root*) even if
    the file is missing, so callers can report which file they looked for.
    """
    value = config.ios_required.signing.provisioning_profile
    if not value:
        return None
    if is_profile_path(value):
        path = Path(value)
        return path if path.is_absolute() else project_root / value
    return find_installed_profile(value, search_dirs)


def xcode_profile_specifier(config: Config, project_root: Path | None) -> str:
    """The ``PROVISIONING_PROFILE_SPECIFIER`` value for *config*.

    A name or UUID passes through unchanged. A ``.mobileprovision`` path is
    replaced by the UUID read from the file, since Xcode resolves specifiers
    against installed profiles and never against paths. If the file cannot be
    read the raw value is kept; ``doctor`` reports the unreadable file.
    """
    value = config.ios_required.signing.provisioning_profile
    if not value or not is_profile_path(value) or project_root is None:
        return value
    path = resolve_profile_path(config, project_root)
    assert path is not None
    try:
        profile = read_profile(path)
    except ProfileError:
        return value
    return profile.uuid or profile.name


def read_profile(path: str | Path) -> ProvisioningProfile:
    """Extract name, App ID, and granted entitlements from a ``.mobileprovision``.

    A profile is a CMS envelope wrapping an XML plist stored verbatim, so the
    payload is sliced straight out of the bytes rather than shelling out to
    ``security cms``. That keeps this pure and unit-testable off a macOS host.
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProfileError(f"cannot read {path.name}: {exc}") from exc

    start = raw.find(_PLIST_START)
    end = raw.find(_PLIST_END)
    if start == -1 or end == -1 or end < start:
        raise ProfileError(f"{path.name} contains no embedded plist")
    try:
        payload = plistlib.loads(raw[start : end + len(_PLIST_END)])
    except Exception as exc:  # plistlib raises a variety of parse errors
        raise ProfileError(f"{path.name} has an unreadable plist: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProfileError(f"{path.name} plist is not a dictionary")

    granted = payload.get("Entitlements")
    granted = dict(granted) if isinstance(granted, dict) else {}
    app_id = granted.get("application-identifier", "")
    uuid = payload.get("UUID", "")
    return ProvisioningProfile(
        name=str(payload.get("Name", "") or path.name),
        app_id=str(app_id) if isinstance(app_id, str) else "",
        entitlements=granted,
        uuid=uuid if isinstance(uuid, str) else "",
    )


def missing_entitlements(declared: Iterable[str], granted: Iterable[str]) -> list[str]:
    """Declared keys the profile does not grant, sorted.

    Key presence only — Apple's per-key grant semantics (wildcards, value
    formats) vary and are deliberately not modelled here.
    """
    granted_keys = set(granted)
    return sorted(key for key in declared if key not in granted_keys)


def preflight_entitlements(
    config: Config,
    project_root: Path,
    target: str,
    *,
    search_dirs: tuple[Path, ...] | None = None,
) -> list[str]:
    """Check declared entitlements against a pinned profile (spec 05 step 7).

    Raises ``SigningError`` under manual signing, where the pinned profile is the
    one that will sign and a missing key is a certain ``codesign`` failure. Under
    automatic signing the missing keys are *returned* instead, so the caller can
    warn while letting Xcode's ``-allowProvisioningUpdates`` try to register them
    mid-build.

    Returns an empty list whenever there is nothing to compare: a target that
    does not sign, no declared entitlements, no pinned profile, a pinned profile
    that cannot be found, or one that cannot be parsed (``doctor`` reports those
    cases — they should not block a build).
    """
    if target == "simulator":
        return []
    declared = config.ios_required.entitlements
    if not declared:
        return []
    path = resolve_profile_path(config, project_root, search_dirs=search_dirs)
    if path is None or not path.exists():
        return []
    try:
        profile = read_profile(path)
    except ProfileError:
        return []

    missing = missing_entitlements(declared, profile.entitlements)
    if not missing:
        return []
    if config.ios_required.signing.auto_signing:
        return missing

    app_id = f"  (App ID: {profile.app_id})" if profile.app_id else ""
    raise SigningError(
        "entitlements declared in pyproject.toml are not granted by the "
        "provisioning profile.\n"
        f"  Profile: {profile.name}{app_id}\n"
        "  Not granted:\n"
        + "".join(f"    - {key}\n" for key in missing)
        + "  Fix one of these ways:\n"
        "    - Enable the matching capability on this App ID at "
        "developer.apple.com,\n"
        "      then regenerate and re-download the profile\n"
        "    - Remove the key from [tool.kivy.ios.entitlements], then re-lock"
    )

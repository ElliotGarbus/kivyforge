"""Generate ``<app>.entitlements`` from ``[tool.kivy.ios.entitlements]`` (spec 06).

Also reads a pinned ``.mobileprovision`` so ``build`` and ``doctor`` can check
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


def resolve_profile_path(config: Config, project_root: Path) -> Path | None:
    """Absolute path of the pinned profile, or None when none is configured."""
    profile = config.ios_required.signing.provisioning_profile
    if not profile:
        return None
    path = Path(profile)
    return path if path.is_absolute() else project_root / profile


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
    return ProvisioningProfile(
        name=str(payload.get("Name", "") or path.name),
        app_id=str(app_id) if isinstance(app_id, str) else "",
        entitlements=granted,
    )


def missing_entitlements(declared: Iterable[str], granted: Iterable[str]) -> list[str]:
    """Declared keys the profile does not grant, sorted.

    Key presence only — Apple's per-key grant semantics (wildcards, value
    formats) vary and are deliberately not modelled here.
    """
    granted_keys = set(granted)
    return sorted(key for key in declared if key not in granted_keys)


def preflight_entitlements(
    config: Config, project_root: Path, target: str
) -> list[str]:
    """Check declared entitlements against a pinned profile (spec 05 step 7).

    Raises ``SigningError`` under manual signing, where the pinned profile is the
    one that will sign and a missing key is a certain ``codesign`` failure. Under
    automatic signing the missing keys are *returned* instead, so the caller can
    warn while letting Xcode's ``-allowProvisioningUpdates`` try to register them
    mid-build.

    Returns an empty list whenever there is nothing to compare: a target that
    does not sign, no declared entitlements, no pinned profile, or a profile that
    cannot be parsed (``doctor`` reports that case — it should not block a build).
    """
    if target == "simulator":
        return []
    declared = config.ios_required.entitlements
    if not declared:
        return []
    path = resolve_profile_path(config, project_root)
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

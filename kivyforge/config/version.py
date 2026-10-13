"""Versions: PEP 440 normalization and what derives from the version.

Kept in the config layer, free of subprocesses and the CLI: resolving a *dynamic*
version through the build backend lives in :mod:`kivyforge.versioning`, and
both end here, in :func:`resolved`, so every source of a version is checked and
derived the same way (docs/design/dev/dynamic-version-proposal.md).
"""

from __future__ import annotations

from dataclasses import replace

from packaging.version import InvalidVersion, Version

from .errors import ConfigError
from .model import (
    ANDROID_VERSION_CODE_CEILING,
    AutoVersionCode,
    Config,
    ResolvedVersion,
)


def normalized(
    raw: str, *, what: str, key_path: str | None = None, line: int | None = None
) -> str:
    """*raw* in PEP 440's normalized form, or a ``ConfigError`` naming *what*.

    The pyproject spec defines ``version`` as a version per the version
    specifier spec, which also requires its normalizations: ``v1.2`` is valid
    and is ``1.2``. *what* names where the string came from (the key, the flag
    or the environment variable), because only a file has a line to point at.
    """
    try:
        return str(Version(raw))
    except InvalidVersion as exc:
        raise ConfigError(
            f"{what} {raw!r} is not a valid version",
            key_path=key_path,
            line=line,
            hint="a version must follow PEP 440, e.g. 1.2.3, 1.2.3rc1 or "
            "1.2.3.dev4; pip refuses to build a project whose version does not.",
        ) from exc


def android_auto_version_code(version: str, auto: AutoVersionCode) -> int:
    """``MAJOR*1_000_000 + MINOR*10_000 + PATCH*100 + build`` (android/01 rule 20).

    Raises ``ConfigError`` at the ``version_code`` line for a version with no
    monotonic integer mapping.
    """
    line = auto.line
    try:
        parsed = Version(version)
    except InvalidVersion as exc:
        raise ConfigError(
            f"[project].version {version!r} is not a valid version; "
            'version_code = "auto" cannot derive from it',
            key_path="tool.kivy.android.version_code",
            line=line,
        ) from exc
    if (
        parsed.is_prerelease
        or parsed.is_devrelease
        or parsed.is_postrelease
        or parsed.epoch != 0
        or parsed.local is not None
    ):
        raise ConfigError(
            f'version_code = "auto" requires a final MAJOR.MINOR.PATCH '
            f"[project].version; {version!r} is not one",
            key_path="tool.kivy.android.version_code",
            line=line,
            hint="pre-release/dev/post/local/epoch versions have no "
            "monotonic integer mapping; set an explicit integer "
            "version_code for those.",
        )
    release = parsed.release
    if len(release) > 3:
        raise ConfigError(
            f"[project].version {version!r} has a 4th numeric "
            'segment; version_code = "auto" supports MAJOR.MINOR.PATCH only',
            key_path="tool.kivy.android.version_code",
            line=line,
            hint="express the extra increment via the `build` counter.",
        )
    major, minor, patch = (*release, 0, 0)[:3]
    if minor > 99 or patch > 99:
        raise ConfigError(
            f"MINOR and PATCH must each be <= 99 for "
            f'version_code = "auto"; got {version!r}',
            key_path="tool.kivy.android.version_code",
            line=line,
        )
    code = major * 1_000_000 + minor * 10_000 + patch * 100 + auto.build
    if code > ANDROID_VERSION_CODE_CEILING:
        raise ConfigError(
            f"auto-derived version_code {code:,} exceeds Google Play's "
            f"ceiling of {ANDROID_VERSION_CODE_CEILING:,}",
            key_path="tool.kivy.android.version_code",
            line=line,
        )
    return code


def android_version_code(config: Config) -> int:
    """The ``versionCode`` for the version *config* builds with.

    An explicit integer verbatim; ``"auto"`` derived from the resolved version,
    so an override or a backend's version is what counts, not the declaration.
    Raises ``ConfigError`` at the ``version_code`` line when that version has no
    integer mapping (a dev version, say).
    """
    declared = config.android_required.version_code
    if isinstance(declared, AutoVersionCode):
        return android_auto_version_code(config.version_required.value, declared)
    return declared


def with_version(config: Config, version: ResolvedVersion | None) -> Config:
    """*config* carrying the version its verb resolved (unchanged for ``None``)."""
    if version is None:
        return config
    return replace(config, resolved_version=version)

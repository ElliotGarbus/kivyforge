"""Parse ``pylock.ios.toml`` back into a ``Lockfile`` and detect drift (spec 02).

The neutral drift helpers (``LockError``, ``compute_pyproject_sha256``,
``is_in_sync``) live in ``kivyforge.lock.reader``; this module adds the iOS
``pylock.ios.toml`` parsing on top.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from kivyforge.lock.pep751 import parse_package as _parse_package
from kivyforge.lock.reader import (
    LockError,
    compute_pyproject_sha256,
    is_in_sync,
)

from .model import (
    LOCK_VERSION,
    TOOL_SCHEMA_VERSION,
    LockedSwiftPackage,
    LockedXcframework,
    Lockfile,
    PythonXcframework,
)

__all__ = [
    "LockError",
    "compute_pyproject_sha256",
    "is_in_sync",
    "load",
    "loads",
]

# Highest major lock-version (PEP 751 top-level) this reader accepts.
SUPPORTED_LOCK_VERSION_MAJOR = int(LOCK_VERSION.split(".", 1)[0])
# Highest [tool.kivyforge].schema_version (the extension's own schema) accepted.
SUPPORTED_TOOL_SCHEMA_VERSION = TOOL_SCHEMA_VERSION


def loads(text: str) -> Lockfile:
    """Parse ``pylock.ios.toml`` text into a ``Lockfile``.

    ``kivyforge lock`` is the writer, so the reader's job is to fail *cleanly*
    when the file is corrupt, hand-edited, or from a future schema — never to
    leak a raw ``KeyError``/``TypeError``. Every shape failure surfaces as
    ``LockError``.
    """
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise LockError(f"pylock.ios.toml is not valid TOML: {exc}") from exc
    if not isinstance(raw, dict):
        raise LockError("pylock.ios.toml must be a TOML table.")
    try:
        return _from_raw(raw)
    except LockError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        # A missing/mistyped field anywhere in the tree — name the trigger but
        # don't leak the raw exception type to callers.
        raise LockError(f"pylock.ios.toml is malformed: {exc!r}") from exc


def load(path: str | Path) -> Lockfile:
    return loads(Path(path).read_text(encoding="utf-8"))


def _from_raw(raw: dict) -> Lockfile:
    lock_version = _check_lock_version(raw)

    tool_raw = raw.get("tool", {})
    if not isinstance(tool_raw, dict):
        raise LockError("pylock.ios.toml [tool] must be a table.")
    tool = tool_raw.get("kivyforge", {})
    if not isinstance(tool, dict) or not tool:
        raise LockError("pylock.ios.toml is missing the [tool.kivyforge] table.")

    schema_version = _check_tool_schema_version(tool)
    python_xcframework = _parse_python_xcframework(tool)

    packages = tuple(_parse_package(p) for p in _as_list(raw, "packages"))
    xcframeworks = tuple(_parse_xcframework(x) for x in _as_list(tool, "xcframeworks"))
    swift_packages = tuple(
        _parse_swift_package(s) for s in _as_list(tool, "swift_packages")
    )

    return Lockfile(
        requires_python=raw.get("requires-python", ">=3.15"),
        packages=packages,
        python_xcframework=python_xcframework,
        kivyforge_version=tool.get("kivyforge_version", ""),
        generated_at=tool.get("generated_at", ""),
        pyproject_sha256=tool.get("pyproject_sha256", ""),
        tool_kivyforge_schema_version=tool.get("tool_kivyforge_schema_version", 1),
        xcframeworks=xcframeworks,
        swift_packages=swift_packages,
        schema_version=schema_version,
        lock_version=lock_version,
        created_by=raw.get("created-by", "kivyforge"),
        extras=tuple(raw.get("extras", [])),
        dependency_groups=tuple(raw.get("dependency-groups", [])),
        default_groups=tuple(raw.get("default-groups", [])),
    )


def _check_lock_version(raw: dict) -> str:
    lock_version = raw.get("lock-version", LOCK_VERSION)
    if not isinstance(lock_version, str):
        raise LockError("pylock.ios.toml lock-version must be a string.")
    major = lock_version.split(".", 1)[0]
    if not major.isdigit():
        raise LockError(
            f"pylock.ios.toml lock-version {lock_version!r} is not a valid version."
        )
    if int(major) > SUPPORTED_LOCK_VERSION_MAJOR:
        raise LockError(
            f"pylock.ios.toml lock-version {lock_version} is newer than this "
            f"kivyforge understands (max {SUPPORTED_LOCK_VERSION_MAJOR}.x). "
            "Upgrade kivyforge."
        )
    return lock_version


def _check_tool_schema_version(tool: dict) -> int:
    schema_version = tool.get("schema_version", SUPPORTED_TOOL_SCHEMA_VERSION)
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise LockError("[tool.kivyforge].schema_version must be an integer.")
    if schema_version > SUPPORTED_TOOL_SCHEMA_VERSION:
        raise LockError(
            f"[tool.kivyforge].schema_version {schema_version} is newer than this "
            f"kivyforge understands (max {SUPPORTED_TOOL_SCHEMA_VERSION}). "
            "Upgrade kivyforge."
        )
    return schema_version


def _parse_python_xcframework(tool: dict) -> PythonXcframework:
    px = tool.get("python_xcframework")
    if not isinstance(px, dict) or not px:
        raise LockError(
            "pylock.ios.toml is missing [tool.kivyforge.python_xcframework]."
        )
    for field in ("version", "url", "sha256"):
        value = px.get(field)
        if not isinstance(value, str) or not value:
            raise LockError(
                f"[tool.kivyforge.python_xcframework].{field} is missing or empty."
            )
    return PythonXcframework(version=px["version"], url=px["url"], sha256=px["sha256"])


def _as_list(table: dict, key: str) -> list:
    value = table.get(key, [])
    if not isinstance(value, list):
        raise LockError(f"pylock.ios.toml {key!r} must be an array of tables.")
    return value


def _parse_xcframework(x: dict) -> LockedXcframework:
    return LockedXcframework(
        name=x["name"],
        version=x["version"],
        sha256=x.get("sha256", ""),
        slices=tuple(x.get("slices", [])),
        url=x.get("url"),
        path=x.get("path"),
        archive_format=x.get("archive_format", "zip"),
        archive_member=x.get("archive_member"),
        privacy_manifest_path=x.get("privacy_manifest_path"),
        link=bool(x.get("link", True)),
        embed=bool(x.get("embed", True)),
        source=x.get("source"),
    )


def _parse_swift_package(s: dict) -> LockedSwiftPackage:
    requirement = s.get("requirement")
    return LockedSwiftPackage(
        name=s["name"],
        products=tuple(s.get("products", [])),
        url=s.get("url"),
        path=s.get("path"),
        requirement=dict(requirement) if requirement else None,
        revision=s.get("revision"),
        version=s.get("version"),
        link=bool(s.get("link", True)),
        embed=bool(s.get("embed", True)),
    )

"""Parse ``pylock.android.toml`` back into an ``AndroidLockfile`` (android/02).

The neutral drift helpers (``LockError``, ``compute_pyproject_sha256``,
``is_in_sync``) live in ``kivyforge.lock.reader``; this module adds the Android
``pylock.android.toml`` parsing on top. The reader fails *cleanly* on corrupt,
hand-edited, or future-schema files — never a raw ``KeyError``.
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
    AndroidLockfile,
    GradleArtifact,
    GradlePins,
    GradleResolvedModule,
    LockedAndroidLib,
    LockedIncludeFile,
    PythonAndroidRuntime,
)

__all__ = [
    "LockError",
    "compute_pyproject_sha256",
    "is_in_sync",
    "load",
    "loads",
]

SUPPORTED_LOCK_VERSION_MAJOR = int(LOCK_VERSION.split(".", 1)[0])
SUPPORTED_TOOL_SCHEMA_VERSION = TOOL_SCHEMA_VERSION


def loads(text: str) -> AndroidLockfile:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise LockError(f"pylock.android.toml is not valid TOML: {exc}") from exc
    if not isinstance(raw, dict):
        raise LockError("pylock.android.toml must be a TOML table.")
    try:
        return _from_raw(raw)
    except LockError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise LockError(f"pylock.android.toml is malformed: {exc!r}") from exc


def load(path: str | Path) -> AndroidLockfile:
    return loads(Path(path).read_text(encoding="utf-8"))


def _from_raw(raw: dict) -> AndroidLockfile:
    lock_version = _check_lock_version(raw)

    tool_raw = raw.get("tool", {})
    if not isinstance(tool_raw, dict):
        raise LockError("pylock.android.toml [tool] must be a table.")
    tool = tool_raw.get("kivyforge", {})
    if not isinstance(tool, dict) or not tool:
        raise LockError("pylock.android.toml is missing the [tool.kivyforge] table.")

    schema_version = _check_tool_schema_version(tool)

    runtimes = tuple(_parse_runtime(r) for r in _as_list(tool, "python_android"))
    if not runtimes:
        raise LockError(
            "pylock.android.toml has no [[tool.kivyforge.python_android]] "
            "entries; re-run `kivyforge lock -p android`."
        )
    packages = tuple(_parse_package(p) for p in _as_list(raw, "packages"))
    android_libs = tuple(_parse_lib(x) for x in _as_list(tool, "android_libs"))
    gradle = _parse_gradle(tool.get("gradle"))
    include_files = tuple(
        _parse_include_file(f) for f in _as_list(tool, "include_files")
    )

    sdl = tool.get("sdl", 2)
    if sdl not in (2, 3):
        raise LockError(f"pylock.android.toml [tool.kivyforge].sdl {sdl!r} invalid.")

    return AndroidLockfile(
        requires_python=raw.get("requires-python", ">=3.14"),
        packages=packages,
        python_android=runtimes,
        kivyforge_version=tool.get("kivyforge_version", ""),
        generated_at=tool.get("generated_at", ""),
        pyproject_sha256=tool.get("pyproject_sha256", ""),
        tool_kivy_android_schema_version=tool.get(
            "tool_kivy_android_schema_version", 1
        ),
        sdl=sdl,
        android_libs=android_libs,
        gradle=gradle,
        include_files=include_files,
        schema_version=schema_version,
        lock_version=lock_version,
        created_by=raw.get("created-by", "kivyforge"),
        extras=tuple(raw.get("extras", [])),
        dependency_groups=tuple(raw.get("dependency-groups", [])),
        default_groups=tuple(raw.get("default-groups", [])),
    )


def _parse_runtime(entry: dict) -> PythonAndroidRuntime:
    return PythonAndroidRuntime(
        version=entry["version"],
        abi=entry["abi"],
        url=entry.get("url"),
        path=entry.get("path"),
        sha256=entry["sha256"],
        min_api=int(entry.get("min_api", 24)),
    )


def _parse_lib(entry: dict) -> LockedAndroidLib:
    return LockedAndroidLib(
        name=entry["name"],
        kind=entry["kind"],
        version=entry["version"],
        url=entry.get("url"),
        path=entry.get("path"),
        sha256=entry["sha256"],
    )


def _parse_gradle(table: object) -> GradlePins:
    if table is None:
        return GradlePins()
    if not isinstance(table, dict):
        raise LockError("pylock.android.toml [tool.kivyforge.gradle] must be a table.")
    resolved = tuple(
        GradleResolvedModule(
            coordinate=m["coordinate"],
            artifacts=tuple(
                GradleArtifact(name=a["name"], sha256=a["sha256"])
                for a in m.get("artifacts", [])
            ),
        )
        for m in table.get("resolved", [])
    )
    return GradlePins(
        dependencies=tuple(table.get("dependencies", [])),
        repositories=tuple(table.get("repositories", [])),
        resolved=resolved,
    )


def _parse_include_file(entry: dict) -> LockedIncludeFile:
    return LockedIncludeFile(
        source=entry["source"], dest=entry["dest"], sha256=entry["sha256"]
    )


def _check_lock_version(raw: dict) -> str:
    lock_version = raw.get("lock-version", LOCK_VERSION)
    if not isinstance(lock_version, str):
        raise LockError("pylock.android.toml lock-version must be a string.")
    major = lock_version.split(".", 1)[0]
    if not major.isdigit():
        raise LockError(
            f"pylock.android.toml lock-version {lock_version!r} is not a valid version."
        )
    if int(major) > SUPPORTED_LOCK_VERSION_MAJOR:
        raise LockError(
            f"pylock.android.toml lock-version {lock_version} is newer than "
            f"this kivyforge understands (<= {SUPPORTED_LOCK_VERSION_MAJOR}.x); "
            "upgrade kivyforge."
        )
    return lock_version


def _check_tool_schema_version(tool: dict) -> int:
    schema_version = tool.get("schema_version", TOOL_SCHEMA_VERSION)
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise LockError(
            "pylock.android.toml [tool.kivyforge].schema_version must be an integer."
        )
    if schema_version > SUPPORTED_TOOL_SCHEMA_VERSION:
        raise LockError(
            f"pylock.android.toml [tool.kivyforge].schema_version "
            f"{schema_version} is newer than this kivyforge understands "
            f"(<= {SUPPORTED_TOOL_SCHEMA_VERSION}); upgrade kivyforge."
        )
    return schema_version


def _as_list(table: dict, key: str) -> list:
    value = table.get(key, [])
    if not isinstance(value, list):
        raise LockError(f"pylock.android.toml {key!r} must be an array of tables.")
    return value

"""Serialize/parse ``pylock.<platform>.toml`` for the wheel+runtime family.

Reuses the platform-neutral PEP 751 ``[[packages]]`` emitter/parser
(``kivyforge.lock.pep751``) and adds the ``[tool.kivyforge]`` extension: the arch
set plus the bundled Python runtime pin (provider + per-arch artifacts). The
platform is carried by the filename, so ``loads``/``load`` take it explicitly
(used only for clear error messages and to stamp the model).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from ..model import LOCK_VERSION
from ..pep751 import arr as _arr
from ..pep751 import emit_package as _emit_package
from ..pep751 import parse_package as _parse_package
from ..pep751 import s as _s
from ..reader import LockError
from .model import (
    TOOL_SCHEMA_VERSION,
    LockedNativeBinary,
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)

SUPPORTED_LOCK_VERSION_MAJOR = int(LOCK_VERSION.split(".", 1)[0])
SUPPORTED_TOOL_SCHEMA_VERSION = TOOL_SCHEMA_VERSION


def dumps(lock: WheelRuntimeLock) -> str:
    lines: list[str] = []

    lines.append(f"lock-version = {_s(lock.lock_version)}")
    lines.append(f"created-by = {_s(lock.created_by)}")
    lines.append(f"requires-python = {_s(lock.requires_python)}")
    lines.append(f"extras = {_arr(lock.extras)}")
    lines.append(f"dependency-groups = {_arr(lock.dependency_groups)}")
    lines.append(f"default-groups = {_arr(lock.default_groups)}")
    lines.append("")

    for pkg in sorted(lock.packages, key=lambda p: p.sort_key):
        _emit_package(lines, pkg)

    lines.append("[tool.kivyforge]")
    lines.append(f"schema_version = {lock.schema_version}")
    lines.append(f"kivyforge_version = {_s(lock.kivyforge_version)}")
    lines.append(f"generated_at = {_s(lock.generated_at)}")
    lines.append(f"pyproject_sha256 = {_s(lock.pyproject_sha256)}")
    lines.append(
        f"tool_kivyforge_schema_version = {lock.tool_kivyforge_schema_version}"
    )
    lines.append(f"archs = {_arr(lock.archs)}")
    lines.append("")
    lines.append("[tool.kivyforge.python_runtime]")
    lines.append(f"provider = {_s(lock.python_runtime.provider)}")
    lines.append(f"version = {_s(lock.python_runtime.version)}")
    if lock.python_runtime.floor:
        lines.append(f"floor = {_s(lock.python_runtime.floor)}")

    for art in sorted(lock.python_runtime.artifacts, key=lambda a: a.arch):
        lines.append("")
        lines.append("[[tool.kivyforge.python_runtime.artifacts]]")
        lines.append(f"arch = {_s(art.arch)}")
        lines.append(f"url = {_s(art.url)}")
        lines.append(f"sha256 = {_s(art.sha256)}")
        lines.append(f"archive_format = {_s(art.archive_format)}")

    for nb in sorted(lock.native_binaries, key=lambda b: b.name):
        lines.append("")
        lines.append("[[tool.kivyforge.native_binaries]]")
        lines.append(f"name = {_s(nb.name)}")
        lines.append(f"version = {_s(nb.version)}")
        if nb.url is not None:
            lines.append(f"url = {_s(nb.url)}")
        else:
            lines.append(f"path = {_s(nb.path)}")
        lines.append(f"sha256 = {_s(nb.sha256)}")

    return "\n".join(lines) + "\n"


def loads(text: str, *, platform: str) -> WheelRuntimeLock:
    name = f"pylock.{platform}.toml"
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise LockError(f"{name} is not valid TOML: {exc}") from exc
    if not isinstance(raw, dict):
        raise LockError(f"{name} must be a TOML table.")
    try:
        return _from_raw(raw, platform=platform, name=name)
    except LockError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise LockError(f"{name} is malformed: {exc!r}") from exc


def load(path: str | Path, *, platform: str) -> WheelRuntimeLock:
    return loads(Path(path).read_text(encoding="utf-8"), platform=platform)


def _from_raw(raw: dict, *, platform: str, name: str) -> WheelRuntimeLock:
    lock_version = _check_lock_version(raw, name)

    tool_raw = raw.get("tool", {})
    if not isinstance(tool_raw, dict):
        raise LockError(f"{name} [tool] must be a table.")
    tool = tool_raw.get("kivyforge", {})
    if not isinstance(tool, dict) or not tool:
        raise LockError(f"{name} is missing the [tool.kivyforge] table.")

    schema_version = _check_tool_schema_version(tool)
    runtime = _parse_runtime(tool, name)
    native_binaries = _parse_native_binaries(tool, name)

    packages = tuple(_parse_package(p) for p in _as_list(raw, "packages", name))

    return WheelRuntimeLock(
        platform=platform,
        requires_python=raw.get("requires-python", ">=3.15"),
        packages=packages,
        python_runtime=runtime,
        archs=tuple(tool.get("archs", [])),
        kivyforge_version=tool.get("kivyforge_version", ""),
        generated_at=tool.get("generated_at", ""),
        pyproject_sha256=tool.get("pyproject_sha256", ""),
        tool_kivyforge_schema_version=tool.get("tool_kivyforge_schema_version", 1),
        schema_version=schema_version,
        lock_version=lock_version,
        created_by=raw.get("created-by", "kivyforge"),
        extras=tuple(raw.get("extras", [])),
        dependency_groups=tuple(raw.get("dependency-groups", [])),
        default_groups=tuple(raw.get("default-groups", [])),
        native_binaries=native_binaries,
    )


def _check_lock_version(raw: dict, name: str) -> str:
    lock_version = raw.get("lock-version", LOCK_VERSION)
    if not isinstance(lock_version, str):
        raise LockError(f"{name} lock-version must be a string.")
    major = lock_version.split(".", 1)[0]
    if not major.isdigit():
        raise LockError(f"{name} lock-version {lock_version!r} is not a valid version.")
    if int(major) > SUPPORTED_LOCK_VERSION_MAJOR:
        raise LockError(
            f"{name} lock-version {lock_version} is newer than this kivyforge "
            f"understands (max {SUPPORTED_LOCK_VERSION_MAJOR}.x). Upgrade kivyforge."
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


def _parse_runtime(tool: dict, name: str) -> PythonRuntime:
    rt = tool.get("python_runtime")
    if not isinstance(rt, dict) or not rt:
        raise LockError(f"{name} is missing [tool.kivyforge.python_runtime].")
    for field in ("provider", "version"):
        value = rt.get(field)
        if not isinstance(value, str) or not value:
            raise LockError(
                f"[tool.kivyforge.python_runtime].{field} is missing or empty."
            )
    artifacts_raw = rt.get("artifacts", [])
    if not isinstance(artifacts_raw, list) or not artifacts_raw:
        raise LockError(
            "[tool.kivyforge.python_runtime] must list at least one artifact."
        )
    artifacts = []
    for a in artifacts_raw:
        for field in ("arch", "url", "sha256"):
            if not isinstance(a.get(field), str) or not a.get(field):
                raise LockError(
                    f"a [tool.kivyforge.python_runtime.artifacts] entry is "
                    f"missing {field!r}."
                )
        artifacts.append(
            RuntimeArtifact(
                arch=a["arch"],
                url=a["url"],
                sha256=a["sha256"],
                archive_format=a.get("archive_format", "tar.gz"),
            )
        )
    return PythonRuntime(
        provider=rt["provider"],
        version=rt["version"],
        artifacts=tuple(artifacts),
        floor=rt.get("floor"),
    )


def _parse_native_binaries(tool: dict, name: str) -> tuple[LockedNativeBinary, ...]:
    raw = tool.get("native_binaries", [])
    if not isinstance(raw, list):
        raise LockError(f"{name} [tool.kivyforge.native_binaries] must be an array.")
    out: list[LockedNativeBinary] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise LockError(
                f"{name} [[tool.kivyforge.native_binaries]] entries must be tables."
            )
        for field in ("name", "version", "sha256"):
            if not isinstance(entry.get(field), str) or not entry.get(field):
                raise LockError(
                    f"a [[tool.kivyforge.native_binaries]] entry is missing {field!r}."
                )
        url = entry.get("url")
        path = entry.get("path")
        if bool(url) == bool(path):
            raise LockError(
                f"native binary {entry['name']!r} must have exactly one of url/path."
            )
        out.append(
            LockedNativeBinary(
                name=entry["name"],
                version=entry["version"],
                sha256=entry["sha256"],
                url=url,
                path=path,
            )
        )
    return tuple(sorted(out, key=lambda b: b.name))


def _as_list(table: dict, key: str, name: str) -> list:
    value = table.get(key, [])
    if not isinstance(value, list):
        raise LockError(f"{name} {key!r} must be an array of tables.")
    return value

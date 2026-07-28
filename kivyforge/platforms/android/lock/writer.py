"""Serialize an ``AndroidLockfile`` to ``pylock.android.toml`` text (android/02).

Hand-rolled emitter like the iOS writer: exact PEP 751 layout via the shared
``kivyforge.lock.pep751`` helpers, deterministic ordering everywhere (packages
by name/version, wheels by filename, runtimes by ABI, libs by name, resolved
Maven modules by coordinate) so re-lock diffs show only real changes.
"""

from __future__ import annotations

from kivyforge.lock.pep751 import arr as _arr
from kivyforge.lock.pep751 import emit_package as _emit_package
from kivyforge.lock.pep751 import s as _s

from .model import (
    AndroidLockfile,
    GradleResolvedModule,
    LockedAndroidLib,
    PythonAndroidRuntime,
)


def dumps(lock: AndroidLockfile) -> str:
    lines: list[str] = []

    # --- PEP 751 top-level scalars ---
    lines.append(f"lock-version = {_s(lock.lock_version)}")
    lines.append(f"created-by = {_s(lock.created_by)}")
    lines.append(f"requires-python = {_s(lock.requires_python)}")
    lines.append(f"extras = {_arr(lock.extras)}")
    lines.append(f"dependency-groups = {_arr(lock.dependency_groups)}")
    lines.append(f"default-groups = {_arr(lock.default_groups)}")
    lines.append("")

    # --- [[packages]] (deterministic order) ---
    for pkg in sorted(lock.packages, key=lambda p: p.sort_key):
        _emit_package(lines, pkg)

    # --- [tool.kivyforge] extension ---
    lines.append("[tool.kivyforge]")
    lines.append(f"schema_version = {lock.schema_version}")
    lines.append(f"kivyforge_version = {_s(lock.kivyforge_version)}")
    lines.append(f"generated_at = {_s(lock.generated_at)}")
    lines.append(f"pyproject_sha256 = {_s(lock.pyproject_sha256)}")
    lines.append(
        f"tool_kivy_android_schema_version = {lock.tool_kivy_android_schema_version}"
    )
    lines.append(f"kivy_generation = {lock.kivy_generation}")

    # --- [[tool.kivyforge.python_android]] (one per ABI, sorted) ---
    for runtime in sorted(lock.python_android, key=lambda r: r.abi):
        lines.append("")
        _emit_runtime(lines, runtime)

    # --- [[tool.kivyforge.android_libs]] ---
    for lib in sorted(lock.android_libs, key=lambda x: (x.name.lower(), x.version)):
        lines.append("")
        _emit_android_lib(lines, lib)

    # --- [tool.kivyforge.gradle] (only when Maven deps are declared) ---
    if lock.gradle.declared:
        lines.append("")
        lines.append("[tool.kivyforge.gradle]")
        lines.append(f"dependencies = {_arr(lock.gradle.dependencies)}")
        lines.append(f"repositories = {_arr(lock.gradle.repositories)}")
        for module in sorted(lock.gradle.resolved, key=lambda m: m.coordinate):
            lines.append("")
            _emit_resolved_module(lines, module)

    # --- [[tool.kivyforge.include_files]] ---
    for pin in sorted(lock.include_files, key=lambda p: (p.dest, p.source)):
        lines.append("")
        lines.append("[[tool.kivyforge.include_files]]")
        lines.append(f"source = {_s(pin.source)}")
        lines.append(f"dest = {_s(pin.dest)}")
        lines.append(f"sha256 = {_s(pin.sha256)}")

    return "\n".join(lines) + "\n"


def _emit_runtime(lines: list[str], runtime: PythonAndroidRuntime) -> None:
    lines.append("[[tool.kivyforge.python_android]]")
    lines.append(f"version = {_s(runtime.version)}")
    lines.append(f"abi = {_s(runtime.abi)}")
    if runtime.url:
        lines.append(f"url = {_s(runtime.url)}")
    else:
        path = runtime.path
        assert path is not None
        lines.append(f"path = {_s(path)}")
    lines.append(f"sha256 = {_s(runtime.sha256)}")
    lines.append(f"min_api = {runtime.min_api}")


def _emit_android_lib(lines: list[str], lib: LockedAndroidLib) -> None:
    lines.append("[[tool.kivyforge.android_libs]]")
    lines.append(f"name = {_s(lib.name)}")
    lines.append(f"kind = {_s(lib.kind)}")
    lines.append(f"version = {_s(lib.version)}")
    if lib.url:
        lines.append(f"url = {_s(lib.url)}")
    else:
        path = lib.path
        assert path is not None
        lines.append(f"path = {_s(path)}")
    lines.append(f"sha256 = {_s(lib.sha256)}")


def _emit_resolved_module(lines: list[str], module: GradleResolvedModule) -> None:
    lines.append("[[tool.kivyforge.gradle.resolved]]")
    lines.append(f"coordinate = {_s(module.coordinate)}")
    artifacts = sorted(module.artifacts, key=lambda a: a.name)
    if not artifacts:
        lines.append("artifacts = []")
        return
    lines.append("artifacts = [")
    for artifact in artifacts:
        lines.append(
            f"    {{ name = {_s(artifact.name)}, sha256 = {_s(artifact.sha256)} }},"
        )
    lines.append("]")

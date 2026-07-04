"""Serialize a ``Lockfile`` to ``pylock.ios.toml`` text (spec 02).

Hand-rolled emitter (rather than a generic TOML writer) so we control the
exact PEP 751 layout — inline ``hashes`` tables, ``[packages.tool.kivyforge]``
placement, and a deterministic ordering (packages sorted by name/version,
wheels by filename) so diffs across runs show only real changes.
"""

from __future__ import annotations

from .model import (
    LockedSwiftPackage,
    LockedXcframework,
    Lockfile,
)
from .pep751 import arr as _arr
from .pep751 import b as _b
from .pep751 import emit_package as _emit_package
from .pep751 import s as _s


def dumps(lock: Lockfile) -> str:
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
        f"tool_kivyforge_schema_version = {lock.tool_kivyforge_schema_version}"
    )
    lines.append("")
    lines.append("[tool.kivyforge.python_xcframework]")
    lines.append(f"version = {_s(lock.python_xcframework.version)}")
    lines.append(f"url = {_s(lock.python_xcframework.url)}")
    lines.append(f"sha256 = {_s(lock.python_xcframework.sha256)}")

    # --- [[tool.kivyforge.xcframeworks]] (deterministic order) ---
    for xc in sorted(lock.xcframeworks, key=lambda x: (x.name.lower(), x.version)):
        lines.append("")
        _emit_xcframework(lines, xc)

    # --- [[tool.kivyforge.swift_packages]] (deterministic order) ---
    for sp in sorted(lock.swift_packages, key=lambda s: s.name):
        lines.append("")
        _emit_swift_package(lines, sp)

    return "\n".join(lines) + "\n"


def _emit_xcframework(lines: list[str], xc: LockedXcframework) -> None:
    lines.append("[[tool.kivyforge.xcframeworks]]")
    lines.append(f"name = {_s(xc.name)}")
    lines.append(f"version = {_s(xc.version)}")
    if xc.url:
        lines.append(f"url = {_s(xc.url)}")
    else:
        path = xc.path
        assert path is not None
        lines.append(f"path = {_s(path)}")
    lines.append(f"sha256 = {_s(xc.sha256)}")
    lines.append(f"slices = {_arr(xc.slices)}")
    lines.append(f"archive_format = {_s(xc.archive_format)}")
    if xc.archive_member:
        lines.append(f"archive_member = {_s(xc.archive_member)}")
    if xc.privacy_manifest_path:
        lines.append(f"privacy_manifest_path = {_s(xc.privacy_manifest_path)}")
    lines.append(f"link = {_b(xc.link)}")
    lines.append(f"embed = {_b(xc.embed)}")
    if xc.source:
        lines.append(f"source = {_s(xc.source)}")


def _emit_swift_package(lines: list[str], sp: LockedSwiftPackage) -> None:
    lines.append("[[tool.kivyforge.swift_packages]]")
    lines.append(f"name = {_s(sp.name)}")
    if sp.url:
        lines.append(f"url = {_s(sp.url)}")
    else:
        path = sp.path
        assert path is not None
        lines.append(f"path = {_s(path)}")
    if sp.requirement:
        lines.append(f"requirement = {_requirement_inline(sp.requirement)}")
    if sp.revision:
        lines.append(f"revision = {_s(sp.revision)}")
    if sp.version:
        lines.append(f"version = {_s(sp.version)}")
    lines.append(f"products = {_arr(sp.products)}")
    lines.append(f"link = {_b(sp.link)}")
    lines.append(f"embed = {_b(sp.embed)}")


def _requirement_inline(requirement: dict[str, object]) -> str:
    ((kind, value),) = requirement.items()
    if isinstance(value, list):
        return f"{{ {kind} = {_arr([str(v) for v in value])} }}"
    return f"{{ {kind} = {_s(str(value))} }}"

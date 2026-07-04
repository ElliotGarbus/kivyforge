"""Shared, platform-neutral PEP 751 serialization helpers.

Both the iOS and macOS lock writers/readers emit and parse the ``[[packages]]``
wheels section identically; only the per-platform ``[tool.kivyforge]`` extension
(the iOS ``python_xcframework``/xcframeworks/swift_packages vs. the macOS python
runtime) differs. Keeping the ``[[packages]]`` machinery here means a single
source of truth for the PEP 751 layout and string escaping.
"""

from __future__ import annotations

from .model import LockedPackage, LockedWheel, PackageDep


def s(value: str) -> str:
    """Emit a TOML basic string with minimal escaping."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def arr(values) -> str:
    if not values:
        return "[]"
    return "[" + ", ".join(s(v) for v in values) + "]"


def b(value: bool) -> str:
    return "true" if value else "false"


def emit_package(lines: list[str], pkg: LockedPackage) -> None:
    lines.append("[[packages]]")
    lines.append(f"name = {s(pkg.name)}")
    lines.append(f"version = {s(pkg.version)}")
    if pkg.requires_python:
        lines.append(f"requires-python = {s(pkg.requires_python)}")
    if pkg.marker:
        lines.append(f"marker = {s(pkg.marker)}")
    if pkg.dependencies:
        deps = ", ".join(_dep_inline(d) for d in pkg.dependencies)
        lines.append(f"dependencies = [{deps}]")

    if pkg.direct_requirement or pkg.source_index:
        lines.append("")
        lines.append("[packages.tool.kivyforge]")
        if pkg.direct_requirement:
            lines.append("direct_requirement = true")
        if pkg.source_index:
            lines.append(f"source_index = {s(pkg.source_index)}")

    for wheel in sorted(pkg.wheels, key=lambda w: w.name):
        lines.append("")
        emit_wheel(lines, wheel)
    lines.append("")


def emit_wheel(lines: list[str], wheel: LockedWheel) -> None:
    lines.append("[[packages.wheels]]")
    lines.append(f"name = {s(wheel.name)}")
    if wheel.upload_time:
        lines.append(f"upload-time = {s(wheel.upload_time)}")
    if wheel.url:
        lines.append(f"url = {s(wheel.url)}")
    else:
        path = wheel.path
        assert path is not None
        lines.append(f"path = {s(path)}")
    lines.append(f"hashes = {{ sha256 = {s(wheel.sha256)} }}")
    if wheel.size is not None:
        lines.append(f"size = {wheel.size}")


def parse_package(p: dict) -> LockedPackage:
    tool = p.get("tool", {}).get("kivyforge", {})
    deps = tuple(
        PackageDep(name=d["name"], marker=d.get("marker"))
        for d in p.get("dependencies", [])
    )
    wheels = tuple(parse_wheel(w) for w in p.get("wheels", []))
    return LockedPackage(
        name=p["name"],
        version=p["version"],
        wheels=wheels,
        requires_python=p.get("requires-python"),
        dependencies=deps,
        marker=p.get("marker"),
        direct_requirement=bool(tool.get("direct_requirement", False)),
        source_index=tool.get("source_index"),
    )


def parse_wheel(w: dict) -> LockedWheel:
    return LockedWheel(
        name=w["name"],
        sha256=w.get("hashes", {}).get("sha256", ""),
        url=w.get("url"),
        path=w.get("path"),
        upload_time=w.get("upload-time"),
        size=w.get("size"),
    )


def _dep_inline(dep: PackageDep) -> str:
    if dep.marker:
        return f"{{ name = {s(dep.name)}, marker = {s(dep.marker)} }}"
    return f"{{ name = {s(dep.name)} }}"

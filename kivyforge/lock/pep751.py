"""Shared, platform-neutral PEP 751 serialization helpers.

Both the iOS and macOS lock writers/readers emit and parse the ``[[packages]]``
wheels section identically; only the per-platform ``[tool.kivyforge]`` extension
(the iOS ``python_xcframework``/xcframeworks/swift_packages vs. the macOS python
runtime) differs. Keeping the ``[[packages]]`` machinery here means a single
source of truth for the PEP 751 layout and string escaping.
"""

from __future__ import annotations

from .model import (
    LockedIncludeFile,
    LockedPackage,
    LockedSwiftPackage,
    LockedWheel,
    PackageDep,
)


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
    if pkg.source_index:
        # PEP 751's own key: the index the package's files were found on (#86).
        lines.append(f"index = {s(pkg.source_index)}")

    if pkg.direct_requirement:
        lines.append("")
        lines.append("[packages.tool.kivyforge]")
        lines.append("direct_requirement = true")

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
        # ``[packages.tool.kivyforge] source_index`` was never written, but a
        # hand-edited lock may carry it; PEP 751's ``index`` is what we write.
        source_index=p.get("index") or tool.get("source_index"),
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


def emit_include_files(lines: list[str], pins) -> None:
    """``[[tool.kivyforge.include_files]]``, one table per pin, sorted."""
    for pin in sorted(pins, key=lambda p: p.key):
        lines.append("")
        lines.append("[[tool.kivyforge.include_files]]")
        lines.append(f"source = {s(pin.source)}")
        lines.append(f"dest = {s(pin.dest)}")
        lines.append(f"sha256 = {s(pin.sha256)}")


def parse_include_file(entry: dict) -> LockedIncludeFile:
    return LockedIncludeFile(
        source=entry["source"], dest=entry["dest"], sha256=entry["sha256"]
    )


def emit_swift_package(
    lines: list[str], sp: LockedSwiftPackage, *, target_settings: bool
) -> None:
    """One ``[[tool.kivyforge.swift_packages]]`` table.

    *target_settings* writes ``link``/``embed``, which only iOS has.
    """
    lines.append("[[tool.kivyforge.swift_packages]]")
    lines.append(f"name = {s(sp.name)}")
    if sp.url:
        lines.append(f"url = {s(sp.url)}")
    else:
        path = sp.path
        assert path is not None
        lines.append(f"path = {s(path)}")
    if sp.requirement:
        lines.append(f"requirement = {_requirement_inline(sp.requirement)}")
    if sp.revision:
        lines.append(f"revision = {s(sp.revision)}")
    if sp.version:
        lines.append(f"version = {s(sp.version)}")
    lines.append(f"products = {arr(sp.products)}")
    if target_settings:
        lines.append(f"link = {b(sp.link)}")
        lines.append(f"embed = {b(sp.embed)}")


def parse_swift_package(entry: dict) -> LockedSwiftPackage:
    requirement = entry.get("requirement")
    return LockedSwiftPackage(
        name=entry["name"],
        products=tuple(entry.get("products", [])),
        url=entry.get("url"),
        path=entry.get("path"),
        requirement=dict(requirement) if requirement else None,
        revision=entry.get("revision"),
        version=entry.get("version"),
        link=bool(entry.get("link", True)),
        embed=bool(entry.get("embed", True)),
    )


def _requirement_inline(requirement: dict[str, object]) -> str:
    ((kind, value),) = requirement.items()
    if isinstance(value, list):
        return f"{{ {kind} = {arr([str(v) for v in value])} }}"
    return f"{{ {kind} = {s(str(value))} }}"


def _dep_inline(dep: PackageDep) -> str:
    if dep.marker:
        return f"{{ name = {s(dep.name)}, marker = {s(dep.marker)} }}"
    return f"{{ name = {s(dep.name)} }}"

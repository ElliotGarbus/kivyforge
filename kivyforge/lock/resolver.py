"""Platform-neutral pip helpers shared by every wheel resolver (spec 02).

The iOS resolver (``kivyforge.platforms.ios.lock.resolver``) and the generic
wheel+runtime resolver (``kivyforge.lock.wheelruntime.resolver``) both drive pip
in dry-run ``--report`` mode per platform tag; the pip-version gate, version
formatting, ABI tag list, ``--python-version`` normalization, and requires-dist
name parsing are identical and live here.
"""

from __future__ import annotations

import subprocess

from packaging.requirements import InvalidRequirement, Requirement

# Minimum host pip that understands PEP 730 iOS platform tags (pip 24.3, 2024-10-27).
# Earlier pip cannot match an ``ios_<dt>_*`` --platform request against a wheel
# tagged at a lower floor (e.g. ios_13_0_*), so compatible wheels are reported as
# missing. kivyforge targets Python that ships iOS support, so requiring a current
# pip is simpler — and far less surprising — than reimplementing tag expansion.
MIN_PIP_VERSION = (24, 3)


def version_str(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


def pip_version(python_executable: str) -> tuple[int, ...] | None:
    """Best-effort ``(major, minor, ...)`` version of pip for ``python_executable``.

    Returns ``None`` when pip can't be queried — treated as "unknown" (don't
    block) rather than "too old", since a genuinely broken pip surfaces its own
    error when resolution runs.
    """
    try:
        proc = subprocess.run(
            [python_executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
        )
    except (OSError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    # Format: "pip 24.3.1 from /path/site-packages/pip (python 3.15)".
    tokens = proc.stdout.split()
    if len(tokens) < 2 or tokens[0] != "pip":
        return None
    return _parse_version(tokens[1])


def _parse_version(text: str) -> tuple[int, ...] | None:
    parts: list[int] = []
    for chunk in text.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) or None


def pip_python_version(python_version: str) -> str:
    """``pip install --python-version`` accepts only integer dotted parts."""
    parts: list[str] = []
    for chunk in python_version.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(digits)
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return python_version


def abi_tags(python_version: str) -> tuple[str, ...]:
    """ABI tags to offer pip; cp<XY> first, then the limited-API/none fallbacks.

    Per the Phase 0 findings we must not over-constrain abi (abi3 wheels would
    be missed otherwise).
    """
    major_minor = "".join(python_version.split(".")[:2])
    return (f"cp{major_minor}", "abi3", "none")


def dep_names_for_environment(
    requires_dist: list[str], environment: dict[str, str]
) -> list[str]:
    """The dependency edges that actually apply on the target platform.

    ``Requires-Dist`` lists every edge a distribution *might* have, gated by
    markers: Kivy's raw list names ``pytest``, ``sphinx`` and
    ``kivy-deps.angle`` alongside its real runtime dependencies. Recording it
    unfiltered would describe a dependency graph the lock does not install, so
    each marker is evaluated against the target environment. ``extra`` is empty
    there, which drops extra-gated edges too.
    """
    names: list[str] = []
    for raw in requires_dist or []:
        try:
            requirement = Requirement(raw)
        except InvalidRequirement:
            # Unparseable metadata is upstream's problem, not a reason to fail
            # the lock; fall back to the permissive name-only reading.
            names.extend(_dep_names([raw]))
            continue
        if requirement.marker is not None and not requirement.marker.evaluate(
            environment
        ):
            continue
        names.append(requirement.name)
    return names


def _dep_names(requires_dist: list[str]) -> list[str]:
    names: list[str] = []
    for raw in requires_dist or []:
        # Strip everything after the name: extras, specifiers, markers.
        name = raw.split(";", 1)[0].split("[", 1)[0]
        for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", "(", " "):
            name = name.split(sep, 1)[0]
        name = name.strip()
        if name:
            names.append(name)
    return names

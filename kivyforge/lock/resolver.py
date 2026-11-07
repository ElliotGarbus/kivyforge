"""Platform-neutral pip helpers shared by every wheel resolver (spec 02).

The iOS resolver (``kivyforge.platforms.ios.lock.resolver``) and the generic
wheel+runtime resolver (``kivyforge.lock.wheelruntime.resolver``) both drive pip
in dry-run ``--report`` mode per platform tag; the pip-version gate, version
formatting, ABI tag list, ``--python-version`` normalization, and requires-dist
name parsing are identical and live here.
"""

from __future__ import annotations

import re
import subprocess

from packaging.requirements import InvalidRequirement, Requirement

from ..report import diagnostics, exit_codes
from ..report.failures import ClassifiedError

# Minimum host pip that understands PEP 730 iOS platform tags (pip 24.3, 2024-10-27).
# Earlier pip cannot match an ``ios_<dt>_*`` --platform request against a wheel
# tagged at a lower floor (e.g. ios_13_0_*), so compatible wheels are reported as
# missing. kivyforge targets Python that ships iOS support, so requiring a current
# pip is simpler — and far less surprising — than reimplementing tag expansion.
MIN_PIP_VERSION = (24, 3)


_UNRESOLVED_RE = re.compile(
    r"(?:No matching distribution found for|"
    r"Could not find a version that satisfies the requirement)\s+(\S+)"
)


def unresolved_requirement(pip_output: str) -> str | None:
    """The requirement pip reports it could not satisfy, or ``None``.

    pip names it in the last lines of a long failure. Surfacing it in our own
    headline keeps the user from reading the wrong package into the error.
    """
    match = _UNRESOLVED_RE.search(pip_output or "")
    return match.group(1) if match else None


class IndexUnreachable(ClassifiedError):
    """pip gave up on the connection to an index or file host mid-resolve."""

    code = diagnostics.LOCK_INDEX_UNREACHABLE
    exit_code = exit_codes.ENVIRONMENT_ERROR


# pip's last word once its retries are spent. Only this line counts: the
# "Retrying ... after connection broken" warnings before it also appear in runs
# that recover.
_UNREACHABLE_RE = re.compile(
    r"Could not install packages due to an OSError:[^\n]*?"
    r"(?:Max retries exceeded|NameResolutionError|Failed to resolve|"
    r"Failed to establish a new connection|ConnectionResetError|"
    r"ConnectionRefusedError|ReadTimeoutError)"
)
_HOST_RE = re.compile(r"host='([^']+)'")


def index_unreachable(pip_output: str, resolving: str) -> IndexUnreachable | None:
    """The failure to raise when pip stopped because the network did, or ``None``.

    Kept apart from a resolution failure because it says nothing about the
    project: without it the headline blamed a missing wheel, and with pins in
    play a retry that happened to connect turned it into
    ``KF-LOCK-PINS-CONFLICT``, whose fix (``--update``) moves every package.
    *resolving* names what was being resolved, for the headline.
    """
    match = _UNREACHABLE_RE.search(pip_output or "")
    if match is None:
        return None
    host = _HOST_RE.search(match.group(0))
    where = host.group(1) if host else "a package host"
    return IndexUnreachable(
        f"pip lost its connection to {where} while resolving {resolving}.\n"
        "  Fix: retry with network access; nothing in pyproject.toml or the lock "
        "needs to change.\n"
        f"  pip said:\n{_indent(pip_output)}",
        context={"host": host.group(1) if host else None},
    )


#: SHA-256 of no bytes at all.
_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

#: Progress note for a resolve retried by :func:`without_cache`.
CACHE_RETRY_NOTE = (
    "pip's HTTP cache served an empty file; retrying without it "
    "(`pip cache purge` removes the bad entry)"
)


def served_empty_file(pip_output: str) -> bool:
    """pip hashed a download with no body, which its own cache served.

    After a download it had to resume, pip caches the file under the URL it
    asked for, before any redirect, with the server's ``ETag``. The next request
    for that URL revalidates with the ETag; the redirect (every GitHub release
    asset has one) carries it to a freshly signed URL with no cache entry, the
    server answers ``304 Not Modified``, and pip hashes the empty body as the
    file. Every resolve then fails the same way until the entry expires, 14 days
    on. Seen in pip 26.1.2 and still in 26.3 (host-python-windows-findings.md).
    """
    text = pip_output or ""
    return "DO NOT MATCH THE HASHES" in text and _EMPTY_SHA256 in text


def without_cache(cmd: list[str]) -> list[str]:
    """*cmd*, a ``pip install`` argv, with pip's HTTP cache turned off."""
    at = cmd.index("install") + 1
    return [*cmd[:at], "--no-cache-dir", *cmd[at:]]


def _indent(text: str) -> str:
    return "\n".join(f"    {line}" for line in (text or "").splitlines())


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
            stdin=subprocess.DEVNULL,
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

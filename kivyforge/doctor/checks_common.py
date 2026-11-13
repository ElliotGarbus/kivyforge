"""Platform-neutral doctor checks shared by every backend (spec 05).

These checks are pure functions over an injectable :class:`Probe` and make no
assumptions about the target platform, so iOS, macOS, and Linux all reuse them.
Platform-specific checks live in ``platforms/<os>/doctor.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from packaging.version import InvalidVersion, Version

from ..bundle.pycompile import Candidate, no_interpreter
from ..config.model import AutoVersionCode, Config, StaticVersion
from ..host import host_runs_natively
from ..lock.resolver import MIN_PIP_VERSION, version_str
from ..report import diagnostics
from .probe import Probe
from .result import CheckResult, Status


class ByteCompileProbe(Protocol):
    """The one probe method the byte-compile check needs, so Android's probe fits."""

    def byte_compile_interpreter(
        self, python_version: str, *, searched: list[Candidate] | None = None
    ) -> tuple[str, ...] | None: ...


SKIP_NOTE = "no pyproject.toml found in current directory"


def lock_parse_fail(platform: str, exc: Exception) -> CheckResult:
    """A FAIL result for an unreadable ``pylock.<platform>.toml``."""
    return CheckResult(
        f"pylock.{platform}.toml",
        Status.FAIL,
        f"failed to parse: {exc}",
        hint=f"Regenerate it with `kivyforge lock -p {platform}`.",
    )


def _ver_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for chunk in v.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer_release(latest: str, current: str) -> bool:
    """Whether PyPI's *latest* kivyforge is newer than the running *current*.

    Compared as PEP 440 versions, not with :func:`_ver_tuple`: a build between
    tags is ``0.1.1.dev1+g813022a22``, which ``_ver_tuple`` reads as
    ``(0, 1, 1, 181302222)`` -- newer than any release. A version that does not
    parse never triggers the upgrade nudge.
    """
    try:
        return Version(latest) > Version(current)
    except InvalidVersion:
        return False


def check_pip_version(probe: Probe) -> CheckResult:
    """pip >= 24.3 is required to match PEP 730 iOS platform tags at lock time."""
    minimum = version_str(MIN_PIP_VERSION)
    version = probe.pip_version()
    if version is None:
        return CheckResult(
            "pip version",
            Status.WARN,
            "could not determine pip version",
            hint="ensure pip is available: `python -m ensurepip --upgrade`.",
        )
    if _ver_tuple(version) < MIN_PIP_VERSION:
        return CheckResult(
            "pip version",
            Status.FAIL,
            f"{version} (need >= {minimum})",
            hint=(
                "pip < 24.3 cannot match iOS platform tags (PEP 730); "
                "upgrade with `python -m pip install -U pip`."
            ),
        )
    return CheckResult("pip version", Status.PASS, version)


def check_kivyforge_version(
    probe: Probe, current: str, *, offline: bool
) -> CheckResult:
    if offline:
        return CheckResult("kivyforge version", Status.PASS, f"{current} (offline)")
    latest = probe.latest_kivyforge_version()
    if latest and is_newer_release(latest, current):
        return CheckResult(
            "kivyforge version",
            Status.WARN,
            f"{current} (latest {latest})",
            hint="upgrade with `pip install -U kivyforge`.",
        )
    return CheckResult("kivyforge version", Status.PASS, current)


BYTE_COMPILE_NAME = "Byte-compile interpreter"


def builds_natively(probe: Probe, archs: tuple[str, ...]) -> bool:
    """Whether *every* configured arch can run on this host.

    Conservative on purpose: if any configured arch is foreign, the check must
    evaluate the host-interpreter fallback, because that is the rung the build
    will land on for that arch. Claiming "native" on the strength of one
    matching arch would hide exactly the cross-build case worth reporting.
    """
    host = probe.host_machine()
    return bool(archs) and all(
        host_runs_natively(arch, host_machine=host) for arch in archs
    )


def check_byte_compile(
    probe: ByteCompileProbe,
    *,
    byte_compile: bool | str,
    python_version: str | None,
    table: str,
    native: bool,
) -> CheckResult:
    """Whether a configured ``byte_compile`` can actually find a compiler.

    The gap this closes: a ``byte_compile`` setting that cannot find a matching
    CPython only surfaces when the build runs, and with the default ``"release"``
    tri-state it then degrades *quietly* to shipping source — the one outcome
    someone who configured stripping does not want to discover after the fact.

    Severity follows how the build reads the setting. ``true`` means "I insist",
    so a missing interpreter is a hard failure there and a FAIL here; the default
    ``"release"`` means "when it makes sense", so it degrades and is a WARN.

    *native* must be passed exactly as the build computes it: when the build can
    run the interpreter it stages, that shipped runtime compiles its own payload
    and nothing on the host matters. Android and iOS never can (there is no
    runnable staged interpreter for either), and a cross-arch desktop build
    cannot either.
    """
    if byte_compile is False:
        return CheckResult(
            BYTE_COMPILE_NAME, Status.SKIP, f"byte_compile = false in [{table}]"
        )
    setting = "true" if byte_compile is True else f'"{byte_compile}"'
    if native:
        return CheckResult(
            BYTE_COMPILE_NAME,
            Status.PASS,
            f"byte_compile = {setting}; the staged runtime compiles its own payload",
        )
    if python_version is None:
        return CheckResult(
            BYTE_COMPILE_NAME,
            Status.SKIP,
            f"byte_compile = {setting}, but no Python version is configured",
        )
    minor = ".".join(python_version.split(".")[:2])
    searched: list[Candidate] = []
    compiler = probe.byte_compile_interpreter(python_version, searched=searched)
    if compiler is not None:
        found = "this interpreter" if compiler == () else " ".join(compiler)
        return CheckResult(
            BYTE_COMPILE_NAME,
            Status.PASS,
            f"byte_compile = {setting}; CPython {minor} via {found}",
        )
    # The same search report and Fix line the six backends print at build time.
    missing = no_interpreter(python_version, table=table, searched=searched)
    hint = missing.detail(indent="       ").lstrip()
    if byte_compile is True:
        return CheckResult(
            BYTE_COMPILE_NAME,
            Status.FAIL,
            f"byte_compile = true, but {missing.headline}; the build will fail",
            hint=hint,
            code=diagnostics.BYTECOMPILE_NO_INTERP,
        )
    return CheckResult(
        BYTE_COMPILE_NAME,
        Status.WARN,
        f"byte_compile = {setting}, but {missing.headline}; release builds will "
        f"silently ship source",
        hint=hint,
        code=diagnostics.BYTECOMPILE_NO_INTERP,
    )


def check_host_python(
    *,
    platform: str,
    byte_compile: bool | str,
    lock: object | None,
    table: str,
    cache=None,
) -> CheckResult:
    """For a build that compiles with a host interpreter: is this host's pin usable?

    iOS, Android and a Linux ``aarch64`` target compile only with the host
    CPython the lock pins for this machine (``kivyforge.bundle.hostpython``),
    so the question is the pin's state, never what is on ``PATH``. ``doctor``
    never downloads or extracts; it reports what the first release build will
    do. Severity follows the setting, as for :func:`check_byte_compile`.
    """
    from ..bundle import hostpython
    from ..lock import host_python as hp

    if byte_compile is False:
        return CheckResult(
            BYTE_COMPILE_NAME, Status.SKIP, f"byte_compile = false in [{table}]"
        )
    setting = "true" if byte_compile is True else f'"{byte_compile}"'
    lockfile = f"pylock.{platform}.toml"
    relock = f"kivyforge lock -p {platform}"
    if lock is None:
        return CheckResult(
            BYTE_COMPILE_NAME,
            Status.SKIP,
            f"no {lockfile} yet; `{relock}` pins the host CPython that byte-compiles",
        )
    triple = hostpython.host_triple()
    if triple is None:
        return CheckResult(
            BYTE_COMPILE_NAME, Status.SKIP, "this host has no host CPython builds"
        )
    bad = Status.FAIL if byte_compile is True else Status.WARN
    consequence = (
        "the build will fail"
        if byte_compile is True
        else "release builds will ship source"
    )
    entries = getattr(lock, "host_python", None)
    entry = hp.entry_for(entries, triple)
    if entries is None or entry is None or entry.state == hp.UNRESOLVED_OFFLINE:
        return CheckResult(
            BYTE_COMPILE_NAME,
            bad,
            f"byte_compile = {setting}, but {lockfile} has no host CPython for "
            f"{triple}; {consequence}",
            hint=f"run `{relock}`; it adds the host CPython and keeps every other pin.",
            code=diagnostics.LOCK_INCOMPLETE,
        )
    if entry.state == hp.NO_BUILD:
        return CheckResult(
            BYTE_COMPILE_NAME,
            bad,
            f"byte_compile = {setting}, but python-build-standalone had no final "
            f"CPython {entry.minor} build for {triple} when the lock was written; "
            f"{consequence}",
            hint=f"once one is published, run `{relock}`.",
            code=diagnostics.BYTECOMPILE_NO_INTERP,
        )
    try:
        allowed = hostpython.downloads_allowed()
    except hostpython.HostPythonError as exc:
        return CheckResult(BYTE_COMPILE_NAME, Status.FAIL, str(exc).splitlines()[0])
    pinned = f"the locked host CPython {entry.version} ({triple})"
    exe = hostpython.installed(entry, cache)
    if exe is not None:
        return CheckResult(
            BYTE_COMPILE_NAME, Status.PASS, f"byte_compile = {setting}; {pinned}: {exe}"
        )
    if hostpython.archive_cached(entry, cache):
        return CheckResult(
            BYTE_COMPILE_NAME,
            Status.PASS,
            f"byte_compile = {setting}; {pinned} is extracted on the first release build",
        )
    if allowed:
        return CheckResult(
            BYTE_COMPILE_NAME,
            Status.PASS,
            f"byte_compile = {setting}; {pinned} is downloaded on the first release build",
        )
    return CheckResult(
        BYTE_COMPILE_NAME,
        bad,
        f"byte_compile = {setting}, but {pinned} isn't in the cache and "
        f"{hostpython.DOWNLOADS_VAR}=never; {consequence}",
        hint=f"run `kivyforge upgrade -p {platform}` with network access, or unset "
        f"{hostpython.DOWNLOADS_VAR}.",
        code=diagnostics.BYTECOMPILE_NO_INTERP,
    )


def check_app_dir(config: Config, project_root: Path) -> CheckResult:
    """``app_dir`` must resolve to an existing directory — it carries the app's
    Python source into the bundle. Config validation only checks the *string*
    (relative, non-empty, etc.), not that it exists on disk; a missing one would
    otherwise build an app with no code (caught at build time, but reported here
    first).
    """
    app_dir = config.kivy.app_dir
    path = project_root / app_dir
    if not path.is_dir():
        return CheckResult(
            "App source directory",
            Status.FAIL,
            f"app_dir {app_dir!r} not found",
            hint="create the directory or fix [tool.kivy].app_dir; it must "
            "point at your app's Python source.",
        )
    return CheckResult("App source directory", Status.PASS, app_dir)


def check_version(config: Config) -> CheckResult:
    """The version a build will carry, without running the build backend.

    A dynamic version is resolved by pip at build time
    (docs/design/dev/dynamic-version-proposal.md); doctor never runs it, because
    an isolated resolution needs network and says nothing about this machine.
    """
    declared = config.project.version
    if isinstance(declared, StaticVersion):
        return CheckResult("Version", Status.PASS, declared.value)
    detail = (
        f"dynamic via {declared.backend} (resolved at build time; the first "
        "build needs network)"
    )
    android = config.android
    if android is not None and isinstance(android.version_code, AutoVersionCode):
        # A WARN, not a PASS with a note: doctor prints hints only for WARN and
        # FAIL, and this combination fails every build between tags.
        return CheckResult(
            "Version",
            Status.WARN,
            detail,
            hint='version_code = "auto" is derived from it at build time, and a '
            "build between tags (a dev version) fails then. Build from a release "
            "tag, or set an explicit integer version_code.",
        )
    return CheckResult("Version", Status.PASS, detail)

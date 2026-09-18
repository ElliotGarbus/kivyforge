"""Platform-neutral doctor checks shared by every backend (spec 05).

These checks are pure functions over an injectable :class:`Probe` and make no
assumptions about the target platform, so iOS, macOS, and Linux all reuse them.
Platform-specific checks live in ``platforms/<os>/doctor.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..config.model import Config
from ..host import host_runs_natively
from ..lock.resolver import MIN_PIP_VERSION, version_str
from .probe import Probe
from .result import CheckResult, Status


class ByteCompileProbe(Protocol):
    """The one probe method the byte-compile check needs, so Android's probe fits."""

    def byte_compile_interpreter(
        self, python_version: str
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
    if latest and _ver_tuple(latest) > _ver_tuple(current):
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
    compiler = probe.byte_compile_interpreter(python_version)
    if compiler is not None:
        found = "this interpreter" if compiler == () else " ".join(compiler)
        return CheckResult(
            BYTE_COMPILE_NAME,
            Status.PASS,
            f"byte_compile = {setting}; CPython {minor} via {found}",
        )
    # Same headline/why/Fix shape the six backends use at build time.
    hint = (
        f"Pre-releases do not count: CPython only freezes the .pyc magic number "
        f"at the first release candidate, so a {minor} alpha writes bytecode "
        f"{python_version} refuses to import.\n"
        f"       Fix: install a final CPython {minor} — kivyforge finds it "
        f"automatically — or set byte_compile = false in [{table}]."
    )
    if byte_compile is True:
        return CheckResult(
            BYTE_COMPILE_NAME,
            Status.FAIL,
            f"byte_compile = true, but no final CPython {minor} found "
            f"(this project ships {python_version}); the build will fail",
            hint=hint,
        )
    return CheckResult(
        BYTE_COMPILE_NAME,
        Status.WARN,
        f"byte_compile = {setting}, but no final CPython {minor} found "
        f"(this project ships {python_version}); release builds will "
        f"silently ship source",
        hint=hint,
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

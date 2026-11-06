"""``kivyforge bytecompiler`` — install a host CPython that byte-compiles.

Writing ``.pyc`` for a target needs a final CPython of the minor it ships on
this machine (``docs/design/common/10-byte-compile.md``). When a build finds
none, its error prints this command, ready to copy. The command reads each
platform's lock as the build does, searches the machine the same way, and
installs a verified python-build-standalone CPython only for a minor nothing
here can compile (``docs/design/dev/host-python-download-proposal.md``).

``-p`` is optional and has no default, unlike every other verb: the host's own
platform (``macos`` on a Mac) compiles with the runtime it ships, so a
defaulted ``-p`` would do nothing when the user meant iOS. Without it, the
command covers every platform the project configures.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field

import click

from ..bundle import hostpython
from ..bundle.pycompile import Candidate, find_interpreter, target_minor
from ..platforms import HostCapabilityError, available_platform_names, get_platform
from ..report import Diagnostic, Report, diagnostics, failures
from ..report.failures import ClassifiedError
from ._common import ToolchainError, find_pyproject
from ._output import output_options, reporting
from ._platform import configured_platforms


@dataclass
class _Minor:
    """One CPython minor some platforms need, and which of them need it."""

    minor: str
    platforms: list[str] = field(default_factory=list)
    versions: list[str] = field(default_factory=list)

    @property
    def prefer(self) -> str:
        """The newest version any of the platforms ships, to install exactly."""
        return max(self.versions, key=lambda v: tuple(int(p) for p in v.split(".")))


@click.command()
@click.option(
    "--platform",
    "-p",
    "cli_platform",
    type=click.Choice(available_platform_names()),
    default=None,
    help="Only this platform's build. Without it, every platform the project "
    "configures.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Reinstall kivyforge's CPython even when one is already found.",
)
@output_options
def bytecompiler(
    cli_platform: str | None,
    force: bool,
    json_out: bool,
    no_color: bool,
    verbosity: int,
) -> None:
    """Install a host CPython that byte-compiles for the target, if none is found.

    Byte-compiling an iOS or Android release, or a Linux aarch64 one, needs a
    final CPython of the minor the app ships on this machine. This installs one
    for kivyforge, for each minor the project's locks ship that nothing here
    can compile. Run it from the project root; build and package then find it.
    """
    with reporting(
        "bytecompiler",
        json_out=json_out,
        no_color=no_color,
        verbosity=verbosity,
        platform=cli_platform,
    ) as report:
        try:
            _run(report, cli_platform, force=force)
        except ClassifiedError as exc:
            raise ToolchainError.wrap(exc) from exc


def _run(report: Report, cli_platform: str | None, *, force: bool) -> None:
    pyproject = find_pyproject()
    project_root = pyproject.parent
    explicit = cli_platform is not None
    names = (
        [cli_platform]
        if cli_platform is not None
        else [
            n
            for n in available_platform_names()
            if n in configured_platforms(pyproject)
        ]
    )
    skipped: list[dict[str, str]] = []
    lock_problems: list[ClassifiedError] = []

    def skip(platform: str, reason: str, code: str | None = None) -> None:
        skipped.append({"platform": platform, "reason": reason})
        report.progress(f"[bytecompiler] {platform}: {reason}")
        if code is not None:
            report.diagnose(
                Diagnostic(
                    code=code,
                    severity=diagnostics.INFO,
                    message=f"{platform} skipped: {reason}",
                    context={"platform": platform},
                )
            )
        report.record(skipped=list(skipped))

    minors: dict[str, _Minor] = {}
    for name in names:
        backend = get_platform(name)
        try:
            backend.check_host()
        except HostCapabilityError as exc:
            if explicit:
                raise ToolchainError(str(exc), **failures.HOST_INCAPABLE) from exc
            skip(name, "this host can't build it", diagnostics.HOST_INCAPABLE)
            continue
        need = backend.byte_compile_need(project_root)
        if need.byte_compile is False:
            skip(name, "byte_compile = false")
            continue
        if not need.host_compiler:
            skip(name, "its build compiles with the runtime it ships")
            continue
        if need.lock_problem is not None:
            if explicit:
                raise need.lock_problem
            lock_problems.append(need.lock_problem)
            skip(name, str(need.lock_problem).splitlines()[0], need.lock_problem.code)
            continue
        version = need.python_version or ""
        if not _is_final(version):
            skip(
                name,
                f"ships CPython {version}, a pre-release; only a final release "
                "can write .pyc it loads",
            )
            continue
        minor = ".".join(str(p) for p in target_minor(version))
        entry = minors.setdefault(minor, _Minor(minor))
        entry.platforms.append(name)
        entry.versions.append(version)

    if not minors:
        if lock_problems:
            raise lock_problems[0]
        report.line(
            "Nothing to install: no platform here byte-compiles with a host CPython."
        )
        report.emit(ok=True, data={"interpreters": [], "skipped": skipped})
        return

    interpreters: list[dict[str, object]] = []
    for entry in sorted(minors.values(), key=lambda m: m.minor):
        interpreters.append(_provide(report, entry, force=force))
        report.record(interpreters=list(interpreters))
    report.emit(ok=True, data={"interpreters": interpreters, "skipped": skipped})


def _provide(report: Report, entry: _Minor, *, force: bool) -> dict[str, object]:
    """Find, or install, a final CPython of *entry*'s minor."""
    who = ", ".join(entry.platforms)
    verb = "ships" if len(entry.platforms) == 1 else "ship"
    searched: list[Candidate] = []
    found = None if force else find_interpreter(entry.prefer, searched=searched)
    record: dict[str, object] = {
        "minor": entry.minor,
        "platforms": list(entry.platforms),
    }
    if found is not None:
        installed = hostpython.installed_interpreter(entry.minor)
        if found == ():
            path, version = sys.executable, ".".join(map(str, sys.version_info[:3]))
        else:
            path = shutil.which(found[0]) or found[0]
            version = searched[-1].version or ""
        source = (
            "already-installed"
            if installed is not None and path == str(installed)
            else "found"
        )
        report.progress(f"[bytecompiler] {who} {verb} CPython {entry.prefer}")
        report.line(f"Already available: CPython {version} compiles for {who}: {path}")
        return {**record, "version": version, "path": path, "source": source}

    report.progress(
        f"[bytecompiler] {who} {verb} CPython {entry.prefer}; "
        + (
            "reinstalling (--force)"
            if force
            else f"no final {entry.minor} on this machine"
        )
    )
    done = hostpython.install(
        entry.minor, prefer=entry.prefer, on_progress=report.progress
    )
    report.line(
        f"Installed CPython {done.version} for byte-compiling: {done.interpreter}"
    )
    return {
        **record,
        "version": done.version,
        "path": str(done.interpreter),
        "source": "installed",
    }


def _is_final(version: str) -> bool:
    """``3.15.2`` is; ``3.15.0rc1``, ``3.16.0b2`` and an empty string are not."""
    parts = version.split(".")
    return len(parts) == 3 and all(p.isdigit() for p in parts)

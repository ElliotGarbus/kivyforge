"""``kivyforge lock`` — resolve dependencies into pylock.<platform>.toml.

The verb resolves the target platform (``-p`` / ``KIVYFORGE_PLATFORM`` / host)
and dispatches to that backend's lock engine, writing ``pylock.<platform>.toml``.
Each backend supplies its own build/serialize/compare callables; the drift check
(``pyproject_sha256``) and atomic write are shared.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import click

from ..config import ConfigError, load_config
from ..lock.reader import LockError, is_in_sync
from ..platforms.base import HostCapabilityError
from ..platforms.ios.lock import (
    BuildError,
    build_lockfile,
    diff_summary,
    dumps,
    load,
    semantic_equal,
)
from ..report import Diagnostic, Report, diagnostics, exit_codes
from ._common import ToolchainError, lockfile_path_for
from ._output import output_options, reporting
from ._platform import platform_option, resolve_target


@dataclass(frozen=True)
class _LockOps:
    """Per-platform lock callables (raise ``BuildError``/``LockError``)."""

    build: Callable
    dumps: Callable
    load: Callable
    semantic_equal: Callable
    diff_summary: Callable
    build_error: type[Exception]
    require_ios: bool
    require_macos: bool
    require_linux: bool = False
    require_windows: bool = False
    require_android: bool = False
    # Wheel+runtime backends (macOS/Linux) surface non-fatal lock warnings
    # (e.g. accepting a vendored plain linux_* wheel) via an on_warning callback.
    emits_warnings: bool = False
    # Most backends resolve with pip alone, so `lock` runs anywhere and the
    # result is committed. iOS is the exception: resolving declared Swift
    # packages shells out to `swift package resolve`, which needs the Xcode
    # toolchain, so the whole iOS workflow — lock included — is macOS-only.
    requires_host_toolchain: bool = False


def _lock_ops(platform: str) -> _LockOps:
    if platform == "ios":
        # Reference the module globals (not a local import) so tests can patch
        # ``lock_cli.build_lockfile`` with a fake-injecting wrapper.
        return _LockOps(
            build=build_lockfile,
            dumps=dumps,
            load=load,
            semantic_equal=semantic_equal,
            diff_summary=diff_summary,
            build_error=BuildError,
            require_ios=True,
            require_macos=False,
            requires_host_toolchain=True,
        )
    if platform == "macos":
        from ..platforms.macos import lock as macos_lock

        return _LockOps(
            build=macos_lock.build_macos_lockfile,
            dumps=macos_lock.dumps,
            load=macos_lock.load,
            semantic_equal=macos_lock.semantic_equal,
            diff_summary=macos_lock.diff_summary,
            build_error=macos_lock.MacosBuildError,
            require_ios=False,
            require_macos=True,
            emits_warnings=True,
        )
    if platform == "linux":
        from ..platforms.linux import lock as linux_lock

        return _LockOps(
            build=linux_lock.build_linux_lockfile,
            dumps=linux_lock.dumps,
            load=linux_lock.load,
            semantic_equal=linux_lock.semantic_equal,
            diff_summary=linux_lock.diff_summary,
            build_error=linux_lock.LinuxBuildError,
            require_ios=False,
            require_macos=False,
            require_linux=True,
            emits_warnings=True,
        )
    if platform == "windows":
        from ..platforms.windows import lock as windows_lock

        return _LockOps(
            build=windows_lock.build_windows_lockfile,
            dumps=windows_lock.dumps,
            load=windows_lock.load,
            semantic_equal=windows_lock.semantic_equal,
            diff_summary=windows_lock.diff_summary,
            build_error=windows_lock.WindowsBuildError,
            require_ios=False,
            require_macos=False,
            require_windows=True,
            emits_warnings=True,
        )
    if platform == "android":
        from ..platforms.android.lock import builder as android_builder
        from ..platforms.android.lock import reader as android_reader
        from ..platforms.android.lock import writer as android_writer

        return _LockOps(
            build=android_builder.build_lockfile,
            dumps=android_writer.dumps,
            load=android_reader.load,
            semantic_equal=android_builder.semantic_equal,
            diff_summary=android_builder.diff_summary,
            build_error=android_builder.BuildError,
            require_ios=False,
            require_macos=False,
            require_android=True,
        )
    raise ToolchainError(
        f"`kivyforge lock` does not support platform {platform!r} yet."
    )


def _require_host_toolchain(backend) -> None:
    """Gate `lock` for backends whose resolution needs a host toolchain."""
    try:
        backend.check_host_capability()
    except HostCapabilityError as exc:
        raise ToolchainError(
            str(exc),
            code=diagnostics.HOST_INCAPABLE,
            exit_code=exit_codes.ENVIRONMENT_ERROR,
        ) from exc


@click.command()
@platform_option
@click.option("--update", is_flag=True, help="Re-resolve even if the lock is in sync.")
@click.option("--offline", is_flag=True, help="Use cached resolution results only.")
@click.option(
    "--check",
    is_flag=True,
    help="CI pre-flight: exit non-zero if the lock is stale; write nothing.",
)
@output_options
def lock(
    cli_platform: str | None,
    update: bool,
    offline: bool,
    check: bool,
    json_out: bool,
    no_color: bool,
) -> None:
    """Generate pylock.<platform>.toml from pyproject.toml."""
    with reporting("lock", json_out=json_out, no_color=no_color) as report:
        backend, project_root = resolve_target(cli_platform, verb="lock")
        report.platform = backend.name
        ops = _lock_ops(backend.name)
        if ops.requires_host_toolchain:
            _require_host_toolchain(backend)

        pyproject = project_root / "pyproject.toml"
        pyproject_text = pyproject.read_text(encoding="utf-8")
        out_path = lockfile_path_for(backend.name, project_root)
        # Recorded before anything can fail, so even a drift or resolution
        # failure names the file it was talking about (agent-friendliness point
        # 2: never make a consumer reconstruct a path from docs).
        report.record(lockfile=out_path.name)

        try:
            config = load_config(
                pyproject,
                require_ios=ops.require_ios,
                require_macos=ops.require_macos,
                require_linux=ops.require_linux,
                require_windows=ops.require_windows,
                require_android=ops.require_android,
            )
        except ConfigError as exc:
            raise ToolchainError(exc.format()) from exc

        if check:
            _run_check(
                report, ops, config, pyproject_text, out_path, project_root, offline
            )
            return

        if out_path.is_file() and not update:
            try:
                existing = ops.load(out_path)
            except LockError:
                existing = None
            if existing is not None and is_in_sync(existing, pyproject_text):
                report.line(f"{out_path.name} is already in sync with pyproject.toml.")
                report.line("  (use --update to force re-resolution)")
                report.emit(
                    ok=True,
                    data={
                        "action": "unchanged",
                        "in_sync": True,
                        "packages": len(existing.packages),
                    },
                )
                return

        new_lock = _build(report, ops, config, pyproject_text, project_root, offline)
        _atomic_write(out_path, ops.dumps(new_lock))
        report.line(
            f"Wrote {out_path.name} ({len(new_lock.packages)} packages pinned)."
        )
        report.emit(
            ok=True,
            data={
                "action": "wrote",
                "in_sync": True,
                "packages": len(new_lock.packages),
            },
        )


def _run_check(
    report: Report,
    ops: _LockOps,
    config,
    pyproject_text: str,
    out_path: Path,
    project_root: Path,
    offline: bool,
) -> None:
    """The CI pre-flight: report drift, write nothing.

    All three failures here mean "your lock is not the lock this
    ``pyproject.toml`` implies", so all three exit ``LOCK_DRIFT`` and differ only
    in code -- a consumer that just wants "re-lock and retry" can branch on the
    number, while one that wants to distinguish a corrupt lock from a stale one
    reads the code.
    """
    relock = f"kivyforge lock -p {report.platform}"
    if not out_path.is_file():
        raise ToolchainError(
            f"{out_path.name} does not exist. Run `kivyforge lock` first.",
            code=diagnostics.LOCK_MISSING,
            exit_code=exit_codes.LOCK_DRIFT,
            remediation=relock,
        )
    try:
        existing = ops.load(out_path)
    except LockError as exc:
        raise ToolchainError(
            str(exc),
            code=diagnostics.LOCK_UNREADABLE,
            exit_code=exit_codes.LOCK_DRIFT,
            remediation=relock,
        ) from exc

    candidate = _build(report, ops, config, pyproject_text, project_root, offline)
    if ops.semantic_equal(existing, candidate):
        report.line(f"{out_path.name} is up to date.")
        report.emit(
            ok=True,
            data={
                "action": "checked",
                "in_sync": True,
                "packages": len(existing.packages),
            },
        )
        return

    # The diff is progress-shaped (it goes to stderr, and it always did), but it
    # is also the *answer* under --check, so it is recorded for the envelope that
    # ``reporting()`` will emit when the raise below propagates.
    diff = list(ops.diff_summary(existing, candidate))
    report.progress(f"{out_path.name} is out of date:")
    for line in diff:
        report.progress(line)
    report.record(action="checked", in_sync=False, diff=diff)
    raise ToolchainError(
        "lock is stale; run `kivyforge lock`.",
        code=diagnostics.LOCK_DRIFT,
        exit_code=exit_codes.LOCK_DRIFT,
        remediation=relock,
    )


def _build(
    report: Report,
    ops: _LockOps,
    config,
    pyproject_text: str,
    project_root: Path,
    offline: bool,
):
    kwargs = {}
    if ops.emits_warnings:
        # Shown *and* recorded. These used to go to stderr only, so a --json
        # consumer could not see that (say) a vendored plain linux_* wheel had
        # been accepted -- a decision worth knowing about from a machine.
        kwargs["on_warning"] = lambda msg: _warn(report, msg)
    try:
        return ops.build(
            config,
            pyproject_text,
            project_root=project_root,
            offline=offline,
            **kwargs,
        )
    except ops.build_error as exc:
        raise ToolchainError(str(exc)) from exc


def _warn(report: Report, message: str) -> None:
    report.progress(message)
    report.diagnose(
        Diagnostic(
            code=diagnostics.LOCK_WARNING,
            severity=diagnostics.WARNING,
            message=message,
        )
    )


def _atomic_write(path: Path, text: str) -> None:
    """Write to a tempfile, fsync, then rename (spec 02 step 5).

    Always LF: a lock file is committed and compared across machines, so
    letting the host's default line ending through would make a re-lock on
    another OS rewrite every line. The lock must depend on the target, never
    on who ran it.
    """
    directory = path.parent
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".pylock.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

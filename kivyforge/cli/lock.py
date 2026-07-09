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
from ..lock import (
    BuildError,
    build_lockfile,
    diff_summary,
    dumps,
    load,
    semantic_equal,
)
from ..lock.reader import LockError, is_in_sync
from ._common import ToolchainError, lockfile_path_for
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
        )
    if platform == "macos":
        from ..lock import macos as macos_lock

        return _LockOps(
            build=macos_lock.build_macos_lockfile,
            dumps=macos_lock.dumps,
            load=macos_lock.load,
            semantic_equal=macos_lock.semantic_equal,
            diff_summary=macos_lock.diff_summary,
            build_error=macos_lock.MacosBuildError,
            require_ios=False,
            require_macos=True,
        )
    if platform == "linux":
        from ..lock import linux as linux_lock

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
        )
    raise ToolchainError(
        f"`kivyforge lock` does not support platform {platform!r} yet."
    )


@click.command()
@platform_option
@click.option("--update", is_flag=True, help="Re-resolve even if the lock is in sync.")
@click.option("--offline", is_flag=True, help="Use cached resolution results only.")
@click.option(
    "--check",
    is_flag=True,
    help="CI pre-flight: exit non-zero if the lock is stale; write nothing.",
)
def lock(cli_platform: str | None, update: bool, offline: bool, check: bool) -> None:
    """Generate pylock.<platform>.toml from pyproject.toml."""
    backend, project_root = resolve_target(cli_platform)
    ops = _lock_ops(backend.name)

    pyproject = project_root / "pyproject.toml"
    pyproject_text = pyproject.read_text(encoding="utf-8")
    out_path = lockfile_path_for(backend.name, project_root)

    try:
        config = load_config(
            pyproject,
            require_ios=ops.require_ios,
            require_macos=ops.require_macos,
            require_linux=ops.require_linux,
        )
    except ConfigError as exc:
        raise ToolchainError(exc.format()) from exc

    if check:
        _run_check(ops, config, pyproject_text, out_path, project_root, offline)
        return

    if out_path.is_file() and not update:
        try:
            existing = ops.load(out_path)
        except LockError:
            existing = None
        if existing is not None and is_in_sync(existing, pyproject_text):
            click.echo(f"{out_path.name} is already in sync with pyproject.toml.")
            click.echo("  (use --update to force re-resolution)")
            return

    new_lock = _build(ops, config, pyproject_text, project_root, offline)
    _atomic_write(out_path, ops.dumps(new_lock))
    click.echo(f"Wrote {out_path.name} ({len(new_lock.packages)} packages pinned).")


def _run_check(
    ops: _LockOps,
    config,
    pyproject_text: str,
    out_path: Path,
    project_root: Path,
    offline: bool,
) -> None:
    if not out_path.is_file():
        raise ToolchainError(
            f"{out_path.name} does not exist. Run `kivyforge lock` first."
        )
    try:
        existing = ops.load(out_path)
    except LockError as exc:
        raise ToolchainError(str(exc)) from exc

    candidate = _build(ops, config, pyproject_text, project_root, offline)
    if ops.semantic_equal(existing, candidate):
        click.echo(f"{out_path.name} is up to date.")
        return
    click.echo(f"{out_path.name} is out of date:", err=True)
    for line in ops.diff_summary(existing, candidate):
        click.echo(line, err=True)
    raise ToolchainError("lock is stale; run `kivyforge lock`.")


def _build(
    ops: _LockOps, config, pyproject_text: str, project_root: Path, offline: bool
):
    try:
        return ops.build(
            config,
            pyproject_text,
            project_root=project_root,
            offline=offline,
        )
    except ops.build_error as exc:
        raise ToolchainError(str(exc)) from exc


def _atomic_write(path: Path, text: str) -> None:
    """Write to a tempfile, fsync, then rename (spec 02 step 5)."""
    directory = path.parent
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".pylock.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

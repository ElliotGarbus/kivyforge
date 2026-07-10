"""``kivyforge status`` — read-only project state snapshot (spec 05)."""

from __future__ import annotations

import click

from ..platforms.ios.cli import ios_status


@click.command()
def status() -> None:
    """Show app identity, Python version, lock sync, and build state."""
    ios_status()

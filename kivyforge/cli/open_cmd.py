"""``kivyforge open`` — open the generated project in its IDE (spec 05)."""

from __future__ import annotations

import click

from ._output import output_options, report_events, reporting
from ._platform import platform_option, resolve_target


@click.command(name="open")
@platform_option
@output_options
def open_(cli_platform: str | None, json_out: bool, no_color: bool) -> None:
    """Open <app>-ios/<app>.xcodeproj in Xcode."""
    with reporting("open", json_out=json_out, no_color=no_color) as report:
        backend, project_root = resolve_target(cli_platform, verb="open")
        report.platform = backend.name
        opened = backend.open_project(project_root, events=report_events(report))
        # What was opened, not that something was: the path is the one fact a
        # consumer cannot derive, since it differs per platform and per app.
        report.emit(
            ok=True, data={"project": opened.relative_to(project_root).as_posix()}
        )

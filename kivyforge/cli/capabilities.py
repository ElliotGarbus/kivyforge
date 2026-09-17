"""``kivyforge capabilities`` — what this kivyforge can do (roadmap item 3).

Machine-first: the payload is the point, and the human rendering is a courtesy.
It answers the question no other verb does — *which hosts can build which
targets* — without a project, a lock, or a network.
"""

from __future__ import annotations

import click

from ..capabilities import Capabilities, collect, host_label
from ._output import output_options, reporting

_COLUMN = 10


@click.command()
@output_options
def capabilities(json_out: bool, no_color: bool) -> None:
    """List platforms, archs, package formats, and which hosts build what."""
    # No project context on purpose: this is introspection of the tool, and an
    # agent asks it *before* it has a project to point at.
    with reporting("capabilities", json_out=json_out, no_color=no_color) as report:
        found = collect()
        for line in render(found):
            report.line(line)
        report.emit(ok=True, data=found.as_dict())


def render(found: Capabilities) -> list[str]:
    """The human report, as lines (returned so it can be asserted directly)."""
    lines = ["Platforms"]
    for platform in found.platforms:
        hosts = ", ".join(host_label(h) for h in platform.buildable_on) or "none"
        default = " (host default)" if platform.host_default_for else ""
        lines.append(f"  {platform.name}")
        lines.append(f"    {'archs:':<{_COLUMN}}{', '.join(platform.archs) or '-'}")
        lines.append(
            f"    {'formats:':<{_COLUMN}}{', '.join(platform.package_formats) or '-'}"
        )
        lines.append(f"    {'hosts:':<{_COLUMN}}{hosts}{default}")

    json_verbs = [name for name, supported in found.verbs.items() if supported]
    human_only = [name for name, supported in found.verbs.items() if not supported]
    lines.append("")
    lines.append(f"Verbs with --json: {', '.join(json_verbs)}")
    if human_only:
        lines.append(f"Human-only verbs:  {', '.join(human_only)}")

    lines.append("")
    lines.append("Exit codes")
    lines += [
        f"  {code}  {meaning}" for code, meaning in sorted(found.exit_codes.items())
    ]
    return lines

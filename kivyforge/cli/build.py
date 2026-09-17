"""``kivyforge build`` — materialize the lock into an Xcode project (specs 05/06).

Build performs, in order:

1. **Drift check** — the lock must be in sync with ``pyproject.toml``.
2-5. **Artifact collection** — Python.xcframework, pinned wheels into
   ``pip-deps/``, wheel-embedded + native ``.xcframework`` into ``Frameworks/``.
6. **Project materialization** — generate ``<app>-ios/`` and the ``.xcodeproj``.
7. **xcodebuild** — only when a target flag is given (Phase 6); a bare
   ``kivyforge build`` stops after step 6 with a ready-to-open project.
"""

from __future__ import annotations

import click

from ._output import output_options, report_events, reporting
from ._platform import platform_option, reject_android_only, resolve_target


@click.command()
@platform_option
@click.option(
    "--simulator",
    "target",
    flag_value="simulator",
    help="Build for the iOS simulator (Debug).",
)
@click.option(
    "--device", "target", flag_value="device", help="Build for a device (Debug)."
)
@click.option(
    "--release", "target", flag_value="release", help="Archive + export a .ipa."
)
@click.option(
    "--arch",
    # x86_64 stays: it is the Linux arch and an Android ABI. It is not a macOS
    # or iOS-simulator arch any more -- those backends reject it themselves.
    type=click.Choice(["arm64", "x86_64"]),
    default=None,
    help="iOS: simulator arch. macOS: assemble a subset of the locked archs.",
)
@click.option(
    "--no-verify-lock", is_flag=True, help="Skip the pyproject drift check (CI only)."
)
@click.option("--no-cache", is_flag=True, help="Force re-download of every artifact.")
@click.option(
    "--team-id", default=None, help="Override [tool.kivy.ios.signing].team_id."
)
@click.option(
    "--signing-identity",
    default=None,
    help="Override [tool.kivy.ios.signing].identity.",
)
@click.option(
    "--export-method",
    type=click.Choice(["app-store", "ad-hoc", "development"]),
    default="app-store",
    help="Export method (only meaningful with --release).",
)
# --- Android-only ---
@click.option(
    "--debug",
    is_flag=True,
    help="Android: assemble the debug-signed artifact after generating.",
)
@click.option(
    "-f",
    "--format",
    "fmt",
    type=click.Choice(["apk", "aab"]),
    default=None,
    help="Android (with --debug): debug artifact format (default apk).",
)
@click.option(
    "--abi",
    type=click.Choice(["arm64_v8a", "x86_64"]),
    default=None,
    help="Android: restrict this build to one ABI.",
)
@output_options
def build(
    cli_platform: str | None,
    target: str | None,
    arch: str | None,
    no_verify_lock: bool,
    no_cache: bool,
    team_id: str | None,
    signing_identity: str | None,
    export_method: str,
    debug: bool,
    fmt: str | None,
    abi: str | None,
    json_out: bool,
    no_color: bool,
) -> None:
    """Download artifacts, generate the platform project, and optionally build it."""
    with reporting("build", json_out=json_out, no_color=no_color) as report:
        # Before anything can fail, so every envelope carries the key.
        report.record(artifacts=[])
        # Resolve the target platform before any work so an unresolved target
        # fails fast with an actionable message (common design doc 02).
        backend, project_root = resolve_target(cli_platform, verb="build")
        report.platform = backend.name
        reject_android_only(
            backend, {"--debug": debug, "-f/--format": fmt, "--abi": abi}
        )

        outcome = backend.build(
            project_root,
            events=report_events(report),
            target=target,
            arch=arch,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
            team_id=team_id,
            signing_identity=signing_identity,
            export_method=export_method,
            debug=debug,
            fmt=fmt,
            abi=abi,
        )
        for note in outcome.notes:
            report.line(note)
        report.emit(ok=True, data=outcome.as_dict())

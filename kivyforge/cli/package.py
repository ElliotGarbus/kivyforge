"""``kivyforge package`` — build the distributable, signed artifact (docs 02/06).

``package`` produces the finished, signed runnable artifact for the resolved
target (wrapping it into an installer/container is out of scope). For iOS this is
the release archive + exported ``.ipa``; other platforms register their own
shapes via ``Platform.package_formats`` and are wired in as they land.
"""

from __future__ import annotations

import click

from ..xcode import CommandError, SigningError, XcodeBuild
from ._common import ToolchainError
from ._macos import macos_package
from ._platform import platform_option, resolve_target
from .build import _load_config, _xcodebuild_step7, prepare_build


@click.command()
@platform_option
@click.option(
    "-f",
    "--format",
    "fmt",
    default=None,
    help="Artifact format for the target (defaults to the platform's default).",
)
@click.option(
    "--arch",
    type=click.Choice(["arm64", "x86_64", "universal2"]),
    default=None,
    help="macOS: assemble a subset of the locked archs.",
)
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
    help="iOS export method.",
)
@click.option(
    "--no-verify-lock", is_flag=True, help="Skip the pyproject drift check (CI only)."
)
@click.option("--no-cache", is_flag=True, help="Force re-download of every artifact.")
def package(
    cli_platform: str | None,
    fmt: str | None,
    arch: str | None,
    team_id: str | None,
    signing_identity: str | None,
    export_method: str,
    no_verify_lock: bool,
    no_cache: bool,
) -> None:
    """Build the signed, distributable artifact for the resolved platform."""
    backend, project_root = resolve_target(cli_platform)
    fmt = _resolve_format(backend, fmt)

    if backend.name == "macos":
        macos_package(
            project_root,
            arch=arch,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
        )
        return

    if backend.name != "ios":
        raise ToolchainError(f"`package` for {backend.name!r} is not implemented yet.")

    config = _load_config(project_root / "pyproject.toml")
    try:
        prepare_build(
            config,
            project_root,
            target="release",
            arch=None,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
        )
        xb = XcodeBuild.from_config(config, project_root)
        _xcodebuild_step7(
            xb,
            config,
            target="release",
            arch=None,
            team_id_flag=team_id,
            signing_identity_flag=signing_identity,
            export_method=export_method,
        )
    except (CommandError, SigningError) as exc:
        raise ToolchainError(str(exc)) from exc


def _resolve_format(backend, fmt: str | None) -> str:
    """Validate/resolve the ``-f`` format against the backend's advertised set."""
    if fmt is None:
        default = backend.default_package_format
        if default is None:
            raise ToolchainError(
                f"{backend.name!r} does not define a package format yet."
            )
        return default
    if fmt not in backend.package_formats:
        allowed = ", ".join(backend.package_formats) or "none"
        raise ToolchainError(
            f"unknown package format {fmt!r} for {backend.name!r}; allowed: {allowed}."
        )
    return fmt

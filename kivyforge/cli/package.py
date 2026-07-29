"""``kivyforge package`` — build the distributable, signed artifact (docs 02/06).

``package`` produces the finished, signed runnable artifact for the resolved
target (wrapping it into an installer/container is out of scope). For iOS this is
the release archive + exported ``.ipa``; other platforms register their own
shapes via ``Platform.package_formats`` and are wired in as they land.
"""

from __future__ import annotations

import click

from ._common import ToolchainError
from ._platform import platform_option, reject_android_only, resolve_target


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
    help="Override [tool.kivy.<platform>.signing].identity.",
)
@click.option(
    "--export-method",
    type=click.Choice(["app-store", "ad-hoc", "development"]),
    default="app-store",
    help="iOS export method.",
)
@click.option(
    "--notarize/--no-notarize",
    "notarize",
    default=None,
    help="macOS: notarize + staple the signed .app (default: when "
    "[tool.kivy.macos.signing].notary_profile is configured).",
)
@click.option(
    "--notary-profile",
    default=None,
    help="macOS: override [tool.kivy.macos.signing].notary_profile.",
)
@click.option(
    "--no-verify-lock", is_flag=True, help="Skip the pyproject drift check (CI only)."
)
@click.option("--no-cache", is_flag=True, help="Force re-download of every artifact.")
# --- Android-only ---
@click.option(
    "--abi",
    type=click.Choice(["arm64_v8a", "x86_64"]),
    default=None,
    help="Android: restrict this package to one ABI.",
)
@click.option(
    "--keystore",
    default=None,
    help="Android: override [tool.kivy.android.signing].keystore.",
)
@click.option(
    "--key-alias",
    default=None,
    help="Android: override [tool.kivy.android.signing].key_alias.",
)
def package(
    cli_platform: str | None,
    fmt: str | None,
    arch: str | None,
    team_id: str | None,
    signing_identity: str | None,
    export_method: str,
    notarize: bool | None,
    notary_profile: str | None,
    no_verify_lock: bool,
    no_cache: bool,
    abi: str | None,
    keystore: str | None,
    key_alias: str | None,
) -> None:
    """Build the signed, distributable artifact for the resolved platform."""
    backend, project_root = resolve_target(cli_platform, verb="package")
    reject_android_only(
        backend,
        {"--abi": abi, "--keystore": keystore, "--key-alias": key_alias},
    )
    fmt = _resolve_format(backend, fmt)

    backend.package(
        project_root,
        fmt=fmt,
        arch=arch,
        team_id=team_id,
        signing_identity=signing_identity,
        export_method=export_method,
        notarize=notarize,
        notary_profile=notary_profile,
        no_verify_lock=no_verify_lock,
        no_cache=no_cache,
        abi=abi,
        keystore=keystore,
        key_alias=key_alias,
    )


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

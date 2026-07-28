"""``kivyforge init`` — smart project initialization (spec 05).

One write path:

* **update** — a ``pyproject.toml`` exists. Only add/replace the target
  platform's ``[tool.kivy]`` + ``[tool.kivy.<platform>]``; ``[project]`` and
  every other namespace are left untouched. No venv required.

Platform-aware: resolves the target the same way as every other verb
(``-p`` / ``KIVYFORGE_PLATFORM``), plus two init-only fallbacks that make sense
only when *configuring* a platform for the first time — see
``_resolve_init_platform``.

If ``requirements.txt`` is found but no ``pyproject.toml``, init exits non-zero
with a migration pointer rather than auto-migrating.
"""

from __future__ import annotations

import os
import platform as _platform_mod
import sys
import tomllib
from importlib import metadata
from pathlib import Path

import click

from ..config.model import (
    DEFAULT_ANDROID_KEY_PASSWORD_ENV,
    DEFAULT_ANDROID_STORE_PASSWORD_ENV,
    DEFAULT_WINDOWS_STORE_SCOPE,
    DEFAULT_WINDOWS_TIMESTAMP_URL,
    AndroidSigningConfig,
    MacosSigningConfig,
    SigningConfig,
    WindowsSigningConfig,
)
from ..platforms import PLATFORM_ENV_VAR, available_platform_names, get_platform
from ._common import PYPROJECT_NAME, ToolchainError
from ._platform import configured_platforms, platform_option
from .init_writer import (
    append_block,
    has_kivy_dep,
    has_platform_overlay,
    has_shared_table,
    normalize_package_name,
    render_android_tables,
    render_kivy_tables,
    render_linux_tables,
    render_macos_tables,
    render_windows_tables,
    strip_platform_tables,
)

REQUIREMENTS_NAME = "requirements.txt"

_REQUIREMENTS_MSG = (
    "requirements.txt found but no pyproject.toml.\n"
    "  kivyforge requires pyproject.toml — it will not migrate requirements.txt\n"
    "  automatically. Transfer your dependencies to a new pyproject.toml:\n\n"
    "    [project]\n"
    '    name = "myapp"  # your app name\n'
    '    version = "0.1.0"\n'
    "    dependencies = [\n"
    '        "kivy>=3.0",\n'
    "        # ... paste your other requirements here\n"
    "    ]\n\n"
    "  Then re-run kivyforge init."
)


@click.command()
@platform_option
@click.option(
    "--force", is_flag=True, help="Regenerate [tool.kivy*] (preserves signing)."
)
def init(cli_platform: str | None, force: bool) -> None:
    """Seed [tool.kivy] + the target platform's overlay into pyproject.toml."""
    cwd = Path.cwd()
    pyproject = cwd / PYPROJECT_NAME
    requirements = cwd / REQUIREMENTS_NAME

    if pyproject.is_file():
        platform_name = _resolve_init_platform(cli_platform, pyproject)
        _run_update_path(pyproject, force=force, platform_name=platform_name)
    elif requirements.is_file():
        raise ToolchainError(_REQUIREMENTS_MSG)
    else:
        raise ToolchainError(
            f"no {PYPROJECT_NAME} found in {cwd}.\n"
            f"  Create a minimal {PYPROJECT_NAME} with your app's metadata, then re-run:\n\n"
            f"    [project]\n"
            f'    name = "myapp"\n'
            f'    version = "0.1.0"\n'
            f"    dependencies = [\n"
            f'        "kivy>=3.0",\n'
            f"    ]\n\n"
            f"  See https://packaging.python.org/tutorials/packaging-projects/ for details."
        )


def _resolve_init_platform(
    cli_platform: str | None,
    pyproject: Path,
    *,
    host_system: str | None = None,
) -> str:
    """Resolve init's target platform.

    Same top two steps as every other verb (``-p`` then ``KIVYFORGE_PLATFORM``),
    but init additionally needs to handle the case it alone faces: *configuring*
    a platform for the first time, when nothing is "configured" yet. So instead
    of the shared ``resolve_target`` (whose host-default step requires the
    platform to already be configured — the right call for build/run/etc., but
    backwards for init), this:

    1. ``--platform`` / ``-p``.
    2. ``KIVYFORGE_PLATFORM``.
    3. The project's one already-configured overlay, if exactly one exists
       (the ``--force``-regenerate case — no flag needed to update what's
       already there).
    4. The host OS's own platform (unconditionally — this *is* how it gets
       configured the first time). iOS never matches here (no host maps to
       it); it always needs an explicit choice, same as everywhere else.

    ``host_system`` is injectable (like the shared ``resolve_target``'s) so
    tests aren't at the mercy of the machine they happen to run on; it
    defaults to the real host (``platform.system()``).
    """
    if cli_platform:
        return cli_platform

    env_platform = os.environ.get(PLATFORM_ENV_VAR)
    if env_platform:
        if env_platform not in available_platform_names():
            raise ToolchainError(
                f"unknown platform {env_platform!r} in ${PLATFORM_ENV_VAR}; "
                f"registered: {', '.join(available_platform_names())}"
            )
        return env_platform

    configured = configured_platforms(pyproject)
    if len(configured) == 1:
        return next(iter(configured))
    if len(configured) > 1:
        example = sorted(configured)[0]
        raise ToolchainError(
            "multiple platforms configured in this pyproject.toml "
            f"({', '.join(sorted(configured))}); pass one explicitly:\n"
            f"  kivyforge init --platform {example}"
        )

    host = host_system if host_system is not None else _platform_mod.system()
    for name in available_platform_names():
        if get_platform(name).host_system == host:
            return name

    raise ToolchainError(
        "cannot infer a target platform on this host.\n"
        "  Pass one explicitly:      kivyforge init --platform macos\n"
        f"  Or set a session default: export {PLATFORM_ENV_VAR}=macos"
    )


def _run_update_path(pyproject: Path, *, force: bool, platform_name: str) -> None:
    text = pyproject.read_text(encoding="utf-8")
    raw = _safe_parse(text, pyproject)

    if "project" not in raw:
        raise ToolchainError(
            f"{PYPROJECT_NAME} has no [project] table.\n"
            "  init updates only [tool.kivy*]; it will not author [project] for "
            "an existing file. Add a minimal [project] (name + version) first."
        )

    table_key = f"tool.kivy.{platform_name}"
    existing_overlay = has_platform_overlay(text, platform_name)
    if existing_overlay and not force:
        raise ToolchainError(
            f"[{table_key}] already exists. Re-run with --force to regenerate "
            f"it (your [{table_key}.signing] is preserved)."
        )

    app_slug = _project_slug(raw)
    deps = raw.get("project", {}).get("dependencies", [])
    kivy = has_kivy_dep(deps) if isinstance(deps, list) else False
    include_shared = not has_shared_table(text)
    table = _platform_table(raw, platform_name)

    if existing_overlay and force:
        stripped = strip_platform_tables(text, platform_name)
        block = _render_overlay(
            platform_name,
            app_slug,
            table,
            has_kivy=kivy,
            include_shared=include_shared,
            preserve=True,
        )
        new_text = append_block(stripped, block)
        pyproject.write_text(new_text, encoding="utf-8")
        click.echo(
            f"Regenerated [{table_key}] (signing/python/icon settings preserved)."
        )
    else:
        block = _render_overlay(
            platform_name,
            app_slug,
            table,
            has_kivy=kivy,
            include_shared=include_shared,
            preserve=False,
        )
        new_text = append_block(text, block)
        pyproject.write_text(new_text, encoding="utf-8")
        added = (
            f"[{table_key}]" if not include_shared else f"[tool.kivy] + [{table_key}]"
        )
        click.echo(f"Added {added} to pyproject.toml.")

    _maybe_warn_drift(raw)
    click.echo(
        f"Next: fill in the TODOs in [{table_key}], then `kivyforge lock -p {platform_name}`."
    )


def _render_overlay(
    platform_name: str,
    app_slug: str,
    table: dict,
    *,
    has_kivy: bool,
    include_shared: bool,
    preserve: bool,
) -> str:
    """Render the (optional) shared ``[tool.kivy]`` + the target platform's overlay."""
    if platform_name == "ios":
        splash_source, splash_background = (
            _read_splash(table) if preserve else (None, None)
        )
        return render_kivy_tables(
            app_slug,
            signing=_read_signing(table) if preserve else None,
            python_version=_read_python_version(table) if preserve else None,
            has_kivy=has_kivy,
            simulator_archs=_read_str_list(table, "simulator_archs")
            if preserve
            else None,
            icon_source=_read_icon_source(table) if preserve else None,
            splash_source=splash_source,
            splash_background=splash_background,
            include_shared=include_shared,
        )
    if platform_name == "macos":
        return render_macos_tables(
            app_slug,
            signing=_read_macos_signing(table) if preserve else None,
            python_version=_read_python_version(table) if preserve else None,
            has_kivy=has_kivy,
            archs=_read_str_list(table, "archs") if preserve else None,
            icon_source=_read_icon_source(table) if preserve else None,
            include_shared=include_shared,
        )
    if platform_name == "linux":
        return render_linux_tables(
            app_slug,
            python_version=_read_python_version(table) if preserve else None,
            has_kivy=has_kivy,
            archs=_read_str_list(table, "archs") if preserve else None,
            icon_source=_read_icon_source(table) if preserve else None,
            categories=_read_categories(table) if preserve else None,
            include_shared=include_shared,
        )
    if platform_name == "windows":
        return render_windows_tables(
            app_slug,
            signing=_read_windows_signing(table) if preserve else None,
            python_version=_read_python_version(table) if preserve else None,
            has_kivy=has_kivy,
            archs=_read_str_list(table, "archs") if preserve else None,
            icon_source=_read_icon_source(table) if preserve else None,
            include_shared=include_shared,
        )
    if platform_name == "android":
        splash_source, splash_background = (
            _read_splash(table) if preserve else (None, None)
        )
        package = table.get("package") if preserve else None
        kivy_generation = table.get("kivy_generation") if preserve else None
        return render_android_tables(
            app_slug,
            signing=_read_android_signing(table) if preserve else None,
            python_version=_read_python_version(table) if preserve else None,
            has_kivy=has_kivy,
            package=package if isinstance(package, str) and package else None,
            abis=_read_str_list(table, "abis") if preserve else None,
            kivy_generation=kivy_generation
            if isinstance(kivy_generation, int)
            and not isinstance(kivy_generation, bool)
            else None,
            icon_source=_read_icon_source(table) if preserve else None,
            splash_source=splash_source,
            splash_background=splash_background,
            include_shared=include_shared,
        )
    raise ToolchainError(
        f"`kivyforge init` does not support platform {platform_name!r} yet."
    )


# --------------------------------------------------------------------------- #
# environment probing
# --------------------------------------------------------------------------- #
def _venv_active() -> bool:
    return sys.prefix != sys.base_prefix


def _installed_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if name:
            out[_canon(name)] = dist.version
    return out


def _canon(name: str) -> str:
    import re

    return re.sub(r"[-_.]+", "-", name).lower()


def _safe_parse(text: str, path: Path) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ToolchainError(f"{path} is not valid TOML: {exc}") from exc


def _project_slug(raw: dict) -> str:
    name = raw.get("project", {}).get("name")
    if isinstance(name, str) and name:
        return normalize_package_name(name)
    return "app"


def _platform_table(raw: dict, platform_name: str) -> dict:
    try:
        table = raw["tool"]["kivy"][platform_name]
    except (KeyError, TypeError):
        return {}
    return table if isinstance(table, dict) else {}


def _read_python_version(table: dict) -> str | None:
    try:
        version = table["python"]["version"]
    except (KeyError, TypeError):
        return None
    return version if isinstance(version, str) and version else None


def _read_str_list(table: dict, key: str) -> list[str] | None:
    """Return a user-set list-of-strings field, or None when absent/invalid.

    None preserves the commented stub on ``--force`` so the default still holds.
    """
    values = table.get(key)
    if isinstance(values, list) and values and all(isinstance(v, str) for v in values):
        return values
    return None


def _read_icon_source(table: dict) -> str | None:
    icons = table.get("icons")
    if isinstance(icons, dict):
        source = icons.get("source")
        if isinstance(source, str) and source:
            return source
    return None


def _read_splash(table: dict) -> tuple[str | None, str | None]:
    splash = table.get("splash")
    if not isinstance(splash, dict):
        return None, None
    source = splash.get("source")
    background = splash.get("background")
    return (
        source if isinstance(source, str) and source else None,
        background if isinstance(background, str) and background else None,
    )


def _read_signing(table: dict) -> SigningConfig | None:
    signing = table.get("signing")
    if not isinstance(signing, dict):
        return None
    return SigningConfig(
        team_id=signing.get("team_id", ""),
        identity=signing.get("identity", "Apple Development"),
        provisioning_profile=signing.get("provisioning_profile", ""),
        auto_signing=bool(signing.get("auto_signing", True)),
        upload_symbols=bool(signing.get("upload_symbols", True)),
    )


def _read_macos_signing(table: dict) -> MacosSigningConfig | None:
    signing = table.get("signing")
    if not isinstance(signing, dict):
        return None
    identity = signing.get("identity", "")
    if not identity:
        return None
    return MacosSigningConfig(
        identity=identity,
        team_id=signing.get("team_id", ""),
        notary_profile=signing.get("notary_profile", ""),
    )


def _read_windows_signing(table: dict) -> WindowsSigningConfig | None:
    signing = table.get("signing")
    if not isinstance(signing, dict):
        return None
    thumbprint = signing.get("thumbprint", "")
    if not thumbprint:
        return None
    return WindowsSigningConfig(
        thumbprint=thumbprint,
        timestamp_url=signing.get("timestamp_url", DEFAULT_WINDOWS_TIMESTAMP_URL),
        store_scope=signing.get("store_scope", DEFAULT_WINDOWS_STORE_SCOPE),
    )


def _read_android_signing(table: dict) -> AndroidSigningConfig | None:
    signing = table.get("signing")
    if not isinstance(signing, dict):
        return None
    keystore = signing.get("keystore", "")
    if not keystore:
        return None
    return AndroidSigningConfig(
        keystore=keystore,
        key_alias=signing.get("key_alias", ""),
        store_password_env=signing.get(
            "store_password_env", DEFAULT_ANDROID_STORE_PASSWORD_ENV
        ),
        key_password_env=signing.get(
            "key_password_env", DEFAULT_ANDROID_KEY_PASSWORD_ENV
        ),
    )


def _read_categories(table: dict) -> list[str] | None:
    desktop = table.get("desktop")
    if not isinstance(desktop, dict):
        return None
    return _read_str_list(desktop, "categories")


def _maybe_warn_drift(raw: dict) -> None:
    """If a venv is active, warn when an installed dep drifts from its specifier."""
    if not _venv_active():
        return
    deps = raw.get("project", {}).get("dependencies", [])
    if not isinstance(deps, list):
        return
    installed = _installed_versions()
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.version import Version

    for raw_req in deps:
        try:
            req = Requirement(raw_req)
        except InvalidRequirement:
            continue
        version = installed.get(_canon(req.name))
        if (
            version
            and str(req.specifier)
            and not req.specifier.contains(Version(version), prereleases=True)
        ):
            click.echo(
                f"warning: installed {req.name} {version} is outside declared "
                f"'{req.specifier}'. (Not modified.)",
                err=True,
            )

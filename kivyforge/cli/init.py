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
BUILDOZER_SPEC_NAME = "buildozer.spec"

# buildozer.spec `[app]` key -> the kivyforge key that replaces it. The value is
# the destination table and key; `None` means the setting has no counterpart
# because kivyforge does the thing differently (see _BUILDOZER_DROPPED).
_BUILDOZER_MAP: tuple[tuple[str, str], ...] = (
    ("title", "[tool.kivy].display_name"),
    ("package.name", "[tool.kivy.android].package  (with package.domain)"),
    ("package.domain", "[tool.kivy.android].package  (with package.name)"),
    ("version", "[project].version"),
    ("source.dir", "[tool.kivy].app_dir"),
    ("requirements", "[project].dependencies  (as PEP 508 requirements)"),
    ("orientation", "[tool.kivy].orientation"),
    ("icon.filename", "[tool.kivy.android.icons].source"),
    ("presplash.filename", "[tool.kivy.android.splash].source"),
    ("android.api", "[tool.kivy.android].target_sdk / compile_sdk"),
    ("android.minapi", "[tool.kivy.android].min_sdk  (kivyforge's floor is 24)"),
    (
        "android.archs",
        "[tool.kivy.android].abis  (arm64-v8a -> arm64_v8a; the 32-bit ABIs "
        "armeabi-v7a and x86 are not supported)",
    ),
    ("android.permissions", "[tool.kivy.android.permissions].uses"),
    ("android.features", "[[tool.kivy.android.permissions.features]]"),
    ("services", "[[tool.kivy.android.services]]"),
    ("android.meta_data", "[tool.kivy.android.manifest].extra_application_xml"),
    ("android.add_activities", "[tool.kivy.android.manifest].extra_manifest_xml"),
    ("android.gradle_dependencies", "[tool.kivy.android].gradle_dependencies"),
    ("android.add_jars", "[[tool.kivy.android.android_libs]]"),
    ("android.release_artifact", "`kivyforge package -f apk|aab`"),
    ("android.debug_artifact", "`kivyforge build --debug -f apk|aab`"),
)

# Settings with no kivyforge counterpart, and why — these are the migration's
# real work, so name them rather than letting the user discover them one by one.
_BUILDOZER_DROPPED: tuple[tuple[str, str], ...] = (
    (
        "p4a.*, android.p4a_whitelist, android.blacklist_src",
        "there is no python-for-android layer: dependencies are Android wheels "
        "resolved by `kivyforge lock`.",
    ),
    (
        "requirements with a p4a recipe (e.g. 'kivy,pyjnius,numpy')",
        "each becomes a normal requirement; anything compiled needs an Android "
        "wheel (see docs/design/platforms/android/03).",
    ),
    (
        "android.ndk, android.sdk, android.ndk_api, android.gradle_version",
        "kivyforge pins the toolchain itself; `kivyforge doctor -p android` "
        "checks the host against those pins.",
    ),
    (
        "android.add_src",
        "app-side Java is not a kivyforge concept; the bootstrap's Java is "
        "generated, and `include_files` covers extra assets.",
    ),
    (
        "android.entrypoint, android.activity_class_name",
        "the launcher is generated; `[tool.kivy].entry_point` names the Python "
        "module to import instead.",
    ),
)

_BUILDOZER_MSG_HEAD = (
    "buildozer.spec found but no pyproject.toml.\n"
    "  kivyforge is configured through pyproject.toml and will not migrate a\n"
    "  buildozer.spec automatically. Create one with your app's metadata, then\n"
    "  re-run `kivyforge init -p android`.\n"
)

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
    buildozer_spec = cwd / BUILDOZER_SPEC_NAME

    if pyproject.is_file():
        platform_name = _resolve_init_platform(cli_platform, pyproject)
        _run_update_path(pyproject, force=force, platform_name=platform_name)
    elif buildozer_spec.is_file():
        raise ToolchainError(_buildozer_migration_message(buildozer_spec))
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


def _read_buildozer_spec(path: Path) -> dict[str, str]:
    """The ``[app]`` section as a flat dict, or ``{}`` if it will not parse.

    buildozer.spec is INI, but a hand-edited one need not be valid, and this is
    an error path — a spec we cannot read still gets the generic key mapping.
    """
    import configparser

    # Raw: buildozer.spec uses %(source.dir)s-style interpolation that means
    # something to buildozer and nothing here, and utf-8-sig because an editor
    # that BOMs the file would otherwise hide the section header.
    parser = configparser.RawConfigParser(strict=False)
    try:
        parser.read(path, encoding="utf-8-sig")
        if not parser.has_section("app"):
            return {}
        return {key: value.strip() for key, value in parser.items("app")}
    except (configparser.Error, OSError, UnicodeDecodeError):
        return {}


def _buildozer_migration_message(path: Path) -> str:
    """The non-zero exit's migration pointer (android/06 §init).

    Echoes the spec's own values next to their kivyforge keys where it can:
    a mapping table the user has to re-read against their file is busywork, and
    the values are right there.
    """
    spec = _read_buildozer_spec(path)
    lines = [_BUILDOZER_MSG_HEAD, "  Your buildozer.spec maps onto these keys:\n"]
    width = max(len(key) for key, _ in _BUILDOZER_MAP)
    for key, target in _BUILDOZER_MAP:
        value = spec.get(key)
        shown = f"    {key.ljust(width)}  ->  {target}"
        if value:
            shown += f"\n    {' ' * width}      currently: {_ellipsize(value)}"
        lines.append(shown)
    lines.append("\n  No kivyforge counterpart:\n")
    for keys, why in _BUILDOZER_DROPPED:
        lines.append(f"    {keys}\n      {why}")
    lines.append(
        "\n  Full reference: docs/design/platforms/android/01-pyproject-android.md"
    )
    return "\n".join(lines)


def _ellipsize(value: str, limit: int = 70) -> str:
    flat = " ".join(value.split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


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

"""Load and validate a kivyforge ``pyproject.toml`` (spec 01).

Implements the spec's validation rules. tomllib surfaces line numbers for
*syntax* errors; for *semantic* errors we report the dotted key path plus a
best-effort source line located by scanning the raw text.
"""

from __future__ import annotations

import keyword
import posixpath
import re
import tomllib
from pathlib import Path, PurePosixPath, PureWindowsPath

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from .errors import ConfigError
from .model import (
    DEFAULT_DESKTOP_CATEGORIES,
    DEFAULT_LINUX_ARCHS,
    DEFAULT_MACOS_ARCHS,
    DEFAULT_SIMULATOR_ARCHS,
    DEFAULT_WINDOWS_ARCHS,
    DEFAULT_WINDOWS_STORE_SCOPE,
    DEFAULT_WINDOWS_TIMESTAMP_URL,
    FREEDESKTOP_MAIN_CATEGORIES,
    MANAGED_INFO_PLIST_KEYS,
    RESERVED_BUILD_SETTINGS,
    SUPPORTED_IOS_SCHEMA_VERSION,
    SUPPORTED_LINUX_SCHEMA_VERSION,
    SUPPORTED_MACOS_SCHEMA_VERSION,
    SUPPORTED_WINDOWS_SCHEMA_VERSION,
    VALID_LINUX_ARCHS,
    VALID_MACOS_ARCHS,
    VALID_ORIENTATIONS,
    VALID_SIMULATOR_ARCHS,
    VALID_SWIFT_REQUIREMENT_KINDS,
    VALID_WINDOWS_ARCHS,
    VALID_WINDOWS_STORE_SCOPES,
    WINDOWS_APP_ID_MAX_LENGTH,
    Author,
    Config,
    DesktopConfig,
    IconConfig,
    IosConfig,
    KivyMeta,
    LinuxConfig,
    MacosConfig,
    MacosSigningConfig,
    NativeBinaryDep,
    ProjectMeta,
    SigningConfig,
    SplashConfig,
    SwiftPackageDep,
    WindowsConfig,
    WindowsSigningConfig,
    XcframeworkDep,
)


def _is_absolute_source(value: str) -> bool:
    """True if ``value`` is absolute under POSIX *or* Windows rules.

    Repo-relative sources/paths in ``pyproject.toml`` must stay portable, so a
    path that is absolute on any host is rejected everywhere. This is host
    independent on purpose: ``os.path.isabs`` changed on Windows in Python 3.13
    (a leading ``/`` is no longer "absolute"), which would otherwise let
    ``"/abs/x"`` slip through the loader on Windows only.
    """
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _posix_normpath(value: str) -> str:
    """Normalize ``value`` under POSIX semantics, treating ``\\`` as a separator.

    ``os.path.normpath`` produces backslash-separated results on Windows that
    ``PurePosixPath`` will not split, so an escaping ``..\\..\\x`` would evade the
    parts check on Windows. Normalizing to forward slashes keeps the escape and
    ``.`` checks host independent.
    """
    return posixpath.normpath(value.replace("\\", "/"))


def load_config(
    path: str | Path,
    *,
    require_ios: bool = True,
    require_macos: bool = False,
    require_linux: bool = False,
    require_windows: bool = False,
) -> Config:
    """Parse and validate ``pyproject.toml`` at ``path``.

    ``require_ios`` / ``require_macos`` / ``require_linux`` / ``require_windows``
    enforce the presence of the respective ``[tool.kivy.<platform>]`` overlay. A
    platform verb requires its own overlay; contexts that only inspect the
    cross-platform tables set them all False.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    return load_config_from_text(
        text,
        require_ios=require_ios,
        require_macos=require_macos,
        require_linux=require_linux,
        require_windows=require_windows,
        project_root=path.parent,
    )


def load_config_from_text(
    text: str,
    *,
    require_ios: bool = True,
    require_macos: bool = False,
    require_linux: bool = False,
    require_windows: bool = False,
    project_root: Path | None = None,
) -> Config:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        # tomllib embeds the line in the message; surface it directly.
        raise ConfigError(f"invalid TOML: {exc}") from exc

    finder = _LineFinder(text)
    project = _parse_project(raw, finder)
    kivy = _parse_kivy(raw, finder)
    ios = _parse_ios(raw, finder, project, project_root=project_root)
    macos = _parse_macos(raw, finder, project, project_root=project_root)
    linux = _parse_linux(raw, finder, project, project_root=project_root)
    windows = _parse_windows(raw, finder, project, project_root=project_root)

    if ios is None and require_ios:
        raise ConfigError(
            "missing [tool.kivy.ios] table",
            key_path="tool.kivy.ios",
            hint="add a [tool.kivy.ios] overlay; [tool.kivy] alone is not a "
            "buildable iOS target. Run `kivyforge init`.",
        )
    if macos is None and require_macos:
        raise ConfigError(
            "missing [tool.kivy.macos] table",
            key_path="tool.kivy.macos",
            hint="add a [tool.kivy.macos] overlay; [tool.kivy] alone is not a "
            "buildable macOS target.",
        )
    if linux is None and require_linux:
        raise ConfigError(
            "missing [tool.kivy.linux] table",
            key_path="tool.kivy.linux",
            hint="add a [tool.kivy.linux] overlay; [tool.kivy] alone is not a "
            "buildable Linux target.",
        )
    if windows is None and require_windows:
        raise ConfigError(
            "missing [tool.kivy.windows] table",
            key_path="tool.kivy.windows",
            hint="add a [tool.kivy.windows] overlay; [tool.kivy] alone is not a "
            "buildable Windows target.",
        )

    return Config(
        project=project,
        kivy=kivy,
        ios=ios,
        macos=macos,
        linux=linux,
        windows=windows,
    )


# --------------------------------------------------------------------------- #
# [project]
# --------------------------------------------------------------------------- #
def _parse_project(raw: dict, finder: _LineFinder) -> ProjectMeta:
    project = raw.get("project")
    if not isinstance(project, dict):
        raise ConfigError(
            "missing [project] table (PEP 621)",
            key_path="project",
            hint="every kivyforge app needs a [project] table with at least "
            "name and version.",
        )

    name = project.get("name")
    if not name or not isinstance(name, str):
        raise ConfigError(
            "missing or empty [project].name",
            key_path="project.name",
            line=finder.line("project"),
        )
    version = project.get("version")
    if not version or not isinstance(version, str):
        raise ConfigError(
            "missing or empty [project].version",
            key_path="project.version",
            line=finder.line("project"),
        )

    deps = project.get("dependencies", [])
    if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
        raise ConfigError(
            "[project].dependencies must be a list of PEP 508 strings",
            key_path="project.dependencies",
        )

    authors: list[Author] = []
    for entry in project.get("authors", []) or []:
        if isinstance(entry, dict):
            authors.append(Author(name=entry.get("name"), email=entry.get("email")))

    return ProjectMeta(
        name=name,
        version=version,
        description=project.get("description"),
        requires_python=project.get("requires-python"),
        dependencies=tuple(deps),
        authors=tuple(authors),
    )


# --------------------------------------------------------------------------- #
# [tool.kivy]
# --------------------------------------------------------------------------- #
def _parse_kivy(raw: dict, finder: _LineFinder) -> KivyMeta:
    tool = raw.get("tool", {})
    kivy = tool.get("kivy") if isinstance(tool, dict) else None
    if not isinstance(kivy, dict):
        raise ConfigError(
            "missing [tool.kivy] table",
            key_path="tool.kivy",
            hint="run `kivyforge init` to scaffold it.",
        )

    app_dir = _validate_app_dir(kivy.get("app_dir"), finder)

    entry_point = kivy.get("entry_point", "main")
    _validate_entry_point(entry_point, finder)

    orientation = kivy.get("orientation", ["portrait"])
    _validate_orientation(orientation, finder)

    return KivyMeta(
        app_dir=app_dir,
        display_name=kivy.get("display_name"),
        entry_point=entry_point,
        orientation=tuple(orientation),
    )


def _validate_app_dir(app_dir: object, finder: _LineFinder) -> str:
    # Rule 6: app_dir is required and must name a subdirectory.
    if app_dir is None:
        raise ConfigError(
            "missing required [tool.kivy].app_dir",
            key_path="tool.kivy.app_dir",
            hint='set app_dir to a subdirectory such as "src".',
        )
    if not isinstance(app_dir, str) or app_dir.strip() == "":
        raise ConfigError(
            "[tool.kivy].app_dir must be a non-empty string",
            key_path="tool.kivy.app_dir",
            line=finder.line("app_dir"),
        )
    if app_dir == "." or _posix_normpath(app_dir) == ".":
        raise ConfigError(
            'app_dir = "." (project root) is not allowed',
            key_path="tool.kivy.app_dir",
            line=finder.line("app_dir"),
            hint="keep app code in a subdirectory (e.g. src/) so the bundle "
            "excludes .git/, .venv/, and the <app>-ios/ build output.",
        )
    if _is_absolute_source(app_dir):
        raise ConfigError(
            "app_dir must be relative, not an absolute path",
            key_path="tool.kivy.app_dir",
            line=finder.line("app_dir"),
        )
    parts = PurePosixPath(_posix_normpath(app_dir)).parts
    if parts and parts[0] == "..":
        raise ConfigError(
            "app_dir must not escape the project directory",
            key_path="tool.kivy.app_dir",
            line=finder.line("app_dir"),
        )
    return app_dir


def _validate_entry_point(entry_point: object, finder: _LineFinder) -> None:
    # Rule 5: entry_point must be a valid (dotted) Python identifier.
    if not isinstance(entry_point, str) or entry_point == "":
        raise ConfigError(
            "[tool.kivy].entry_point must be a non-empty string",
            key_path="tool.kivy.entry_point",
            line=finder.line("entry_point"),
        )
    parts = entry_point.split(".")
    if not all(p.isidentifier() and not keyword.iskeyword(p) for p in parts):
        raise ConfigError(
            f"entry_point {entry_point!r} is not a valid dotted Python identifier",
            key_path="tool.kivy.entry_point",
            line=finder.line("entry_point"),
            hint='e.g. "main" for src/main.py, or "pkg.start" for src/pkg/start.py.',
        )


def _validate_orientation(orientation: object, finder: _LineFinder) -> None:
    # Rule 7: orientation values must be within the allowed set.
    if not isinstance(orientation, list) or not orientation:
        raise ConfigError(
            "[tool.kivy].orientation must be a non-empty list",
            key_path="tool.kivy.orientation",
            line=finder.line("orientation"),
        )
    bad = [o for o in orientation if o not in VALID_ORIENTATIONS]
    if bad:
        raise ConfigError(
            f"invalid orientation value(s): {', '.join(map(str, bad))}",
            key_path="tool.kivy.orientation",
            line=finder.line("orientation"),
            hint=f"allowed: {', '.join(sorted(VALID_ORIENTATIONS))}.",
        )


# --------------------------------------------------------------------------- #
# [tool.kivy.ios]
# --------------------------------------------------------------------------- #
def _parse_ios(
    raw: dict,
    finder: _LineFinder,
    project: ProjectMeta,
    *,
    project_root: Path | None = None,
) -> IosConfig | None:
    tool = raw.get("tool", {})
    kivy = tool.get("kivy", {}) if isinstance(tool, dict) else {}
    ios = kivy.get("ios") if isinstance(kivy, dict) else None
    if ios is None:
        return None
    if not isinstance(ios, dict):
        raise ConfigError("[tool.kivy.ios] must be a table", key_path="tool.kivy.ios")

    # Rule 3: schema_version required + supported.
    schema_version = ios.get("schema_version")
    if schema_version is None:
        raise ConfigError(
            "missing required [tool.kivy.ios].schema_version",
            key_path="tool.kivy.ios.schema_version",
        )
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ConfigError(
            "[tool.kivy.ios].schema_version must be an integer",
            key_path="tool.kivy.ios.schema_version",
            line=finder.line("schema_version"),
        )
    if schema_version > SUPPORTED_IOS_SCHEMA_VERSION:
        raise ConfigError(
            f"[tool.kivy.ios].schema_version {schema_version} is newer than this "
            f"kivyforge understands (max {SUPPORTED_IOS_SCHEMA_VERSION})",
            key_path="tool.kivy.ios.schema_version",
            line=finder.line("schema_version"),
            hint="upgrade kivyforge.",
        )
    if schema_version < 1:
        raise ConfigError(
            f"unsupported [tool.kivy.ios].schema_version {schema_version}",
            key_path="tool.kivy.ios.schema_version",
            line=finder.line("schema_version"),
        )

    # Rule 4: bundle_id required.
    bundle_id = ios.get("bundle_id")
    if not bundle_id or not isinstance(bundle_id, str):
        raise ConfigError(
            "missing required [tool.kivy.ios].bundle_id",
            key_path="tool.kivy.ios.bundle_id",
            hint='e.g. bundle_id = "org.example.myapp".',
        )
    # A bundle identifier is a UTI: only alphanumerics, hyphen, and period are
    # allowed.  Catch invalid characters (commonly an underscore copied from a
    # Python package name) here rather than as a cryptic Xcode build failure.
    if not re.fullmatch(r"[A-Za-z0-9.-]+", bundle_id):
        raise ConfigError(
            f"invalid character in [tool.kivy.ios].bundle_id {bundle_id!r}",
            key_path="tool.kivy.ios.bundle_id",
            line=finder.line("bundle_id"),
            hint=(
                "bundle identifiers may contain only letters, digits, hyphen "
                "(-), and period (.). Replace underscores with hyphens, e.g. "
                '"org.example.hello-world".'
            ),
        )

    build = ios.get("build", 1)
    if not isinstance(build, int) or isinstance(build, bool):
        raise ConfigError(
            "[tool.kivy.ios].build must be an integer",
            key_path="tool.kivy.ios.build",
            line=finder.line("build"),
        )

    deployment_target = ios.get("deployment_target", "13.0")
    if not isinstance(deployment_target, str):
        raise ConfigError(
            "[tool.kivy.ios].deployment_target must be a string",
            key_path="tool.kivy.ios.deployment_target",
            line=finder.line("deployment_target"),
        )

    simulator_archs = _parse_simulator_archs(ios, finder)

    extra_index_urls = ios.get("extra_index_urls", [])
    if not isinstance(extra_index_urls, list) or not all(
        isinstance(u, str) for u in extra_index_urls
    ):
        raise ConfigError(
            "[tool.kivy.ios].extra_index_urls must be a list of strings",
            key_path="tool.kivy.ios.extra_index_urls",
            line=finder.line("extra_index_urls"),
        )

    find_links = _parse_find_links(ios, finder, project_root=project_root)
    exclude = _parse_exclude(ios, finder)

    python_version = _parse_python_version(ios)
    _check_requires_python(project, python_version, finder)

    icons = _parse_icons(ios)
    splash = _parse_splash(ios)
    xcframeworks = _parse_xcframeworks(ios, finder)
    swift_packages = _parse_swift_packages(ios, finder)
    signing = _parse_signing(ios, finder)
    info_plist = _parse_info_plist(ios, finder)
    build_settings = _parse_build_settings(ios, finder)
    privacy_source = _parse_privacy(ios)
    entitlements = _parse_entitlements(ios)

    return IosConfig(
        schema_version=schema_version,
        bundle_id=bundle_id,
        build=build,
        deployment_target=deployment_target,
        simulator_archs=simulator_archs,
        extra_index_urls=tuple(extra_index_urls),
        find_links=tuple(find_links),
        exclude=tuple(exclude),
        python_version=python_version,
        icons=icons,
        splash=splash,
        xcframeworks=tuple(xcframeworks),
        swift_packages=tuple(swift_packages),
        entitlements=entitlements,
        signing=signing,
        privacy_manifest_source=privacy_source,
        info_plist=info_plist,
        build_settings=build_settings,
    )


# --------------------------------------------------------------------------- #
# [tool.kivy.macos]
# --------------------------------------------------------------------------- #
def _parse_macos(
    raw: dict,
    finder: _LineFinder,
    project: ProjectMeta,
    *,
    project_root: Path | None = None,
) -> MacosConfig | None:
    tool = raw.get("tool", {})
    kivy = tool.get("kivy", {}) if isinstance(tool, dict) else {}
    macos = kivy.get("macos") if isinstance(kivy, dict) else None
    if macos is None:
        return None
    if not isinstance(macos, dict):
        raise ConfigError(
            "[tool.kivy.macos] must be a table", key_path="tool.kivy.macos"
        )

    schema_version = _parse_platform_schema_version(
        macos,
        finder,
        key_path="tool.kivy.macos.schema_version",
        supported=SUPPORTED_MACOS_SCHEMA_VERSION,
    )

    bundle_id = macos.get("bundle_id")
    if not bundle_id or not isinstance(bundle_id, str):
        raise ConfigError(
            "missing required [tool.kivy.macos].bundle_id",
            key_path="tool.kivy.macos.bundle_id",
            hint='e.g. bundle_id = "org.example.myapp".',
        )
    if not re.fullmatch(r"[A-Za-z0-9.-]+", bundle_id):
        raise ConfigError(
            f"invalid character in [tool.kivy.macos].bundle_id {bundle_id!r}",
            key_path="tool.kivy.macos.bundle_id",
            line=finder.line("bundle_id"),
            hint=(
                "bundle identifiers may contain only letters, digits, hyphen "
                "(-), and period (.). Replace underscores with hyphens, e.g. "
                '"org.example.hello-world".'
            ),
        )

    build = macos.get("build", 1)
    if not isinstance(build, int) or isinstance(build, bool):
        raise ConfigError(
            "[tool.kivy.macos].build must be an integer",
            key_path="tool.kivy.macos.build",
            line=finder.line("build"),
        )

    minimum_system_version = macos.get("minimum_system_version")
    if minimum_system_version is not None and not isinstance(
        minimum_system_version, str
    ):
        raise ConfigError(
            "[tool.kivy.macos].minimum_system_version must be a string",
            key_path="tool.kivy.macos.minimum_system_version",
            line=finder.line("minimum_system_version"),
        )

    archs = _parse_macos_archs(macos, finder)

    extra_index_urls = macos.get("extra_index_urls", [])
    if not isinstance(extra_index_urls, list) or not all(
        isinstance(u, str) for u in extra_index_urls
    ):
        raise ConfigError(
            "[tool.kivy.macos].extra_index_urls must be a list of strings",
            key_path="tool.kivy.macos.extra_index_urls",
            line=finder.line("extra_index_urls"),
        )

    find_links = _parse_platform_find_links(
        macos,
        finder,
        key_path="tool.kivy.macos.find_links",
        project_root=project_root,
    )
    exclude = _parse_platform_exclude(macos, finder, key_path="tool.kivy.macos.exclude")

    python_version = _parse_platform_python_version(
        macos, key_path="tool.kivy.macos.python"
    )
    _check_requires_python_generic(
        project,
        python_version,
        finder,
        key_path="tool.kivy.macos.python.version",
    )

    icons = _parse_platform_icons(macos, key_path="tool.kivy.macos.icons")
    entitlements = _parse_macos_entitlements(macos)
    signing = _parse_macos_signing(macos, finder)
    _check_macos_entitlements_notarizable(entitlements, signing, finder)
    binaries = _parse_native_binaries(macos, "macos", finder)

    return MacosConfig(
        schema_version=schema_version,
        bundle_id=bundle_id,
        build=build,
        minimum_system_version=minimum_system_version,
        archs=archs,
        extra_index_urls=tuple(extra_index_urls),
        find_links=tuple(find_links),
        exclude=tuple(exclude),
        python_version=python_version,
        icons=icons,
        entitlements=entitlements,
        signing=signing,
        binaries=tuple(binaries),
    )


def _parse_macos_entitlements(macos: dict) -> dict[str, object]:
    ent = macos.get("entitlements")
    if ent is None:
        return {}
    if not isinstance(ent, dict):
        raise ConfigError(
            "[tool.kivy.macos.entitlements] must be a table",
            key_path="tool.kivy.macos.entitlements",
        )
    return dict(ent)


def _check_macos_entitlements_notarizable(
    entitlements: dict[str, object],
    signing: MacosSigningConfig,
    finder: _LineFinder,
) -> None:
    """Reject ``get-task-allow: true`` when Developer ID signing is configured.

    Apple's notary service always rejects a submission carrying this
    entitlement ("The executable requests the com.apple.security.get-task-
    allow entitlement.") — see "Resolving common notarization issues". It's
    only meaningful for local-debug (ad-hoc) builds, which never receive
    ``[tool.kivy.macos.entitlements]`` (see ``sign_bundle_adhoc``), so this is
    only checked once Developer ID signing is configured.
    """
    if not signing.configured:
        return
    key = "com.apple.security.get-task-allow"
    if entitlements.get(key) is True:
        raise ConfigError(
            f"[tool.kivy.macos.entitlements] sets {key!r} to true, but "
            "Developer ID signing is configured",
            key_path=f"tool.kivy.macos.entitlements.{key}",
            line=finder.line(key),
            hint="notarization always rejects this entitlement; remove it (or "
            "set it to false) before packaging for distribution.",
        )


def _parse_macos_signing(macos: dict, finder: _LineFinder) -> MacosSigningConfig:
    signing = macos.get("signing")
    if signing is None:
        return MacosSigningConfig()
    if not isinstance(signing, dict):
        raise ConfigError(
            "[tool.kivy.macos.signing] must be a table",
            key_path="tool.kivy.macos.signing",
        )
    for key in ("identity", "team_id", "notary_profile"):
        value = signing.get(key, "")
        if not isinstance(value, str):
            raise ConfigError(
                f"[tool.kivy.macos.signing].{key} must be a string",
                key_path=f"tool.kivy.macos.signing.{key}",
                line=finder.line(key),
            )
    return MacosSigningConfig(
        identity=signing.get("identity", ""),
        team_id=signing.get("team_id", ""),
        notary_profile=signing.get("notary_profile", ""),
    )


def _parse_macos_archs(macos: dict, finder: _LineFinder) -> tuple[str, ...]:
    raw = macos.get("archs")
    if raw is None:
        return DEFAULT_MACOS_ARCHS
    line = finder.line("archs")
    if not isinstance(raw, list) or not all(isinstance(a, str) for a in raw):
        raise ConfigError(
            "[tool.kivy.macos].archs must be a list of strings",
            key_path="tool.kivy.macos.archs",
            line=line,
        )
    if not raw:
        raise ConfigError(
            "[tool.kivy.macos].archs must not be empty",
            key_path="tool.kivy.macos.archs",
            line=line,
            hint='at least one of "arm64", "x86_64" is required.',
        )
    unknown = [a for a in raw if a not in VALID_MACOS_ARCHS]
    if unknown:
        valid = ", ".join(sorted(VALID_MACOS_ARCHS))
        raise ConfigError(
            f"unknown macOS arch(es) {unknown} in [tool.kivy.macos].archs",
            key_path="tool.kivy.macos.archs",
            line=line,
            hint=f"valid values are: {valid}.",
        )
    seen: set[str] = set()
    ordered: list[str] = []
    for arch in raw:
        if arch not in seen:
            seen.add(arch)
            ordered.append(arch)
    return tuple(ordered)


# --------------------------------------------------------------------------- #
# [tool.kivy.linux]
# --------------------------------------------------------------------------- #
def _parse_linux(
    raw: dict,
    finder: _LineFinder,
    project: ProjectMeta,
    *,
    project_root: Path | None = None,
) -> LinuxConfig | None:
    tool = raw.get("tool", {})
    kivy = tool.get("kivy", {}) if isinstance(tool, dict) else {}
    linux = kivy.get("linux") if isinstance(kivy, dict) else None
    if linux is None:
        return None
    if not isinstance(linux, dict):
        raise ConfigError(
            "[tool.kivy.linux] must be a table", key_path="tool.kivy.linux"
        )

    schema_version = _parse_platform_schema_version(
        linux,
        finder,
        key_path="tool.kivy.linux.schema_version",
        supported=SUPPORTED_LINUX_SCHEMA_VERSION,
    )

    app_id = linux.get("app_id")
    if not app_id or not isinstance(app_id, str):
        raise ConfigError(
            "missing required [tool.kivy.linux].app_id",
            key_path="tool.kivy.linux.app_id",
            hint='e.g. app_id = "org.example.myapp".',
        )
    # app_id names the <app_id>.desktop file, Icon= key, and StartupWMClass;
    # restrict it to a valid .desktop basename (mirrors macOS bundle_id).
    if not re.fullmatch(r"[A-Za-z0-9.-]+", app_id):
        raise ConfigError(
            f"invalid character in [tool.kivy.linux].app_id {app_id!r}",
            key_path="tool.kivy.linux.app_id",
            line=finder.line("app_id"),
            hint=(
                "app_id may contain only letters, digits, hyphen (-), and period "
                '(.). Replace underscores with hyphens, e.g. "org.example.hello".'
            ),
        )

    glibc_floor = linux.get("glibc_floor")
    if glibc_floor is not None and not isinstance(glibc_floor, str):
        raise ConfigError(
            "[tool.kivy.linux].glibc_floor must be a string",
            key_path="tool.kivy.linux.glibc_floor",
            line=finder.line("glibc_floor"),
        )

    archs = _parse_linux_archs(linux, finder)

    extra_index_urls = linux.get("extra_index_urls", [])
    if not isinstance(extra_index_urls, list) or not all(
        isinstance(u, str) for u in extra_index_urls
    ):
        raise ConfigError(
            "[tool.kivy.linux].extra_index_urls must be a list of strings",
            key_path="tool.kivy.linux.extra_index_urls",
            line=finder.line("extra_index_urls"),
        )

    find_links = _parse_platform_find_links(
        linux,
        finder,
        key_path="tool.kivy.linux.find_links",
        project_root=project_root,
    )
    exclude = _parse_platform_exclude(linux, finder, key_path="tool.kivy.linux.exclude")

    python_version = _parse_platform_python_version(
        linux, key_path="tool.kivy.linux.python"
    )
    _check_requires_python_generic(
        project,
        python_version,
        finder,
        key_path="tool.kivy.linux.python.version",
    )

    icons = _parse_platform_icons(linux, key_path="tool.kivy.linux.icons")
    desktop = _parse_desktop(linux, finder)
    binaries = _parse_native_binaries(linux, "linux", finder)

    return LinuxConfig(
        schema_version=schema_version,
        app_id=app_id,
        glibc_floor=glibc_floor,
        archs=archs,
        extra_index_urls=tuple(extra_index_urls),
        find_links=tuple(find_links),
        exclude=tuple(exclude),
        python_version=python_version,
        icons=icons,
        desktop=desktop,
        binaries=tuple(binaries),
    )


def _parse_linux_archs(linux: dict, finder: _LineFinder) -> tuple[str, ...]:
    raw = linux.get("archs")
    if raw is None:
        return DEFAULT_LINUX_ARCHS
    line = finder.line("archs")
    if not isinstance(raw, list) or not all(isinstance(a, str) for a in raw):
        raise ConfigError(
            "[tool.kivy.linux].archs must be a list of strings",
            key_path="tool.kivy.linux.archs",
            line=line,
        )
    if not raw:
        raise ConfigError(
            "[tool.kivy.linux].archs must not be empty",
            key_path="tool.kivy.linux.archs",
            line=line,
            hint='only "x86_64" is supported this phase.',
        )
    unknown = [a for a in raw if a not in VALID_LINUX_ARCHS]
    if unknown:
        valid = ", ".join(sorted(VALID_LINUX_ARCHS))
        raise ConfigError(
            f"unsupported Linux arch(es) {unknown} in [tool.kivy.linux].archs",
            key_path="tool.kivy.linux.archs",
            line=line,
            hint=f"only {valid} is supported this phase (aarch64 is planned).",
        )
    seen: set[str] = set()
    ordered: list[str] = []
    for arch in raw:
        if arch not in seen:
            seen.add(arch)
            ordered.append(arch)
    return tuple(ordered)


def _parse_desktop(linux: dict, finder: _LineFinder) -> DesktopConfig:
    desktop = linux.get("desktop")
    if desktop is None:
        return DesktopConfig()
    if not isinstance(desktop, dict):
        raise ConfigError(
            "[tool.kivy.linux.desktop] must be a table",
            key_path="tool.kivy.linux.desktop",
        )
    raw = desktop.get("categories")
    if raw is None:
        return DesktopConfig()
    if not isinstance(raw, list) or not all(isinstance(c, str) and c for c in raw):
        raise ConfigError(
            "[tool.kivy.linux.desktop].categories must be a list of non-empty strings",
            key_path="tool.kivy.linux.desktop.categories",
            line=finder.line("categories"),
        )
    # Categories must be freedesktop *main* categories (linux-spec); reject typos
    # here so an invalid value never ships in a .desktop that breaks menu/search
    # integration (also enforced by desktop-file-validate at build/package time).
    unknown = [c for c in raw if c not in FREEDESKTOP_MAIN_CATEGORIES]
    if unknown:
        valid = ", ".join(sorted(FREEDESKTOP_MAIN_CATEGORIES))
        raise ConfigError(
            f"invalid [tool.kivy.linux.desktop].categories value(s): "
            f"{', '.join(unknown)}",
            key_path="tool.kivy.linux.desktop.categories",
            line=finder.line("categories"),
            hint=f"use freedesktop main categories: {valid}.",
        )
    return DesktopConfig(categories=tuple(raw) or DEFAULT_DESKTOP_CATEGORIES)


# --------------------------------------------------------------------------- #
# [tool.kivy.windows]
# --------------------------------------------------------------------------- #
def _parse_windows(
    raw: dict,
    finder: _LineFinder,
    project: ProjectMeta,
    *,
    project_root: Path | None = None,
) -> WindowsConfig | None:
    tool = raw.get("tool", {})
    kivy = tool.get("kivy", {}) if isinstance(tool, dict) else {}
    windows = kivy.get("windows") if isinstance(kivy, dict) else None
    if windows is None:
        return None
    if not isinstance(windows, dict):
        raise ConfigError(
            "[tool.kivy.windows] must be a table", key_path="tool.kivy.windows"
        )

    schema_version = _parse_platform_schema_version(
        windows,
        finder,
        key_path="tool.kivy.windows.schema_version",
        supported=SUPPORTED_WINDOWS_SCHEMA_VERSION,
    )

    app_id = _validate_windows_app_id(windows.get("app_id"), finder)
    archs = _parse_windows_archs(windows, finder)

    extra_index_urls = windows.get("extra_index_urls", [])
    if not isinstance(extra_index_urls, list) or not all(
        isinstance(u, str) for u in extra_index_urls
    ):
        raise ConfigError(
            "[tool.kivy.windows].extra_index_urls must be a list of strings",
            key_path="tool.kivy.windows.extra_index_urls",
            line=finder.line("extra_index_urls"),
        )

    find_links = _parse_platform_find_links(
        windows,
        finder,
        key_path="tool.kivy.windows.find_links",
        project_root=project_root,
    )
    exclude = _parse_platform_exclude(
        windows, finder, key_path="tool.kivy.windows.exclude"
    )

    python_version = _parse_platform_python_version(
        windows, key_path="tool.kivy.windows.python"
    )
    _check_requires_python_generic(
        project,
        python_version,
        finder,
        key_path="tool.kivy.windows.python.version",
    )

    icons = _parse_platform_icons(windows, key_path="tool.kivy.windows.icons")
    signing = _parse_windows_signing(windows, finder)
    binaries = _parse_native_binaries(windows, "windows", finder)

    return WindowsConfig(
        schema_version=schema_version,
        app_id=app_id,
        archs=archs,
        extra_index_urls=tuple(extra_index_urls),
        find_links=tuple(find_links),
        exclude=tuple(exclude),
        python_version=python_version,
        icons=icons,
        signing=signing,
        binaries=tuple(binaries),
    )


def _validate_windows_app_id(app_id: object, finder: _LineFinder) -> str:
    # app_id is the Windows AppUserModelID. Enforce only Microsoft's *hard*
    # constraints — no spaces, ≤128 characters (windows-spec). Pascal-case /
    # period-delimited style is a doctor WARNING, not a config-time error, and
    # hyphens are allowed. This is a different identifier from the Linux
    # reverse-DNS app_id and the macOS bundle_id, so it does not mirror theirs.
    if not app_id or not isinstance(app_id, str):
        raise ConfigError(
            "missing required [tool.kivy.windows].app_id",
            key_path="tool.kivy.windows.app_id",
            hint='e.g. app_id = "Example.MyApp" (AppUserModelID).',
        )
    if " " in app_id:
        raise ConfigError(
            f"[tool.kivy.windows].app_id {app_id!r} must not contain spaces",
            key_path="tool.kivy.windows.app_id",
            line=finder.line("app_id"),
            hint="an AppUserModelID may not contain spaces; use a compact "
            'identifier such as "Example.MyApp".',
        )
    if len(app_id) > WINDOWS_APP_ID_MAX_LENGTH:
        raise ConfigError(
            f"[tool.kivy.windows].app_id is {len(app_id)} characters; the "
            f"AppUserModelID maximum is {WINDOWS_APP_ID_MAX_LENGTH}",
            key_path="tool.kivy.windows.app_id",
            line=finder.line("app_id"),
        )
    return app_id


def _parse_windows_archs(windows: dict, finder: _LineFinder) -> tuple[str, ...]:
    raw = windows.get("archs")
    if raw is None:
        return DEFAULT_WINDOWS_ARCHS
    line = finder.line("archs")
    if not isinstance(raw, list) or not all(isinstance(a, str) for a in raw):
        raise ConfigError(
            "[tool.kivy.windows].archs must be a list of strings",
            key_path="tool.kivy.windows.archs",
            line=line,
        )
    if not raw:
        raise ConfigError(
            "[tool.kivy.windows].archs must not be empty",
            key_path="tool.kivy.windows.archs",
            line=line,
            hint='only "amd64" is supported this phase.',
        )
    # arm64: the "win-arm64 is planned" hint + the amd64-only validation relax
    # automatically once VALID_WINDOWS_ARCHS gains "arm64". See arm64-windows.md §1.
    unknown = [a for a in raw if a not in VALID_WINDOWS_ARCHS]
    if unknown:
        valid = ", ".join(sorted(VALID_WINDOWS_ARCHS))
        raise ConfigError(
            f"unsupported Windows arch(es) {unknown} in [tool.kivy.windows].archs",
            key_path="tool.kivy.windows.archs",
            line=line,
            hint=f"only {valid} is supported this phase (win-arm64 is planned).",
        )
    seen: set[str] = set()
    ordered: list[str] = []
    for arch in raw:
        if arch not in seen:
            seen.add(arch)
            ordered.append(arch)
    return tuple(ordered)


def _parse_windows_signing(windows: dict, finder: _LineFinder) -> WindowsSigningConfig:
    signing = windows.get("signing")
    if signing is None:
        return WindowsSigningConfig()
    if not isinstance(signing, dict):
        raise ConfigError(
            "[tool.kivy.windows.signing] must be a table",
            key_path="tool.kivy.windows.signing",
        )
    for key in ("thumbprint", "timestamp_url", "store_scope"):
        value = signing.get(key, "")
        if not isinstance(value, str):
            raise ConfigError(
                f"[tool.kivy.windows.signing].{key} must be a string",
                key_path=f"tool.kivy.windows.signing.{key}",
                line=finder.line(key),
            )
    store_scope = signing.get("store_scope", DEFAULT_WINDOWS_STORE_SCOPE)
    if store_scope not in VALID_WINDOWS_STORE_SCOPES:
        valid = ", ".join(sorted(VALID_WINDOWS_STORE_SCOPES))
        raise ConfigError(
            f"[tool.kivy.windows.signing].store_scope {store_scope!r} is invalid",
            key_path="tool.kivy.windows.signing.store_scope",
            line=finder.line("store_scope"),
            hint=f"valid values are: {valid}.",
        )
    return WindowsSigningConfig(
        thumbprint=signing.get("thumbprint", ""),
        timestamp_url=signing.get("timestamp_url", DEFAULT_WINDOWS_TIMESTAMP_URL),
        store_scope=store_scope,
    )


def _parse_platform_schema_version(
    table: dict, finder: _LineFinder, *, key_path: str, supported: int
) -> int:
    # Each platform overlay carries its *own* schema_version and evolves
    # independently (spec 01), so the ceiling is the caller's platform constant
    # — never another platform's (e.g. Linux must not be gated by the macOS max).
    schema_version = table.get("schema_version")
    if schema_version is None:
        raise ConfigError(
            f"missing required [{key_path.rsplit('.', 1)[0]}].schema_version",
            key_path=key_path,
        )
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ConfigError(
            "schema_version must be an integer",
            key_path=key_path,
            line=finder.line("schema_version"),
        )
    if schema_version > supported:
        raise ConfigError(
            f"schema_version {schema_version} is newer than this kivyforge "
            f"understands (max {supported})",
            key_path=key_path,
            line=finder.line("schema_version"),
            hint="upgrade kivyforge.",
        )
    if schema_version < 1:
        raise ConfigError(
            f"unsupported schema_version {schema_version}",
            key_path=key_path,
            line=finder.line("schema_version"),
        )
    return schema_version


def _parse_platform_python_version(table: dict, *, key_path: str) -> str:
    python = table.get("python")
    if python is None:
        raise ConfigError(
            f"missing required [{key_path}] table with a 'version'",
            key_path=f"{key_path}.version",
            hint=f'add:\n    [{key_path}]\n    version = "3.15.0"',
        )
    if not isinstance(python, dict):
        raise ConfigError(f"[{key_path}] must be a table", key_path=key_path)
    version = python.get("version")
    if version is None:
        raise ConfigError(
            f"missing required [{key_path}].version", key_path=f"{key_path}.version"
        )
    if not isinstance(version, str) or not version.strip():
        raise ConfigError(
            f"[{key_path}].version must be a non-empty string",
            key_path=f"{key_path}.version",
        )
    return version


def _parse_platform_icons(table: dict, *, key_path: str) -> IconConfig:
    icons = table.get("icons")
    if icons is None:
        return IconConfig()
    if not isinstance(icons, dict):
        raise ConfigError(f"[{key_path}] must be a table", key_path=key_path)
    return IconConfig(source=icons.get("source"))


def _parse_platform_find_links(
    table: dict, finder: _LineFinder, *, key_path: str, project_root: Path | None
) -> list[str]:
    raw = table.get("find_links", [])
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise ConfigError(
            f"[{key_path}] must be a list of strings",
            key_path=key_path,
            line=finder.line("find_links"),
        )
    out: list[str] = []
    for path in raw:
        if _is_absolute_source(path) or _posix_normpath(path) == "..":
            raise ConfigError(
                "find_links entries must be repo-relative paths",
                key_path=key_path,
                line=finder.line("find_links"),
            )
        normalized = _posix_normpath(path)
        if project_root is not None:
            _validate_find_link_scope(
                project_root, normalized, finder, key_path=key_path
            )
        out.append(normalized)
    return out


def _parse_platform_exclude(
    table: dict, finder: _LineFinder, *, key_path: str
) -> list[str]:
    raw = table.get("exclude", [])
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise ConfigError(
            f"[{key_path}] must be a list of package-name strings",
            key_path=key_path,
            line=finder.line("exclude"),
        )
    return [str(p) for p in raw]


def _check_requires_python_generic(
    project: ProjectMeta,
    python_version: str | None,
    finder: _LineFinder,
    *,
    key_path: str,
) -> None:
    if not project.requires_python or not python_version:
        return
    try:
        spec = SpecifierSet(project.requires_python)
    except InvalidSpecifier:
        raise ConfigError(
            f"[project].requires-python is not a valid specifier: "
            f"{project.requires_python!r}",
            key_path="project.requires-python",
        ) from None
    try:
        ver = Version(python_version)
    except InvalidVersion:
        raise ConfigError(
            f"[{key_path}] is not a valid version: {python_version!r}",
            key_path=key_path,
        ) from None
    if not spec.contains(ver, prereleases=True):
        hint = "align requires-python with the platform Python version."
        if ver.is_prerelease:
            hint = (
                f"pre-release runtimes such as {python_version} need an explicit "
                f'floor (e.g. requires-python = ">={python_version}").'
            )
        raise ConfigError(
            f"[project].requires-python ({project.requires_python}) excludes the "
            f"selected Python version {python_version}",
            key_path=key_path,
            line=finder.line("requires-python"),
            hint=hint,
        )


def _parse_simulator_archs(ios: dict, finder: _LineFinder) -> tuple[str, ...]:
    """``[tool.kivy.ios].simulator_archs`` — which simulator slices to pin.

    Defaults to device-arm64-plus both simulator arches; a project that no longer
    targets Intel simulator hosts may set ``["arm64"]`` to stop pinning x86_64.
    """
    raw = ios.get("simulator_archs")
    if raw is None:
        return DEFAULT_SIMULATOR_ARCHS
    line = finder.line("simulator_archs")
    if not isinstance(raw, list) or not all(isinstance(a, str) for a in raw):
        raise ConfigError(
            "[tool.kivy.ios].simulator_archs must be a list of strings",
            key_path="tool.kivy.ios.simulator_archs",
            line=line,
        )
    if not raw:
        raise ConfigError(
            "[tool.kivy.ios].simulator_archs must not be empty",
            key_path="tool.kivy.ios.simulator_archs",
            line=line,
            hint='at least one of "arm64", "x86_64" is required.',
        )
    unknown = [a for a in raw if a not in VALID_SIMULATOR_ARCHS]
    if unknown:
        valid = ", ".join(sorted(VALID_SIMULATOR_ARCHS))
        raise ConfigError(
            f"unknown simulator arch(es) {unknown} in [tool.kivy.ios].simulator_archs",
            key_path="tool.kivy.ios.simulator_archs",
            line=line,
            hint=f"valid values are: {valid}.",
        )
    # De-dupe while preserving declared order (stable, deterministic slices).
    seen: set[str] = set()
    ordered: list[str] = []
    for arch in raw:
        if arch not in seen:
            seen.add(arch)
            ordered.append(arch)
    return tuple(ordered)


def _parse_python_version(ios: dict) -> str:
    # Rule: [tool.kivy.ios.python].version is required (spec 01). Without it,
    # `kivyforge lock` would silently fall back to a hidden default Python
    # version rather than building against the version the project declares.
    python = ios.get("python")
    if python is None:
        raise ConfigError(
            "missing required [tool.kivy.ios.python] table with a 'version'",
            key_path="tool.kivy.ios.python.version",
            hint='add:\n    [tool.kivy.ios.python]\n    version = "3.15.0"\n'
            "  (the Python.xcframework version to build against).",
        )
    if not isinstance(python, dict):
        raise ConfigError(
            "[tool.kivy.ios.python] must be a table", key_path="tool.kivy.ios.python"
        )
    version = python.get("version")
    if version is None:
        raise ConfigError(
            "missing required [tool.kivy.ios.python].version",
            key_path="tool.kivy.ios.python.version",
        )
    if not isinstance(version, str) or not version.strip():
        raise ConfigError(
            "[tool.kivy.ios.python].version must be a non-empty string",
            key_path="tool.kivy.ios.python.version",
        )
    return version


def _check_requires_python(
    project: ProjectMeta, python_version: str | None, finder: _LineFinder
) -> None:
    # Rule 10: requires-python must not exclude the selected python version.
    if not project.requires_python or not python_version:
        return
    try:
        spec = SpecifierSet(project.requires_python)
    except InvalidSpecifier:
        raise ConfigError(
            f"[project].requires-python is not a valid specifier: "
            f"{project.requires_python!r}",
            key_path="project.requires-python",
        ) from None
    try:
        ver = Version(python_version)
    except InvalidVersion:
        raise ConfigError(
            f"[tool.kivy.ios.python].version is not a valid version: "
            f"{python_version!r}",
            key_path="tool.kivy.ios.python.version",
        ) from None
    if not spec.contains(ver, prereleases=True):
        hint = "align requires-python with the iOS Python version."
        if ver.is_prerelease:
            hint = (
                f"pre-release runtimes such as {python_version} need an explicit "
                f'floor (e.g. requires-python = ">={python_version}"), not '
                f'">=3.15" alone.'
            )
        raise ConfigError(
            f"[project].requires-python ({project.requires_python}) excludes the "
            f"selected Python.xcframework version {python_version}",
            key_path="tool.kivy.ios.python.version",
            line=finder.line("requires-python"),
            hint=hint,
        )


def _parse_find_links(
    ios: dict, finder: _LineFinder, *, project_root: Path | None = None
) -> list[str]:
    raw = ios.get("find_links", [])
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise ConfigError(
            "[tool.kivy.ios].find_links must be a list of strings",
            key_path="tool.kivy.ios.find_links",
            line=finder.line("find_links"),
        )
    out: list[str] = []
    for path in raw:
        if _is_absolute_source(path) or _posix_normpath(path) == "..":
            raise ConfigError(
                "find_links entries must be repo-relative paths",
                key_path="tool.kivy.ios.find_links",
                line=finder.line("find_links"),
            )
        normalized = _posix_normpath(path)
        if project_root is not None:
            _validate_find_link_scope(project_root, normalized, finder)
        out.append(normalized)
    return out


def _repo_root(start: Path) -> Path | None:
    """Nearest ancestor (inclusive) containing a ``.git`` marker, else None."""
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _validate_find_link_scope(
    project_root: Path,
    entry: str,
    finder: _LineFinder,
    *,
    key_path: str = "tool.kivy.ios.find_links",
) -> None:
    """Constrain find_links to repo-relative locations.

    Permitted: inside the project, a sibling under the same parent (e.g.
    ``../wheels``), or — when the project lives in a git checkout — anywhere
    within that repository (e.g. a shared ``examples/wheels/`` reached from a
    nested ``examples/<group>/<app>/`` via ``../../wheels``). This keeps wheels
    inside the tree while supporting one shared wheelhouse for grouped examples.
    ``key_path`` names the offending overlay so the error points at the right
    platform (find_links is a shared iOS/macOS/Linux surface).
    """
    resolved = (project_root / entry).resolve()
    root = project_root.resolve()
    allowed = [root, root.parent]
    repo = _repo_root(root)
    if repo is not None:
        allowed.append(repo)
    for base in allowed:
        if resolved == base or base in resolved.parents:
            return
    raise ConfigError(
        "find_links entries must stay within the project directory, a sibling "
        "directory under the same parent, or the enclosing repository",
        key_path=key_path,
        line=finder.line("find_links"),
        hint='e.g. "wheels" inside the project, "../wheels" for a sibling dir, '
        'or "../../wheels" for a shared examples wheelhouse.',
    )


def _parse_exclude(ios: dict, finder: _LineFinder) -> list[str]:
    raw = ios.get("exclude", [])
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise ConfigError(
            "[tool.kivy.ios].exclude must be a list of package-name strings",
            key_path="tool.kivy.ios.exclude",
            line=finder.line("exclude"),
        )
    return [str(p) for p in raw]


def _parse_icons(ios: dict) -> IconConfig:
    icons = ios.get("icons")
    if icons is None:
        return IconConfig()
    if not isinstance(icons, dict):
        raise ConfigError(
            "[tool.kivy.ios.icons] must be a table", key_path="tool.kivy.ios.icons"
        )
    return IconConfig(source=icons.get("source"))


def _parse_splash(ios: dict) -> SplashConfig:
    splash = ios.get("splash")
    if splash is None:
        return SplashConfig()
    if not isinstance(splash, dict):
        raise ConfigError(
            "[tool.kivy.ios.splash] must be a table", key_path="tool.kivy.ios.splash"
        )
    return SplashConfig(
        source=splash.get("source"), background=splash.get("background")
    )


def _parse_xcframeworks(ios: dict, finder: _LineFinder) -> list[XcframeworkDep]:
    native = ios.get("native")
    if not isinstance(native, dict):
        return []
    table = native.get("xcframeworks")
    if table is None:
        return []
    if not isinstance(table, dict):
        raise ConfigError(
            "[tool.kivy.ios.native.xcframeworks] must be a table",
            key_path="tool.kivy.ios.native.xcframeworks",
        )
    out: list[XcframeworkDep] = []
    for name, entry in table.items():
        key_path = f"tool.kivy.ios.native.xcframeworks.{name}"
        if not isinstance(entry, dict):
            raise ConfigError(
                f"xcframework {name!r} must be an inline table with version + source",
                key_path=key_path,
            )
        version = entry.get("version")
        source = entry.get("source")
        if not isinstance(version, str) or not version:
            raise ConfigError(
                f"xcframework {name!r} requires a string 'version'",
                key_path=key_path,
            )
        if not isinstance(source, str) or not source:
            raise ConfigError(
                f"xcframework {name!r} requires an explicit 'source' (URL or "
                f"repo-relative path)",
                key_path=key_path,
            )
        _validate_artifact_source("xcframework", name, source, key_path)
        out.append(
            XcframeworkDep(
                name=name,
                version=version,
                source=source,
                link=_require_bool(
                    entry.get("link", True),
                    key_path=f"{key_path}.link",
                    field="link",
                    finder=finder,
                ),
                embed=_require_bool(
                    entry.get("embed", True),
                    key_path=f"{key_path}.embed",
                    field="embed",
                    finder=finder,
                ),
            )
        )
    return out


def _validate_artifact_source(kind: str, name: str, source: str, key_path: str) -> None:
    # A URL is fetched as-is; anything else is a repo-relative path that must
    # stay inside the project (mirrors find_links / swift path rules, spec 01).
    # Shared by xcframeworks (iOS) and native binaries (desktop).
    if source.startswith(("http://", "https://")):
        return
    if _is_absolute_source(source):
        raise ConfigError(
            f"{kind} {name!r} source must not be an absolute path",
            key_path=key_path,
        )
    parts = PurePosixPath(_posix_normpath(source)).parts
    if parts and parts[0] == "..":
        raise ConfigError(
            f"{kind} {name!r} source must not escape the project directory",
            key_path=key_path,
            hint="vendor the artifact under the project (or a sibling dir) and use "
            "a repo-relative path, or give a direct https:// URL.",
        )


def _parse_native_binaries(
    overlay: dict, platform: str, finder: _LineFinder
) -> list[NativeBinaryDep]:
    """Parse ``[tool.kivy.<platform>.native.binaries]`` into ``NativeBinaryDep``s.

    Shared across the desktop backends; the ``platform`` string only shapes the
    ``key_path`` used in diagnostics.
    """
    native = overlay.get("native")
    if not isinstance(native, dict):
        return []
    table = native.get("binaries")
    if table is None:
        return []
    base = f"tool.kivy.{platform}.native.binaries"
    if not isinstance(table, dict):
        raise ConfigError(f"[{base}] must be a table", key_path=base)
    out: list[NativeBinaryDep] = []
    for name, entry in table.items():
        key_path = f"{base}.{name}"
        if not isinstance(entry, dict):
            raise ConfigError(
                f"native binary {name!r} must be an inline table with version + source",
                key_path=key_path,
            )
        version = entry.get("version")
        source = entry.get("source")
        if not isinstance(version, str) or not version:
            raise ConfigError(
                f"native binary {name!r} requires a string 'version'",
                key_path=key_path,
            )
        if not isinstance(source, str) or not source:
            raise ConfigError(
                f"native binary {name!r} requires an explicit 'source' (URL or "
                f"repo-relative path)",
                key_path=key_path,
            )
        _validate_artifact_source("native binary", name, source, key_path)
        out.append(NativeBinaryDep(name=name, version=version, source=source))
    return out


def _parse_swift_packages(ios: dict, finder: _LineFinder) -> list[SwiftPackageDep]:
    native = ios.get("native")
    if not isinstance(native, dict):
        return []
    table = native.get("swift_packages")
    if table is None:
        return []
    if not isinstance(table, dict):
        raise ConfigError(
            "[tool.kivy.ios.native.swift_packages] must be a table",
            key_path="tool.kivy.ios.native.swift_packages",
        )
    out: list[SwiftPackageDep] = []
    for name, entry in table.items():
        key_path = f"tool.kivy.ios.native.swift_packages.{name}"
        if not isinstance(entry, dict):
            raise ConfigError(
                f"swift package {name!r} must be an inline table",
                key_path=key_path,
            )
        url = entry.get("url")
        path = entry.get("path")
        if url is not None and (not isinstance(url, str) or not url):
            raise ConfigError(
                f"swift package {name!r} 'url' must be a non-empty string",
                key_path=key_path,
            )
        # Rule: exactly one of url / path identifies the package source.
        if bool(url) == bool(path):
            raise ConfigError(
                f"swift package {name!r} must set exactly one of 'url' or 'path'",
                key_path=key_path,
                hint="a remote package needs 'url' + 'requirement'; a local one "
                "needs a repo-relative 'path'.",
            )
        requirement: dict[str, object] | None = None
        if url:
            requirement = _parse_swift_requirement(
                name, entry.get("requirement"), key_path
            )
        else:
            path = _validate_swift_path(name, path, key_path)
        products = entry.get("products")
        if (
            not isinstance(products, list)
            or not products
            or not all(isinstance(p, str) and p for p in products)
        ):
            raise ConfigError(
                f"swift package {name!r} requires a non-empty 'products' list of "
                f"strings (the SPM library product(s) to link)",
                key_path=key_path,
            )
        out.append(
            SwiftPackageDep(
                name=name,
                products=tuple(products),
                url=url or None,
                path=path or None,
                requirement=requirement,
                link=_require_bool(
                    entry.get("link", True),
                    key_path=f"{key_path}.link",
                    field="link",
                    finder=finder,
                ),
                embed=_require_bool(
                    entry.get("embed", True),
                    key_path=f"{key_path}.embed",
                    field="embed",
                    finder=finder,
                ),
            )
        )
    return out


def _parse_swift_requirement(
    name: str, requirement: object, key_path: str
) -> dict[str, object]:
    valid = ", ".join(sorted(VALID_SWIFT_REQUIREMENT_KINDS))
    if not isinstance(requirement, dict) or len(requirement) != 1:
        raise ConfigError(
            f"remote swift package {name!r} needs a 'requirement' with exactly one "
            f"version rule",
            key_path=key_path,
            hint=f"valid rules: {valid}.",
        )
    ((kind, value),) = requirement.items()
    if kind not in VALID_SWIFT_REQUIREMENT_KINDS:
        raise ConfigError(
            f"swift package {name!r} has unknown requirement rule {kind!r}",
            key_path=key_path,
            hint=f"valid rules: {valid}.",
        )
    if kind == "range":
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(v, str) and v for v in value)
        ):
            raise ConfigError(
                f"swift package {name!r} 'range' must be two version strings "
                f"[lower, upper)",
                key_path=key_path,
            )
    elif not isinstance(value, str) or not value:
        raise ConfigError(
            f"swift package {name!r} requirement {kind!r} must be a non-empty string",
            key_path=key_path,
        )
    return dict(requirement)


def _validate_swift_path(name: str, path: object, key_path: str) -> str:
    if not isinstance(path, str) or not path:
        raise ConfigError(
            f"swift package {name!r} 'path' must be a non-empty string",
            key_path=key_path,
        )
    if _is_absolute_source(path):
        raise ConfigError(
            f"swift package {name!r} 'path' must be relative, not an absolute path",
            key_path=key_path,
        )
    parts = PurePosixPath(_posix_normpath(path)).parts
    if parts and parts[0] == "..":
        raise ConfigError(
            f"swift package {name!r} 'path' must not escape the project directory",
            key_path=key_path,
        )
    return path


def _require_bool(
    value: object, *, key_path: str, field: str, finder: _LineFinder
) -> bool:
    """Reject non-boolean TOML values. ``bool("false")`` is ``True``, so coercing
    with ``bool()`` would silently turn a stray string/int into the wrong flag.
    """
    if not isinstance(value, bool):
        raise ConfigError(
            f"[{key_path}] must be a boolean (true/false), not {type(value).__name__}",
            key_path=key_path,
            line=finder.line(field),
        )
    return value


def _parse_signing(ios: dict, finder: _LineFinder) -> SigningConfig:
    signing = ios.get("signing")
    if signing is None:
        return SigningConfig()
    if not isinstance(signing, dict):
        raise ConfigError(
            "[tool.kivy.ios.signing] must be a table",
            key_path="tool.kivy.ios.signing",
        )
    return SigningConfig(
        team_id=signing.get("team_id", ""),
        identity=signing.get("identity", "Apple Development"),
        provisioning_profile=signing.get("provisioning_profile", ""),
        auto_signing=_require_bool(
            signing.get("auto_signing", True),
            key_path="tool.kivy.ios.signing.auto_signing",
            field="auto_signing",
            finder=finder,
        ),
        upload_symbols=_require_bool(
            signing.get("upload_symbols", True),
            key_path="tool.kivy.ios.signing.upload_symbols",
            field="upload_symbols",
            finder=finder,
        ),
    )


def _parse_info_plist(ios: dict, finder: _LineFinder) -> dict[str, object]:
    info = ios.get("info_plist")
    if info is None:
        return {}
    if not isinstance(info, dict):
        raise ConfigError(
            "[tool.kivy.ios.info_plist] must be a table",
            key_path="tool.kivy.ios.info_plist",
        )
    conflicts = sorted(set(info) & MANAGED_INFO_PLIST_KEYS)
    if conflicts:
        raise ConfigError(
            f"[tool.kivy.ios.info_plist] sets kivyforge-managed key(s): "
            f"{', '.join(conflicts)}",
            key_path="tool.kivy.ios.info_plist",
            line=finder.line("info_plist"),
            hint="set these via their dedicated schema fields instead.",
        )
    return dict(info)


def _parse_build_settings(ios: dict, finder: _LineFinder) -> dict[str, str]:
    # Rule 8: reserved keys under xcode.build_settings are rejected.
    xcode = ios.get("xcode")
    if not isinstance(xcode, dict):
        return {}
    settings = xcode.get("build_settings")
    if settings is None:
        return {}
    if not isinstance(settings, dict):
        raise ConfigError(
            "[tool.kivy.ios.xcode.build_settings] must be a table",
            key_path="tool.kivy.ios.xcode.build_settings",
        )
    conflicts = sorted(set(settings) & RESERVED_BUILD_SETTINGS)
    if conflicts:
        raise ConfigError(
            f"[tool.kivy.ios.xcode.build_settings] sets toolchain-reserved key(s): "
            f"{', '.join(conflicts)}",
            key_path="tool.kivy.ios.xcode.build_settings",
            line=finder.line("build_settings"),
            hint="these are managed by the toolchain and cannot be overridden.",
        )
    # Xcode build settings are strings (spec 01); reject non-strings rather than
    # silently str()-coercing a TOML int/bool/list into a surprising value.
    result: dict[str, str] = {}
    for key, value in settings.items():
        if not isinstance(value, str):
            raise ConfigError(
                f"[tool.kivy.ios.xcode.build_settings].{key} must be a string, not "
                f"{type(value).__name__} (Xcode build settings are strings; quote "
                f'the value, e.g. {key} = "NO")',
                key_path=f"tool.kivy.ios.xcode.build_settings.{key}",
                line=finder.line(key),
            )
        result[key] = value
    return result


def _parse_privacy(ios: dict) -> str | None:
    privacy = ios.get("privacy_manifest")
    if privacy is None:
        return None
    if not isinstance(privacy, dict):
        raise ConfigError(
            "[tool.kivy.ios.privacy_manifest] must be a table",
            key_path="tool.kivy.ios.privacy_manifest",
        )
    return privacy.get("source")


def _parse_entitlements(ios: dict) -> dict[str, object]:
    ent = ios.get("entitlements")
    if ent is None:
        return {}
    if not isinstance(ent, dict):
        raise ConfigError(
            "[tool.kivy.ios.entitlements] must be a table",
            key_path="tool.kivy.ios.entitlements",
        )
    return dict(ent)


class _LineFinder:
    """Best-effort source-line lookup for a bare key name.

    tomllib does not expose per-key positions for semantically-valid TOML, so
    we scan the raw text for the first ``key =`` (or ``[table]``) occurrence.
    Returns None when not found; callers fall back to the dotted key path.
    """

    def __init__(self, text: str) -> None:
        self._lines = text.splitlines()

    def line(self, key: str) -> int | None:
        key_re = re.compile(rf"^\s*(\[*\s*){re.escape(key)}\b")
        for i, line in enumerate(self._lines, start=1):
            if key_re.search(line):
                return i
        return None

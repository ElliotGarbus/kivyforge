"""Toolchain-managed Xcode build settings (spec 06 §"Toolchain-managed build settings")."""

from __future__ import annotations

from pathlib import Path

from kivyforge.config.model import Config

from .entitlements import xcode_profile_specifier
from .staging import APP_METADATA_DIR, StagingLayout

#: The Build Python script up to package metadata (0.x to 3.0.0.dev1). Kept
#: verbatim: the generator finds the phase to replace by its exact text, so
#: without it a project generated before would end up with both phases.
_BUILD_PYTHON_SCRIPT_V1 = (
    "set -e\n"
    'UTILS="$PROJECT_DIR/Python.xcframework/build/build_utils.sh"\n'
    'if [ ! -f "$UTILS" ]; then UTILS="$PROJECT_DIR/Python.xcframework/build/utils.sh"; fi\n'
    'source "$UTILS"\n'
    "# Copy the platform-appropriate pip-deps slice into the app bundle so\n"
    "# that device and simulator builds never share compiled extension modules.\n"
    'if [ "$EFFECTIVE_PLATFORM_NAME" = "-iphonesimulator" ]; then\n'
    '    PIP_DEPS_SRC="$PROJECT_DIR/pip-deps-simulator"\n'
    '    COLLECT_HINT="kivyforge build --simulator"\n'
    "else\n"
    '    PIP_DEPS_SRC="$PROJECT_DIR/pip-deps-device"\n'
    '    COLLECT_HINT="kivyforge build --device"\n'
    "fi\n"
    "# Fail loudly if this platform's slice was never collected. Only one slice\n"
    "# is populated per `kivyforge build/run <target>`, but Xcode picks the slice\n"
    "# from its own destination -- switching the destination to an uncollected\n"
    "# target would otherwise ship an app with no dependencies (crash at launch).\n"
    "# The `.collected` marker is written by collect (kivyforge build/run); it,\n"
    "# not directory emptiness, is the signal -- an empty slice WITH the marker is\n"
    "# valid (an app with no third-party dependencies).\n"
    'if [ ! -f "${PIP_DEPS_SRC}.collected" ]; then\n'
    '    echo "error: ${PIP_DEPS_SRC} was never collected for this '
    "platform. Run '$COLLECT_HINT' (or 'kivyforge run') first, then rebuild.\"\n"
    "    exit 1\n"
    "fi\n"
    'mkdir -p "$CODESIGNING_FOLDER_PATH/pip-deps"\n'
    'rsync -a --delete "$PIP_DEPS_SRC/" "$CODESIGNING_FOLDER_PATH/pip-deps/"\n'
    "install_python Python.xcframework app pip-deps\n"
)

#: The app's own package metadata (docs/design/dev/package-metadata-proposal.md
#: 2.2). Copy Bundle Resources has just copied ``app/`` into the bundle -- in a
#: debug build, the folder ``<app>-ios/app`` links to, which is ``app_dir`` --
#: and code signing comes after this script (spike F6). So this is where every
#: build, debug or release, and every Xcode-only rebuild, replaces the
#: development egg-info that copy carries, and any stale ``.dist-info`` of the
#: app's own name, with the folder ``kivyforge build`` staged. With nothing
#: staged (entry points in ``dynamic``) the copy is left alone. It never runs
#: through a link: that would delete from the user's source tree.
APP_METADATA_SCRIPT = (
    "# The app's own package metadata, staged by `kivyforge build`, in place of\n"
    "# any development egg-info. Only ever in the bundle's copy of app/.\n"
    'APP_BUNDLE_DIR="$CODESIGNING_FOLDER_PATH/app"\n'
    f'APP_METADATA_SRC="$PROJECT_DIR/{APP_METADATA_DIR}"\n'
    'if [ -L "$APP_BUNDLE_DIR" ]; then\n'
    '    echo "error: $APP_BUNDLE_DIR is a symlink; refusing to edit through it."\n'
    "    exit 1\n"
    "fi\n"
    'if [ -d "$APP_METADATA_SRC" ]; then\n'
    '    find "$APP_BUNDLE_DIR" -mindepth 1 -maxdepth 1 -name "*.egg-info" '
    "-exec rm -rf {} +\n"
    '    for META in "$APP_METADATA_SRC"/*.dist-info; do\n'
    '        [ -d "$META" ] || continue\n'
    '        OWN="$(basename "$META")"\n'
    '        OWN="${OWN%%-*}"\n'
    "        # Any spelling of the app's name, normalized as Python reads it.\n"
    '        for DIST in "$APP_BUNDLE_DIR"/*.dist-info; do\n'
    '            [ -e "$DIST" ] || continue\n'
    '            NAME="$(basename "$DIST" .dist-info)"\n'
    "            NAME=\"$(printf '%s' \"${NAME%%-*}\" | tr '[:upper:]' '[:lower:]' "
    "| sed -E 's/[-_.]+/_/g')\"\n"
    '            if [ "$NAME" = "$OWN" ]; then rm -rf "$DIST"; fi\n'
    "        done\n"
    "    done\n"
    '    rsync -a "$APP_METADATA_SRC/" "$APP_BUNDLE_DIR/"\n'
    "fi\n"
)

BUILD_PYTHON_SCRIPT = _BUILD_PYTHON_SCRIPT_V1 + APP_METADATA_SCRIPT

#: Every earlier text of the phase, oldest first, for the generator to remove.
PREVIOUS_BUILD_PYTHON_SCRIPTS = (_BUILD_PYTHON_SCRIPT_V1,)

#: Where the Build Python script writes inside the app bundle, declared as the
#: phase's output paths. Xcode re-signs the app only when an input it tracks
#: has changed, and a script's declared outputs inside the product are the
#: only way a script's writes become one. Undeclared, an Xcode-only rebuild
#: (Cmd-R, or re-running kivyforge's ``xcodebuild`` command) left the app
#: sealed over the bundle as it was before the script ran: on a device every
#: ``Frameworks/<ext>.framework`` binary, which ``install_python`` re-signs
#: with a fresh signing time on each run, then failed ``codesign --verify``.
#: ``app/`` is not listed: Copy Bundle Resources produces it, and two
#: producers of one path is an Xcode error. The script's edits there (the
#: app's metadata) are still signed, because every run also rewrites
#: ``Frameworks/``.
BUILD_PYTHON_OUTPUTS = tuple(
    f"$(TARGET_BUILD_DIR)/$(WRAPPER_NAME)/{folder}"
    for folder in ("python", "pip-deps", "Frameworks")
)


def managed_settings(
    config: Config, *, configuration: str, layout: StagingLayout | None = None
) -> dict[str, str]:
    """Return the managed build settings for a given configuration (Debug/Release).

    ``ENABLE_TESTABILITY`` and ``DEBUG_INFORMATION_FORMAT`` are per-configuration
    (spec 06); the rest are constant across configs.
    """
    ios = config.ios
    assert ios is not None
    is_release = configuration.lower() == "release"

    settings: dict[str, str] = {
        "PRODUCT_BUNDLE_IDENTIFIER": ios.bundle_id,
        "PRODUCT_NAME": "$(TARGET_NAME)",
        "IPHONEOS_DEPLOYMENT_TARGET": ios.deployment_target,
        "TARGETED_DEVICE_FAMILY": "1,2",
        "SDKROOT": "iphoneos",
        "INFOPLIST_FILE": f"{config.app_slug}-Info.plist",
        "ENABLE_USER_SCRIPT_SANDBOXING": "NO",
        "ENABLE_TESTABILITY": "NO" if is_release else "YES",
        "DEBUG_INFORMATION_FORMAT": "dwarf-with-dsym" if is_release else "dwarf",
        "FRAMEWORK_SEARCH_PATHS": "$(PROJECT_DIR)",
        "HEADER_SEARCH_PATHS": _header_search_paths(layout),
        # Embedded dynamic frameworks (Python.xcframework, the SDL3/ANGLE family,
        # wheel-embedded and SPM frameworks) are loaded via @rpath at runtime.
        # Manage the runpath explicitly rather than relying on pbxproj embedding
        # side effects, so any embed path resolves under .app/Frameworks/.
        "LD_RUNPATH_SEARCH_PATHS": "$(inherited) @executable_path/Frameworks",
        # Linked for every project. Kivy apps need it through SDL3.framework.
        # The no-SDL smoke-test path does not call UIApplicationMain.
        "OTHER_LDFLAGS": "-framework UIKit",
        "GCC_WARN_QUOTED_INCLUDE_IN_FRAMEWORK_HEADER": "NO",
        "ALWAYS_SEARCH_USER_PATHS": "NO",
        # The SDL3 family and Python frameworks ship ad-hoc code-signed; Xcode's
        # built-in default COPY_PHASE_STRIP=YES tries to strip them on embed and
        # warns "not stripping binary because it is signed". Disable it (Xcode's
        # own project templates also default this to NO).
        "COPY_PHASE_STRIP": "NO",
    }

    if _sdl3_staged(layout):
        # Fail the build at compile time if SDL3 headers then turn out to be
        # missing (a broken vendoring step, a manually edited
        # HEADER_SEARCH_PATHS), rather than silently compiling the no-SDL
        # smoke-test path in kivyforge_bootstrap.m -- an app that launches
        # but can never open a window. Credit: PR #1 (kengoon).
        settings["GCC_PREPROCESSOR_DEFINITIONS"] = (
            "$(inherited) KIVYFORGE_REQUIRES_SDL=1"
        )

    if ios.icons.source:
        # Designate the AppIcon set in Assets.xcassets as the app icon. Without
        # this the catalog still compiles, but Xcode assigns no icon — the
        # generated AppIcon.appiconset is silently ignored.
        settings["ASSETCATALOG_COMPILER_APPICON_NAME"] = "AppIcon"

    if ios.entitlements:
        settings["CODE_SIGN_ENTITLEMENTS"] = f"{config.app_slug}.entitlements"

    return settings


def _sdl3_staged(layout: StagingLayout | None) -> bool:
    """Whether this build stages ``SDL3.xcframework`` — i.e. it depends on Kivy.

    The one signal used everywhere this distinction matters: SDL3 header
    search paths, and (``KIVYFORGE_REQUIRES_SDL``) the compile-time guard
    against a Kivy app silently building without SDL3 headers.
    """
    return layout is not None and (layout.frameworks / "SDL3.xcframework").is_dir()


def _header_search_paths(layout: StagingLayout | None) -> str:
    paths = ["$(BUILT_PRODUCTS_DIR)/Python.framework/Headers"]
    if _sdl3_staged(layout):
        for slice_name in ("ios-arm64_x86_64-simulator", "ios-arm64"):
            paths.append(
                f"$(PROJECT_DIR)/Frameworks/SDL3.xcframework/"
                f"{slice_name}/SDL3.framework/Headers"
            )
    return " ".join(f'"{path}"' for path in paths)


SIGNING_SETTING_KEYS = frozenset(
    {
        "CODE_SIGN_STYLE",
        "CODE_SIGN_IDENTITY",
        "DEVELOPMENT_TEAM",
        "PROVISIONING_PROFILE_SPECIFIER",
    }
)
"""Every key :func:`signing_settings` can emit."""


def signing_settings(
    config: Config, *, team_id: str | None = None, project_root: Path | None = None
) -> dict[str, str]:
    """Map [tool.kivy.ios.signing] to CODE_SIGN_* build settings (spec 06).

    *team_id*, if given, overrides ``[tool.kivy.ios.signing].team_id`` — pass
    the value already resolved by ``xcode/commands.py::resolve_team_id``
    (``--team-id`` flag → ``KIVYFORGE_TEAM_ID`` env → pyproject), so those two
    documented overrides actually reach the generated ``.xcodeproj`` instead of
    only satisfying the upfront preflight check. Before this, ``build
    --device``/``run --device``/``package`` always wrote ``DEVELOPMENT_TEAM``
    from pyproject alone — silently ignoring both overrides — because
    ``preflight_signing`` (which resolves all three sources) validates that a
    team_id exists somewhere but the resolved value never reached here.

    ``provisioning_profile`` is a name or UUID, which Xcode resolves against
    installed profiles. A ``.mobileprovision`` path is accepted too and replaced
    by the UUID inside the file, resolved against *project_root*.
    """
    ios = config.ios
    assert ios is not None
    signing = ios.signing
    settings: dict[str, str] = {
        "CODE_SIGN_STYLE": "Automatic" if signing.auto_signing else "Manual",
    }
    effective_team_id = team_id if team_id is not None else signing.team_id
    if effective_team_id:
        settings["DEVELOPMENT_TEAM"] = effective_team_id
    if signing.identity:
        settings["CODE_SIGN_IDENTITY"] = signing.identity
    if signing.provisioning_profile:
        settings["PROVISIONING_PROFILE_SPECIFIER"] = xcode_profile_specifier(
            config, project_root
        )
    return settings


def user_build_settings(config: Config) -> dict[str, str]:
    """Free-form [tool.kivy.ios.xcode.build_settings] (reserved keys already rejected)."""
    if not config.ios:
        return {}
    return dict(config.ios.build_settings)

"""Pure helpers for ``kivyforge init`` (spec 05).

Kept side-effect-free (no filesystem, no venv probing) so they can be unit
tested directly. ``init.py`` orchestrates these with the real environment.

Init uses *text surgery* — it only ever adds/replaces
``[tool.kivy*]`` sections and leaves ``[project]`` and every other namespace
byte-for-byte intact. We deliberately do not round-trip the whole file through
a TOML writer (which would drop comments and reorder keys).
"""

from __future__ import annotations

import re

from packaging.requirements import InvalidRequirement, Requirement

from ..config.model import (
    AndroidSigningConfig,
    MacosSigningConfig,
    SigningConfig,
    WindowsSigningConfig,
)

# Default Python.xcframework version init seeds (spec 01).
DEFAULT_PYTHON_VERSION = "3.15.0b2"
DEFAULT_DEPLOYMENT_TARGET = "13.0"
# Default python-build-standalone version seeded for macOS/Linux (desktop
# targets pin a released runtime, not a beta xcframework).
DEFAULT_DESKTOP_PYTHON_VERSION = "3.13.14"
# Default python.org Android embeddable-package version init seeds (android/01;
# the load-model prototype validated 3.14.6 — android-loadmodel-findings.md).
DEFAULT_ANDROID_PYTHON_VERSION = "3.14.6"

# Exclude block emitted when kivy is a direct dependency.  Each entry is
# documented with the Kivy feature that requires it so users know which lines
# are safe to remove for their specific app.
_KIVY_EXCLUDE_LINES = [
    "# Kivy's wheel declares deps that are not needed at runtime for most apps.",
    "# Remove an entry only if your app actually uses that feature.",
    "exclude = [",
    "    # kivy-garden: the extension registry / download CLI.  Rarely needed at",
    "    # runtime (app stores generally prohibit dynamic package installation).",
    "    # Individual garden widgets (e.g. kivy-garden.mapview) are separate",
    "    # packages — add them to [project].dependencies instead.",
    '    "kivy-garden",',
    "    # requests and its transitive deps (below) are used by",
    "    # kivy.network.urlrequest.UrlRequest *and* by kivy-garden.",
    "    # Remove these lines only if your app uses UrlRequest for HTTP calls.",
    '    "requests",',
    '    "certifi",',
    '    "charset-normalizer",',
    '    "idna",',
    '    "urllib3",',
    "    # docutils: required by the RSTDocument widget (kivy.uix.rst).",
    "    # Remove this line if your app uses RSTDocument.",
    '    "docutils",',
    "    # pygments: required by the CodeInput widget (kivy.uix.codeinput).",
    "    # Remove this line if your app uses CodeInput.",
    '    "pygments",',
    "    # NOTE: filetype is imported unconditionally by kivy/core/image/__init__.py",
    "    # and cannot be excluded regardless of which widgets you use.",
    "]",
]

_TABLE_HEADER = re.compile(r"^\s*\[\[?\s*(?P<key>[^\]]+?)\s*\]\]?\s*(#.*)?$")


def normalize_package_name(raw: str) -> str:
    """Normalize a directory name into a valid Python package name.

    Lowercase; hyphens/spaces/dots → underscores; drop other invalid chars;
    ensure it does not start with a digit.
    """
    name = raw.strip().lower()
    name = re.sub(r"[-\s.]+", "_", name)
    name = re.sub(r"[^a-z0-9_]", "", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        name = "app"
    if name[0].isdigit():
        name = f"app_{name}"
    return name


def _canon(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def bundle_id_segment(app_slug: str) -> str:
    """Convert a Python ``app_slug`` into a valid bundle-identifier segment.

    Bundle identifiers are UTIs: only alphanumeric, hyphen, and period are
    allowed.  ``app_slug`` is a Python package name (underscores are valid
    there) so underscores are mapped to hyphens here.
    """
    seg = app_slug.replace("_", "-")
    seg = re.sub(r"[^A-Za-z0-9-]", "", seg)
    return seg.strip("-") or "app"


def has_kivy_dep(dependencies: list[str]) -> bool:
    """Return True if any entry in *dependencies* is the ``kivy`` package."""
    for dep in dependencies:
        try:
            name = Requirement(dep).name
        except InvalidRequirement:
            name = dep.split(";", 1)[0].split("[", 1)[0].strip()
        if _canon(name) == "kivy":
            return True
    return False


def render_kivy_tables(
    app_slug: str,
    signing: SigningConfig | None = None,
    *,
    python_version: str | None = None,
    has_kivy: bool = False,
    simulator_archs: list[str] | tuple[str, ...] | None = None,
    icon_source: str | None = None,
    splash_source: str | None = None,
    splash_background: str | None = None,
    include_shared: bool = True,
) -> str:
    """Render the ``[tool.kivy]`` + ``[tool.kivy.ios]`` block.

    When ``signing`` is provided (the ``--force`` preserve path) its concrete
    values are emitted; otherwise a commented template invites the user to fill
    in ``team_id``. ``python_version`` overrides the default xcframework pin.
    When ``has_kivy`` is True a documented ``exclude`` block is included so
    users know which transitive Kivy deps are safe to drop for their app.

    ``simulator_archs`` / ``icon_source`` / ``splash_source`` /
    ``splash_background`` are the user's existing values on the ``--force``
    preserve path: when set, they are emitted as active TOML; when ``None`` (the
    initial-add path, or a value the user never set) a commented TODO stub is
    emitted instead so the build-time default stays in effect.

    ``include_shared`` controls whether the cross-platform ``[tool.kivy]``
    table is emitted. Set it to ``False`` when the project already declares
    ``[tool.kivy]`` (e.g. adding iOS alongside an existing macOS/Linux overlay)
    so init never emits a second, TOML-invalidating ``[tool.kivy]`` table.
    """
    display = app_slug.replace("_", " ").title()
    if simulator_archs is not None:
        archs_toml = ", ".join(f'"{a}"' for a in simulator_archs)
        sim_line = f"simulator_archs = [{archs_toml}]"
    else:
        sim_line = (
            '# simulator_archs = ["arm64"]  '
            '# drop "x86_64" once you no longer run the simulator on Intel Macs '
            "(default pins both)"
        )
    lines: list[str] = []
    if include_shared:
        lines += [
            "[tool.kivy]",
            f'display_name = "{display}"',
            'app_dir = "src"',
            'entry_point = "main"',
            'orientation = ["portrait"]',
            "",
        ]
    lines += [
        "[tool.kivy.ios]",
        "schema_version = 1",
        f'bundle_id = "org.example.{bundle_id_segment(app_slug)}"  '
        "# TODO: change to your reverse-DNS bundle identifier",
        "build = 1",
        f'deployment_target = "{DEFAULT_DEPLOYMENT_TARGET}"',
        sim_line,
    ]
    if has_kivy:
        lines += [""] + _KIVY_EXCLUDE_LINES
    if icon_source is not None:
        icon_lines = [f'source = "{icon_source}"']
    else:
        icon_lines = [
            '# source = "assets/icon.png"  '
            "# TODO: 1024x1024 PNG app icon — required for App Store submission"
        ]
    if splash_source is not None:
        splash_lines = [f'source = "{splash_source}"']
    else:
        splash_lines = ['# source = "assets/splash.png"  # TODO: optional launch image']
    if splash_background is not None:
        splash_lines.append(f'background = "{splash_background}"')
    else:
        splash_lines.append(
            '# background = "#000000"        '
            "# TODO: optional launch-screen background color"
        )
    lines += [
        "",
        "[tool.kivy.ios.python]",
        f'version = "{python_version or DEFAULT_PYTHON_VERSION}"',
        "",
        "[tool.kivy.ios.icons]",
        *icon_lines,
        "",
        "[tool.kivy.ios.splash]",
        *splash_lines,
        "",
        "[tool.kivy.ios.signing]",
    ]
    if signing is not None:
        lines += [
            f'team_id = "{signing.team_id}"',
            f'identity = "{signing.identity}"',
            f'provisioning_profile = "{signing.provisioning_profile}"',
            f"auto_signing = {str(signing.auto_signing).lower()}",
            f"upload_symbols = {str(signing.upload_symbols).lower()}",
        ]
    else:
        lines += [
            '# team_id = "ABCDE12345"  '
            "# TODO: set your Apple Developer Team ID for device/release builds",
            "auto_signing = true",
        ]
    lines += _SWIFT_PACKAGES_STUB
    return "\n".join(lines) + "\n"


# Commented native-dependency stub. Left inert so a vanilla app needs no Swift
# toolchain; uncomment to pull in an SPM package (resolved + embedded by Xcode).
_SWIFT_PACKAGES_STUB = [
    "",
    "# Optional: native Swift Package Manager dependencies (spec 07). Xcode resolves,",
    "# builds, and embeds these; `kivyforge lock` pins each to a commit.",
    "# [tool.kivy.ios.native.swift_packages]",
    '# Sentry = { url = "https://github.com/getsentry/sentry-cocoa", '
    'requirement = { from = "8.49.0" }, products = ["Sentry"] }',
]


def has_kivyforge_table(text: str) -> bool:
    """True if the text already declares a [tool.kivy.ios] table."""
    return has_platform_overlay(text, "ios")


def has_shared_table(text: str) -> bool:
    """True if the text already declares the bare, cross-platform [tool.kivy] table."""
    return "tool.kivy" in _section_keys(text)


def has_platform_overlay(text: str, platform: str) -> bool:
    """True if the text already declares [tool.kivy.<platform>] (or a sub-table)."""
    prefix = f"tool.kivy.{platform}"
    keys = _section_keys(text)
    return prefix in keys or any(k.startswith(f"{prefix}.") for k in keys)


def _section_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for line in text.splitlines():
        m = _TABLE_HEADER.match(line)
        if m:
            keys.add(m.group("key").strip())
    return keys


def strip_kivy_tables(text: str) -> str:
    """Remove every ``[tool.kivy]`` / ``[tool.kivy.*]`` section from the text.

    Used by ``--force`` before re-appending freshly rendered tables. Non-kivy
    sections (including ``[project]`` and other tool namespaces) are preserved
    verbatim.
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    dropping = False
    for line in lines:
        m = _TABLE_HEADER.match(line.rstrip("\n"))
        if m:
            key = m.group("key").strip()
            dropping = key == "tool.kivy" or key.startswith("tool.kivy.")
            if dropping:
                continue
        if dropping:
            continue
        out.append(line)
    result = "".join(out).rstrip("\n")
    return result + "\n" if result else ""


def strip_platform_tables(text: str, platform: str) -> str:
    """Remove only ``[tool.kivy.<platform>]`` and its sub-tables.

    Unlike :func:`strip_kivy_tables` (which drops the shared ``[tool.kivy]``
    table too, safe only when there is exactly one platform), this preserves
    ``[tool.kivy]`` and every *other* platform's overlay — required so
    regenerating one platform's overlay (``init --force -p macos``) in a
    multi-platform ``pyproject.toml`` never touches iOS/Linux's tables.
    """
    prefix = f"tool.kivy.{platform}"
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    dropping = False
    for line in lines:
        m = _TABLE_HEADER.match(line.rstrip("\n"))
        if m:
            key = m.group("key").strip()
            dropping = key == prefix or key.startswith(prefix + ".")
            if dropping:
                continue
        if dropping:
            continue
        out.append(line)
    result = "".join(out).rstrip("\n")
    return result + "\n" if result else ""


def append_kivy_tables(
    text: str,
    app_slug: str,
    signing: SigningConfig | None = None,
    *,
    python_version: str | None = None,
    has_kivy: bool = False,
    simulator_archs: list[str] | tuple[str, ...] | None = None,
    icon_source: str | None = None,
    splash_source: str | None = None,
    splash_background: str | None = None,
    include_shared: bool = True,
) -> str:
    """Append freshly rendered kivy tables to existing pyproject text."""
    block = render_kivy_tables(
        app_slug,
        signing,
        python_version=python_version,
        has_kivy=has_kivy,
        simulator_archs=simulator_archs,
        icon_source=icon_source,
        splash_source=splash_source,
        splash_background=splash_background,
        include_shared=include_shared,
    )
    return append_block(text, block)


def append_block(text: str, block: str) -> str:
    """Append a rendered ``[tool.kivy*]`` block to existing pyproject text."""
    base = text.rstrip("\n")
    if not base:
        return block
    return f"{base}\n\n{block}"


# --------------------------------------------------------------------------- #
# macOS / Linux overlays — same text-surgery approach as iOS above.
# --------------------------------------------------------------------------- #


def render_macos_tables(
    app_slug: str,
    signing: MacosSigningConfig | None = None,
    *,
    python_version: str | None = None,
    has_kivy: bool = False,
    archs: list[str] | tuple[str, ...] | None = None,
    icon_source: str | None = None,
    include_shared: bool = True,
) -> str:
    """Render the ``[tool.kivy]`` (optional) + ``[tool.kivy.macos]`` block."""
    display = app_slug.replace("_", " ").title()
    if archs is not None:
        archs_toml = ", ".join(f'"{a}"' for a in archs)
        archs_line = f"archs = [{archs_toml}]"
    else:
        archs_line = 'archs = ["arm64", "x86_64"]  # two entries = universal2; one = a thin build'
    lines: list[str] = []
    if include_shared:
        lines += [
            "[tool.kivy]",
            f'display_name = "{display}"',
            'app_dir = "src"',
            'entry_point = "main"',
            'orientation = ["portrait"]',
            "",
        ]
    lines += [
        "[tool.kivy.macos]",
        "schema_version = 1",
        f'bundle_id = "org.example.{bundle_id_segment(app_slug)}"  '
        "# TODO: change to your reverse-DNS bundle identifier",
        "build = 1",
        archs_line,
    ]
    if has_kivy:
        lines += [""] + _KIVY_EXCLUDE_LINES
    if icon_source is not None:
        icon_lines = [f'source = "{icon_source}"']
    else:
        icon_lines = [
            '# source = "assets/icon.png"  '
            "# TODO: 1024x1024 PNG app icon (rendered to .icns)"
        ]
    lines += [
        "",
        "[tool.kivy.macos.python]",
        f'version = "{python_version or DEFAULT_DESKTOP_PYTHON_VERSION}"',
        "",
        "[tool.kivy.macos.icons]",
        *icon_lines,
        "",
        "[tool.kivy.macos.signing]",
    ]
    if signing is not None and signing.identity:
        lines.append(f'identity = "{signing.identity}"')
        if signing.team_id:
            lines.append(f'team_id = "{signing.team_id}"')
        if signing.notary_profile:
            lines.append(f'notary_profile = "{signing.notary_profile}"')
    else:
        lines += [
            '# identity = "Developer ID Application: Your Name (TEAMID1234)"  '
            "# TODO: set for Gatekeeper-trusted distribution (ad-hoc signing is "
            "the default without it)",
            '# notary_profile = "kivyforge-notary"  '
            "# TODO: `xcrun notarytool store-credentials` profile name",
        ]
    lines += _MACOS_NATIVE_BINARIES_STUB
    return "\n".join(lines) + "\n"


# Commented native-binary stub. Left inert so a vanilla app needs no extra
# artifacts; uncomment to stage a non-wheel dylib/helper (SHA-256-pinned by
# `kivyforge lock`, staged into Contents/Resources/bin, and covered by the
# signing sweep).
_MACOS_NATIVE_BINARIES_STUB = [
    "",
    "# Optional: non-wheel native binaries (macos-spec). Each is pinned by",
    "# `kivyforge lock` and staged into the app's bin directory (on PATH at",
    "# runtime; load dylibs by absolute path via Path(sys.prefix).parent / 'bin').",
    "# [tool.kivy.macos.native.binaries]",
    '# ffmpeg = { version = "7.1", source = "https://example.com/ffmpeg-macos-universal2.zip" }',
    '# libgreet = { version = "0.1.0", source = "binaries/macos/libgreet.dylib" }',
]


def render_linux_tables(
    app_slug: str,
    *,
    python_version: str | None = None,
    has_kivy: bool = False,
    archs: list[str] | tuple[str, ...] | None = None,
    icon_source: str | None = None,
    categories: list[str] | tuple[str, ...] | None = None,
    include_shared: bool = True,
) -> str:
    """Render the ``[tool.kivy]`` (optional) + ``[tool.kivy.linux]`` block."""
    display = app_slug.replace("_", " ").title()
    if archs is not None:
        archs_toml = ", ".join(f'"{a}"' for a in archs)
        archs_line = f"archs = [{archs_toml}]"
    else:
        archs_line = 'archs = ["x86_64"]'
    lines: list[str] = []
    if include_shared:
        lines += [
            "[tool.kivy]",
            f'display_name = "{display}"',
            'app_dir = "src"',
            'entry_point = "main"',
            'orientation = ["portrait"]',
            "",
        ]
    lines += [
        "[tool.kivy.linux]",
        "schema_version = 1",
        f'app_id = "org.example.{bundle_id_segment(app_slug)}"  '
        "# TODO: change to your reverse-DNS app id",
        archs_line,
    ]
    if has_kivy:
        lines += [""] + _KIVY_EXCLUDE_LINES
    if icon_source is not None:
        icon_lines = [f'source = "{icon_source}"']
    else:
        icon_lines = [
            '# source = "assets/icon.png"  '
            "# TODO: 1024x1024 PNG app icon (resized into the hicolor set)"
        ]
    if categories is not None:
        cats_toml = ", ".join(f'"{c}"' for c in categories)
        cats_line = f"categories = [{cats_toml}]"
    else:
        cats_line = 'categories = ["Utility"]'
    lines += [
        "",
        "[tool.kivy.linux.python]",
        f'version = "{python_version or DEFAULT_DESKTOP_PYTHON_VERSION}"',
        "",
        "[tool.kivy.linux.icons]",
        *icon_lines,
        "",
        "[tool.kivy.linux.desktop]",
        cats_line,
    ]
    lines += _LINUX_NATIVE_BINARIES_STUB
    return "\n".join(lines) + "\n"


# Commented native-binary stub. Left inert so a vanilla app needs no extra
# artifacts; uncomment to stage a non-wheel .so/helper (SHA-256-pinned by
# `kivyforge lock`, staged into usr/bin). At runtime helpers resolve by name on
# PATH; libraries load by soname (ctypes.CDLL("libgreet.so")) via the appended
# LD_LIBRARY_PATH. Both .zip and .tar.gz/.tgz archive sources are extracted.
_LINUX_NATIVE_BINARIES_STUB = [
    "",
    "# Optional: non-wheel native binaries (linux-spec). Each is pinned by",
    "# `kivyforge lock` and staged into the AppDir's usr/bin (helpers on PATH by",
    "# name; libraries load by soname, e.g. ctypes.CDLL('libgreet.so')).",
    "# [tool.kivy.linux.native.binaries]",
    '# ffmpeg = { version = "7.1", source = "https://example.com/ffmpeg-linux-x86_64.tar.gz" }',
    '# libgreet = { version = "0.1.0", source = "binaries/linux/libgreet.so" }',
]


def _windows_app_id(app_slug: str) -> str:
    """A Pascal-cased, period-delimited AppUserModelID stub (the good-style form)."""
    pascal = app_slug.replace("_", " ").title().replace(" ", "") or "MyApp"
    return f"Example.{pascal}"


def render_windows_tables(
    app_slug: str,
    signing: WindowsSigningConfig | None = None,
    *,
    python_version: str | None = None,
    has_kivy: bool = False,
    archs: list[str] | tuple[str, ...] | None = None,
    icon_source: str | None = None,
    include_shared: bool = True,
) -> str:
    """Render the ``[tool.kivy]`` (optional) + ``[tool.kivy.windows]`` block."""
    display = app_slug.replace("_", " ").title()
    if archs is not None:
        archs_toml = ", ".join(f'"{a}"' for a in archs)
        archs_line = f"archs = [{archs_toml}]"
    else:
        archs_line = 'archs = ["amd64"]'
    lines: list[str] = []
    if include_shared:
        lines += [
            "[tool.kivy]",
            f'display_name = "{display}"',
            'app_dir = "src"',
            'entry_point = "main"',
            'orientation = ["portrait"]',
            "",
        ]
    lines += [
        "[tool.kivy.windows]",
        "schema_version = 1",
        f'app_id = "{_windows_app_id(app_slug)}"  '
        "# TODO: your AppUserModelID (no spaces, <=128 chars)",
        archs_line,
    ]
    if has_kivy:
        lines += [""] + _KIVY_EXCLUDE_LINES
    if icon_source is not None:
        icon_lines = [f'source = "{icon_source}"']
    else:
        icon_lines = [
            '# source = "assets/icon.png"  '
            "# TODO: 1024x1024 PNG app icon (rendered to a multi-size .ico)"
        ]
    lines += [
        "",
        "[tool.kivy.windows.python]",
        f'version = "{python_version or DEFAULT_DESKTOP_PYTHON_VERSION}"',
        "",
        "[tool.kivy.windows.icons]",
        *icon_lines,
        "",
        "[tool.kivy.windows.signing]",
    ]
    if signing is not None and signing.thumbprint:
        lines.append(f'thumbprint = "{signing.thumbprint}"')
        if signing.timestamp_url:
            lines.append(f'timestamp_url = "{signing.timestamp_url}"')
        if signing.store_scope:
            lines.append(f'store_scope = "{signing.store_scope}"')
    else:
        lines += [
            '# thumbprint = "AB12CD34...EF"  '
            "# TODO: code-signing cert thumbprint (artifact is unsigned without it)",
            '# timestamp_url = "http://timestamp.digicert.com"',
            '# store_scope = "current_user"  # or "machine" (adds signtool /sm)',
        ]
    lines += _WINDOWS_NATIVE_BINARIES_STUB
    return "\n".join(lines) + "\n"


def render_android_tables(
    app_slug: str,
    signing: AndroidSigningConfig | None = None,
    *,
    python_version: str | None = None,
    has_kivy: bool = False,
    package: str | None = None,
    abis: list[str] | tuple[str, ...] | None = None,
    sdl: int | None = None,
    icon_source: str | None = None,
    splash_source: str | None = None,
    splash_background: str | None = None,
    include_shared: bool = True,
) -> str:
    """Render the ``[tool.kivy]`` (optional) + ``[tool.kivy.android]`` block.

    Seeds per android/06 §init: ``package = "org.example.<slug>"`` with a
    change-me comment, ``min_sdk = 24``, the latest known target/compile SDK,
    both 64-bit ABIs, ``INTERNET`` as an ordinary editable permission, and
    commented TODO stubs for icons/splash/signing/find_links. On ``--force``
    the caller passes the preserved values (package, abis, sdl, python,
    icon/splash sources, signing).
    """
    display = app_slug.replace("_", " ").title()
    if abis is not None:
        abis_toml = ", ".join(f'"{a}"' for a in abis)
        abis_line = f"abis = [{abis_toml}]"
    else:
        abis_line = 'abis = ["arm64_v8a", "x86_64"]'
    package_line = (
        f'package = "{package}"'
        if package
        else f'package = "org.example.{app_slug}"  '
        "# TODO: your applicationId (reverse-DNS)"
    )
    lines: list[str] = []
    if include_shared:
        lines += [
            "[tool.kivy]",
            f'display_name = "{display}"',
            'app_dir = "src"',
            'entry_point = "main"',
            'orientation = ["portrait"]',
            "",
        ]
    lines += [
        "[tool.kivy.android]",
        "schema_version = 1",
        package_line,
        'version_code = 1  # or "auto" to derive from [project].version (android/01)',
        "min_sdk = 24",
        "target_sdk = 35",
        f"sdl = {sdl if sdl is not None else 2}  "
        "# 2 = Kivy 2.3.1 (SDL2); 3 = Kivy 3.0 (SDL3)",
        abis_line,
        '# find_links = ["wheels"]  '
        "# TODO: vendored android wheels (kivy/pyjnius) until they are on PyPI",
    ]
    if has_kivy:
        lines += [""] + _KIVY_EXCLUDE_LINES
    lines += [
        "",
        "[tool.kivy.android.python]",
        f'version = "{python_version or DEFAULT_ANDROID_PYTHON_VERSION}"',
        "",
        "[tool.kivy.android.permissions]",
        'uses = ["INTERNET"]  # ordinary editable entry; delete it if unwanted',
        "",
        "[tool.kivy.android.icons]",
    ]
    if icon_source is not None:
        lines.append(f'source = "{icon_source}"')
    else:
        lines.append(
            '# source = "assets/icon.png"  '
            "# TODO: 1024x1024 PNG (adaptive-icon foreground)"
        )
    lines += ["", "[tool.kivy.android.splash]"]
    if splash_source is not None:
        lines.append(f'source = "{splash_source}"')
        if splash_background is not None:
            lines.append(f'background = "{splash_background}"')
    else:
        lines += [
            '# source = "assets/splash.png"  '
            "# TODO: centered splash icon (PNG or AnimatedVectorDrawable XML)",
            '# background = "#000000"',
        ]
    lines += ["", "[tool.kivy.android.signing]"]
    if signing is not None and signing.keystore:
        lines.append(f'keystore = "{signing.keystore}"')
        lines.append(f'key_alias = "{signing.key_alias}"')
        if signing.store_password_env != "KIVYFORGE_KEYSTORE_PASSWORD":
            lines.append(f'store_password_env = "{signing.store_password_env}"')
        if signing.key_password_env != "KIVYFORGE_KEY_PASSWORD":
            lines.append(f'key_password_env = "{signing.key_password_env}"')
    else:
        lines += [
            '# keystore = "release.keystore"  '
            "# TODO: release keystore (debug builds need none)",
            '# key_alias = "upload"',
            "# passwords come from KIVYFORGE_KEYSTORE_PASSWORD / "
            "KIVYFORGE_KEY_PASSWORD",
        ]
    return "\n".join(lines) + "\n"


# Commented native-binary stub. Left inert so a vanilla app needs no extra
# artifacts; uncomment to stage a non-wheel .dll/helper .exe (SHA-256-pinned by
# `kivyforge lock`, staged into the bundle's bin\ directory). At runtime helpers
# resolve by name on PATH; DLLs load by name (ctypes.WinDLL("sdk.dll")) via the
# add_dll_directory-registered bin\. Both .zip and .tar.gz/.tgz sources extract.
_WINDOWS_NATIVE_BINARIES_STUB = [
    "",
    "# Optional: non-wheel native binaries (windows-spec). Each is pinned by",
    "# `kivyforge lock` and staged into the bundle's bin\\ (helpers on PATH by",
    "# name; DLLs load by name, e.g. ctypes.WinDLL('sdk.dll')).",
    "# [tool.kivy.windows.native.binaries]",
    '# ffmpeg = { version = "7.1", source = "https://example.com/ffmpeg-windows-amd64.zip" }',
    '# sdk = { version = "0.1.0", source = "binaries/windows/sdk.dll" }',
]

"""Typed model of the kivyforge ``pyproject.toml`` surface (spec 01).

These dataclasses are the validated, in-memory representation produced by
``kivyforge.config.loader.load_config``. They intentionally only model the
fields kivyforge consumes; unknown keys elsewhere in ``pyproject.toml`` are
ignored (PEP 518 tool-namespace convention).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The iOS schema major version this build understands (spec 01).
SUPPORTED_IOS_SCHEMA_VERSION = 1

# The macOS overlay schema major version this build understands (macos-spec).
SUPPORTED_MACOS_SCHEMA_VERSION = 1

# The Linux overlay schema major version this build understands (linux-spec).
SUPPORTED_LINUX_SCHEMA_VERSION = 1

# macOS build architectures. Two entries => a universal2 build; one => a thin
# build. Default is universal2 (arm64 + x86_64) unless the project narrows it.
VALID_MACOS_ARCHS = frozenset({"arm64", "x86_64"})
DEFAULT_MACOS_ARCHS = ("arm64", "x86_64")

# Linux build architectures. Only x86_64 is allowed this phase; the field stays
# list-shaped so aarch64 is purely additive later (linux-spec). Unlike macOS
# there is no fat binary — each arch would be a separate AppImage.
VALID_LINUX_ARCHS = frozenset({"x86_64"})
DEFAULT_LINUX_ARCHS = ("x86_64",)

# The Windows overlay schema major version this build understands (windows-spec).
SUPPORTED_WINDOWS_SCHEMA_VERSION = 1

# Windows build architectures. Only amd64 (x86-64) this phase; the field stays
# list-shaped so win-arm64 is purely additive later (windows-spec). Like Linux
# and unlike macOS there is no fat binary — each arch is a separate onedir.
# arm64: add "arm64" to VALID_WINDOWS_ARCHS to accept it; DEFAULT stays amd64
# (arm64 is opt-in via [tool.kivy.windows].archs). See arm64-windows.md §1.
VALID_WINDOWS_ARCHS = frozenset({"amd64"})
DEFAULT_WINDOWS_ARCHS = ("amd64",)

# Microsoft's real AppUserModelID hard constraints (windows-spec): no spaces and
# at most this many characters. Pascal-case / period-delimited *style* is only a
# doctor warning, so the loader enforces just these two.
WINDOWS_APP_ID_MAX_LENGTH = 128

# Default Authenticode RFC-3161 timestamp server (signing-windows).
DEFAULT_WINDOWS_TIMESTAMP_URL = "http://timestamp.digicert.com"

# Certificate-store scopes for signtool / the doctor certificate check
# (signing-windows). ``current_user`` -> ``Cert:\CurrentUser\My``; ``machine``
# -> ``Cert:\LocalMachine\My`` and adds signtool's ``/sm``.
VALID_WINDOWS_STORE_SCOPES = frozenset({"current_user", "machine"})
DEFAULT_WINDOWS_STORE_SCOPE = "current_user"

# Default freedesktop main category for the generated .desktop entry.
DEFAULT_DESKTOP_CATEGORIES = ("Utility",)

# The freedesktop **main** categories (desktop-entry menu spec). A generated
# ``.desktop`` must carry categories from this set so it registers correctly in
# menus/search; a typo/invalid value is rejected at config time (linux-spec).
FREEDESKTOP_MAIN_CATEGORIES = frozenset(
    {
        "AudioVideo",
        "Audio",
        "Video",
        "Development",
        "Education",
        "Game",
        "Graphics",
        "Network",
        "Office",
        "Science",
        "Settings",
        "System",
        "Utility",
    }
)

VALID_ORIENTATIONS = frozenset(
    {"portrait", "portrait-upside-down", "landscape-left", "landscape-right"}
)

DEFAULT_DEPLOYMENT_TARGET = "13.0"
DEFAULT_ENTRY_POINT = "main"
DEFAULT_ORIENTATION = ("portrait",)

# Simulator architectures pinned by ``kivyforge lock`` (spec 01/02). The device
# slice is always arm64; these are the *simulator* slices. ``x86_64`` exists only
# to run the simulator on an Intel Mac, so a project that no longer targets Intel
# hosts may set ``simulator_archs = ["arm64"]`` and stop pinning the dying slice.
VALID_SIMULATOR_ARCHS = frozenset({"arm64", "x86_64"})
DEFAULT_SIMULATOR_ARCHS = ("arm64", "x86_64")

# Info.plist keys kivyforge writes from the schema; users may not set these via
# [tool.kivy.ios.info_plist] (spec 01).
MANAGED_INFO_PLIST_KEYS = frozenset(
    {
        "CFBundleName",
        "CFBundleDisplayName",
        "CFBundleIdentifier",
        "CFBundleShortVersionString",
        "CFBundleVersion",
        "MinimumOSVersion",
        "UISupportedInterfaceOrientations",
        "UISupportedInterfaceOrientations~ipad",
        "LSRequiresIPhoneOS",
        "CFBundlePackageType",
        "CFBundleInfoDictionaryVersion",
        "CFBundleExecutable",
        "NSHumanReadableCopyright",
        # SDL3 scene lifecycle — written automatically for all Kivy apps.
        "UIApplicationSceneManifest",
    }
)

# Xcode build settings the toolchain manages; rejected under
# [tool.kivy.ios.xcode.build_settings] (spec 01).
RESERVED_BUILD_SETTINGS = frozenset(
    {
        "INFOPLIST_FILE",
        "PRODUCT_BUNDLE_IDENTIFIER",
        "IPHONEOS_DEPLOYMENT_TARGET",
        "TARGETED_DEVICE_FAMILY",
        "DEBUG_INFORMATION_FORMAT",
        "CODE_SIGN_STYLE",
        "CODE_SIGN_IDENTITY",
        "DEVELOPMENT_TEAM",
        "PROVISIONING_PROFILE_SPECIFIER",
        "ENABLE_USER_SCRIPT_SANDBOXING",
        "ENABLE_TESTABILITY",
        "FRAMEWORK_SEARCH_PATHS",
        "HEADER_SEARCH_PATHS",
        "LD_RUNPATH_SEARCH_PATHS",
        "GCC_WARN_QUOTED_INCLUDE_IN_FRAMEWORK_HEADER",
    }
)


@dataclass(frozen=True)
class Author:
    name: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class ProjectMeta:
    """PEP 621 ``[project]`` subset consumed by kivyforge."""

    name: str
    version: str
    description: str | None = None
    requires_python: str | None = None
    dependencies: tuple[str, ...] = ()
    authors: tuple[Author, ...] = ()


@dataclass(frozen=True)
class IconConfig:
    source: str | None = None


@dataclass(frozen=True)
class SplashConfig:
    source: str | None = None
    background: str | None = None


@dataclass(frozen=True)
class XcframeworkDep:
    name: str
    version: str
    source: str
    link: bool = True
    embed: bool = True


@dataclass(frozen=True)
class NativeBinaryDep:
    """One ``[tool.kivy.<platform>.native.binaries]`` entry (macos-spec).

    A non-wheel native binary (a vendor SDK DLL/dylib/so, or a helper
    executable) declared by name. ``source`` is always explicit: a direct
    ``http(s)://`` URL, or a repo-relative path to a vendored artifact. The
    entry is SHA-256-pinned into the lock and staged into the bundle's ``bin``
    directory at build time (see ``NativeBinaryDep`` handling in each desktop
    backend).
    """

    name: str
    version: str
    source: str


# SPM version-rule kinds (spec 07), mapping 1:1 to Swift Package Manager's own
# requirement rules. Each ``requirement`` inline table sets exactly one of these.
VALID_SWIFT_REQUIREMENT_KINDS = frozenset(
    {"exact", "from", "up_to_next_minor", "range", "branch", "revision"}
)


@dataclass(frozen=True)
class SwiftPackageDep:
    """One ``[tool.kivy.ios.native.swift_packages]`` entry (spec 07).

    Exactly one of ``url`` (remote, with a ``requirement`` rule) or ``path``
    (local, repo-relative) is set. ``requirement`` is a single-key inline table
    (one of ``VALID_SWIFT_REQUIREMENT_KINDS``); it is ``None`` for local
    packages.
    """

    name: str
    products: tuple[str, ...]
    url: str | None = None
    path: str | None = None
    requirement: dict[str, object] | None = None
    link: bool = True
    embed: bool = True

    def __post_init__(self) -> None:
        if bool(self.url) == bool(self.path):
            raise ValueError(
                f"swift package {self.name!r} must have exactly one of url/path"
            )


@dataclass(frozen=True)
class SigningConfig:
    team_id: str = ""
    identity: str = "Apple Development"
    provisioning_profile: str = ""
    auto_signing: bool = True
    upload_symbols: bool = True


@dataclass(frozen=True)
class IosConfig:
    """``[tool.kivy.ios]`` overlay."""

    schema_version: int
    bundle_id: str
    build: int = 1
    deployment_target: str = DEFAULT_DEPLOYMENT_TARGET
    simulator_archs: tuple[str, ...] = DEFAULT_SIMULATOR_ARCHS
    extra_index_urls: tuple[str, ...] = ()
    find_links: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    python_version: str | None = None
    icons: IconConfig = field(default_factory=IconConfig)
    splash: SplashConfig = field(default_factory=SplashConfig)
    xcframeworks: tuple[XcframeworkDep, ...] = ()
    swift_packages: tuple[SwiftPackageDep, ...] = ()
    entitlements: dict[str, object] = field(default_factory=dict)
    signing: SigningConfig = field(default_factory=SigningConfig)
    privacy_manifest_source: str | None = None
    info_plist: dict[str, object] = field(default_factory=dict)
    build_settings: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MacosSigningConfig:
    """``[tool.kivy.macos.signing]`` (macos-spec, Developer ID workstream).

    ``identity`` empty means Developer ID signing is not configured and
    ``package`` falls back to the ad-hoc floor. ``notary_profile`` names a
    keychain profile created with ``xcrun notarytool store-credentials`` —
    credentials stay in the keychain, never in ``pyproject.toml``.
    """

    identity: str = ""
    team_id: str = ""
    notary_profile: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.identity)


@dataclass(frozen=True)
class MacosConfig:
    """``[tool.kivy.macos]`` overlay (macos-spec).

    ``archs`` is a lock-level property: it drives which macOS wheel tags and
    per-arch runtimes the lock must cover. ``minimum_system_version`` is
    ``None`` when unset, meaning the bundled runtime's own floor applies.
    """

    schema_version: int
    bundle_id: str
    build: int = 1
    minimum_system_version: str | None = None
    archs: tuple[str, ...] = DEFAULT_MACOS_ARCHS
    extra_index_urls: tuple[str, ...] = ()
    find_links: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    python_version: str | None = None
    icons: IconConfig = field(default_factory=IconConfig)
    entitlements: dict[str, object] = field(default_factory=dict)
    signing: MacosSigningConfig = field(default_factory=MacosSigningConfig)
    binaries: tuple[NativeBinaryDep, ...] = ()


@dataclass(frozen=True)
class WindowsSigningConfig:
    """``[tool.kivy.windows.signing]`` (signing-windows, optional).

    Authenticode identity is a certificate-store **thumbprint**, never a
    ``.pfx`` path/password. ``store_scope`` selects which store both ``signtool``
    (via ``/sm`` for ``machine``) and the doctor certificate check inspect, so
    they always agree. ``thumbprint`` empty means signing is not configured and
    ``package`` leaves the artifact unsigned.
    """

    thumbprint: str = ""
    timestamp_url: str = DEFAULT_WINDOWS_TIMESTAMP_URL
    store_scope: str = DEFAULT_WINDOWS_STORE_SCOPE

    @property
    def configured(self) -> bool:
        return bool(self.thumbprint)


@dataclass(frozen=True)
class WindowsConfig:
    """``[tool.kivy.windows]`` overlay (windows-spec).

    ``archs`` drives which ``win_amd64`` wheel tag and per-arch runtime the lock
    must cover. ``app_id`` is the Windows **AppUserModelID** — a different
    identifier from the Linux reverse-DNS ``app_id`` and the macOS ``bundle_id``;
    the loader enforces only Microsoft's hard constraints (no spaces, ≤128
    chars), leaving pascal-case/period style to a doctor warning.
    """

    schema_version: int
    app_id: str
    archs: tuple[str, ...] = DEFAULT_WINDOWS_ARCHS
    extra_index_urls: tuple[str, ...] = ()
    find_links: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    python_version: str | None = None
    icons: IconConfig = field(default_factory=IconConfig)
    signing: WindowsSigningConfig = field(default_factory=WindowsSigningConfig)
    binaries: tuple[NativeBinaryDep, ...] = ()


@dataclass(frozen=True)
class DesktopConfig:
    """``[tool.kivy.linux.desktop]`` — freedesktop ``.desktop`` entry options."""

    categories: tuple[str, ...] = DEFAULT_DESKTOP_CATEGORIES


@dataclass(frozen=True)
class LinuxConfig:
    """``[tool.kivy.linux]`` overlay (linux-spec).

    ``archs`` drives which manylinux wheel tags and per-arch runtime the lock
    must cover. ``glibc_floor`` is ``None`` when unset, meaning the bundled
    runtime's own glibc floor (2.17) applies; setting it higher admits
    newer-manylinux-only wheels at the cost of raising the artifact's host floor.
    """

    schema_version: int
    app_id: str
    glibc_floor: str | None = None
    archs: tuple[str, ...] = DEFAULT_LINUX_ARCHS
    extra_index_urls: tuple[str, ...] = ()
    find_links: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    python_version: str | None = None
    icons: IconConfig = field(default_factory=IconConfig)
    desktop: DesktopConfig = field(default_factory=DesktopConfig)
    binaries: tuple[NativeBinaryDep, ...] = ()


@dataclass(frozen=True)
class KivyMeta:
    """Cross-platform ``[tool.kivy]`` table."""

    app_dir: str
    display_name: str | None = None
    entry_point: str = DEFAULT_ENTRY_POINT
    orientation: tuple[str, ...] = DEFAULT_ORIENTATION


@dataclass(frozen=True)
class Config:
    """Fully-validated kivyforge project configuration."""

    project: ProjectMeta
    kivy: KivyMeta
    ios: IosConfig | None = None
    macos: MacosConfig | None = None
    linux: LinuxConfig | None = None
    windows: WindowsConfig | None = None

    @property
    def display_name(self) -> str:
        if self.kivy.display_name:
            return self.kivy.display_name
        return self.project.name

    @property
    def app_slug(self) -> str:
        """The Xcode target / folder slug derived from [project].name."""
        return self.project.name

    @property
    def ios_required(self) -> IosConfig:
        """``[tool.kivy.ios]`` after ``load_config(..., require_ios=True)``.

        Pyright cannot infer that ``ios`` is set from the loader alone; iOS CLI
        verbs should use this accessor instead of ``config.ios`` directly.
        """
        if self.ios is None:
            raise RuntimeError(
                "Config.ios is None; call load_config with require_ios=True "
                "before accessing ios_required."
            )
        return self.ios

    @property
    def macos_required(self) -> MacosConfig:
        """``[tool.kivy.macos]`` after ``load_config(..., require_macos=True)``."""
        if self.macos is None:
            raise RuntimeError(
                "Config.macos is None; call load_config with require_macos=True "
                "before accessing macos_required."
            )
        return self.macos

    @property
    def linux_required(self) -> LinuxConfig:
        """``[tool.kivy.linux]`` after ``load_config(..., require_linux=True)``."""
        if self.linux is None:
            raise RuntimeError(
                "Config.linux is None; call load_config with require_linux=True "
                "before accessing linux_required."
            )
        return self.linux

    @property
    def windows_required(self) -> WindowsConfig:
        """``[tool.kivy.windows]`` after ``load_config(..., require_windows=True)``."""
        if self.windows is None:
            raise RuntimeError(
                "Config.windows is None; call load_config with require_windows=True "
                "before accessing windows_required."
            )
        return self.windows

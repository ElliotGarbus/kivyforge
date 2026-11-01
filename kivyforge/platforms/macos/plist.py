"""Build the ``.app`` ``Info.plist`` from the project config (macos-spec).

kivyforge owns the identity/versioning keys and merges the user's free-form
``[tool.kivy.macos.info_plist]`` on top (#201), mirroring the iOS managed-plist
discipline: setting a managed key is refused at config load, and again here so
the builder is safe in isolation.
"""

from __future__ import annotations

from kivyforge.config.model import MANAGED_MACOS_INFO_PLIST_KEYS, Config

# LSMinimumSystemVersion when the project sets none. Matches the macOS lock's
# default pip floor so the plist and the resolved wheels agree.
DEFAULT_MINIMUM_SYSTEM_VERSION = "11.0"


def build_info_plist(config: Config, *, executable: str, icon_file: str | None) -> dict:
    macos = config.macos_required
    plist: dict[str, object] = {
        "CFBundleName": config.display_name,
        "CFBundleDisplayName": config.display_name,
        "CFBundleIdentifier": macos.bundle_id,
        "CFBundleExecutable": executable,
        "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleShortVersionString": config.version_required.value,
        "CFBundleVersion": str(macos.build),
        "LSMinimumSystemVersion": (
            macos.minimum_system_version or DEFAULT_MINIMUM_SYSTEM_VERSION
        ),
        "NSHighResolutionCapable": True,
        # A GUI app (Kivy opens a window); without this Finder still launches it,
        # but it is the correct declaration for a windowed, non-agent app.
        "LSBackgroundOnly": False,
    }
    if icon_file is not None:
        plist["CFBundleIconFile"] = icon_file
    for key, value in macos.info_plist.items():
        if key in MANAGED_MACOS_INFO_PLIST_KEYS:
            raise ValueError(f"info_plist key {key!r} is managed by kivyforge")
        plist[key] = value
    return plist

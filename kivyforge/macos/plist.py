"""Build the ``.app`` ``Info.plist`` from the project config (macos-spec).

kivyforge owns the identity/versioning keys (mirroring the iOS managed-plist
discipline); there is no user Info.plist merge on macOS in this phase.
"""

from __future__ import annotations

from ..config.model import Config

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
        "CFBundleShortVersionString": config.project.version,
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
    return plist

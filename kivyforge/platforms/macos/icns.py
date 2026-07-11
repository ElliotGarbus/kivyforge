"""Generate a macOS ``.icns`` from a 1024×1024 PNG source (macos-spec).

Uses the system ``sips`` (resize) + ``iconutil`` (iconset → icns), so no image
libraries are needed. The source is validated as a 1024×1024 PNG first, matching
the iOS icon discipline.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from kivyforge.config.icons import IconSourceError, validate_icon_source

from . import AppBundleError

# (pixel size, iconset filename) pairs Apple's iconutil expects. Retina (@2x)
# variants are rendered at 2× the point size from the single 1024² source.
_ICONSET = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]


def generate_icns(source: Path, dest: Path) -> None:
    """Render *source* (1024×1024 PNG) into an ``.icns`` at *dest*."""
    validate_icon_source(source)
    with tempfile.TemporaryDirectory(prefix="kivy-icns-") as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for size, name in _ICONSET:
            _sips_resize(source, iconset / name, size)
        _iconutil(iconset, dest)


def _sips_resize(source: Path, out: Path, size: int) -> None:
    _run(
        [
            "sips",
            "-z",
            str(size),
            str(size),
            str(source),
            "--out",
            str(out),
        ]
    )


def _iconutil(iconset: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["iconutil", "-c", "icns", str(iconset), "-o", str(dest)])


def _run(cmd: list[str]) -> None:
    if shutil.which(cmd[0]) is None:
        raise AppBundleError(
            f"required macOS tool {cmd[0]!r} not found (ships with macOS)."
        )
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AppBundleError(f"{cmd[0]} failed: {(proc.stderr or proc.stdout).strip()}")


__all__ = ["AppBundleError", "IconSourceError", "generate_icns"]

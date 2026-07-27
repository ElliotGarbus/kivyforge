#!/usr/bin/env python3
"""Verify the vendored SDL Java glue matches kivy-mobile-wheels (android/05).

kivyforge/platforms/android/bootstrap/templates/sdl2|sdl3/ vendor the SDL Java
glue paired with the libSDL*.so that the kivy-mobile-wheels repo cross-builds
and ships (recipes/android/sdl-glue*/<version>/). SDLActivity.onCreate aborts
*silently* on a version mismatch between the two (contract.py,
check_sdl_glue_contract) — no logcat, no traceback, a black screen — so the
pairing is treated as a hard contract, not a convention.

check_sdl_glue_contract() catches a *version-stamp* mismatch, but only for
whoever next builds an app, and only after the fact. It cannot catch the
vendored copies diverging in *content* while the stamped version stays the
same (e.g. a hand-edit on one side, or the wheels repo patching its glue
without bumping SDL_REVISION.txt) — nothing links the two repos together.

This script is that missing link: for each SDL generation, it reads the
version kivyforge currently vendors from SDL_REVISION.txt, fetches the
matching version directory from kivy-mobile-wheels over HTTPS (public repo,
no auth), and diffs every glue file byte-for-byte. Run in CI on every push/PR.

Usage: python scripts/check_sdl_glue_sync.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_ROOT = REPO_ROOT / "kivyforge/platforms/android/bootstrap/templates"
WHEELS_REPO_RAW = (
    "https://raw.githubusercontent.com/ElliotGarbus/kivy-mobile-wheels/main"
)

_GLUE_FILES = [
    "LICENSE-SDL.txt",
    "SDL_REVISION.txt",
    "org/libsdl/app/HIDDevice.java",
    "org/libsdl/app/HIDDeviceBLESteamController.java",
    "org/libsdl/app/HIDDeviceManager.java",
    "org/libsdl/app/HIDDeviceUSB.java",
    "org/libsdl/app/SDL.java",
    "org/libsdl/app/SDLActivity.java",
    "org/libsdl/app/SDLAudioManager.java",
    "org/libsdl/app/SDLControllerManager.java",
    "org/libsdl/app/SDLSurface.java",
]

# (kivyforge template dir, wheels-repo glue dir, third SDL_REVISION.txt macro,
# extra files this generation's glue carries beyond _GLUE_FILES)
GENERATIONS = [
    ("sdl2", "sdl-glue", "SDL_PATCHLEVEL", []),
    (
        "sdl3",
        "sdl-glue-sdl3",
        "SDL_MICRO_VERSION",
        [
            "org/libsdl/app/SDLDummyEdit.java",
            "org/libsdl/app/SDLInputConnection.java",
            "org/libsdl/app/SDLSensorManager.java",
        ],
    ),
]


class SyncError(Exception):
    """A vendored glue file is missing, unfetchable, or diverged."""


def _committed_bytes(path: Path) -> bytes:
    """The file's content as actually committed, bypassing checkout-time EOL
    conversion (kivyforge/.gitattributes does not force an EOL for .java/.txt,
    so a Windows checkout with core.autocrlf=true reads CRLF locally even
    though the blob — and what kivy-mobile-wheels serves — is LF)."""
    rel = path.resolve().relative_to(REPO_ROOT).as_posix()
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    return result.stdout


def _extract_macro(text: str, macro: str) -> str | None:
    match = re.search(rf"#define\s+{macro}\s+(\d+)", text)
    return match.group(1) if match else None


def vendored_sdl_version(gen: str, patch_macro: str) -> str:
    """The SDL version kivyforge currently vendors, from SDL_REVISION.txt."""
    path = TEMPLATES_ROOT / gen / "SDL_REVISION.txt"
    text = _committed_bytes(path).decode()
    major = _extract_macro(text, "SDL_MAJOR_VERSION")
    minor = _extract_macro(text, "SDL_MINOR_VERSION")
    patch = _extract_macro(text, patch_macro)
    if not (major and minor and patch):
        raise SyncError(
            f"{path} does not carry SDL_MAJOR_VERSION/SDL_MINOR_VERSION/"
            f"{patch_macro} #define lines; cannot determine the vendored "
            "SDL version to check against."
        )
    return f"{major}.{minor}.{patch}"


def _fetch(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SyncError(f"not found in kivy-mobile-wheels: {url}") from exc
        raise
    except urllib.error.URLError as exc:
        raise SyncError(f"could not reach kivy-mobile-wheels: {url} ({exc})") from exc


def check_generation(
    gen: str, wheels_dir: str, patch_macro: str, extra: list[str]
) -> list[str]:
    version = vendored_sdl_version(gen, patch_macro)
    local_root = TEMPLATES_ROOT / gen
    remote_root = f"{WHEELS_REPO_RAW}/recipes/android/{wheels_dir}/{version}"
    problems = []
    for rel in _GLUE_FILES + extra:
        local_path = local_root / rel
        if not local_path.is_file():
            problems.append(f"{gen}/{rel}: vendored file is missing")
            continue
        local_bytes = _committed_bytes(local_path)
        try:
            remote_bytes = _fetch(f"{remote_root}/{rel}")
        except SyncError as exc:
            problems.append(str(exc))
            continue
        if local_bytes != remote_bytes:
            problems.append(
                f"{gen}/{rel} differs from kivy-mobile-wheels "
                f"recipes/android/{wheels_dir}/{version}/{rel}"
            )
    return problems


def main() -> int:
    all_problems: list[str] = []
    checked_versions: list[str] = []
    for gen, wheels_dir, patch_macro, extra in GENERATIONS:
        try:
            checked_versions.append(
                f"{gen}: SDL {vendored_sdl_version(gen, patch_macro)}"
            )
            all_problems.extend(check_generation(gen, wheels_dir, patch_macro, extra))
        except SyncError as exc:
            all_problems.append(str(exc))

    if all_problems:
        print("SDL glue sync check FAILED:", file=sys.stderr)
        for problem in all_problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\n  kivyforge's vendored SDL Java glue "
            "(kivyforge/platforms/android/bootstrap/templates/sdl2|sdl3/) must "
            "be byte-identical to the matching version directory in "
            "https://github.com/ElliotGarbus/kivy-mobile-wheels "
            "(recipes/android/sdl-glue*/<version>/) — they are a matched pair "
            "with the libSDL*.so shipped in the Kivy wheel, and a silent "
            "mismatch is an on-device black screen, not a build error "
            "(kivyforge/platforms/android/bootstrap/contract.py). Re-vendor "
            "whichever side is stale.",
            file=sys.stderr,
        )
        return 1

    for line in checked_versions:
        print(f"  {line}: glue matches kivy-mobile-wheels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

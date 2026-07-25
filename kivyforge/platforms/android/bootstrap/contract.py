"""The bootstrap's matched-pair gates (android/05).

Two independent pairings are enforced here. Both are contracts between a
generated Java source and a binary that ships in a wheel, with nothing linking
them at compile time — so kivyforge checks them explicitly at build time rather
than discovering them on-device.

``org.jnius.NativeInvocationHandler``'s ``invoke0`` native method and the
pyjnius wheel's implementation are an ABI contract that must move together.
The wheel ships no Java and nothing links them at compile time, so kivyforge
enforces the pairing explicitly: the bootstrap template carries a contract
version and the pyjnius version range it is compatible with, and
``kivyforge build`` **fails** (doctor: **FAIL**) when the locked pyjnius falls
outside it. A mismatch is a guaranteed runtime crash — never something to ship.

Wheel-side status: the spike wheel carries no machine-readable marker yet
(see android/05 §"Implementation status"), so this range list IS the
enforcement until upstream pyjnius grows one. Widening the range is a
bootstrap-template change that must re-run the contract smoke test
(android/08 §revalidation).
"""

from __future__ import annotations

import re
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

# The invoke0 contract version this template set implements (android/08 row
# "invoke0 contract v1": Object invoke0(Object proxy, Method method,
# Object[] args) via RegisterNatives — the shape proven by the spike's Step 5
# and the Phase-0 prototype).
INVOKE0_CONTRACT_VERSION = 1

# pyjnius releases whose invoke0 implementation matches contract v1. 1.7.x is
# the spike-validated series; anything newer must be revalidated (and this
# range widened) before it is accepted.
COMPATIBLE_PYJNIUS = SpecifierSet(">=1.7.0,<1.8")


class ContractError(Exception):
    """The locked pyjnius is outside the bootstrap template's invoke0 range."""


def check_pyjnius_contract(locked_version: str) -> None:
    """Hard build gate (android/05): raise unless the pyjnius version is in range."""
    try:
        version = Version(locked_version)
    except InvalidVersion as exc:
        raise ContractError(
            f"locked pyjnius version {locked_version!r} is not a valid version; "
            "cannot verify the NativeInvocationHandler.invoke0 contract."
        ) from exc
    if version not in COMPATIBLE_PYJNIUS:
        raise ContractError(
            f"locked pyjnius {locked_version} is outside the bootstrap "
            f"template's compatible range ({COMPATIBLE_PYJNIUS}) for invoke0 "
            f"contract v{INVOKE0_CONTRACT_VERSION}.\n"
            "  The invoke0 native-method signature is an ABI contract between "
            "the pyjnius wheel and the generated "
            "org.jnius.NativeInvocationHandler; a mismatch crashes at first "
            "proxy use.\n"
            "  Fix: re-lock to a compatible pyjnius, or upgrade kivyforge for "
            "a newer bootstrap template (android/05 §matched pair)."
        )


# --- SDL glue <-> libSDL2.so ------------------------------------------------
# SDLActivity.onCreate compares its own compiled-in SDL_{MAJOR,MINOR,MICRO}
# _VERSION constants against nativeGetVersion() and, when they differ, sets
# mBrokenLibraries and *returns before creating the surface*. It logs nothing:
# the app shows a black screen, SDL_main is never called, and no Python ever
# runs — indistinguishable from a hung interpreter unless you know to look.
# The Java glue and libSDL2.so must therefore come from the same SDL release
# (docs/design/dev/android-wheel-build-recipe.md step 2).

_JAVA_VERSION_RE = re.compile(
    r"SDL_MAJOR_VERSION\s*=\s*(\d+).*?"
    r"SDL_MINOR_VERSION\s*=\s*(\d+).*?"
    r"SDL_MICRO_VERSION\s*=\s*(\d+)",
    re.DOTALL,
)
# SDL stamps its build with SDL_REVISION, e.g. "release-2.32.10-0-g5d2495703".
_SO_REVISION_RE = re.compile(rb"release-(\d+)\.(\d+)\.(\d+)[-\w.]*")


def sdl_version_from_glue(java_source: str) -> str:
    """The SDL version the Java glue was taken from, as ``major.minor.micro``."""
    match = _JAVA_VERSION_RE.search(java_source)
    if match is None:
        raise ContractError(
            "SDLActivity.java carries no SDL_MAJOR/MINOR/MICRO_VERSION "
            "constants; the SDL Java glue template is not a stock SDL source "
            "and its version cannot be verified against libSDL2.so."
        )
    return ".".join(match.groups())


def sdl_version_from_library(so_path: Path) -> str | None:
    """The SDL version stamped into ``libSDL2.so``, or ``None`` if absent.

    ``None`` is not a failure: a stripped or unusually-built SDL simply cannot
    be checked, and refusing to build over it would be worse than the risk.
    """
    try:
        blob = so_path.read_bytes()
    except OSError:
        return None
    match = _SO_REVISION_RE.search(blob)
    return ".".join(part.decode() for part in match.groups()) if match else None


def check_sdl_glue_contract(*, java_source: str, so_path: Path) -> None:
    """Hard build gate: the SDL Java glue must match the shipped libSDL2.so."""
    glue = sdl_version_from_glue(java_source)
    native = sdl_version_from_library(so_path)
    if native is None or glue == native:
        return
    raise ContractError(
        f"SDL version mismatch: the bootstrap's Java glue is SDL {glue} but "
        f"{so_path.name} is SDL {native}.\n"
        "  SDLActivity refuses to start on a mismatch and returns from "
        "onCreate *silently* — the app would show a black screen with no "
        "error in logcat and no Python ever running.\n"
        "  Fix: ship the org/libsdl/app/*.java glue from the same SDL release "
        "as the libSDL2.so in the Kivy wheel (android/05 §matched pair; "
        "docs/design/dev/android-wheel-build-recipe.md step 2)."
    )

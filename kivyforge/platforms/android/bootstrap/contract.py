"""The bootstrap's matched-pair gates (android/05).

Two independent pairings are enforced here. Both are contracts between a
generated Java source and a binary that ships in a wheel, with nothing linking
them at compile time — so kivyforge checks them explicitly at build time rather
than discovering them on-device.

``org.jnius.NativeInvocationHandler``'s ``invoke0`` native method and the
pyjnius wheel's implementation are an ABI contract that must move together.
The wheel ships no Java and nothing links them at compile time, so kivyforge
enforces the pairing explicitly: the bootstrap template carries a contract
version, and ``kivyforge build`` **fails** when the installed pyjnius wheel does
not bind the ``invoke0`` signature the template declares (doctor: **FAIL** when
the locked version predates the contract). A mismatch is a guaranteed runtime
crash — never something to ship.

The check is on the wheel's binary, not a version ceiling, so a new pyjnius
release that keeps the contract works without a kivyforge release. The version
is only a floor (``COMPATIBLE_PYJNIUS``).
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

# The oldest pyjnius whose invoke0 implementation matches contract v1. 1.7.x is
# the spike-validated series; 1.8.x is the first release to ship Android wheels
# on PyPI. This is a *floor only*: pyjnius releases often and the contract has
# not moved since 1.7 (1.9.0 was verified byte-for-byte), so a version ceiling
# only turned every upstream release into a kivyforge outage (#113). What would
# actually break is the signature changing, and that is checked directly against
# the wheel's binary by ``check_invoke0_signature`` rather than guessed from the
# version number.
COMPATIBLE_PYJNIUS = SpecifierSet(">=1.7.0")

# The JNI signature pyjnius passes to RegisterNatives for ``invoke0``
# (jnius/jnius_proxy.pxi). It sits verbatim in the wheel's compiled extension, so
# its presence there proves the wheel binds the method NativeInvocationHandler
# declares: ``native Object invoke0(Object, Method, Object[])``.
INVOKE0_JNI_SIGNATURE = (
    b"(Ljava/lang/Object;Ljava/lang/reflect/Method;[Ljava/lang/Object;)"
    b"Ljava/lang/Object;"
)


class ContractError(Exception):
    """The locked pyjnius does not satisfy the bootstrap template's invoke0 contract."""


def check_pyjnius_contract(locked_version: str) -> None:
    """Early build gate (android/05): raise if pyjnius predates contract v1.

    Only a floor — see ``COMPATIBLE_PYJNIUS``. The authoritative check for newer
    releases is ``check_invoke0_signature`` on the installed wheel.
    """
    try:
        version = Version(locked_version)
    except InvalidVersion as exc:
        raise ContractError(
            f"locked pyjnius version {locked_version!r} is not a valid version; "
            "cannot verify the NativeInvocationHandler.invoke0 contract."
        ) from exc
    if version not in COMPATIBLE_PYJNIUS:
        raise ContractError(
            f"locked pyjnius {locked_version} is older than the bootstrap "
            f"template supports ({COMPATIBLE_PYJNIUS}) for invoke0 "
            f"contract v{INVOKE0_CONTRACT_VERSION}.\n"
            "  The invoke0 native-method signature is an ABI contract between "
            "the pyjnius wheel and the generated "
            "org.jnius.NativeInvocationHandler; a mismatch crashes at first "
            "proxy use.\n"
            "  Fix: require a newer pyjnius in [project].dependencies "
            f'(e.g. "pyjnius{COMPATIBLE_PYJNIUS}") and re-lock '
            "(android/05 §matched pair)."
        )


def pyjnius_extensions(site_packages: Path) -> list[Path]:
    """The compiled ``jnius`` extension module(s) in an installed site-packages."""
    package = site_packages / "jnius"
    return sorted(package.glob("*.so")) if package.is_dir() else []


def check_invoke0_signature(so_path: Path) -> None:
    """Hard build gate: the wheel must bind the ``invoke0`` the template declares.

    Checks the shipped binary, so it holds for any pyjnius version — including
    one released after this kivyforge. An unreadable file is not a failure (the
    version floor still applies); a readable one without the signature is.
    """
    try:
        blob = so_path.read_bytes()
    except OSError:
        return
    if INVOKE0_JNI_SIGNATURE in blob:
        return
    raise ContractError(
        f"{so_path.name} does not bind the invoke0 signature the bootstrap "
        f"template declares (contract v{INVOKE0_CONTRACT_VERSION}: "
        "native Object invoke0(Object, Method, Object[])).\n"
        "  The wheel's pyjnius changed the NativeInvocationHandler ABI, so "
        "the first Python object a Java callback touches would crash the app.\n"
        "  Fix: pin pyjnius in [project].dependencies to the last release "
        "that kept the contract and re-lock, or upgrade kivyforge for a "
        "newer bootstrap template (android/05 §matched pair)."
    )


# --- SDL glue <-> libSDL<N>.so ----------------------------------------------
# SDLActivity.onCreate compares its own compiled-in SDL_{MAJOR,MINOR,MICRO}
# _VERSION constants against nativeGetVersion() and, when they differ, sets
# mBrokenLibraries and *returns before creating the surface*. It logs nothing:
# the app shows a black screen, SDL_main is never called, and no Python ever
# runs — indistinguishable from a hung interpreter unless you know to look.
# The Java glue and the shipped libSDL<N>.so must therefore come from the same
# SDL release (docs/design/dev/android-wheel-build-recipe.md step 2). Both
# generations are checked: an SDL3 project whose wheel ships SDL2 fails just as
# opaquely, so neither is allowed to skip the gate.

_JAVA_VERSION_RE = re.compile(
    r"SDL_MAJOR_VERSION\s*=\s*(\d+).*?"
    r"SDL_MINOR_VERSION\s*=\s*(\d+).*?"
    r"SDL_MICRO_VERSION\s*=\s*(\d+)",
    re.DOTALL,
)
# SDL stamps its build with SDL_REVISION, e.g. "release-2.32.10-0-g5d2495703".
_SO_REVISION_RE = re.compile(rb"release-(\d+)\.(\d+)\.(\d+)[-\w.]*")
# The family core library, e.g. libSDL2.so / libSDL3.so (not libSDL2_image.so).
_SDL_CORE_RE = re.compile(r"^libSDL(\d+)\.so$")


def sdl_library_name(generation: int) -> str:
    """The core SDL library the generation's Java glue will ``loadLibrary``."""
    return f"libSDL{generation}.so"


def check_sdl_generation(*, generation: int, staged: list[str]) -> None:
    """The staged jniLibs must carry the SDL family the rendered glue loads.

    A wheel shipping the other generation's SDL is not a version mismatch the
    glue can detect — ``SDLActivity`` dies in its static initializer on
    ``loadLibrary("SDL3")`` before any of its own code runs, so the build has to
    catch it.
    """
    expected = sdl_library_name(generation)
    if expected in staged:
        return
    present = sorted(name for name in staged if _SDL_CORE_RE.match(name))
    if not present:
        return  # nothing SDL staged (e.g. a Kivy-less project): nothing to check
    raise ContractError(
        f"kivy_generation = {generation} renders the SDL{generation} Java glue, "
        f"which loads {expected} — but the staged native libraries provide "
        f"{', '.join(present)}.\n"
        "  SDLActivity loads the SDL family in its static initializer, so the "
        "app dies with an UnsatisfiedLinkError before any kivyforge or Python "
        "code runs.\n"
        f"  Fix: set [tool.kivy.android].kivy_generation to match the Kivy "
        f"wheel's SDL family, or lock a Kivy that ships {expected} "
        "(android/05 §matched pair)."
    )


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
    """The SDL version stamped into ``libSDL<N>.so``, or ``None`` if absent.

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
    """Hard build gate: the SDL Java glue must match the shipped libSDL<N>.so."""
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
        f"as the {so_path.name} in the Kivy wheel (android/05 §matched pair; "
        "docs/design/dev/android-wheel-build-recipe.md step 2)."
    )

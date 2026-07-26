"""Render the bootstrap templates for one project (android/05).

The templates are the *proven* Phase-0 prototype sources; rendering is
deliberately minimal — targeted substitutions on known markers, never a
general templating language — so that rendering with the prototype's own
parameters (``sdl=2``, Python 3.14) reproduces the proven sources byte-for-
byte (the Phase-3 diff-clean gate).

Substitution points today:
- ``PythonActivity.java`` ``getLibraries()``: the SDL family for the selected
  generation + the ``pythonX.Y`` soname stem.

``main.c``/``CMakeLists.txt`` need no substitution (the launcher reads its
environment at runtime; CMake gets ``PYTHON_VERSION`` as a Gradle argument).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"

# The SDL2 family the proven prototype loads, in load order (android/05).
SDL2_LIBRARIES = ("SDL2", "SDL2_image", "SDL2_mixer", "SDL2_ttf")
# SDL3 names for the sdl = 3 generation (schema-complete; on-device validation
# is Pending until a Kivy 3.0 host exists — android/08).
SDL3_LIBRARIES = ("SDL3", "SDL3_image", "SDL3_mixer", "SDL3_ttf")

# The exact getLibraries block in the proven PythonActivity.java; rendering
# replaces it wholesale so the template file itself stays byte-identical to
# the prototype.
_PROTO_LIBRARIES_BLOCK = (
    '            "SDL2", "SDL2_image", "SDL2_mixer", "SDL2_ttf",\n'
    '            "python3.14",\n'
)
_PROTO_PYTHON_STEM = "python3.14"


class RenderError(Exception):
    pass


@dataclass(frozen=True)
class RenderedFile:
    """One generated source file, relative to the app module root."""

    relpath: str  # POSIX, relative to app/src/main/
    content: str


def python_stem(python_version: str) -> str:
    """``3.14.6`` -> ``python3.14`` (the libpython soname stem)."""
    parts = python_version.split(".")
    if len(parts) < 2 or not all(p.split("rc")[0].isdigit() for p in parts[:2]):
        raise RenderError(
            f"cannot derive a libpython soname from python version {python_version!r}"
        )
    return f"python{parts[0]}.{parts[1]}"


def render_bootstrap(*, sdl: int, python_version: str) -> list[RenderedFile]:
    """Render every bootstrap source for the generated project's app module.

    Returns Java sources (kivyforge bootstrap + SDL glue), the native
    launcher's C sources, and the finder module content is exposed separately
    via :func:`finder_source` (it ships in the asset bundle, not ``src/main``).
    """
    if sdl == 2:
        sdl_dir = TEMPLATES_DIR / "sdl2"
        libraries = SDL2_LIBRARIES
    elif sdl == 3:
        sdl_dir = TEMPLATES_DIR / "sdl3"
        libraries = SDL3_LIBRARIES
        if not sdl_dir.is_dir():
            raise RenderError(
                "sdl = 3 is schema-complete but this kivyforge release ships "
                "no SDL3 Java glue yet: the SDL3 path is Pending on-device "
                "validation until a Kivy 3.0 host exists (android/08). "
                "Use sdl = 2 (Kivy 2.3.1) for now."
            )
    else:  # pragma: no cover - loader rule 9 rejects earlier
        raise RenderError(f"unknown sdl generation {sdl!r}")

    out: list[RenderedFile] = []

    # 1. PythonActivity with the generation's library list + python stem.
    activity = _read(TEMPLATES_DIR / "java/org/kivy/android/PythonActivity.java")
    stem = python_stem(python_version)
    # Same shape as the prototype block: the SDL family on one line, then the
    # libpython stem — so rendering with the prototype's parameters is a
    # byte-identical no-op (the diff-clean gate).
    sdl_line = "            " + ", ".join(f'"{lib}"' for lib in libraries) + ",\n"
    lib_lines = sdl_line + f'            "{stem}",\n'
    if _PROTO_LIBRARIES_BLOCK not in activity:
        raise RenderError(
            "PythonActivity.java template drifted: the proven getLibraries "
            "block was not found (re-extract from a proven prototype)."
        )
    activity = activity.replace(_PROTO_LIBRARIES_BLOCK, lib_lines)
    out.append(RenderedFile("java/org/kivy/android/PythonActivity.java", activity))

    # 2. The pyjnius glue (matched pair; see contract.py).
    out.append(
        RenderedFile(
            "java/org/jnius/NativeInvocationHandler.java",
            _read(TEMPLATES_DIR / "java/org/jnius/NativeInvocationHandler.java"),
        )
    )

    # 2b. Kivy-compatibility shims (org.renpy.android.*), verbatim. Kivy's own
    # Python code autoclasses these (android/05 §namespace preservation).
    for compat in sorted((TEMPLATES_DIR / "java/org/renpy/android").glob("*.java")):
        out.append(RenderedFile(f"java/org/renpy/android/{compat.name}", _read(compat)))

    # 3. Stock SDL Java glue for the generation, verbatim.
    for java in sorted(sdl_dir.rglob("*.java")):
        rel = java.relative_to(sdl_dir).as_posix()
        out.append(RenderedFile(f"java/{rel}", _read(java)))

    # 4. Native launcher sources (compiled by the NDK via externalNativeBuild).
    out.append(RenderedFile("cpp/main.c", _read(TEMPLATES_DIR / "cpp/main.c")))
    out.append(
        RenderedFile("cpp/CMakeLists.txt", _read(TEMPLATES_DIR / "cpp/CMakeLists.txt"))
    )
    return out


def finder_source() -> str:
    """The extension-module finder shipped in the asset bundle's bootstrap/."""
    return _read(TEMPLATES_DIR / "bootstrap_py/_kivyforge_bootstrap.py")


def kivy_bootstrap_source() -> str:
    """kivyforge's side of Kivy 3's Android bootstrap contract.

    Named by Kivy, not by us: Kivy imports ``_kivy_bootstrap`` to reach the
    current Activity, so this is what makes an unmodified Kivy run on a
    kivyforge-built app.  Ships in the bundle's ``bootstrap/``, which is on
    ``sys.path`` before the app's entry module.
    """
    return _read(TEMPLATES_DIR / "bootstrap_py/_kivy_bootstrap.py")


def selftest_source() -> str:
    """The inert contract self-test, shipped in the asset bundle's bootstrap/."""
    return _read(TEMPLATES_DIR / "bootstrap_py/_kivyforge_selftest.py")


def androidtest_files() -> list[RenderedFile]:
    """The generated instrumented contract test, relative to app/src/."""
    out: list[RenderedFile] = []
    root = TEMPLATES_DIR / "androidtest"
    for java in sorted(root.glob("*.java")):
        out.append(
            RenderedFile(
                f"androidTest/java/org/kivyforge/test/{java.name}", _read(java)
            )
        )
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RenderError(
            f"bootstrap template missing or unreadable: {path} ({exc}); "
            "the kivyforge installation is incomplete."
        ) from exc

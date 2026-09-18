"""The ``.app`` launcher — a compiled Mach-O stub (the iOS ``main.m`` analog).

The bundle's ``CFBundleExecutable`` must be a real Mach-O binary, not a shell
script: Finder/LaunchServices treats a text-script main executable as a document
and spawns a Terminal/console window for it, and a script also can't be
ad-hoc-signed as the app's main image. So kivyforge compiles a tiny C launcher
(with ``clang`` from the Xcode command-line tools, which are already required for
``codesign``). At runtime it locates the bundle relative to itself — so the
``.app`` stays fully relocatable — points the bundled CPython at its own home +
the app's ``lib``/``app`` directories, and ``execv``s the entry-point module.

The entry point is run with ``-m`` rather than by path — the same fix applied
to the Linux ``AppRun`` (``platforms/linux/launcher.py``) for the identical
defect. Exec'ing ``Resources/app/{entry}.py`` shipped a release ``.app`` that
could not start at all: ``package`` applies ``strip_source`` by default, which
leaves ``main.pyc`` and deletes the ``main.py`` this launcher was still naming,
so the interpreter exited 2 (``can't open file '.../app/main.py'``) before
Python came up. ``-m`` goes through the import system, which loads a
sourceless ``.pyc`` in the legacy layout exactly as happily as a ``.py`` — so
the payload can change shape without the launcher having to be told.

``-P`` is included for symmetry with the Linux launcher and to keep
``sys.path`` deriving from ``PYTHONPATH`` alone, but it is not load-bearing
here the way it is on Linux: this launcher already ``chdir``s into ``app``
before exec, so the directory plain ``-m`` would add to ``sys.path`` is the one
we want anyway. Needs CPython >= 3.11; the bundled runtime satisfies it.

``PYTHONDONTWRITEBYTECODE`` is set for a reason specific to macOS: the very
first real launch this launcher ever had wrote ``__pycache__`` into the
bundle's embedded stdlib (shipped as ``.py`` — stripping is deliberately
scoped to ``app``/``site-packages`` only) and invalidated the bundle's own
code signature. A macOS ``.app`` is signed once, at build time, and never
touched again; a running app writing into itself breaks that invariant on the
very first launch, which nothing had ever exercised until now.

Since roadmap item 9 the build byte-compiles the staged stdlib *before*
signing, so the bundle ships with its ``__pycache__`` sealed in and a launch
has nothing it wants to write. This variable is now the guarantee rather than
the trade-off it used to be: it no longer costs a slow start.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from kivyforge.report.failures import spawn_failure

from . import AppBundleError

# The launcher is intentionally minimal: resolve its own path, derive the bundle
# layout, set the Python environment, and exec the interpreter on the entry
# module via ``-m`` (see the module docstring for why not by path).
# ``{entry}`` is filled with the (identifier-only) entry-point name.
_SOURCE = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <libgen.h>
#include <unistd.h>
#include <mach-o/dyld.h>

static const char *ENTRY = "{entry}";

int main(int argc, char *argv[]) {{
    char raw[PATH_MAX];
    uint32_t size = sizeof(raw);
    if (_NSGetExecutablePath(raw, &size) != 0) return 71;
    char exe[PATH_MAX];
    if (realpath(raw, exe) == NULL) return 71;   /* .../Contents/MacOS/<name> */

    char a[PATH_MAX];
    strncpy(a, exe, sizeof(a)); a[sizeof(a) - 1] = 0;
    char *macos = dirname(a);                     /* .../Contents/MacOS */
    char b[PATH_MAX];
    strncpy(b, macos, sizeof(b)); b[sizeof(b) - 1] = 0;
    char *contents = dirname(b);                  /* .../Contents */

    char home[PATH_MAX], app[PATH_MAX], lib[PATH_MAX], bin[PATH_MAX];
    char py[PATH_MAX], pypath[2 * PATH_MAX];
    snprintf(home, sizeof(home), "%s/Resources/python", contents);
    snprintf(app, sizeof(app), "%s/Resources/app", contents);
    snprintf(lib, sizeof(lib), "%s/Resources/lib", contents);
    snprintf(bin, sizeof(bin), "%s/Resources/bin", contents);
    snprintf(py, sizeof(py), "%s/bin/python3", home);
    snprintf(pypath, sizeof(pypath), "%s:%s", app, lib);

    setenv("PYTHONHOME", home, 1);
    setenv("PYTHONPATH", pypath, 1);
    /* Isolate from ~/.local and user site config; the bundle is self-contained. */
    setenv("PYTHONNOUSERSITE", "1", 1);
    /* The embedded stdlib ships as .py source (strip_source is scoped to
       app+site-packages only), so importing it would otherwise write
       __pycache__ into the signed bundle on first launch -- silently
       invalidating its own code signature (codesign reports "a sealed
       resource is missing or invalid" on the very next `--verify`). Never
       write bytecode caches into a bundle that is signed once, at build
       time, and never rewritten after. */
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1);
    /* Prepend Resources/bin so user-declared native helper executables resolve by
       name (subprocess/PATH lookups). Harmless when the directory is absent. */
    const char *old_path = getenv("PATH");
    char newpath[3 * PATH_MAX];
    if (old_path != NULL && old_path[0] != 0) {{
        snprintf(newpath, sizeof(newpath), "%s:%s", bin, old_path);
    }} else {{
        snprintf(newpath, sizeof(newpath), "%s", bin);
    }}
    setenv("PATH", newpath, 1);
    chdir(app);

    char **child = (char **)malloc(sizeof(char *) * (argc + 4));
    if (child == NULL) return 71;
    child[0] = py;
    child[1] = "-P";
    child[2] = "-m";
    child[3] = (char *)ENTRY;
    for (int i = 1; i < argc; i++) child[i + 3] = argv[i];
    child[argc + 3] = NULL;
    execv(py, child);
    perror("kivyforge launcher: execv");
    return 71;
}}
"""


def render_launcher_source(entry_point: str) -> str:
    """The C source for a launcher that execs ``-m`` *entry_point* (pure/testable)."""
    if not entry_point.isidentifier():
        raise AppBundleError(f"entry_point {entry_point!r} is not a valid module name.")
    return _SOURCE.format(entry=entry_point)


def build_launcher(dest: Path, *, entry_point: str, arch: str) -> None:
    """Compile the launcher for *arch* to *dest*."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    source = render_launcher_source(entry_point)
    with tempfile.TemporaryDirectory(prefix="kivy-launcher-") as tmp:
        src = Path(tmp) / "launcher.c"
        src.write_text(source, encoding="utf-8")
        _compile(["clang", "-O2", "-Wall", "-arch", arch, "-o", str(dest), str(src)])
    dest.chmod(0o755)


def _compile(cmd: list[str]) -> None:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
    except OSError as exc:
        reason = (
            "not found" if isinstance(exc, FileNotFoundError) else f"unusable ({exc})"
        )
        raise AppBundleError(
            f"clang {reason}; the launcher needs the Xcode command-line tools.\n"
            "  Install them with: xcode-select --install",
            **spawn_failure("clang", exc),
        ) from exc
    if proc.returncode != 0:
        raise AppBundleError(
            f"failed to compile the app launcher: "
            f"{(proc.stderr or proc.stdout).strip()}"
        )

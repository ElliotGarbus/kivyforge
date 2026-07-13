"""The ``.app`` launcher — a compiled Mach-O stub (the iOS ``main.m`` analog).

The bundle's ``CFBundleExecutable`` must be a real Mach-O binary, not a shell
script: Finder/LaunchServices treats a text-script main executable as a document
and spawns a Terminal/console window for it, and a script also can't be
ad-hoc-signed as the app's main image. So kivyforge compiles a tiny C launcher
(with ``clang`` from the Xcode command-line tools, which are already required for
``codesign``). At runtime it locates the bundle relative to itself — so the
``.app`` stays fully relocatable — points the bundled CPython at its own home +
the app's ``lib``/``app`` directories, and ``execv``s the entry-point module.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from . import AppBundleError

# The launcher is intentionally minimal: resolve its own path, derive the bundle
# layout, set the Python environment, and exec the interpreter on the entry
# script. ``{entry}`` is filled with the (identifier-only) entry-point name.
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
    char py[PATH_MAX], script[PATH_MAX], pypath[2 * PATH_MAX];
    snprintf(home, sizeof(home), "%s/Resources/python", contents);
    snprintf(app, sizeof(app), "%s/Resources/app", contents);
    snprintf(lib, sizeof(lib), "%s/Resources/lib", contents);
    snprintf(bin, sizeof(bin), "%s/Resources/bin", contents);
    snprintf(py, sizeof(py), "%s/bin/python3", home);
    snprintf(script, sizeof(script), "%s/%s.py", app, ENTRY);
    snprintf(pypath, sizeof(pypath), "%s:%s", app, lib);

    setenv("PYTHONHOME", home, 1);
    setenv("PYTHONPATH", pypath, 1);
    /* Isolate from ~/.local and user site config; the bundle is self-contained. */
    setenv("PYTHONNOUSERSITE", "1", 1);
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

    char **child = (char **)malloc(sizeof(char *) * (argc + 2));
    if (child == NULL) return 71;
    child[0] = py;
    child[1] = script;
    for (int i = 1; i < argc; i++) child[i + 1] = argv[i];
    child[argc + 1] = NULL;
    execv(py, child);
    perror("kivyforge launcher: execv");
    return 71;
}}
"""


def render_launcher_source(entry_point: str) -> str:
    """The C source for a launcher that execs *entry_point*.py (pure/testable)."""
    if not entry_point.isidentifier():
        raise AppBundleError(f"entry_point {entry_point!r} is not a valid module name.")
    return _SOURCE.format(entry=entry_point)


def build_launcher(dest: Path, *, entry_point: str, archs: tuple[str, ...]) -> None:
    """Compile the launcher for *archs* to *dest* (universal2 when >1 arch)."""
    if not archs:
        raise AppBundleError("build_launcher requires at least one arch")
    dest.parent.mkdir(parents=True, exist_ok=True)
    source = render_launcher_source(entry_point)
    with tempfile.TemporaryDirectory(prefix="kivy-launcher-") as tmp:
        src = Path(tmp) / "launcher.c"
        src.write_text(source, encoding="utf-8")
        cmd = ["clang", "-O2", "-Wall"]
        for arch in archs:
            cmd += ["-arch", arch]
        cmd += ["-o", str(dest), str(src)]
        _compile(cmd)
    dest.chmod(0o755)


def _compile(cmd: list[str]) -> None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise AppBundleError(
            "clang not found; the launcher needs the Xcode command-line tools.\n"
            "  Install them with: xcode-select --install"
        ) from exc
    if proc.returncode != 0:
        raise AppBundleError(
            f"failed to compile the app launcher: "
            f"{(proc.stderr or proc.stdout).strip()}"
        )

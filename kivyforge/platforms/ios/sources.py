"""Render the fixed source files and the per-project ``main_config.h`` (spec 06).

Generated source layout in <app>-ios/:
  main.m                  — trivial entry point; calls kivyforge_main()
  kivyforge_bootstrap.h    — bootstrap public header
  kivyforge_bootstrap.m    — dual-mode bootstrap (SDL3 for Kivy, UIKit for pure-Python)
  main_config.h           — per-project defines (entry point, py version)
  kivyforge_native_modules.h — inittab for package-contributed native modules

Mobile window/display geometry (DPI, scale, safe area, keyboard height) is no
longer vendored here — it ships in Kivy core as ``kivy.mobile`` (kivy/kivy#9331).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from kivyforge.config.model import Config

_TEMPLATES = Path(__file__).parent / "templates"

# Files that are copied verbatim from templates/ into the generated project.
_BOOTSTRAP_FILES = ("kivyforge_bootstrap.h", "kivyforge_bootstrap.m")


@dataclass(frozen=True)
class NativeModule:
    """A Python extension module a package implements natively.

    ``name`` is what Python imports; ``init`` is the C init symbol, which
    defaults to ``PyInit_<name>`` but need not match — a Swift package named
    ``PyWebViews`` may implement a module whose Swift type is ``WebViews`` and
    whose Python name is ``web_views``.
    """

    name: str
    init: str


def main_m_source() -> str:
    return (_TEMPLATES / "main.m").read_text(encoding="utf-8")


def render_main_config_h(config: Config, *, python_version: str | None = None) -> str:
    """Fill the main_config.h template with APP_DIR / ENTRY_POINT / py version.

    ``app/`` is the symlink name inside ``<app>-ios/`` (always ``app``), so
    APP_DIR is the bundle-relative folder name, not the user's ``app_dir`` path.
    """
    version = (
        python_version
        or (config.ios.python_version if config.ios else None)
        or "3.15.0"
    )
    major_minor = ".".join(version.split(".")[:2])
    template = (_TEMPLATES / "main_config.h.in").read_text(encoding="utf-8")
    return (
        template.replace("@APP_DIR@", "app")
        .replace("@ENTRY_POINT@", config.kivy.entry_point)
        .replace("@PYTHON_MAJOR_MINOR@", major_minor)
    )


def render_native_modules_h(modules: Sequence[NativeModule] = ()) -> str:
    """Fill the inittab template with package-contributed native modules.

    ``modules`` comes from ``[[ios.contributes.python_modules]]`` declarations
    once the sidecar reader lands (native-integration SPEC.md §7.7). Until then
    it is always empty, and the generated table holds only its terminator — the
    seam exists so the bootstrap has somewhere to dispatch from, not because
    anything fills it yet.
    """
    externs = "\n".join(f"extern PyObject *{m.init}(void);" for m in modules)
    entries = "".join(f'    {{"{m.name}", {m.init}}},\n' for m in modules)
    template = (_TEMPLATES / "kivyforge_native_modules.h.in").read_text(
        encoding="utf-8"
    )
    return template.replace("@NATIVE_MODULE_EXTERNS@", externs).replace(
        "@NATIVE_MODULE_ENTRIES@", entries
    )


def write_sources(
    config: Config,
    project_dir: str | Path,
    *,
    python_version: str | None = None,
    native_modules: Sequence[NativeModule] = (),
) -> tuple[Path, Path]:
    project_dir = Path(project_dir)
    main_m = project_dir / "main.m"
    main_h = project_dir / "main_config.h"
    main_m.write_text(main_m_source(), encoding="utf-8")
    main_h.write_text(
        render_main_config_h(config, python_version=python_version), encoding="utf-8"
    )
    (project_dir / "kivyforge_native_modules.h").write_text(
        render_native_modules_h(native_modules), encoding="utf-8"
    )
    for fname in _BOOTSTRAP_FILES:
        (project_dir / fname).write_text(
            (_TEMPLATES / fname).read_text(encoding="utf-8"), encoding="utf-8"
        )
    return main_m, main_h

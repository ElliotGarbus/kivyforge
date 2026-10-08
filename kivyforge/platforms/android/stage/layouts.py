"""Recognise wheel layouts kivyforge does not stage (android/03 §"Wheel layouts").

Chaquopy's convention, which BeeWare's mobile-forge and Flet's index follow,
ships each native library as its own wheel: ``opt/lib/*.so`` with headers in
``opt/include/`` and often static ``*.a`` archives, pinned by the wrapper's
``Requires-Dist``. Its runtime knows to load from ``opt/lib``; kivyforge's does
not, and staging the files would rename each library to an extension-module
name the linker never asks for. So the build stops and names the layout.

Only that exact signature matches. An ``opt`` that is a Python package, or
that holds no libraries or headers, is left alone.
"""

from __future__ import annotations

import re
from pathlib import Path

from .conflicts import installers

_SHARED_OBJECT = re.compile(r"\.so(\.\d+)*$")


def separate_library_wheels(site_packages: Path) -> list[str] | None:
    """The distributions that installed a Chaquopy-style ``opt/``, if any.

    ``None`` when the layout is absent. A layout no RECORD claims is reported
    as ``["opt"]``, so it is never missed for want of a name.
    """
    opt = site_packages / "opt"
    if not opt.is_dir() or (opt / "__init__.py").exists():
        return None
    lib = opt / "lib"
    has_libraries = lib.is_dir() and any(
        _SHARED_OBJECT.search(p.name) for p in lib.iterdir() if p.is_file()
    )
    if not has_libraries and not (opt / "include").is_dir():
        return None
    return installers(site_packages, "opt") or ["opt"]

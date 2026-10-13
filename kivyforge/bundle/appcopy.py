"""What every backend leaves out when it copies ``[tool.kivy].app_dir``.

Each backend keeps its own ignore list for build debris (``__pycache__``,
``*.pyc``, ``.DS_Store``), and those differ on purpose. This module holds the
part that must not differ.

``*.egg-info`` is setuptools' install metadata. ``pip install .`` and
``pip install -e .`` write it into the project's package root, which in a src
layout is ``src/``, the directory many projects name as ``app_dir``. Copied
into an app, it describes the developer's checkout rather than the app (the
version it records is whatever was installed last, and its ``SOURCES.txt``
lists host paths), and it lets ``importlib.metadata`` find a distribution that
was never installed in the app. Nothing in the app needs it.
"""

from __future__ import annotations

#: ``shutil.ignore_patterns`` globs excluded from every app_dir copy.
APP_COPY_EXCLUDES: tuple[str, ...] = ("*.egg-info",)

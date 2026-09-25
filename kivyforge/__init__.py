"""kivyforge: build, run, and package Kivy apps for Android, iOS, macOS,
Windows, and Linux.

kivyforge 3.0 reads a user-authored ``pyproject.toml`` (PEP 621 ``[project]``
plus ``[tool.kivy]`` and one ``[tool.kivy.<platform>]`` overlay per target),
resolves a PEP 751 ``pylock.<platform>.toml`` build manifest, and materializes
it into that platform's project or bundle. See ``docs/design`` for the full
specification.
"""

__version__ = "3.0.0.dev0"

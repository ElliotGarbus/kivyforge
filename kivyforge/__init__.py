"""kivyforge: build, run, and package Kivy apps for Android, iOS, macOS,
Windows, and Linux.

kivyforge reads a user-authored ``pyproject.toml`` (PEP 621 ``[project]``
plus ``[tool.kivy]`` and one ``[tool.kivy.<platform>]`` overlay per target),
resolves a PEP 751 ``pylock.<platform>.toml`` build manifest, and materializes
it into that platform's project or bundle. See ``docs/design`` for the full
specification.
"""

from importlib.metadata import PackageNotFoundError, version

# The version comes from git tags at build time (setuptools-scm), so the only
# place it exists is the installed distribution's metadata. A tree imported
# without being installed has none; "0+unknown" is still a valid PEP 440
# version, so nothing that parses it breaks.
try:
    __version__ = version("kivyforge")
except PackageNotFoundError:  # pragma: no cover - only outside an install
    __version__ = "0+unknown"

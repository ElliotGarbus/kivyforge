"""Vendored prebuilt Windows binaries (windows-spec).

Contains the compiled onedir launcher (``launcher-amd64.exe``, built from the
in-repo C source by ``launcher/build_launcher.py``) and ``rcedit-x64.exe`` (the
resource-patch tool, re-fetched/verified by ``fetch_rcedit.py``). Both are
SHA-256-pinned in ``SHA256SUMS``; see ``LICENSE.rcedit`` and ``NOTICE`` for
provenance.
"""

# arm64: add a second vendored launcher (launcher-arm64.exe) + its SHA256SUMS
# entry + a pyproject package-data glob. rcedit-x64.exe is reused (emulated on
# Arm64 Windows; it only edits PE resources). See arm64-windows.md §5, §10.

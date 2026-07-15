"""Vendored prebuilt Windows binaries (windows-spec).

Contains the compiled onedir launcher (``launcher-amd64.exe``, built from the
in-repo C source by ``launcher/build_launcher.py``) and ``rcedit-x64.exe`` (the
resource-patch tool, re-fetched/verified by ``fetch_rcedit.py``). Both are
SHA-256-pinned in ``SHA256SUMS``; see ``LICENSE.rcedit`` and ``NOTICE`` for
provenance.
"""

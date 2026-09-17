"""A ``run_command`` stand-in that leaves behind what a successful xcodebuild would.

``build`` announces a product only after checking it exists, so a fake that just
returns exit 0 now fails the way a real xcodebuild that wrote nothing would.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def _arg(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def fake_xcodebuild(argv, *args, **kwargs):
    if "-derivedDataPath" in argv:
        products = Path(_arg(argv, "-derivedDataPath")) / "Build" / "Products"
        folder = f"{_arg(argv, '-configuration')}-{_arg(argv, '-sdk')}"
        (products / folder / f"{_arg(argv, '-scheme')}.app").mkdir(
            parents=True, exist_ok=True
        )
    if "-exportArchive" in argv:
        export = Path(_arg(argv, "-exportPath"))
        export.mkdir(parents=True, exist_ok=True)
        (export / f"{Path(_arg(argv, '-archivePath')).stem}.ipa").write_bytes(b"PK")
    return SimpleNamespace(returncode=0, stdout="", stderr="")

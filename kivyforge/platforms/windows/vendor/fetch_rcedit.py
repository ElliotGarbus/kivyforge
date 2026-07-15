"""Fetch + verify the vendored ``rcedit-x64.exe`` against its pinned SHA-256.

rcedit is a third-party prebuilt tool (electron/rcedit, MIT). Rather than trust
whatever is on disk, this script downloads the pinned release and verifies its
SHA-256 against ``SHA256SUMS`` before writing it, so refreshing the vendored
binary is reproducible and tamper-evident. Run it when bumping the pinned
version (update ``RCEDIT_VERSION`` + the manifest hash together).

    python -m kivyforge.platforms.windows.vendor.fetch_rcedit          # fetch+verify
    python -m kivyforge.platforms.windows.vendor.fetch_rcedit --check  # verify only
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
RCEDIT_NAME = "rcedit-x64.exe"
RCEDIT_PATH = HERE / RCEDIT_NAME
MANIFEST = HERE / "SHA256SUMS"

RCEDIT_VERSION = "2.0.0"
RCEDIT_URL = (
    f"https://github.com/electron/rcedit/releases/download/v{RCEDIT_VERSION}/"
    f"{RCEDIT_NAME}"
)


class RceditFetchError(Exception):
    """rcedit could not be fetched or failed its SHA-256 verification."""


def pinned_sha256() -> str:
    if not MANIFEST.is_file():
        raise RceditFetchError(f"manifest missing: {MANIFEST}")
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition("  ")
        if name.strip() == RCEDIT_NAME:
            return digest.strip()
    raise RceditFetchError(f"{RCEDIT_NAME} has no pinned SHA-256 in {MANIFEST}.")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_only() -> int:
    if not RCEDIT_PATH.is_file():
        raise RceditFetchError(f"{RCEDIT_PATH} is missing; run without --check.")
    actual = _sha256(RCEDIT_PATH.read_bytes())
    expected = pinned_sha256()
    if actual != expected:
        raise RceditFetchError(
            f"{RCEDIT_NAME} SHA-256 {actual} does not match the pin {expected}."
        )
    print(f"verified {RCEDIT_PATH} ({actual})")
    return 0


def fetch() -> int:
    expected = pinned_sha256()
    with urllib.request.urlopen(RCEDIT_URL, timeout=60) as resp:  # noqa: S310
        data = resp.read()
    actual = _sha256(data)
    if actual != expected:
        raise RceditFetchError(
            f"downloaded {RCEDIT_NAME} SHA-256 {actual} does not match the pin "
            f"{expected}; refusing to write. (Bump RCEDIT_VERSION + the manifest "
            "together to update.)"
        )
    RCEDIT_PATH.write_bytes(data)
    print(f"fetched {RCEDIT_PATH} ({actual})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="verify the on-disk binary only."
    )
    args = parser.parse_args(argv)
    try:
        return verify_only() if args.check else fetch()
    except (RceditFetchError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

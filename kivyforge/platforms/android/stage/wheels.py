"""Install locked wheels per ABI (android/06 build step 4).

The lock holds the full transitive set with URLs/hashes, so installation is
``pip install --no-deps --target`` on the **verified local wheel files** — pip
never re-resolves and never touches an index. Wheel selection per ABI applies
the tag-floor rule (an ``android_<api>_<abi>`` wheel with ``api <= min_sdk``;
highest compatible api wins) plus the shared ``py3-none-any`` entries.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from kivyforge.lock.model import LockedPackage, LockedWheel


class WheelStageError(Exception):
    pass


def select_wheel(package: LockedPackage, *, abi: str, min_sdk: int) -> LockedWheel:
    """Pick the wheel slice this ABI installs (android/01 §tag floor)."""
    best: tuple[int, LockedWheel] | None = None
    for wheel in package.wheels:
        if wheel.is_pure_python:
            if best is None:
                best = (-1, wheel)
            continue
        tag = wheel.platform_tag
        parts = tag.split("_", 2)
        if parts[0] != "android" or len(parts) != 3 or parts[2] != abi:
            continue
        try:
            api = int(parts[1])
        except ValueError:
            continue
        if api <= min_sdk and (best is None or api > best[0]):
            best = (api, wheel)
    if best is None:
        raise WheelStageError(
            f"{package.name} {package.version} has no wheel for ABI {abi!r} "
            f"(min_sdk {min_sdk}) in the lock — re-run `kivyforge lock`."
        )
    return best[1]


def install_wheels(
    wheel_files: list[Path],
    target: Path,
    *,
    python_version: str,
    python_executable: str | None = None,
) -> None:
    """``pip install --no-deps --target`` the verified wheel files.

    Cross-install: the host interpreter rarely matches the target's version or
    platform, so the target environment is described explicitly — the platform
    tags are taken from the selected wheel files themselves (exact match by
    construction), the version/ABI from the locked target Python.
    """
    if not wheel_files:
        target.mkdir(parents=True, exist_ok=True)
        return
    from kivyforge.lock.resolver import abi_tags, pip_python_version

    platforms: list[str] = []
    for wheel in wheel_files:
        stem = wheel.name[:-4] if wheel.name.endswith(".whl") else wheel.name
        tag = stem.rsplit("-", 1)[-1]
        if tag != "any" and tag not in platforms:
            platforms.append(tag)

    cmd = [
        python_executable or sys.executable,
        "-m",
        "pip",
        "install",
        "--no-deps",
        "--no-index",
        "--only-binary=:all:",
        "--python-version",
        pip_python_version(python_version),
        "--implementation",
        "cp",
        "--target",
        str(target),
        "--quiet",
    ]
    for platform_tag in platforms:
        cmd += ["--platform", platform_tag]
    for abi in abi_tags(python_version):
        cmd += ["--abi", abi]
    cmd += [str(w) for w in wheel_files]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise WheelStageError(
            "pip could not install the locked wheels into the staging "
            f"directory.\n  pip said:\n{_indent(proc.stderr or proc.stdout)}"
        )


def _indent(text: str) -> str:
    return "\n".join(f"    {line}" for line in (text or "").splitlines())

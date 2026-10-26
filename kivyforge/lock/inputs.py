"""What a platform's lock is derived from, and the hash that detects drift.

A lock is stale only when something it records could have changed: its lock
inputs. Each platform names them here as config paths (``LOCK_INPUTS``), and a
lock stores ``lock_inputs_sha256``, the SHA-256 of their parsed values. Fields
outside the projection (signing, icons, the display name, another platform's
overlay) are read from ``pyproject.toml`` on every build, so editing them never
stales a lock (docs/design/dev/lock-inputs-proposal.md).

``tests/lock/test_lock_inputs.py`` runs every lock builder on a config that
records what it reads, and fails if a read path is missing here: a forgotten
input would ship a stale dependency graph without an error.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Protocol

from ..config.model import Config

#: Bump when the projection's *encoding* changes, so every lock reads stale.
#: Adding or removing a path changes the hash on its own.
SCHEME = 1

_PROJECT = ("project.dependencies", "project.requires_python")
_INDEXES = ("extra_index_urls", "find_links", "exclude", "indexes", "sources")


def _overlay(platform: str, *fields: str) -> tuple[str, ...]:
    return tuple(f"{platform}.{name}" for name in ("schema_version", *fields))


LOCK_INPUTS: dict[str, tuple[str, ...]] = {
    "macos": _PROJECT
    + _overlay(
        "macos",
        "python_version",
        "archs",
        "minimum_system_version",
        *_INDEXES,
        "binaries",
        "include_files",
    ),
    "linux": _PROJECT
    + _overlay(
        "linux", "python_version", "archs", "glibc_floor", *_INDEXES, "binaries"
    ),
    "windows": _PROJECT
    + _overlay("windows", "python_version", "archs", *_INDEXES, "binaries"),
    "android": _PROJECT
    + _overlay(
        "android",
        "python",
        "abis",
        "min_sdk",
        "kivy_generation",
        *_INDEXES,
        "aars",
        "jars",
        "gradle",
        "include_files",
    ),
    "ios": _PROJECT
    + _overlay(
        "ios",
        "python_version",
        "deployment_target",
        "simulator_archs",
        *_INDEXES,
        "xcframeworks",
        "swift_packages",
        "include_files",
    ),
}


class _HasInputsSha(Protocol):
    # Read-only, so frozen dataclass locks satisfy it.
    @property
    def lock_inputs_sha256(self) -> str: ...


def lock_inputs(config: Config, platform: str) -> dict[str, object]:
    """Each lock input's path mapped to its value, as plain JSON data."""
    return {path: _plain(_lookup(config, path)) for path in LOCK_INPUTS[platform]}


def lock_inputs_sha256(config: Config, platform: str) -> str:
    document = {"scheme": SCHEME, "inputs": lock_inputs(config, platform)}
    text = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_in_sync(lock: _HasInputsSha, config: Config, platform: str) -> bool:
    """True if the lock was written from the inputs ``config`` has now.

    A lock written before lock inputs were hashed has an empty
    ``lock_inputs_sha256``, so it reads as stale.
    """
    return lock.lock_inputs_sha256 == lock_inputs_sha256(config, platform)


def _lookup(config: Config, path: str) -> object:
    value: object = config
    for name in path.split("."):
        if value is None:
            return None
        value = getattr(value, name)
    return value


def _plain(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value

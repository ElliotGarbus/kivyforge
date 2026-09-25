---
title: Lockfiles
sources:
  - docs/design/common/03-lockfile-concept.md
  - docs/design/platforms/android/02-pylock-android-spec.md
  - docs/design/platforms/ios/02-pylock-ios-spec.md
  - kivyforge/lock/reader.py
  - kivyforge/cli/lock.py
---

# Lockfiles

A lockfile records the exact set of artifacts a build consumes, pinned so the
build is reproducible. kivyforge writes one lockfile per target.

## One lockfile per platform

`kivyforge lock` resolves your dependencies for a single target and writes
`pylock.<platform>.toml` next to `pyproject.toml`:

- `pylock.ios.toml`
- `pylock.android.toml`
- `pylock.macos.toml`
- `pylock.linux.toml`
- `pylock.windows.toml`

The filename identifies the platform; no field inside the file does. Each
lockfile is a [PEP 751](https://peps.python.org/pep-0751/) document: its
standard `[[packages]]` section follows the PEP 751 format. kivyforge's own
build-specific pins, such as the Python runtime and native artifacts, live in a
single `[tool.kivyforge]` extension table.

## What a lock pins

Every artifact is pinned by URL and SHA-256, so a later build fetches
byte-for-byte the same file or fails. A lock records:

- the resolved Python wheels for the target's platform tags;
- the prebuilt Python runtime for the target;
- any native artifacts, such as iOS xcframeworks, Android `.aar` and `.jar`
  libraries, and the Android runtime for each ABI.

## Drift: when to re-lock

A lock records a SHA-256 hash of the `pyproject.toml` it was resolved from. Any
edit to `pyproject.toml`, even to a comment or a signing setting, makes the lock
out of date. kivyforge calls this **drift**.

- Re-lock with `kivyforge lock -p PLATFORM`, replacing `PLATFORM` with the
  target name. If the lock is already in sync, `lock` leaves it unchanged; add
  `--update` to re-resolve anyway.
- `build`, `run`, and `package` refuse to use a drifted lock. They exit with
  code 4 and `KF-LOCK-DRIFT` (or `KF-LOCK-MISSING` when there is no lock),
  rather than building something stale.
- In CI, run `kivyforge lock --check` as a pre-flight. It re-resolves, writes
  nothing, and exits with code 4 if the result differs from the lock on disk.

See [Manage dependencies and re-lock](../guides/cross-platform/dependencies.md)
for the workflow.

## Committing locks

Whether to commit a lockfile is your choice. Committing it makes CI builds
reproducible and makes `lock --check` meaningful. Most kivyforge examples do not
commit their locks, because the lock can be regenerated. A few on-device test
examples commit theirs deliberately.

## What's next

- [Manage dependencies and re-lock](../guides/cross-platform/dependencies.md).
- [Lockfile format](../reference/lockfile.md) reference.
- [Prebuilt runtimes and wheels](runtimes-and-wheels.md).

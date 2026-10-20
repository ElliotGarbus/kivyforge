# Proposal — re-lock only when lock inputs change, and keep existing pins

> Status: **implemented 2026-10-18** for
> [#126](https://github.com/ElliotGarbus/kivyforge/issues/126). Supersedes the
> whole-file `pyproject_sha256` drift check described in
> [`03-lockfile-concept.md`](../common/03-lockfile-concept.md).

## 1. Problem

Every lock recorded the SHA-256 of the whole `pyproject.toml`. Any edit made
every platform's lock stale: a comment, a signing block, a display name,
another platform's overlay. The repair, `kivyforge lock`, resolved from
scratch to the newest version each specifier allowed, so one unrelated edit
upgraded Kivy, pyjnius and every unpinned transitive dependency at once
([#107](https://github.com/ElliotGarbus/kivyforge/issues/107)).

## 2. Decisions

### 2.1 Hash the lock inputs, not the file

Each platform declares, in `kivyforge/lock/inputs.py`, the config paths its
lock is derived from: `LOCK_INPUTS[platform]`. The lock records
`lock_inputs_sha256`, the SHA-256 of a canonical JSON object mapping each path
to its parsed value. Comments, key order, whitespace and every field outside
the projection do not count.

| Platform | Inputs beyond `project.dependencies` and `project.requires_python` |
|---|---|
| macOS | `schema_version`, `python_version`, `archs`, `minimum_system_version`, `extra_index_urls`, `find_links`, `exclude`, `binaries` |
| Linux | `schema_version`, `python_version`, `archs`, `glibc_floor`, `extra_index_urls`, `find_links`, `exclude`, `binaries` |
| Windows | `schema_version`, `python_version`, `archs`, `extra_index_urls`, `find_links`, `exclude`, `binaries` |
| Android | `schema_version`, `python`, `abis`, `min_sdk`, `kivy_generation`, `extra_index_urls`, `find_links`, `exclude`, `aars`, `jars`, `gradle`, `include_files` |
| iOS | `schema_version`, `python_version`, `deployment_target`, `simulator_archs`, `extra_index_urls`, `find_links`, `exclude`, `xcframeworks`, `swift_packages` |

Everything else (signing, display name, icons, splash, permissions, manifest,
services, `entry_point`, `app_dir`, orientation, `[project].version`, other
project metadata, and every other platform's overlay) is read from
`pyproject.toml` by `build` on every run, so editing it never stales a lock.

**The projection is checked against the builders.** A forgotten field would
ship a stale graph with no error, which is the failure this hash exists to
prevent. `tests/lock/test_lock_inputs.py` runs each platform's real lock
builder (with its fake resolvers) on a config wrapped in a proxy that records
every leaf attribute read, properties included, and fails if a recorded path
is not covered by `LOCK_INPUTS[platform]`.

Files a lock hashes by content (`include_files`, vendored wheels) are outside
the projection, as they were outside the old hash: editing one still needs
`lock --update`.

### 2.2 Keep existing pins

When a lock exists and `--update` is not given, `lock` resolves with the
existing lock as a preference. Each locked package is passed to pip as a
`name==version` constraint (`-c`), so nothing moves that does not have to.

- **A direct requirement whose specifier now excludes its locked version**
  (for example `kivy>=2.4` with 2.3.1 locked) loses its pin before resolving,
  so the package the user asked to move moves, and the rest stay.
- **If the constrained resolve still fails**, it is retried without
  preferences. If that succeeds, the old pins were the conflict: `lock` fails
  with `KF-LOCK-PINS-CONFLICT`, quotes pip, and points at `--update`. If the
  retry fails too, the error is pip's own, as before. The exit status is `1`,
  not `4`: `4` tells an agent to re-lock, and a plain re-lock would fail the
  same way.
- `--update` resolves to newest, as before. Exact `==` pins in
  `pyproject.toml` still forbid movement entirely.

The preference covers pip packages and, for macOS, Linux and Windows, the
python-build-standalone runtime: a re-lock or `--check` keeps the locked
runtime while its CPython version, provider, provider floor and per-arch
artifacts still match, which skips a GitHub API lookup that pages through
releases (20 to 30 s on Windows, 2026-10-20). `--update` looks it up again.
The Android and iOS runtimes, and Gradle, Swift package and xcframework pins,
are re-resolved as before.

`lock --check` builds its candidate with the same preference, so a new upstream
release no longer fails CI while `pyproject.toml` is unchanged.

### 2.3 Migration: none in code

An existing lock has no `lock_inputs_sha256`, so it reads as stale, with the
usual message. The `CHANGELOG.md` migration note says to run `kivyforge lock`
once per platform, and that the re-lock keeps the versions already pinned.
Supporting both schemes would be code carried forever for a handful of beta
testers.

The tracked locks in this repository were re-locked in the same change, with
the preference: each diff is the hash and `generated_at` only, which is also
the first real check that the pins hold. The Linux and macOS gate fixtures were
locked from WSL2, because a desktop lock for those targets cannot be resolved
from a Windows host (pip evaluates Kivy's `sys_platform == "win32"` markers for
the host; a separate, older bug). `examples/mobile/hello-kivy/pylock.ios.toml`
needs Xcode to re-lock, so its one changed line was written from
`lock_inputs_sha256()` and checked with `is_in_sync()`; `lock --check -p ios` on
a Mac confirms it.

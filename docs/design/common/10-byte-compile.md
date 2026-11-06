# 10 — Byte-compiling: which interpreter writes the `.pyc`

Every backend can ship its Python payload as `.pyc`. The mechanics are shared
(`kivyforge/bundle/pycompile.py`); what differs per platform is which trees are
compiled, which the platform specs list. This page is the one description of
how the compiler is chosen. The platform specs link here rather than repeating
it, so a change to the search updates this page alone.

## The settings

Each platform has `byte_compile` and `strip_source` in its `build_settings`
table: `[tool.kivy.ios.python.build_settings]`,
`[tool.kivy.android.build_settings]`, and `[tool.kivy.<macos|linux|windows>.build_settings]`.
Each is `"release"` (the default: release builds only, as each platform defines
them) or an explicit `true` / `false`. `strip_source` is ignored while
`byte_compile` is off, because stripping sources with no `.pyc` beside them
would ship a payload that imports nothing.

The two spellings of "on" mean different things, and the difference decides
what happens when no interpreter is found (below):

- `"release"` means *when it makes sense*. A build nobody configured is never
  broken by the absence of an interpreter nobody asked for.
- `true` means *I insist*. Silently shipping source would leave the user
  believing the payload was compiled.

## What a compiler must be

A `.pyc` loads only in the CPython whose magic number wrote it. The magic number
is fixed per **minor version** from the first release candidate on, and does
not depend on architecture or OS. So a compiler must be:

- **the same minor** as the runtime the platform ships, read from that
  platform's lock (any patch release will do: a host 3.15.0 compiles for a
  shipped 3.15.2);
- **a final release** (`sys.version_info.releaselevel == "final"`). Alphas and
  betas change the magic number, so their output fails to import once
  `strip_source` has removed the source. Release candidates are excluded too:
  the freeze makes them safe in principle, but the margin isn't worth it when
  the fallback is shipping readable source.

## Which interpreter compiles

There are two cases, and they never mix.

**Desktop builds whose staged runtime runs here** compile with it: the bundle
ships an interpreter, the lock pins it, and when target arch == host arch it
compiles its own payload (kivyforge never depends on emulation). That is every
macOS build (arm64 only), every Windows build (amd64 only), and a Linux
`x86_64` build on an x86_64 host.

**iOS, Android, and a Linux `aarch64` target built on x86_64** can't run what
they ship (`Python.xcframework` is a library; Android's runtime is built for the
device; an aarch64 binary doesn't run on x86_64). They compile with **the host
CPython the lock pins for this machine, and nothing else**: not kivyforge's own
interpreter, not `python3.15` on `PATH`, not a uv-managed one. Every machine
building a given lock compiles with the same build
(`host-python-download-proposal.md`, Q5).

## The pinned host CPython

`lock` pins one python-build-standalone (PBS) build per host that can build the
platform, as `[[tool.kivyforge.host_python]]` (`kivyforge/lock/host_python.py`):

| Platform | Hosts pinned |
|---|---|
| iOS | `aarch64-apple-darwin` |
| Android | `aarch64-apple-darwin`, `x86_64-unknown-linux-gnu`, `x86_64-pc-windows-msvc` |
| Linux, `archs` including `aarch64` | `x86_64-unknown-linux-gnu` |

- **One version for every host** of a platform: the version the lock ships if
  PBS has it for all of them, otherwise the newest final release they all
  have. Never a pre-release.
- **The stripped variant** (`install_only_stripped`) where PBS publishes it,
  otherwise `install_only`, recorded as `variant`. For 3.15.0 stripped is
  36 MB against 79 MB on Linux and 23 MB against 50 MB on Windows (measured
  2026-11-06); it compiles identically.
- **Each entry has a state**, so a missing table can only mean a lock written
  before it existed: `pinned` (with `version`, `variant`, `url`, `sha256`),
  `no-build` (PBS had no final build of the minor for the host), or
  `unresolved-offline` (`lock --offline` had no pin to keep).
- **Keeping pins.** `lock` and `lock --check` keep every pinned entry while the
  minor still matches, and skip the GitHub lookup; `lock --update` re-pins.
  A plain `lock` completes a lock written before the table, keeping every
  other pin. `lock --check` reports a missing table, or an
  `unresolved-offline` entry, as `KF-LOCK-INCOMPLETE` (exit 4); a `no-build`
  entry passes with a warning.

`build` (`kivyforge/bundle/hostpython.py`) turns this host's entry into an
interpreter. The archive is a pinned artifact in the artifact cache, verified
against the lock's SHA-256. The install is that archive extracted to
`<cache>/host-python/<sha256>/`, complete only once its `.kivyforge-complete`
marker exists, written after the interpreter answered a probe for the pinned
minor and a final release. An install without the marker, or whose interpreter
no longer runs, is extracted again. A per-pin file lock keeps parallel builds
sharing a cache from installing the same build at once. `clean --cache`
removes archives and installs alike, and `kivyforge upgrade` fetches the
archive ahead of time.

Two environment variables, for the machine rather than the project, and for
this interpreter only:

- **`KIVYFORGE_HOST_PYTHON_DOWNLOADS`**: `automatic` (default) or `never`. With
  `never`, a build uses the install, or extracts a cached archive, and never
  reaches the network for it. `--no-cache` with `never` is exit 1.
- **`KIVYFORGE_HOST_PYTHON_MIRROR`**: replaces
  `https://github.com/astral-sh/python-build-standalone/releases/download` in
  a pinned URL; the pinned SHA-256 still verifies what it serves. It serves
  builds from an existing lock only: `lock` still reads the release list from
  GitHub.

**What is guaranteed:** every machine building a given lock compiles with the
same pinned CPython build, and the `.pyc` load in the shipped runtime. Not
byte-for-byte identical `.pyc` across hosts: on Windows the source path recorded
in each code object keeps backslashes.

## When there's no compiler

| Case | `"release"` | `true` | Code |
|---|---|---|---|
| No table for this host (an older lock), or `unresolved-offline` | ships source, warns | exit 4 | `KF-LOCK-INCOMPLETE` |
| `no-build` | ships source, warns | exit 3 | `KF-BYTECOMPILE-NO-INTERP` |
| Downloads off and nothing cached | ships source, warns | exit 3 | `KF-BYTECOMPILE-NO-INTERP` |
| A failed download or a SHA-256 mismatch, or another build holding the install lock | ships source, warns | exit 3 | `KF-HOST-PYTHON-FETCH` |
| The extracted interpreter won't run as the pinned minor | ships source, warns | exit 3 | `KF-BYTECOMPILE-NO-INTERP` |
| Disk or permission failure writing the cache | exit 1 | exit 1 | `KF-ERROR` (`os_failure()`) |

Every message names the case and its fix (`hostpython.compiler_for`, one
wording for every call site); `hostpython.pinned_compiler` applies the
setting's policy, so the four call sites can't drift. For example:

```
Error: [tool.kivy.ios.python.build_settings].byte_compile = true, but pylock.ios.toml has no host CPython to compile with (it predates the host CPython pin).
  Fix: run `kivyforge lock -p ios`; it adds the host CPython and keeps every other pin. Or set byte_compile = false.
```

`doctor` reads the same entry and never downloads or extracts: PASS when it's
installed, when its archive is cached ("extracted on the first release build"),
or when downloads are on ("downloaded on the first release build"); FAIL
(`true`) or WARN (`"release"`) for downloads off with nothing cached, `no-build`,
and a missing or unresolved entry.

### The desktop search, for a missing staged runtime

A desktop build whose staged interpreter is missing falls back to
`find_interpreter()`: kivyforge's own interpreter, `py -3.X` (Windows),
`python3.X` / `python3` / `python` on `PATH`, then `uv python find
--no-project --no-python-downloads 3.X` when uv is installed. Each candidate
must report the target minor and a final release. With none, the message lists
what it looked at (`pycompile.no_interpreter()`), and `doctor`'s
`check_byte_compile` does the same.

## What is written

Fixed for every platform (`pycompile.py`'s module docstring has the reasons):

- **Hash-based, unchecked invalidation** (PEP 552), so importing doesn't `stat`
  the source, and no mtime goes into a `.pyc`.
- **Payload-relative paths**, so no host path leaks into the artifact and
  identical inputs give identical output on any machine of the same OS (on
  Windows the relative path keeps backslashes).
- **Optimization level 0.**
- **Layout.** Keeping sources, `.pyc` go in `__pycache__/`. Stripping sources,
  they go beside where the `.py` was (the legacy layout), because sourceless
  imports never look in `__pycache__/`.

## Code

- `kivyforge/lock/host_python.py`: the table, its states, which hosts each
  platform pins, resolution, completeness.
- `kivyforge/lock/wheelruntime/pbs_github.py::find_common_install_only`: the
  PBS lookup, one version across hosts, in one pass over the releases.
- `kivyforge/cli/lock.py`: pinning on a re-lock, completing an older lock, and
  `KF-LOCK-INCOMPLETE` from `lock --check`.
- `kivyforge/bundle/hostpython.py`: `compiler_for` and `pinned_compiler`, the
  archive, install, marker and file lock, and the two environment variables.
- The call sites, one per payload: `platforms/ios/staging.py` (app sources),
  `artifacts/collect.py` (iOS pip-deps), `platforms/android/cli.py`, and
  Linux's `bundle.py` for a foreign arch; macOS, Windows and native Linux use
  `pycompile.select_compiler`.
- `doctor/checks_common.py`: `check_host_python` and `check_byte_compile`.
- `kivyforge/cli/upgrade.py`: fetching the pin ahead of time.

The design and its decisions are in
[`host-python-download-proposal.md`](../dev/host-python-download-proposal.md).

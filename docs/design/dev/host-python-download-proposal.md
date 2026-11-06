# Proposal — pin the host Python that byte-compiles in the lock

> Status: **implemented 2026-11-06** on branch `host-python-lock`, not yet
> released. The hermetic tests in section 10 pass; the real-toolchain runs in
> section 10 and the re-lock of the tracked example locks (section 11) are not
> done yet. Every question in section 4 is decided, including the review's
> (4.2). This design replaces
> the `kivyforge bytecompiler` command of 2026-11-05, which was implemented on
> branch `bytecompiler`
> ([#213](https://github.com/ElliotGarbus/kivyforge/pull/213), not merged) and
> is now superseded (section 6). #213 is reworked in place to this design
> (Q15).
>
> Responds to [#209](https://github.com/ElliotGarbus/kivyforge/issues/209).
> Writing `.pyc` for iOS or Android needs a final CPython of the shipped minor
> *on the machine that builds*, and the reporter had none.
> [#212](https://github.com/ElliotGarbus/kivyforge/pull/212) made the error
> say what it searched. This proposal removes the need to search: `lock` pins
> one build of that CPython for each host that can build the target, and
> `build` fetches and uses it, as it already does for every other pinned
> artifact.

## 1. Problem

`byte_compile` writes the `.pyc` files with an interpreter that has to run on
the build machine. Desktop builds have one: the runtime they ship, which the
lock pins and which runs on the host. iOS and Android never do, because their
runtime is built for the device, and neither does a Linux `aarch64` target
built on x86_64. The `.pyc` format is fixed per CPython minor from the first
release candidate on, so any final `3.15.x` can compile for a shipped `3.15.2`,
but something has to provide it.

Today the user does. A developer who has never installed 3.15 on their Mac, or
a CI runner with only the system Python, gets a release that silently ships
source (`byte_compile = "release"`, with a `KF-BYTECOMPILE-NO-INTERP` warning)
or a failed build (`byte_compile = true`, exit 3). And when a 3.15 *is* found,
which one depends on the machine: kivyforge's own interpreter, `python3.15` on
`PATH`, a uv-managed one. Different machines compile the same app with
different builds of CPython.

## 2. What ships today (#212, `cad70344`)

[10 — byte-compiling](../common/10-byte-compile.md) describes it. For iOS,
Android and a Linux `aarch64` target, `bundle/pycompile.py::find_interpreter`
searches kivyforge's own interpreter, the `py` launcher (Windows), `python3.X`
/ `python3` / `python` on `PATH`, then `uv python find`, and takes the first
final release of the minor. With none, a shared message lists what it looked
at, and `byte_compile = true` fails with `KF-BYTECOMPILE-NO-INTERP`, exit 3.

This proposal replaces that search for those three cases (3.4). Desktop
builds whose staged runtime runs on the host are unchanged.

## 3. Design

### 3.1 The flow

```
$ kivyforge lock -p ios
[lock] host CPython 3.15.2 for byte-compiling: aarch64-apple-darwin
...
Wrote pylock.ios.toml

$ kivyforge package -p ios
[stage] host CPython 3.15.2 (aarch64-apple-darwin): installing from the lock
[download] cpython-3.15.2+20261101-aarch64-apple-darwin-install_only_stripped.tar.gz  100% of ...
[stage] byte-compiling app sources with the locked host CPython 3.15.2 (.pyc only)
...

$ kivyforge package -p ios        # any later build, on any machine with it cached
[stage] byte-compiling app sources with the locked host CPython 3.15.2 (.pyc only)
```

No step for the user to remember, and nothing waits for input. A teammate who
clones the repo, or a CI job that runs `lock --check`, gets the same pinned
build from the committed lock.

### 3.2 What the lock pins

A new table in the platform's lock, **one entry per host that can build it,
always**. Each entry records its state explicitly, so a missing entry can only
mean a lock written before this table existed (R1):

```toml
[[tool.kivyforge.host_python]]
triple = "aarch64-apple-darwin"
state = "pinned"
version = "3.15.2"
variant = "install_only_stripped"
url = "https://github.com/astral-sh/python-build-standalone/releases/download/20261101/cpython-3.15.2%2B20261101-aarch64-apple-darwin-install_only_stripped.tar.gz"
sha256 = "..."

[[tool.kivyforge.host_python]]
triple = "x86_64-pc-windows-msvc"
state = "no-build"           # PBS has no final build of this minor for the triple yet
minor = "3.16"
```

| `state` | Meaning | Fields |
|---|---|---|
| `pinned` | A build is pinned for this host. | `version`, `variant`, `url`, `sha256` |
| `no-build` | PBS publishes no final build of the minor for this triple, when `lock` last looked. | `minor` |
| `unresolved-offline` | `lock --offline` ran with no earlier pin to keep. | `minor` |

**Which platforms.** Those whose build compiles with a host interpreter: iOS,
Android, and Linux when `archs` includes `aarch64`. macOS and Windows ship only
the arch they build on, so their staged runtime always compiles its own
payload, and their locks gain nothing. The table is written whatever
`byte_compile` says: `build_settings` is not a lock input, so turning
`byte_compile` on later must not find the pin missing.

**Which hosts** (Q2). Every host that can build the target, so a lock written
on one machine serves the others:

| Platform | Triples |
|---|---|
| iOS | `aarch64-apple-darwin` |
| Android | `aarch64-apple-darwin`, `x86_64-unknown-linux-gnu`, `x86_64-pc-windows-msvc` |
| Linux, `archs` including `aarch64` | `x86_64-unknown-linux-gnu` |

These are kivyforge's three build hosts
([`get-started/hosts.md`](../../guides/get-started/hosts.md), and `hosts` /
`host_machines` in `capabilities --json`). An Intel Mac and an aarch64 Linux
machine are not build hosts.

**Which version** (Q3). **One version for every triple a platform pins**, so
all hosts compile with the same CPython release:

1. the version the lock ships, if PBS has it for every triple;
2. otherwise the newest final release of the minor that PBS has for every
   triple;
3. a triple with no final build of the minor at all gets `no-build`, and the
   others still share one version;
4. never a pre-release: a project shipping `3.16.0b2` gets `no-build` on every
   triple.

One release's `SHA256SUMS` lists every triple, so the lookup reads each
release once for all of them, newest first (a batched form of
`GithubPbsMetadataFetcher.find_install_only` from #213).

**Which variant** (Q12). `install_only_stripped` (debug symbols removed, the
same layout, compiling identically) where PBS publishes it for the chosen
version and triple, otherwise `install_only`. Measured 2026-11-06 for 3.15.0:
36.2 MB against 78.7 MB on Linux, 23.3 MB against 50.0 MB on Windows, and
26.4 MB against 26.5 MB on macOS. The entry records `variant`, so
a build never has to infer it from the URL.

### 3.3 `lock`, `lock --check`, `--update` and older locks

- **Plain `lock` completes a lock before its "already in sync" shortcut**
  (R2). `cli/lock.py` returns early when `lock_inputs_sha256` matches, and
  `build_settings` and the host-Python table aren't lock inputs, so without a
  check a plain `lock` would report "in sync" and add nothing. Before that
  shortcut, `lock` checks the table: a missing table, or an entry that is
  `no-build` or `unresolved-offline`, is resolved, and the lock rewritten with
  every other pin kept. This is lighter than the pyjnius precedent, whose fix
  is `lock --update` and re-resolves every dependency.
- **Keeping pins** (Q8). Plain `lock` and `lock --check` keep every `pinned`
  entry while the minor still matches, as `prefer_runtime` keeps a desktop
  runtime, and skip the lookup. A new PBS release is not drift, and
  `lock --check` on a complete lock stays off GitHub's API.
- **`lock --update` re-pins** (R4): it resolves the host Python afresh, as it
  does every dependency.
- **`lock --check` on an incomplete lock.** A missing table on a platform that
  needs one is **`KF-LOCK-INCOMPLETE`**, exit 4: the lock matches
  `pyproject.toml` but predates something kivyforge now supplies (the code's
  existing meaning). `unresolved-offline` is also incomplete, so CI notices a
  lock written offline. `no-build` passes: there is nothing for a re-lock to
  pin until PBS publishes, and finding out would put the check on the network.
  It is reported as a warning.
- **`lock --offline`** keeps existing pins, and records `unresolved-offline`
  where there is none.

### 3.4 What `build` does

For iOS, Android and a Linux `aarch64` target, when `byte_compile` applies,
`build` reads this host's entry from the lock. There is **no fallback** to an
interpreter already on the machine (Q5, 4.1): the pinned build is the only
compiler.

| This host's entry | `build` |
|---|---|
| `pinned` | Use the installed pin; else extract the cached archive; else fetch it (unless downloads are off, 3.7). Verify, extract and probe (3.5), then compile with it. |
| `no-build` | No compiler: ships source or fails (3.8). |
| `unresolved-offline` | No compiler, and the lock is incomplete: ships source or fails. |
| No table (an older lock) | No compiler, and the lock is incomplete: ships source or fails. |

Desktop builds whose staged runtime runs here keep compiling with it. That
runtime is also pinned in the lock, so every byte-compile is done by a pinned
build.

### 3.5 Archive, install, cache and concurrency

- **Two states on disk.** The **archive** is a pinned artifact in
  `ArtifactCache`, fetched and verified like any other. The **install** is the
  archive extracted to `<cache>/host-python/<full sha256>/`, keyed by the
  pin's full SHA-256, so two projects pinning different builds keep both, and
  `clean --cache` removes them with everything else. Extracting a cached
  archive needs no network, so it is allowed with downloads off.
- **Completion marker.** An install is complete only when its
  `.kivyforge-complete` marker exists, written last, after the extracted
  interpreter has been probed (it must run and report the pinned minor and a
  final release). An install directory without the marker, or one whose
  interpreter no longer runs, is deleted and extracted again from the archive.
  The new tree is extracted beside the final directory and renamed into place,
  so a failed install never leaves a half-written one (from #213).
- **Concurrency** (Q11). A file lock per pin
  (`<cache>/host-python/<sha256>.lock`) around fetch and extract, so parallel
  jobs sharing one cache don't install the same build twice at once. The second
  waits up to a timeout, then finds it installed. A lock it can't acquire in
  that time is a failure (3.8), not a race.

### 3.6 Verification and provenance

`artifacts/verify.py` checks the archive against the lock's SHA-256 before
extraction, and the probe checks the interpreter after. The T3 magic check
still verifies the shipped `.pyc`.

What the committed hash does, stated precisely: it makes every machine use the
same bytes, and it catches an archive replaced or corrupted after locking, on
GitHub, a mirror or the cache. It does **not** strengthen where the build came
from: the hash was read from the same GitHub release that serves the archive,
so `lock` trusts GitHub, over HTTPS, exactly once.

### 3.7 Download settings

Both are environment variables, because both describe the machine or the
organisation, not the project (Q9, Q10). Both affect **only the host Python
that byte-compiles**: runtimes, wheels and other pinned artifacts download as
before. The names say so (R5), rather than matching uv's broader
`UV_PYTHON_DOWNLOADS` and `UV_PYTHON_INSTALL_MIRROR`.

- **`KIVYFORGE_HOST_PYTHON_DOWNLOADS`**: `automatic` (default) or `never`. With
  `never`, `build` uses the pinned install, or extracts the pinned archive if
  it is cached, and never reaches the network for it; otherwise it ships source
  or fails (3.8). For hermetic CI images, air-gapped machines with a pre-filled
  cache, and policies that forbid build tools downloading executables. No CLI
  flag: the choice belongs to the machine, not one invocation.
  **`--no-cache` with `never` is a usage error**, exit 1: one asks to
  download again, the other forbids downloading.
- **`KIVYFORGE_HOST_PYTHON_MIRROR`**: a URL that replaces
  `https://github.com/astral-sh/python-build-standalone/releases/download` in
  a pinned URL. The pinned SHA-256 still verifies what the mirror serves.
  **It serves builds from an existing lock only** (R3): `lock` still lists
  releases through GitHub's API and reads their `SHA256SUMS` from GitHub, so
  writing or updating a lock needs GitHub access. A machine behind a firewall
  can build from a lock committed elsewhere.

### 3.8 Failures and codes

| Case | `"release"` | `true` | Code | Fix in the message |
|---|---|---|---|---|
| No table for this host (an older lock), or `unresolved-offline` | ships source, warns | exit 4 | `KF-LOCK-INCOMPLETE` | `kivyforge lock -p <platform>` |
| `no-build` | ships source, warns | exit 3 | `KF-BYTECOMPILE-NO-INTERP` | wait for a PBS build and re-lock, or `byte_compile = false` |
| Downloads off and nothing cached | ships source, warns | exit 3 | `KF-BYTECOMPILE-NO-INTERP` | `kivyforge upgrade -p <platform>` with network, or unset the variable |
| No network, a timeout, or a GitHub rate limit | ships source, warns | exit 3 | `KF-HOST-PYTHON-FETCH` | retry with network access; set `GITHUB_TOKEN` |
| SHA-256 mismatch | ships source, warns | exit 3 | `KF-HOST-PYTHON-FETCH` | check the mirror serves the pinned file; re-lock if the release changed; report it if neither |
| Extraction fails, or the extracted interpreter won't run as the pinned minor | ships source, warns | exit 3 | `KF-BYTECOMPILE-NO-INTERP` | the cache is cleared for that pin; retry, or `clean --cache` |
| Disk full or permission denied writing the cache | exit 1 | exit 1 | `KF-ERROR`, unclassified | `os_failure()`'s message: what was being done, the path and the reason |
| The install lock can't be acquired in time | ships source, warns | exit 3 | `KF-HOST-PYTHON-FETCH` | another build is installing; retry |
| `--no-cache` with `KIVYFORGE_HOST_PYTHON_DOWNLOADS=never` | exit 1 | exit 1 | usage | drop one |

Exit 4 where the fix is in the lock, exit 3 where it is on the machine. An OS
refusal stays unclassified and fails in both modes, as every other one in
kivyforge does (`report/failures.py::os_failure`): a full disk or a read-only
cache would break the rest of the build anyway, and has nothing in common with
a missing compiler.
`KF-HOST-PYTHON-FETCH` is new in #213 and unreleased, so its meaning can still
be set: "the pinned host CPython could not be fetched". The mismatch case
shares it but carries its own fix, because a retry rarely helps.

### 3.9 Messages and `doctor`

No list of what was searched. The message names the entry and its fix, for
example:

```
Error: [tool.kivy.ios.python.build_settings].byte_compile = true, but the locked host CPython 3.15.2 (aarch64-apple-darwin) isn't available: KIVYFORGE_HOST_PYTHON_DOWNLOADS=never, and it isn't in the cache.
  Fix: run `kivyforge upgrade -p ios` on a machine with network access, unset KIVYFORGE_HOST_PYTHON_DOWNLOADS, or set byte_compile = false.
```

`doctor`, for each platform that byte-compiles with a host interpreter, never
downloading or extracting:

| This host's state | Result |
|---|---|
| `pinned`, installed | PASS, naming it |
| `pinned`, archive cached | PASS: "extracted on the first release build" |
| `pinned`, not cached, downloads on | PASS: "downloaded on the first release build" |
| `pinned`, not cached, downloads off | FAIL with `true`, WARN with `"release"` |
| `no-build` | FAIL with `true`, WARN with `"release"`: no PBS build yet |
| No table, or `unresolved-offline` | FAIL with `true`, WARN with `"release"`: re-lock |

No size is given: `SHA256SUMS` doesn't record one, and fetching it would cost
`lock` a request per triple.

### 3.10 `upgrade`

`kivyforge upgrade -p <platform>` already re-fetches every artifact the lock
pins, and now fetches this host's `pinned` archive with them (Q14). Its
selectors:

| Form | Host Python |
|---|---|
| no selector | fetched |
| `--python` | fetched, with the runtime |
| `--name host-python` | fetched alone |
| `--libs`, `--xcframeworks` | not fetched |

It fetches the archive; the first build extracts it, offline if need be. It is
how to fill a cache ahead of time. It is **not** enough for a fully offline CI
image: `upgrade` never fetches wheels. An image that must build offline runs a
full `package` while it's being built, which fills every cache, and then sets
`KIVYFORGE_HOST_PYTHON_DOWNLOADS=never`. There is no `bytecompiler` verb.

### 3.11 What is guaranteed, and what isn't

Guaranteed: every machine that builds a given lock compiles with the same
pinned CPython build, and the `.pyc` it writes load in the shipped runtime.

Not guaranteed (R2 of 4.2): byte-for-byte identical `.pyc` across hosts. Each
host runs a different PBS binary, and on Windows the source path recorded in
each code object keeps backslashes after the payload prefix is stripped, so a
`.pyc` written on Windows differs from one written on macOS. `marshal` output
has also been reported to depend on reference counts in some CPython
versions; that is unverified for 3.15. Byte-identity across hosts would be a
separate goal, with a three-host comparison in CI (section 7).

### 3.12 What #212 and #213 leave behind

Removed, for the three host-compiled cases: the search (kivyforge's own
interpreter, the `py` launcher, `PATH`, uv), its "Looked at:" list, and the
`bytecompiler` verb with its `-p`, `--force` and `data.interpreters`. Kept from
#213: the PBS lookup (made batched across triples), download, verification,
extraction and probe (`bundle/hostpython.py`), the host-triple table, and
`KF-HOST-PYTHON-FETCH`. Desktop builds whose staged runtime can't run (a
missing staged interpreter) keep reporting `KF-BYTECOMPILE-NO-INTERP`.

## 4. Decisions (recorded 2026-11-06)

| # | Question | Decision |
|---|---|---|
| Q1 | Does `lock` pin the host Python and `build` fetch it, or does a command the user runs install it? | **`lock` pins, `build` fetches.** A command was the 2026-11-05 design (6.2). It never reached a teammate or CI building from a committed lock, the common case. |
| Q2 | Which hosts get an entry? | **Every host that can build the target** (3.2), so a lock from a Mac serves Android CI on Linux. Only the host that ran `lock` was rejected for that reason. |
| Q3 | Which version? | **One version for all of a platform's triples:** the shipped version if every triple has it, otherwise the newest final every triple has; never a pre-release (3.2). Changed in review: choosing per triple could pin 3.15.1 on one host and 3.15.2 on another. |
| Q4 | The pin, or an interpreter already on the machine, first? | **The pin**, so every machine compiles with the same build. Superseded by Q5: the pin is the only one. |
| Q5 | Fall back to an interpreter on the machine when there's no usable pin? | **No** (4.1). |
| Q6 | Let uv do the install when it's present? | **No; and with no fallback, moot.** uv can't install a specific pinned build, its result would depend on whether and which uv is installed, and it writes outside kivyforge's cache. |
| Q7 | What is a lock without the table? | **Incomplete, not drift: `KF-LOCK-INCOMPLETE`, exit 4**, and a plain `lock` completes it (3.3). Changed in review from "drift": `pyproject.toml` didn't move, and the code exists for exactly this. |
| Q8 | Do `lock` and `lock --check` keep pins? | **Yes**, like `prefer_runtime`, so a new PBS build isn't drift and the check stays off the GitHub API. |
| Q9 | A setting to never download? | **Yes: `KIVYFORGE_HOST_PYTHON_DOWNLOADS=automatic\|never`**, an environment variable only (3.7). Extracting a cached archive is still allowed. The use case it no longer serves is compiling with your own CPython on purpose, the weakest of the four. |
| Q10 | A mirror setting? | **Yes, now: `KIVYFORGE_HOST_PYTHON_MIRROR`**, for builds from an existing lock (3.7, R3). |
| Q11 | A lock on concurrent installs? | **Yes**, per pin, with a timeout (3.5). |
| Q12 | Stripped or full PBS build? | **Stripped where PBS publishes it, otherwise full, recorded as `variant`** (3.2). Decided in review; measuring the sizes confirms the choice and changes nothing if stripped turns out no smaller. |
| Q13 | Failure codes at build time? | **`KF-HOST-PYTHON-FETCH`, exit 3**, for a failed fetch, a hash mismatch (with its own fix) and a lock timeout; `KF-LOCK-INCOMPLETE`, exit 4, where the lock is the problem; `"release"` degrades to shipping source in every case (3.8). |
| Q14 | What happens to `kivyforge bytecompiler`? | **Dropped.** Fetching ahead of time moves into `upgrade` (3.10). |
| Q15 | #213: rework or replace? | **Rework in place**: most of its code carries over (3.12). |

### 4.1 Q5: why no fallback

Decided 2026-11-06. A fallback to an interpreter already on the machine was
proposed and rejected; each reason for it is covered another way.

| Reason for a fallback | Covered by |
|---|---|
| Older locks keep byte-compiling until a re-lock | A plain `lock` completes them (3.3). |
| No network on the first build after a clone | Explicit: `"release"` ships source with a warning, `true` fails. `upgrade` fetches ahead of time. |
| Networks that block GitHub | The mirror, for builds from a committed lock (3.7), or a pre-filled cache. Writing the lock still needs GitHub. |
| "Never download" users | Hermetic images (a full `package`, then `never`), air-gapped machines and reviewed-artifact policies are served by a cache or a mirror. Only "compile with my own CPython" is lost, and byte-compiling needs only the right minor. |

Against it: a compiler that differs per machine, and a second path to test and
explain. Without it, most of the #212 search goes for the host-compiled cases,
and the message and `doctor` get simpler (3.9). That search is unreleased, so
removing it breaks no user.

### 4.2 Review, 2026-11-06

A review of the first 2026-11-06 revision found five gaps and asked four
questions. Each is now resolved:

| Point | Resolution |
|---|---|
| A lock with no entry, and one written offline or before a build existed, looked the same | Every capable host gets an entry with an explicit `state` (3.2); absence means only "older lock". |
| Plain `lock` would say "in sync" and never add the pin | A completeness check before the shortcut (3.3). |
| Android could pin a different patch per host | One version common to all triples (Q3). |
| Byte-identical cross-host `.pyc` was assumed | The claim is narrowed to "the same pinned compiler, loadable `.pyc`" (3.11). |
| The mirror doesn't help `lock` behind a firewall | Documented: it serves builds from an existing lock only (3.7). |
| Clarifications | Archive versus install, full-hash directory and completion marker (3.5); `--no-cache` with `never` (3.7); variable names scoped to the host Python (3.7); `upgrade` selectors and offline images (3.10); no size estimate (3.9); a fuller failure table and the mismatch fix (3.8); Q12 decided; `--update` re-pins (3.3); provenance stated precisely (3.6). |

The review's questions, answered:

- **R1. Should `lock` succeed when a triple has no PBS build?** Yes, with an
  explicit `no-build` entry, never a silent absence.
- **R2. Is byte-for-byte cross-host `.pyc` reproducibility a requirement?** No:
  the same pinned compiler, and `.pyc` the runtime loads (3.11).
- **R3. Must the mirror support writing and updating locks without GitHub?**
  No, not now (section 7).
- **R4. Should `lock --update` re-pin the host Python?** Yes (3.3).
- **R5** (from the clarifications). The variables are named for the host
  Python they control, not uv's broader names (3.7).

## 5. How other tools do it

None of these downloads a prebuilt host Python for byte-compiling. Read from
each project's source, 2026-11-05.

| Tool | Approach |
|---|---|
| python-for-android (Buildozer) | Builds a host CPython from source (`hostpython3` recipe), and refuses unless its version equals the target `python3` recipe's. Compiles with `hostpython -m compileall -b`; `--no-byte-compile-python` opts out ([recipe](https://github.com/kivy/python-for-android/blob/develop/pythonforandroid/recipes/hostpython3/__init__.py)). |
| kivy-ios | The same: a `hostpython3` recipe built from python.org source at the iOS `python3` version, used by `compileall` ([recipe](https://github.com/kivy/kivy-ios/blob/master/kivy_ios/recipes/hostpython3/__init__.py)). |
| Briefcase | The app's Python is the Python running Briefcase (`python_version_tag` from its own `sys.version_info`), so a matching host interpreter always exists. It doesn't byte-compile iOS apps itself; Android goes through Chaquopy ([source](https://github.com/beeware/briefcase/blob/main/src/briefcase/commands/base.py)). |
| Chaquopy | Searches `python3.X`, `python3`, `python` (`py -3.X` on Windows), with a `buildPython` override in `build.gradle`. A failed compile warns and ships source unless `pyc` is set to `true`, much as #212 shipped ([docs](https://github.com/chaquo/chaquopy/blob/master/product/runtime/docs/sphinx/android.rst)). |
| uv | Not a build tool, but the reference for installing interpreters: PBS builds verified against hashes shipped with uv, a mirror setting, a downloads on/off switch, and locking around installs. This design takes the last three (3.5, 3.7). |

p4a and kivy-ios get a pinned, exact-version host interpreter because they must
build CPython anyway. kivyforge uses prebuilt python.org runtimes, so it gets
the same property by pinning a prebuilt host build instead.

## 6. Rejected and superseded designs

### 6.1 An opt-in `pyproject.toml` key (draft of 2026-11-05)

`compiler = "download"` in `build_settings` let `build` download an unpinned
interpreter. Dropped the same day: a missing tool on one machine isn't a
property of the project, and "edit `pyproject.toml`" was the wrong fix to print.

### 6.2 `kivyforge bytecompiler` (2026-11-05, implemented in #213)

A command run once per machine that searched first and installed a PBS build
only when nothing qualified, with the hash read from the release's
`SHA256SUMS`. It worked (test-matrix §7, 2026-11-05, including a device boot),
but:

- **It never reached a committed lock's users.** CI and teammates build from a
  lock they didn't write, and still had to know to run it.
- **The compiler still varied per machine**, since the search came first.
- **Its hash was read at install time**, not committed, so a replaced archive
  went unnoticed.

Its name was chosen over `setup`, `doctor --fix`, `python`, `python install` and
`hostpython`; that reasoning no longer applies with no verb.

### 6.3 Asking yes/no at build time

Rejected: AGENTS.md's rule is that no verb waits for input. CI and scripts
would hang, the build would behave differently at a terminal than in CI, an
agent running `--json` couldn't answer, and the answer would need somewhere to
live. Automatic download from a pinned lock needs no question.

### 6.4 A `--python X.Y` switch

For the `bytecompiler` command, installing a minor without reading a project.
Dropped for lack of a use case, and because a minor picked by hand could differ
from what the lock ships. Moot without the verb.

### 6.5 A setting naming the interpreter, like Chaquopy's `buildPython`

Chaquopy needs one mostly because Gradle runs inside Android Studio, which may
not see the shell's `PATH`. kivyforge byte-compiles from the shell; a machine
path doesn't belong in a committed `pyproject.toml`; and one value can't serve
a project shipping different minors per platform. With no fallback, there is
also nothing for it to point at: the pin is the compiler.

## 7. Not in this change

- **A mirror for writing locks**: serving the release list and `SHA256SUMS`
  without GitHub. Only if someone needs to lock behind a firewall (R3).
- **Byte-identical `.pyc` across hosts**, including normalising the Windows
  path separator in code objects, and a three-host comparison in CI (R2).
- **Using the pinned host Python for anything else** (resolving, building
  sdists). It compiles `.pyc` and nothing more.
- **Free-threaded or non-CPython builds.** The pin is PBS's standard CPython.
- **Classifying `HashMismatch` for every other download.** It still has no code
  outside this path; a separate change.

## 8. Steps

1. Measure the stripped and full archives for the three triples, and confirm
   the stripped layout matches (Q12).
2. Lock model: the `host_python` table with its three states, in the iOS,
   Android and Linux lock models, readers, writers, `semantic_equal` and
   `diff_summary`.
3. Lock resolution: one version common to the platform's triples, in one pass
   over the releases (3.2); keeping pins (Q8); `--update` re-pinning; `no-build`
   and `unresolved-offline` entries; the completeness check before `lock`'s
   shortcut, and `KF-LOCK-INCOMPLETE` from `lock --check` (3.3).
4. Build: the pinned interpreter as the only compiler for the host-compiled
   cases (3.4), replacing `find_interpreter` there; archive, install, marker
   and recovery, and the per-pin file lock, from #213's `hostpython` (3.5).
5. `KIVYFORGE_HOST_PYTHON_DOWNLOADS` and `KIVYFORGE_HOST_PYTHON_MIRROR`, and
   the `--no-cache` conflict (3.7).
6. Failures and messages (3.8, 3.9); `doctor`'s six states.
7. `upgrade` fetches this host's pin, with its selectors (3.10).
8. Remove the `bytecompiler` verb, its tests and docs, and the parts of the
   #212 search the host-compiled cases no longer use (3.12).
9. Re-lock the tracked example locks that need the table (section 11).
10. The documentation in section 9, and CHANGELOG under `[Unreleased]`.

## 9. Documentation

| Document | Change |
|---|---|
| [`docs/design/common/10-byte-compile.md`](../common/10-byte-compile.md) | Rewrite "The search" and "Installing one" around the pin: the table and its states, how `build` gets it, the two environment variables, the failures, and what is and isn't guaranteed (3.11). Desktop's staged-runtime rule stays. |
| `docs/design/common/03-lockfile-concept.md` | The `host_python` table: a lock entry for a tool that never ships, why it's still a lock's job, and the completeness rule. |
| `docs/design/common/02-cli-and-platform-resolution.md` | Remove `bytecompiler` from "Verbs" and its resolution note; `upgrade` fetches the host-Python pin. |
| `docs/design/platforms/ios/02-pylock-ios-spec.md`, and the Android and Linux lock docs | The table, its triples and states, and `KF-LOCK-INCOMPLETE`. |
| `docs/design/platforms/ios/01-pyproject-ios.md`, `android/01-pyproject-android.md`, `linux/linux-spec.md` | Replace "run `kivyforge bytecompiler`" with the pinned interpreter. |
| `docs/design/dev/roadmap.md` | Item 14 retitled and pointed at this design. |
| `docs/design/dev/hardware-checklist.toml`, `ios-strip-source` | "Needs" no longer asks for a Python on `PATH`. |
| `docs/design/dev/test-matrix.md` §7 | The real-toolchain rows from section 10. |
| `docs/guides/reference/pyproject/ios.md`, `android.md`, `linux.md` | The byte-compile note: the lock pins it and the first release build downloads it; the two environment variables; drop the `bytecompiler` and `PATH` advice. |
| `docs/guides/reference/environment.md` | `KIVYFORGE_HOST_PYTHON_DOWNLOADS` and `KIVYFORGE_HOST_PYTHON_MIRROR`, including the mirror's limit. |
| `docs/guides/reference/lockfile.md` | The `host_python` table. |
| `docs/guides/concepts/build-vs-package.md`, `get-started/hosts.md` | The host-Python lines: nothing to install; the first release build downloads it. |
| `docs/guides/guides/cross-platform/ci-and-agents.md` | Replace the `bytecompiler` step: `GITHUB_TOKEN` for `lock`, and for offline images a full `package` while building the image, then `KIVYFORGE_HOST_PYTHON_DOWNLOADS=never`. |
| `docs/guides/troubleshooting/index.md`, `docs/hooks/kf_generated.py` | The three codes' fixes from 3.8. |
| `docs/guides/reference/json-output.md` | Remove `data.interpreters`. |
| `README.md`, `AGENTS.md` | Remove the `bytecompiler` lines; AGENTS.md's hint becomes "`KF-LOCK-INCOMPLETE`: run `kivyforge lock`; `KF-HOST-PYTHON-FETCH`: retry with network access". |

Generated, so they update themselves: `docs/guides/reference/cli.md` and
`docs/guides/reference/codes.md`.

## 10. Test plan

**Hermetic** (no network, no toolchain):

- `lock` writes one entry per capable triple for iOS, Android and Linux with
  `aarch64`, and no table for macOS, Windows or Linux without `aarch64`.
- One version across triples: the shipped version when every triple has it;
  the newest common final otherwise; a triple with no build gets `no-build`
  while the others still share a version; never a pre-release.
- The variant: stripped where published, full otherwise, recorded.
- Plain `lock` on an older lock (no table) adds it and keeps every other pin,
  instead of reporting "in sync"; it also resolves `no-build` and
  `unresolved-offline` entries.
- `lock --check` keeps pins without calling the fetcher; reports
  `KF-LOCK-INCOMPLETE` (exit 4) for a missing table and for
  `unresolved-offline`; passes `no-build` with a warning.
- `lock --update` re-pins; `lock --offline` keeps pins and writes
  `unresolved-offline` where there is none.
- `build` uses the pinned interpreter and no other, whatever is on `PATH`. An
  installed pin is used; a cached archive is extracted with downloads off; a
  miss fetches, verifies, extracts, probes and writes the marker.
- An install directory without the marker, or whose interpreter won't run, is
  rebuilt from the archive.
- Two concurrent installs of one pin: one installs, the other waits and reuses
  it; a lock not acquired in time fails as 3.8 says.
- `KIVYFORGE_HOST_PYTHON_DOWNLOADS=never` with the install, with only the
  archive, and with neither; `--no-cache` with `never` exits 1; the mirror
  rewrites the URL and the hash still verifies; neither variable affects a
  runtime or wheel download.
- Each row of 3.8 with `"release"` and with `true`, including the mismatch's
  own fix; messages encode as cp1252.
- `doctor`'s six states; `upgrade`'s selectors.
- stdout under `--json` is exactly one envelope on success and every failure.

**Real toolchain** (logged in `test-matrix.md` §7):

- iOS on a Mac with no `python3.15` and no uv: `lock`, then `package` downloads
  the pin once and compiles with it; the T3 stripped check passes; the app
  boots on a device (`ios-strip-source`).
- Android on an x86_64 Linux host from a lock written on the Mac: the Linux
  entry is fetched and used; release APK on an emulator.
- `upgrade -p ios`, then `KIVYFORGE_HOST_PYTHON_DOWNLOADS=never` with the
  network off: `package` extracts and compiles from the cache.
- An older iOS lock: `lock --check` reports `KF-LOCK-INCOMPLETE`, a plain
  `lock` adds the table and nothing else changes.

## 11. Migration

- **Re-lock once** each iOS and Android lock, and each Linux lock with
  `aarch64`, with a plain `kivyforge lock -p <platform>`: it adds the table and
  keeps every other pin. Until then `lock --check` reports `KF-LOCK-INCOMPLETE`,
  and a release build ships source (`"release"`) or fails (`true`). The
  CHANGELOG says so. Desktop locks without a host-compiled target are
  unaffected.
- **Tracked example locks.** `hello-kivy` (iOS) and `hello-android`,
  `hello-sdl3`, `android-services`, `android-activity-class` (Android) track
  their locks (`03-lockfile-concept.md`, "Example-repo lock policy"). Re-locking
  adds the table; the change is diffed and reported, and committed by the owner.
- **Machines that compiled with their own Python** under #212 now download the
  pinned build once. Nothing to do.

## 12. Done when

- The hermetic tests in section 10 pass, and the iOS and Android
  real-toolchain runs are in `test-matrix.md` §7.
- Every document in section 9 is updated in the same change.
- #209 is answered.

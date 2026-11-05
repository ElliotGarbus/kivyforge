# Proposal — a command that installs the host Python that byte-compiles

> Status: **draft 2026-11-05.** The verb's name, `bytecompiler`, is decided
> (section 4, Q1); the other questions in section 4 are open. Nothing here is
> implemented.
>
> Responds to [#209](https://github.com/ElliotGarbus/kivyforge/issues/209).
> Writing `.pyc` for iOS or Android needs a final CPython of the shipped minor
> *on the machine that builds*, and the reporter had none. `cad70344` fixed the
> message and the search (section 2). On the issue, the reporter then proposed
> keeping a host install as the default, with an opt-in way for kivyforge to
> provide one.
>
> An earlier draft of this proposal did that with a `pyproject.toml` key that
> let `build` download the interpreter. It was dropped the same day. A missing
> tool on one machine is not a property of the project, and the fix shouldn't
> be "edit `pyproject.toml`". This draft replaces the key with a command you run
> once per machine, and that the error message prints ready to copy.

## 1. Problem

`byte_compile` writes the `.pyc` files with an interpreter that has to run on
the build machine. Desktop builds usually have one: the runtime they ship, when
it can run here. iOS and Android never do, because their runtime is built for
the device. The `.pyc` format is fixed per CPython minor from the first release
candidate on, so any final `3.15.x` on the build machine can compile for a
shipped `3.15.2`, but something has to be installed.

Today that is the user's job. A developer who has never installed 3.15 on their
Mac, or a CI runner with only the system Python, gets one of two outcomes:

- with the default `byte_compile = "release"`, a release that silently ships
  source, with a `KF-BYTECOMPILE-NO-INTERP` warning;
- with `byte_compile = true`, a failed build, exit 3.

The message says what to install, but leaves the user to find an installer.
kivyforge already downloads standalone CPython builds (python-build-standalone,
"PBS") for the desktop runtimes it ships, so it can install one for the host on
request.

## 2. What ships today (`cad70344`)

`bundle/pycompile.py::find_interpreter` searches, in order:

1. kivyforge's own interpreter, if it is a final release of the target minor;
2. `py -3.X` (Windows only);
3. `python3.X`, `python3` and `python` on `PATH`;
4. `uv python find --no-project --no-python-downloads 3.X`, only when uv is
   installed.

Each candidate must report the target minor *and* `releaselevel == "final"`.
When none does, all six call sites (iOS app sources, iOS pip-deps, macOS, Linux,
Windows, Android) and `doctor` print one shared message
(`pycompile.no_interpreter`). It lists every candidate and its version, and its
`Fix:` line says to install the minor or set `byte_compile = false`. A
`byte_compile = true` failure is `KF-BYTECOMPILE-NO-INTERP`, exit 3.

All of that stays. This proposal adds a command, one more search step, and a
line in the message.

## 3. Design

### 3.1 The flow

```
$ kivyforge package -p ios
Error: [tool.kivy.ios.python.build_settings].byte_compile = true, but no final CPython 3.15 found (this project ships 3.15.2).
  The .pyc files must be written by a final CPython 3.15 on this machine. Looked at:
    ...
  Fix: run `kivyforge bytecompiler -p ios` to install a host CPython 3.15 for
  byte-compiling, or install any final CPython 3.15.x yourself (for example
  `uv python install 3.15`, or python.org) so python3.15 is on PATH, or set
  byte_compile = false in [tool.kivy.ios.python.build_settings].

$ kivyforge bytecompiler -p ios
[bytecompiler] ios ships CPython 3.15.2; no final 3.15 on this machine
[bytecompiler] downloading CPython 3.15.2 (aarch64-apple-darwin) ...
Installed CPython 3.15.2 for byte-compiling: ~/Library/Caches/kivyforge/host-python/3.15/bin/python3.15

$ kivyforge package -p ios
[stage] byte-compiling app sources with ~/Library/Caches/kivyforge/host-python/3.15/bin/python3.15 (.pyc only)
...
```

`build` and `package` never download a host Python themselves. The network is
used only when the user runs the command, so a build's network use is
unchanged, and nothing waits for input: the error suggests a command, and the
user decides whether to run it.

### 3.2 The command

| Form | Installs |
|---|---|
| `kivyforge bytecompiler` | For every platform the project configures, the minor its build would compile for, where this machine can't already supply one. A project that ships 3.15 to iOS and 3.14 to Android gets both. |
| `kivyforge bytecompiler -p ios` | The same, for that platform only. |

It runs in a project, like `build`: the error that sends a user here comes from
one. `-p` selects a *version*, never the interpreter's target: the interpreter
is always for the host, so its triple comes from the machine (3.5).

**`-p` is optional, and has no default.** Other verbs fall back to
`KIVYFORGE_PLATFORM`, then to the host's own platform. That would be wrong
here: on a Mac the host platform is `macos`, which compiles with the runtime it
ships, so a defaulted `bytecompiler` would do nothing when the user meant iOS. Without
`-p`, the command covers every configured platform instead.

**What "configured" means**, for the no-`-p` form, decided per platform:

- the project has that platform's overlay (`[tool.kivy.<platform>]`);
- this host can build it (`capabilities`); others are skipped with a line
  saying so (iOS on Windows);
- `byte_compile` is not `false` for it;
- its build cannot already compile with what it ships. On desktop that is only
  a Linux `aarch64` target built on an x86_64 host. macOS ships only arm64 and
  Windows only amd64, so their staged runtime always runs.

**Which version a platform needs** comes from its lock, exactly as `build`
reads it: `python_xcframework.version` (iOS), `python_android[0].version`
(Android), `python_runtime.version` (macOS, Linux, Windows). With no lock, or a
stale one, the platform is reported ("run `kivyforge lock -p ios` first") and
the others still run. Reading `pyproject.toml` instead would be wrong for any
project whose lock has not caught up with its config.

**Idempotent.** For each minor the command first runs the same search a build
runs (section 2, plus 3.3). If anything qualifies, it says what and installs
nothing:

```
[bytecompiler] ios ships CPython 3.15.2; already compiled by python3.15 (3.15.0)
```

`--force` reinstalls kivyforge's copy (Q7).

### 3.3 Where it goes, and the new search step

The interpreter is extracted to a host-tools directory beside the artifact
cache, one per minor: `<cache>/host-python/<major.minor>/`. The `.tar.gz`
itself stays in `ArtifactCache` like any other download.

`find_interpreter` gains a step right after "this interpreter": **a final
CPython of the minor that kivyforge installed.** Putting it before `PATH` makes
the install the deterministic choice once the user has asked for it, whatever
`PATH` holds. A newer final patch release replaces the old one in the same
directory, because only one is needed per minor.

### 3.4 Which build is installed

1. The **exact version the lock ships** (`3.15.2`), when PBS has an
   `install_only` build of it for the host's triple.
2. Otherwise the **newest final release of the same minor** PBS has for that
   triple. PBS can lag a CPython patch release by days, and any final release
   of the minor writes `.pyc` the runtime loads.
3. **Never a pre-release.** A project shipping `3.16.0b2` gets nothing, with a
   line saying why, as in the search.

`GithubPbsMetadataFetcher.fetch(version, triple)` already does step 1. Step 2
needs a minor-wide lookup it doesn't have: reading `SHA256SUMS` newest first
and taking the first final `cpython-3.15.*` for the triple.

### 3.5 Host triples

The host's own triple. kivyforge supports three build hosts
([`get-started/hosts.md`](../../guides/get-started/hosts.md), and `hosts` /
`host_machines` in `capabilities --json`), so the table is complete:

| Host | Triple |
|---|---|
| macOS arm64 (Apple Silicon) | `aarch64-apple-darwin` |
| Linux x86_64 | `x86_64-unknown-linux-gnu` |
| Windows amd64 | `x86_64-pc-windows-msvc` |

An Intel Mac and an aarch64 Linux machine are not build hosts. A Raspberry Pi
is a Linux *target* built from an x86_64 host. On a host missing from the
table, the command fails with exit 3 rather than guessing a triple.

### 3.6 Verification

The interpreter is a binary kivyforge will run, so it is verified even though
no lock pins it:

- the sha256 comes from the PBS release's own `SHA256SUMS`, which the existing
  fetcher already reads for desktop runtimes;
- the archive is checked with `artifacts/verify.py` before it is extracted;
- after extraction, the installed interpreter is probed like any search
  candidate, and must report the expected minor and `final`.

**Trust model, stated plainly:** this trusts the hash published *with* the
release, fetched over HTTPS from GitHub. That is weaker than a desktop runtime,
whose hash the user commits in the lock. It is accepted here because the
interpreter never ships, and because the T3 magic check verifies the `.pyc` it
writes (Q5).

Cost: one archive per host and minor, about 24 MB for `aarch64-apple-darwin`
(measured from a cached 3.13 build), shared by every project on the machine.

### 3.7 Output

- Progress on stderr, prefixed `[bytecompiler]`, as in 3.1.
- One product line per minor on stdout: `Installed CPython 3.15.2 for
  byte-compiling: <path>`, or `Already available: ...`.
- `--json`, like every verb but `run`. `data.interpreters` lists one entry per
  minor: `{"minor", "version", "path", "source": "installed" | "found" |
  "already-installed", "platforms": [...]}`. It is not `data.artifacts`: an
  interpreter is a tool, not a build product.
- Skipped platforms (no lock, host can't build, `byte_compile = false`) are
  `INFO` diagnostics, so an agent can see why a platform got nothing.

### 3.8 Failures

All of these are about the machine, so all are exit 3:

| Case | Code | Message names |
|---|---|---|
| No network, or the fetch fails | Q6 | the URL tried |
| GitHub rate limit (403/429) | Q6 | the existing fetcher's rate-limit hint |
| No final PBS build of the minor for this triple | `KF-BYTECOMPILE-NO-INTERP` | the triple and minor |
| Hash mismatch | Q6 (`artifacts/verify.py::HashMismatch` is unclassified today) | the file and both hashes |
| Host not in the table (3.5) | `KF-HOST-INCAPABLE` | the host |

A project problem is exit 1 or 4 as elsewhere: no project found (1), or
`-p <platform>` whose lock is missing or stale (4). Without
`-p`, such a platform is skipped with an `INFO` diagnostic instead (3.2), and
the command fails only if no platform is left to set up.

### 3.9 The message, `doctor` and `clean`

- **The shared message** gets the command as its first `Fix:` option (3.1),
  with `-p <platform>`, since the build knows its platform. `doctor` prints the
  same.
- **`doctor`**: with no interpreter, the hint carries the same command. With
  kivyforge's own install found, the check passes and names it ("via
  kivyforge's CPython 3.15.2"). `doctor` never downloads.
- **`clean --cache`** already removes the whole cache, so it removes these
  installs too. Its help text should say so, since the next release build
  would then fail until `bytecompiler` runs again.

### 3.10 The lock and `pyproject.toml` are untouched

Nothing is written to the project. The interpreter never ships, and which final
`3.15.x` writes the `.pyc` doesn't change whether the runtime loads them, so no
lock records it. There is no new config key. The objections to the earlier
draft's per-host-arch lock entries and forced re-lock don't arise.

## 4. Questions (Q1 decided 2026-11-05; the rest open)

| # | Question | Leaning |
|---|---|---|
| Q1 | **The verb's name.** | **Decided 2026-11-05: `bytecompiler`** (4.1). |
| Q2 | **Search order.** Should kivyforge's own install come before `PATH` (deterministic once installed) or after it (a user's own Python wins)? | **Before**, so that running the command always changes what the build uses. Either works for `.pyc`, since any final release of the minor is correct. |
| Q3 | **Is a `SHA256SUMS` hash from the release itself enough?** The alternative is pinning per host triple somewhere committed, which reopens the lock question. | **Yes, with the trust model documented** (3.6). |
| Q4 | **Exact patch, or newest of the minor?** | **Exact when PBS has it, newest final of the minor otherwise** (3.4). |
| Q5 | **Should `bytecompiler` also verify the `.pyc` it would write?** It could compile a one-line module and check its magic against the lock's runtime stdlib. | **No.** The T3 magic check already covers shipped `.pyc`; the probe in 3.6 covers the interpreter. |
| Q6 | **A new code for download failures?** `KF-BYTECOMPILE-NO-INTERP` still fits the outcome; a new code (for example `KF-HOST-PYTHON-FETCH`) would let an agent tell "no network" from "nothing to download". | **New code** for the network, rate-limit and hash-mismatch rows; keep `NO-INTERP` for "PBS has no build". Classifying `HashMismatch` everywhere is a separate change. |
| Q7 | **Upgrades and removal.** Does a plain `bytecompiler` replace an installed `3.15.0` with a newer `3.15.2`, or only `--force`? Is there an uninstall? | **Only `--force`.** An installed 3.15.0 already compiles correctly. No uninstall verb; `clean --cache` covers it. |

### 4.1 Q1: why `bytecompiler`

Decided 2026-11-05. The verb is narrow, so its name is too: it installs the
interpreter that byte-compiles, and nothing broader.

- **It answers the error.** The failure begins `byte_compile = true, but no
  final CPython 3.15 found`, so `kivyforge bytecompiler -p ios` reads as its
  fix.
- **One word, like the other verbs.** Nouns are already verbs here (`doctor`,
  `status`, `capabilities`), and no verb is hyphenated.
- **Nothing else in kivyforge it could mean.**

As a noun it doesn't say "install". That is acceptable because the command is
idempotent: it reports what it found, or installs when nothing qualifies. The
help line leads with the action: `Install a host CPython that byte-compiles for
the target, if none is found`.

Rejected:

| Name | Why not |
|---|---|
| `setup` | Promises "everything this project needs on this machine" and does one narrow thing. Too generic. |
| `doctor --fix` | `--fix` promises to fix any problem `doctor` reports, and this would fix exactly one. It would also turn `doctor` from a read-only check into something that downloads. |
| `python` | kivyforge already has three Pythons: the one it runs under, each platform's shipped runtime (which `status` shows), and the host interpreter. `kivyforge python -p ios` reads as the *iOS runtime*, the opposite of what it does. The bare word also reads as "run Python", as in `uv run python`. |
| `python install` (a group) | Mirrors `uv python install`, but is only worth it with `list` and `find` subcommands, which are more than this feature needs. It would also be kivyforge's first subcommand group. |
| `hostpython` | Literal, and familiar from python-for-android, but it doesn't explain itself in the error, and "host" is jargon to a user who wants their iOS build to work. |

Also considered and not shortlisted: `install` (collides with installing the
app on a device, which `run` does), `bootstrap` (collides with the Android
bootstrap), `provision` (generic, and close to Apple's provisioning profiles),
`compiler` and `install-compiler` (read as a C compiler next to Xcode and the
NDK), and hyphenated forms such as `install-python` (no verb is hyphenated).

## 5. Not in this change

- **`build` or `package` downloading anything.** That was the earlier draft.
  It stays rejected: a build should not fetch a toolchain unasked, and a flag on
  `build` would have to be passed on every CI run.
- **Asking yes/no at build time** ("Download a host Python? [y/N]"). Rejected
  2026-11-05. AGENTS.md's rule is that no verb waits for input, with `run`'s
  app launch the only exception, and this would break it:
  - **CI and scripts hang.** With no terminal attached, the build waits until
    the job times out, a worse failure than today's clear error.
  - **Behaviour depends on how it ran.** Prompting only at a terminal makes the
    same `package -p ios` download at a terminal and fail in CI.
  - **Agents can't answer.** An agent running `package --json` would block on a
    question it can't see, with stdout's single envelope unfinished.
  - **The answer needs a home.** Asking on every build nags; remembering the
    answer rebuilds the config key this proposal dropped, only hidden.
  - **A download mid-build.** Yes puts the network, and its failures, back
    into `build`, in the middle of staging.
  - **Escape hatches.** It would need `--yes`, `--no-input` and a CI check,
    three paths to test for one keystroke. The copy-paste command gets almost
    all of that keystroke's value.
- **A `--python X.Y` switch** that installs a given minor without reading a
  project. Dropped 2026-11-05 for lack of a use case:
  - **CI image baking** doesn't need it. A CI job checks out the project
    anyway, so `kivyforge bytecompiler -p ios` is one step there, and an image
    built ahead of any project can use `uv python install` or python.org.
  - **Outside a project** there is no build that needs byte-compiling.
  - **It can be wrong.** `--python 3.14` while the lock ships 3.15 installs
    something useless, and the same error comes back. Reading the version from
    the lock, as the build does, can't make that mistake.
  - **The flow it serves** is "a build failed, run the fix it printed", which
    happens in a project. Choosing a version by hand doesn't fit it.

  Dropping it also removed a rule (`-p` and `--python` exclusive) and a
  question (which form the error prints).
- **Using the installed Python for anything else** (resolving, building
  sdists). It compiles `.pyc` and nothing more.
- **Free-threaded or non-CPython hosts.** PBS's `install_only` default build is
  the standard one. The search's missing CPython check (`sys.implementation`) is
  a separate fix.

## 6. Steps

1. The verb (Q1): `-p`, `--force`, `--json`, and the no-`-p`
   platform walk (3.2), reading each lock's runtime version.
2. A host-triple helper (3.5).
3. A minor-wide PBS lookup (3.4, step 2) next to `GithubPbsMetadataFetcher`.
4. Download, verify, extract and probe (3.6), reusing `ArtifactCache` and
   `artifacts/verify.py`.
5. `pycompile`: the new search step (3.3), recorded in `searched`.
6. Failure classification (3.8); the `Fix:` line, `doctor` and `clean --cache`
   help (3.9).
7. `capabilities --json` lists the verb. Docs: the iOS and Android pyproject
   references, the hosts guide, and the CI guide's iOS recipe. CHANGELOG under
   `[Unreleased]`.

## 7. Test plan

**Hermetic** (no network, no toolchain):

- No `-p`: a project with iOS on 3.15 and Android on 3.14 asks for both minors;
  a platform with `byte_compile = false`, no lock, or a host that can't build it
  is skipped with an `INFO` diagnostic.
- `-p ios` asks only for iOS's minor.
- Outside a project, the command fails with exit 1, like other verbs.
- An interpreter found by the search means no download, and `source: "found"`.
- A fake fetcher: exact patch first, then the newest final of the minor, never
  a pre-release.
- A second run is `already-installed` and doesn't call the fetcher. `--force`
  does.
- The new search step finds the install ahead of `PATH` (Q2), and records it in
  `searched`.
- No network, rate limit, hash mismatch, no PBS build and an unsupported host
  each give exit 3 and their code.
- The message's `Fix:` line names `bytecompiler -p <platform>` and encodes as cp1252;
  `doctor`'s hint does too.
- stdout under `--json` is exactly one envelope, on success and on every
  failure (`tests/cli/test_build_package_json.py`'s pattern).

**Real toolchain** (logged in `test-matrix.md` §7):

- iOS: on a Mac with no `python3.15` on `PATH` and no uv, `package -p ios`
  fails with the new `Fix:` line; `bytecompiler -p ios` installs; `package` then
  compiles with the installed interpreter, the T3 stripped check passes, and the
  app boots on a device (`ios-strip-source`).
- Android: the same on an x86_64 Linux host, release APK on an emulator.
- A second `bytecompiler` with the network off reports `already-installed` and exits 0.

## 8. Migration

None. The verb is new, nothing in the project changes, and no lock goes stale.
A machine that already has the right Python is unaffected.

## 9. Done when

- Section 4's remaining questions are decided and recorded here.
- The hermetic tests in section 7 pass, and the iOS real-toolchain run is in
  `test-matrix.md` §7.
- #209 is answered, pointing at the command.

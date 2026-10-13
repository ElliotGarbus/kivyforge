# Proposal — dynamic `[project].version`

> Status: **proposal, 2026-10-12. Not implemented.** Written for
> [issue #111](https://github.com/ElliotGarbus/kivyforge/issues/111). Code
> claims were read from the source on branch `pyjnius-no-version-ceiling`
> (`fc8ce40e`); line numbers are as of that commit. The pip behaviour in
> section 3.3 was measured on macOS on the same date; section 7 has the runs.

A project that gets its version from git through setuptools-scm (or hatch-vcs,
versioningit, ...) declares no version string at all:

```toml
[build-system]
requires = ["setuptools", "setuptools-scm"]
build-backend = "setuptools.build_meta"

[project]
name = "myapp"
dynamic = ["version"]
```

kivyforge refuses that project before any verb runs:

```
$ uv run kf lock -p android
Error: missing or empty [project].version (line 5)
```

The conclusion: **have pip ask the project's build backend for the version,
and do it only in the verbs that write the version into an artifact. An
explicit override comes first.** Section 3 is the design; sections 1 and 2
explain why it has to be this one.

## 1. What `dynamic` means, and what that rules out

PEP 621 says that a field named in `[project].dynamic` is supplied by the build
backend, and that tools other than the backend must not infer it. The version
does not exist until the backend runs. For setuptools-scm it is a function of
the git state (latest tag, distance from it, dirty tree) and comes out like
`1.2.4.dev3+g1a2b3c`.

Every standards-following consumer gets it the same way. pip, `build` and uv
call the backend's PEP 517 `prepare_metadata_for_build_wheel` hook and read the
`Version:` line from the METADATA file it writes.

That rules out two shortcuts:

- **Running `git describe` ourselves.** That reimplements one backend's
  algorithm (tag regex, dev-distance format, local segment, dirty marker) and
  would disagree with what `pip wheel .` produces for the same tree.
- **Importing setuptools-scm directly, or shipping it as a kivyforge
  dependency.** That covers one backend; hatch-vcs, versioningit, pdm-backend
  and the rest would each need the same. A pinned copy can also disagree with
  the version range the project's `[build-system].requires` asks for, and it
  costs every user with a static version an install they never use.

## 2. Where the version is used today

| Consumer | Site | Needs |
|---|---|---|
| Android `versionName` | `platforms/android/generate/project.py:287` | Any string |
| Android `version_code = "auto"` | `config/loader.py:1386-1437` | Final `MAJOR.MINOR.PATCH`; rejects pre/dev/post/local |
| iOS `CFBundleShortVersionString` | `platforms/ios/plist.py:46` | Up to three dot-separated integers (Apple) |
| macOS `CFBundleShortVersionString` | `platforms/macos/plist.py:25` | Same |
| Windows resource `ProductVersion` / `FILEVERSION` | `platforms/windows/bundle.py:287` | String, plus four-part numeric via `pep440_to_file_version` |
| Windows doctor resource check | `platforms/windows/doctor.py:326` | Display only |
| Linux / Windows artifact filenames | `platforms/linux/cli.py:109`, `platforms/windows/cli.py:138` | A filename-safe string |

Three facts follow from this table:

1. **`lock` does not use the version.** The error in the issue fires only
   because `_parse_project` (`config/loader.py:330`) validates every
   `[project]` field for every verb. Lock drift is `pyproject_sha256`
   (`lock/reader.py:32`), and a git-derived version never touches
   `pyproject.toml`. So a dynamic version changing on every commit causes **no**
   re-lock churn, which is a real improvement over a static version a user
   bumps by hand.
2. **`version_code = "auto"` is computed at config-load time.** It is folded
   into `AndroidConfig.version_code` inside the loader (`loader.py:1229`), so a
   version that is resolved later has to recompute it too. It cannot just
   overwrite one string field.
3. **The Apple plists pass the raw string through today.** A static
   `version = "1.0rc1"` already produces a `CFBundleShortVersionString` that
   App Store Connect rejects. Nobody has hit this because hand-written versions
   are usually final. Between tags, setuptools-scm versions are *never* final,
   so dynamic versions turn this latent bug into the common case. Section 3.5
   covers it.

## 3. Design

### 3.1 Parsing: accept `dynamic`, defer the value

`_parse_project` accepts `"version"` in `[project].dynamic` and leaves the value
unresolved. `ProjectMeta` gains a field recording that:

```python
version: str | None          # None only when version_dynamic
version_dynamic: bool = False
```

These stay config errors (exit 1, as today):

- `version` neither set nor listed in `dynamic`. The message is today's, with a
  hint that names `dynamic = ["version"]`.
- `version` both set *and* listed in `dynamic`. PEP 621 forbids this, and
  silently picking one would hide the mistake.

**Related hole, closed in the same change.** Today a project with
`dynamic = ["dependencies"]` parses as having *no* dependencies
(`deps = project.get("dependencies", [])`), and `lock` writes a lock that is
silently empty. That is the silent-wrong failure `AGENTS.md` warns about. Any
`dynamic` entry kivyforge consumes but cannot resolve (`dependencies`, `name`,
`requires-python`) becomes a config error that names the field. Only `version`
gets the backend path. The others change the lock, and resolving them would
mean running the backend at lock time.

### 3.2 Resolution order

One function, called once per invocation by the verbs that need it:

| # | When | Version |
|---|---|---|
| 1 | `--app-version X` on the command line, or `KIVYFORGE_APP_VERSION=X` | `X`, verbatim; nothing else is read |
| 2 | `[project].version` is set | That string (today's behaviour) |
| 3 | `"version"` is in `[project].dynamic` | The backend computes it, run by pip (section 3.3) |

Row 1 is the release-pipeline path, and the offline path. A CI job that
already knows the tag should not depend on the checkout depth or the network.
Every scm plugin offers the same escape hatch for the same reason
(`SETUPTOOLS_SCM_PRETEND_VERSION` and friends), and those keep working under
row 3 because the backend reads them itself. Row 1 adds a kivyforge spelling
that works the same way for every backend.

**Decided 2026-10-12: the flag is `--app-version`.** It must not be
`--version`, which by click convention prints kivyforge's own version.

The override must be a valid PEP 440 version (`packaging.version.Version`), or
it is a config error. This catches `v1.2.3` pasted from a tag name.

**Which verbs resolve:** `build`, `package` and `run`, because each builds an
artifact that carries the version. `run` resolves on every launch, since every
launch rebuilds (`cli/run.py:104`). `run --no-build` does not resolve: it builds
nothing, and the build tree it launches has no version in its path (the
versioned paths at `linux/cli.py:109` and `windows/cli.py:138` are `package`'s). **Never** `lock`, `status`,
`clean`, `capabilities` or `init`. `doctor` does not run the backend; see
section 3.6.

### 3.3 Calling the backend: through pip

kivyforge does not call the backend itself. It asks pip to prepare the
project's metadata without installing anything, and reads the version from
pip's JSON installation report:

```
<python> -m pip install --dry-run --ignore-installed --no-deps --quiet
                        --report - [--no-build-isolation] <project_root>
```

The version is `install[0].metadata.version` in the document pip writes to
stdout. `<python>` is `sys.executable`, the same interpreter `lock` already
runs `-m pip` with.

**Why pip, not a hook library.** The obvious design is to call
`prepare_metadata_for_build_wheel` directly (with `pyproject_hooks`) in
kivyforge's own interpreter. It fails in the common installs:

- Under `uv tool install kivyforge` or pipx, kivyforge has a private
  environment that contains kivyforge's dependencies and nothing of the
  project's. The backend (`setuptools_scm`) is not importable there.
- Under `uv run kf` (the reporter's setup), the project's `.venv` usually does
  not contain it either. uv installs `[build-system].requires` into a
  temporary build environment, not into `.venv`. This repo's own `.venv`
  confirms it: `import setuptools_scm` fails there (section 7).

pip already solves exactly this problem. With build isolation it creates a
temporary environment, installs `[build-system].requires` at the versions the
project asks for, and runs the hook there. That makes it independent of how
kivyforge was installed and of which backend the project uses. kivyforge
already requires `pip>=25.1` (`pyproject.toml`), so this adds no dependency.

**Two modes, chosen by a cheap check.** Before calling pip, check
`[build-system].requires` against `importlib.metadata` in kivyforge's
interpreter:

- **All satisfied → `--no-build-isolation`.** pip runs the backend in the
  current environment: no network, about 0.4 s (section 7). This is the case
  for a user who ran `uv tool install kivyforge --with setuptools-scm`, and
  the error message in section 3.7 suggests exactly that.
- **Anything missing → isolated (the default).** pip fetches the backend from
  the configured index, about 1.2 s with a warm pip cache (section 7). The
  first run needs the network.

**No `[build-system]` table:** pip applies PEP 517's default
(`setuptools.build_meta:__legacy__`) itself, so kivyforge does not special-case
it. The requirements check treats it as `setuptools>=40.8.0`, which is what pip
assumes.

**The repo's process rules:**

- The pip subprocess gets `stdin=DEVNULL` (nothing waits for input).
- Its stdout is **captured**: it is the JSON report, and under `--json`
  kivyforge's stdout must be exactly one envelope. Its stderr is captured too.
  On failure, the tail goes into the error message. On success it is dropped,
  and shown on stderr under `--verbose`.
- **The project tree must be left as it was found.** An isolated run writes
  `<name>.egg-info/` into the project's package root: the project root for a
  flat layout, `src/` for a src layout. A non-isolated run writes nothing.
  The cause: with isolation, pip calls the backend's
  `get_requires_for_build_wheel` hook to learn what else to install into the
  build environment, and setuptools implements that hook by running a plain
  `egg_info` command in the project. `prepare_metadata_for_build_wheel` keeps
  its egg-info in the metadata directory pip hands it. Without isolation pip
  installs nothing, so it never calls the first hook.
  `tests/test_pip_metadata_live.py` pins all of this (section 7). So
  kivyforge lists `*.egg-info` in the project root and its immediate
  subdirectories before the call, removes any that appeared during it, and
  never removes one that was already there. Running pip on a copy of the
  project does not work, because the scm plugin needs the git history. This is
  the same directory `pip install .` leaves behind for any setuptools project,
  so many projects already gitignore it, but kivyforge should not count on that.

  What the cleanup does and does not promise:

  - **"As found" means no folder added, not no file changed.** An `egg-info`
    that existed before the call is kept, but an isolated run's `egg_info` step
    rewrites the files inside it (`PKG-INFO` gets the current version), exactly
    as any `pip install .` would. A non-isolated run does not touch it.
  - **A concurrent writer can lose its folder.** Anything that creates an
    `egg-info` in the same places during the 0.4–1.2 s pip call (the user
    running `pip install -e .` or `uv sync` in the project at the same moment)
    is indistinguishable from pip's and gets removed. Accepted: it is unlikely;
    a PEP 660 editable install keeps its metadata in the environment, not in
    that folder; and a legacy `setup.py develop` install recreates it on its
    next install.
  - **Removal is best-effort.** The version is already resolved when cleanup
    runs, so a failed delete (on Windows, antivirus or the indexer briefly
    holding a new file) is a WARNING that names the folder, never a failed
    build. A leftover folder cannot reach the artifact either: every app copy
    excludes `*.egg-info` (a separate change, made because the user's own
    `pip install -e .` already put one there).
  - **setuptools-scm's `version_file` is written too, and is kept.** A project
    with `[tool.setuptools_scm] version_file = "src/myapp/_version.py"` gets
    that file (re)written by the backend in **both** modes (measured, section
    7). It usually sits inside `app_dir`, so it ships, carrying the same
    version kivyforge resolved. That is wanted: inside a bundle it is the way
    the app can know its own version, because `importlib.metadata` cannot work
    there (the app is not installed as a distribution). The cleanup removes
    only `*.egg-info`, so it never touches this file.
  - **Order:** resolution and cleanup finish before anything copies `app_dir`.
    Resolution runs at the start of the verb, so this holds by construction;
    it is stated so a later refactor keeps it.

**Index configuration.** pip honours `pip.conf` and `PIP_INDEX_URL`, which is
what `lock` relies on today. uv's `[tool.uv.index]` is not read. A project that
fetches its build backend from a private index only through uv configuration
must set pip's index too, or use row 1. The docs say so.

**Cache:** none across invocations. The answer depends on git state that
kivyforge does not track.

### 3.4 After resolution

The resolved string replaces `ProjectMeta.version` through `dataclasses.replace`,
and `version_code = "auto"` is recomputed from it with the existing
`_parse_android_version_code` rules. Every consumer in section 2 then reads a
plain `str` exactly as it does today. Only `ProjectMeta` and the loader learn
that versions can be dynamic, and no backend changes.

The verb reports what it used, because the user never typed this version:

- **Human:** one stderr line before the build starts:
  `Version 1.2.4.dev3+g1a2b3c (from setuptools.build_meta, via pip)`.
- **`--json`:** `data.version = {"value": "...", "source": "override" |
  "static" | "backend"}`. This is additive to the envelope, so no schema bump.

The echo is also the only defence against the most common scm surprise: a
shallow CI checkout (`actions/checkout` defaults to `fetch-depth: 1`) has no
tags, and setuptools-scm then reports something like `0.1.dev1+g...`. kivyforge
cannot tell that from a real version and should not try. Printing it makes it
visible, and the docs say to use `fetch-depth: 0` or row 1.

### 3.5 Store-facing fields

The full PEP 440 string stays the *display* version: Android `versionName`, the
Windows string `ProductVersion`, and the artifact filename. Each store field
that has its own grammar gets a derived value:

| Field | Rule |
|---|---|
| Android `versionCode` (`"auto"`) | Unchanged. Already refuses non-final versions with a hint to set an integer. A dev version with `auto` therefore fails `build`, which is correct: Play rejects a non-monotonic code. |
| Apple `CFBundleShortVersionString` | `release[:3]` joined with dots (e.g. `1.2.4`). When that drops a pre/dev/post/local segment, emit a **WARNING** diagnostic (new code, below) that names both strings. Applies to static versions too, which fixes latent bug 3 in section 2. |
| Windows `FILEVERSION` | Unchanged; `pep440_to_file_version` already handles every segment. |
| Filenames | Replace `+` with `_`. `+` is legal on every filesystem but becomes a space in a URL query string and trips naive upload scripts. |

The Apple warning says the version was reduced, not that the build is wrong. A
dev build for the simulator is a normal thing to make, so `ok` stays `true`.

### 3.6 `doctor`

A new common check, **Version**, that never runs the backend or pip:

- Static: PASS, with the value.
- Dynamic, `[build-system].requires` installed in kivyforge's interpreter:
  PASS, `dynamic via setuptools.build_meta (resolved offline at build time)`.
- Dynamic, requirements not installed: PASS with a note,
  `dynamic via setuptools.build_meta (pip will fetch the backend at build
  time; needs network)`. Not a WARN: this is the normal state under
  `uv tool` and pipx, and it works.

The Windows resource check (`doctor.py:326`) shows `dynamic` instead of a value.

### 3.7 Failure classification

New codes in `report/diagnostics.py`:

| Code | Exit | When |
|---|---|---|
| `KF-VERSION-UNRESOLVED` | 1 (config) | pip exited non-zero, or its report has no version. The message carries pip's captured stderr tail; `context` names the `backend` and whether the run was `isolated`. Remediation: fix the project's scm setup (not a git checkout, no tags, shallow clone), or pass `--app-version`; when isolated, also "needs network to fetch the build backend, or `uv tool install kivyforge --with <backend requirements>`". |
| `KF-VERSION-REDUCED` | — (WARNING) | The Apple short version dropped segments (section 3.5). `context`: `version`, `reduced`. |

pip not being able to start at all is already covered: `spawn_failure("pip",
exc)` gives `KF-TOOLCHAIN-MISSING` / exit 3, as for `lock`.

**One code, exit 1, on purpose.** An isolated run that fails because the index
is unreachable is a machine problem (exit 3), and one that fails because the
project is not a git checkout is a config problem (exit 1). From outside, the
only way to tell them apart is pip's stderr wording, which is not a contract
(measured: `Failed to build ... when installing build dependencies`, section 7).
Classifying on it would be right today and silently wrong after a pip release.
An unspecific code is never wrong; the remediation names both causes. If agents
need the split later, add `KF-VERSION-BACKEND-UNAVAILABLE` (exit 3) keyed on
that phrase, with a test that pins the pip version it was observed on.

`KF-VERSION-UNRESOLVED` is exit 1, not 5: it happens before any build tool
runs, and the fix is not in a build log.

## 4. Dependencies

None added. pip is already a runtime dependency (`pip>=25.1`), and
`--dry-run --report` has been in pip since well before that floor. The earlier
draft of this note added `pyproject_hooks`; going through pip makes that
unnecessary.

## 5. Open questions

1. **`--app-version` and a static version leave `version_file` stale.** Rows 1
   and 2 of section 3.2 never run the backend, so a project's
   `src/myapp/_version.py` keeps whatever the last backend run wrote, and the
   app reports a different version than its plist, `versionName` or file
   name. Options: run the pip call anyway under row 1 with
   `SETUPTOOLS_SCM_PRETEND_VERSION=<override>` (setuptools-scm only, and pays
   the pip cost the override was meant to skip); warn when a `version_file`
   is configured and disagrees with the version used; or document it.
   Recommendation: the warning. It is cheap, works for every backend that
   writes such a file, and never changes the user's tree behind their back.

The earlier question, why only the isolated run leaves `*.egg-info`, is
answered in section 3.3.

## 6. Verification plan

- **Hermetic:** the resolver takes the pip runner as a parameter, so tests
  inject a fake. Cover: the three precedence rows; set-and-dynamic both;
  dynamic `dependencies` rejected; `lock` and `run --no-build` never call
  pip; isolated vs `--no-build-isolation` chosen
  from the requirements check; pip non-zero → `KF-VERSION-UNRESOLVED` and
  exit 1; pip missing → `KF-TOOLCHAIN-MISSING` and exit 3; `--json` stdout
  still one envelope; a new `*.egg-info` removed and a pre-existing one kept;
  `version_code = "auto"` recomputed from a resolved version; Apple reduction
  warning; `+` in filenames.
- **pip and setuptools behaviour (exists):** `tests/test_pip_metadata_live.py`,
  opt-in with `--pip-metadata-live` (needs git and network). It pins what the
  design assumes, not kivyforge code: both modes report the scm version, the
  isolated mode writes egg-info (flat and src layouts) and the non-isolated
  mode does not, and the `get_requires_for_build_wheel` hook is the cause. If
  a pip or setuptools release changes any of it, this test is where that
  shows. It belongs in a CI job that passes the flag.
- **Integration (`integration` marker):** a temp git repo with a real
  setuptools-scm project, run through real pip both ways, via kivyforge's
  resolver. Tag `v1.2.3` gives
  `1.2.3`; one commit past it gives `1.2.4.dev1+g...`; no git gives
  `KF-VERSION-UNRESOLVED`; the project root is unchanged afterwards. Needs
  network, so it belongs in the integration job, not the hermetic suite.
- **Install modes:** one dated run each under `uv tool install kivyforge`,
  pipx, and `uv run kf` in a uv project, logged in `test-matrix.md` §7.
- **Real toolchain:** one dated row per platform in `test-matrix.md` §7,
  confirming the plist / `versionName` / resource version on a built artifact
  from a dynamic-version example.
- **Docs:** the user-facing config page gets the precedence table, the
  network note for the first build, `--with setuptools-scm` for offline use,
  the pip-index note, `fetch-depth: 0` for CI, and the Apple reduction rule.
  CHANGELOG under `[Unreleased]`: dynamic versions are accepted,
  `--app-version` is new, and Apple short versions are now reduced to
  `MAJOR.MINOR.PATCH` (a behaviour change for anyone shipping a static
  pre-release version today).

## 7. Measurements (2026-10-12, macOS, pip from kivyforge's dev `.venv`)

Test project: the `pyproject.toml` at the top of this note with an empty
`[tool.setuptools_scm]` table, `git init`, tag `v1.2.3`, then one more commit.

| Run | Environment | Result | Time | Left in project root |
|---|---|---|---|---|
| Isolated (default) | kivyforge `.venv`; `import setuptools_scm` fails there | `1.2.4.dev1+g6c836d1e9` | 1.24 s (warm pip cache) | `myapp.egg-info/` |
| `--no-build-isolation` | Fresh venv with `setuptools` and `setuptools-scm` installed | `1.2.4.dev1+g6c836d1e9` | 0.38 s | nothing |
| Isolated, `--index-url http://127.0.0.1:9/simple` (unreachable index) | Same fresh venv | exit 1; `ERROR: Failed to build '...' when installing build dependencies` | — | — |

Same day, `tests/test_pip_metadata_live.py --pip-metadata-live` (pip 26.2.1,
setuptools 84.0.0, setuptools-scm 10.3.4, Python 3.14.7): 5 passed in 6.4 s.
That confirms the rows above, adds the src layout (the isolated run writes
`src/myapp.egg-info`), and shows the cause directly: calling
`get_requires_for_build_wheel` in the project writes `myapp.egg-info`, and
`prepare_metadata_for_build_wheel` alone does not.

Same day, by hand: with `version_file = "myapp/_version.py"` added to
`[tool.setuptools_scm]`, the isolated run left `myapp.egg-info/` and
`myapp/_version.py`; the non-isolated run left only `myapp/_version.py`, which
holds the resolved version.

Not yet measured: a cold pip cache, Windows, Linux, and a project with no git
history.

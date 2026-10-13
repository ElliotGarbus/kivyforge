# Proposal — dynamic `[project].version`

> Status: **proposal, revised 2026-10-12 after review. Not implemented.**
> Written for [issue #111](https://github.com/ElliotGarbus/kivyforge/issues/111).
> Code claims were read from the source at `70573b79` (`main`); line numbers are
> as of that commit. The pip behaviour was measured on macOS on the same date;
> section 8 has the runs. Section 7 records what the review changed and why.

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

The conclusion: **have pip ask the project's build backend for the version, in
an isolated build environment, once per invocation, only in the verbs that
build an artifact, and hand the result to the backend as a value.** An explicit
`--app-version` comes first. Section 3 is the design; sections 1 and 2 explain
why it has to be this one.

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

Four facts follow from this table and the code around it:

1. **`lock` does not use the version.** The error in the issue fires only
   because `_parse_project` (`config/loader.py:330`) validates every
   `[project]` field for every verb. Lock drift is `pyproject_sha256`
   (`lock/reader.py:32`), and a git-derived version never touches
   `pyproject.toml`. So a dynamic version changing on every commit causes **no**
   re-lock churn, which is a real improvement over a static version a user
   bumps by hand.
2. **`version_code = "auto"` is computed at config-load time.** It is folded
   into `AndroidConfig.version_code` inside the loader (`loader.py:1229`), so it
   depends on the version and has to move with it.
3. **The Apple plists pass the raw string through today.** A static
   `version = "1.0rc1"` already produces a `CFBundleShortVersionString` that
   App Store Connect rejects. Nobody has hit this because hand-written versions
   are usually final. Between tags, setuptools-scm versions are *never* final,
   so dynamic versions turn this latent bug into the common case. Section 3.6
   covers it.
4. **Backends load their own configuration.** `Platform.build`, `package` and
   `run` (`platforms/base.py:91-121`) take `project_root`, and each backend's
   `cli.py` calls `load_config` itself (e.g. `platforms/windows/cli.py:378`).
   A version resolved in the verb therefore has no way into the backend unless
   the interface carries it. Section 3.4.

## 3. Design

### 3.1 Parsing: a declared version, not a missing one

`_parse_project` accepts `"version"` in `[project].dynamic`. The parsed config
records a **declaration**, not a value:

```python
@dataclass(frozen=True)
class StaticVersion:
    value: str               # validated PEP 440, see below

@dataclass(frozen=True)
class DynamicVersion:
    backend: str             # [build-system].build-backend, for messages

DeclaredVersion = StaticVersion | DynamicVersion
```

`ProjectMeta.version` becomes `DeclaredVersion`. It is **not** `str | None`:
that would push a `None` check into every generator, and a forgotten one would
write `None` into a plist. No generator reads `ProjectMeta.version` any more;
they read the resolved value of section 3.4, so the type system enforces that a
version was resolved before anything is built.

**Android's `version_code` stays unresolved through config load too.** Today
`AndroidConfig.version_code` is an `int` computed inside the loader (fact 2),
and `doctor`, `status`, `clean` and `lock` all load that config. With a dynamic
version there is nothing to compute it from at load time, and those verbs must
keep working. So the field becomes a declaration as well:

```python
@dataclass(frozen=True)
class AutoVersionCode:
    build: int     # the [tool.kivy.android].build counter
    line: int | None  # where version_code = "auto" sits in pyproject.toml

AndroidConfig.version_code: int | AutoVersionCode
```

An explicit integer is still validated at load time, as today. `"auto"` is
computed during resolution (section 3.4) by the existing
`_parse_android_version_code` rules, and its errors keep today's messages
**and the `version_code` line number** from the file, which is why the
declaration carries `line`. The only reader of the computed value is the
Android project generator (`platforms/android/generate/project.py:286`), which
takes it from `ResolvedVersion`. `version_code_auto` disappears: the type says
it.

The same reasoning is why `"version"` in `dynamic` must parse for **every**
verb. Resolution stays limited to `build`, `package` and `run`.

These are config errors (exit 1):

- `version` neither set nor listed in `dynamic`. Today's message, with a hint
  that names `dynamic = ["version"]`.
- `version` both set *and* listed in `dynamic`. PEP 621 forbids it, and
  silently picking one would hide the mistake.
- `dynamic` present but not a list of strings.

**A static `version` that is not valid PEP 440 keeps working.** Today any
non-empty string is accepted (`loader.py:330`), and that stays: it is written
through unchanged everywhere it is written today, Windows' numeric resource
still degrades to `0.0.0.0`, and `version_code = "auto"` still refuses it.
Rejecting it would be standards-aligned (PEP 621 requires PEP 440, and pip
refuses such a project), but it would break existing projects for no gain to
the dynamic case. Instead the build emits `KF-VERSION-NOT-PEP440` (WARNING),
because the stores may reject what is written. Only `--app-version` and
`KIVYFORGE_APP_VERSION` are validated as PEP 440, since they are new.

**Other dynamic fields kivyforge reads are errors.** The loader reads six
`[project]` fields: `name`, `version`, `dependencies`, `authors`,
`description` and `requires-python`. Today a dynamic one silently parses as
absent: `dependencies` as none, so `lock` writes an empty lock; `description`
as none, so the Linux `.desktop` file has no `Comment=`
(`platforms/linux/desktop.py:30`); `authors` as none, so the Windows resources
have no company or copyright (`platforms/windows/bundle.py:277`). Each of those
is the silent-wrong failure `AGENTS.md` warns about. Any of the five other than
`version` listed in `dynamic` becomes a config error naming the field. Dynamic
fields kivyforge never reads (`readme`, `classifiers`, `entry-points`, ...)
stay allowed. Only `version` gets the backend path: the others either change
the lock or are not worth a backend run.

### 3.2 Resolution order

| # | When | Version |
|---|---|---|
| 1 | `--app-version X` on `build`, `package` or `run`; else `KIVYFORGE_APP_VERSION=X`. **The flag wins** when both are set | `X`; nothing else is read |
| 2 | `StaticVersion` | Its value (today's behaviour) |
| 3 | `DynamicVersion` | The backend computes it, run by pip (section 3.3) |

Row 1 is the release-pipeline path and the offline path. A CI job that already
knows the tag should not depend on the checkout depth or the network. Every scm
plugin offers the same escape hatch for the same reason
(`SETUPTOOLS_SCM_PRETEND_VERSION` and friends), and those keep working under
row 3 because the backend reads them itself. Row 1 is the kivyforge spelling
that works the same way for every backend. The override must be valid PEP 440,
or it is a config error; this catches `v1.2.3` pasted from a tag name.

**Decided 2026-10-12: the flag is `--app-version`.** It must not be
`--version`, which by click convention prints kivyforge's own version. It is
declared on the `build`, `package` and `run` commands only, not on the shared
group: there, `lock --app-version` would be accepted and silently ignored.

**Which verbs resolve:** `build`, `package` and `run`, because each builds an
artifact that carries the version. `run` resolves on every launch, since every
launch rebuilds (`cli/run.py:104`). **Never** `lock`, `status`, `clean`,
`capabilities` or `init`. `doctor` does not run the backend (section 3.7).

**`run` modes that build nothing do not resolve, and reject the flag.**
`run --no-build` launches the build tree as it is, and `run --list-devices`
lists devices; neither produces anything that carries a version. An explicit
`--app-version` with either is a usage error rather than silently ignored,
because the user evidently expected it to do something. `KIVYFORGE_APP_VERSION`
in the environment is ambient, so it is ignored there, not an error.

### 3.3 Calling the backend: through pip, isolated

kivyforge does not call the backend itself. It asks pip to prepare the
project's metadata without installing anything, and reads the version from
pip's JSON installation report:

```
<python> -m pip install --dry-run --ignore-installed --no-deps --quiet
                        --report - <project_root>
```

The version is `install[0].metadata.version` in the document pip writes to
stdout. `<python>` is `sys.executable`, the same interpreter `lock` already
runs `-m pip` with.

`--ignore-installed` matters under `uv run kf`, where the project is normally
installed (often editable) in the very interpreter pip runs in. Without it,
pip could treat the project as already satisfied and report the installed copy,
or nothing, instead of the tree. Measured with pip 26.2.1 (section 8), pip
re-reads a local directory either way, so today the flag is a safeguard, not a
fix. It is kept because nothing in pip promises that.

**Why pip, not a hook library.** Calling `prepare_metadata_for_build_wheel`
directly (with `pyproject_hooks`) in kivyforge's own interpreter fails in the
common installs. Under `uv tool install kivyforge` or pipx, kivyforge's private
environment does not contain the backend. Under `uv run kf` the project's
`.venv` usually does not either, because uv installs `[build-system].requires`
into a temporary build environment, not into `.venv`; this repo's own `.venv`
confirms it (section 8). pip already solves this: with build isolation it
creates a temporary environment, installs what the project's build needs, and
runs the hook there, independent of how kivyforge was installed and of which
backend the project uses. kivyforge already requires `pip>=25.1`, so this adds
no dependency.

**Always isolated by default.** An earlier draft switched to
`--no-build-isolation` automatically whenever `[build-system].requires` was
already installed. That is unsound. An isolated pip also calls the backend's
`get_requires_for_build_wheel` hook and installs whatever it returns
(setuptools returns `setup_requires`); a non-isolated pip calls neither. So
"`[build-system].requires` is satisfied" does not mean "the build has what it
needs", and the failure is not always loud. Measured (section 8): a project
that gets setuptools-scm through `setup_requires` in `setup.py`, built
non-isolated in an environment with only setuptools, makes pip **exit 0 and
report `0.0.0`**. setuptools never loads the plugin, ignores
`use_scm_version`, and falls back to its default. Isolated, the same project
reports `1.2.3`.

**Non-isolated is explicit opt-in.** `--no-build-isolation` on `build`,
`package` and `run` (pip's own name, so its meaning is already known) passes
through to pip. It is for users who need offline builds and vouch that
kivyforge's environment holds everything the backend needs, e.g.
`uv tool install kivyforge --with setuptools-scm`. It is faster (about 0.4 s
against 1.2 s, section 8) and needs no network. The docs carry the `0.0.0`
hazard above. kivyforge does not try to detect it: `0.0.0` is also a legitimate
version.

**No `[build-system]` table:** pip applies PEP 517's default
(`setuptools.build_meta:__legacy__`) itself, so kivyforge does not special-case
it.

**The repo's process rules:**

- The pip subprocess gets `stdin=DEVNULL` (nothing waits for input).
- Its stdout is **captured**: it is the JSON report, and under `--json`
  kivyforge's stdout must be exactly one envelope. Its stderr is captured too.
  On failure, the tail goes into the error message. On success it is dropped,
  and shown on stderr under `--verbose`.

**Index configuration.** pip honours `pip.conf` and `PIP_INDEX_URL`, which is
what `lock` relies on today. uv's `[tool.uv.index]` is not read. A project that
fetches its build backend from a private index only through uv configuration
must set pip's index too, or use row 1. The docs say so.

**Cache:** none across invocations. The answer depends on git state that
kivyforge does not track.

### 3.4 Getting the version to the backend

Fact 4: backends take `project_root` and load configuration themselves. The
flow becomes two-phase, with the version as a value that crosses the interface:

1. **Declare.** The verb loads the config as today. `ProjectMeta.version` is a
   `DeclaredVersion` (section 3.1).
2. **Resolve, once.** The verb calls `resolve_version(declared, project_root,
   override=..., isolated=...)`, which returns a `ResolvedVersion`. This is the
   only place pip runs.
3. **Finalise.** `ResolvedVersion` carries every version-derived value, each
   computed and validated once:

   ```python
   @dataclass(frozen=True)
   class ResolvedVersion:
       value: str                 # full PEP 440 string
       source: Literal["override", "static", "backend"]
       apple_short: str           # section 3.6
       windows_file_version: str  # pep440_to_file_version(value)
       filename_part: str         # value with "+" -> "_"
       android_version_code: int | None  # "auto" or explicit; None off Android
       warnings: tuple[Diagnostic, ...]  # KF-VERSION-REDUCED, if any
   ```

   An `"auto"` version code that cannot be derived (a dev version, say) fails
   here, in the verb, before any backend work starts, with today's message.
4. **Pass it in.** `Platform.build`, `package` and `run` gain a keyword-only
   `version: ResolvedVersion`. For `run` it is `ResolvedVersion | None`, `None`
   exactly when nothing is built (`--no-build`, `--list-devices`). The backend
   threads it to the version consumers of section 2, which take it as a
   parameter instead of reading `config.project.version`.

This keeps the backends' own `load_config` calls; replacing those with a config
passed down from the verb is a worthwhile refactor, but it is not needed for
this feature, and coupling the two would make this change much
larger. What it does guarantee: one resolution per invocation, a version that
is typed as resolved wherever it is used, and no backend that can quietly fall
back to the declaration.

### 3.5 Reporting the version

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

### 3.6 Store-facing fields

The full PEP 440 string stays the *display* version: Android `versionName`, the
Windows string `ProductVersion`, and the artifact filename. Each store field
with its own grammar gets a derived value:

| Field | Rule |
|---|---|
| Android `versionCode` (`"auto"`) | Unchanged rules. Already refuses non-final versions with a hint to set an integer, so a dev version with `auto` fails, which is correct: Play rejects a non-monotonic code. |
| Apple `CFBundleShortVersionString` | `release[:3]` joined with dots (`1.2.4`). One rule for the warning: emit **`KF-VERSION-REDUCED`** (WARNING) naming both strings **whenever the string written differs from the version**. That covers every loss without listing them: `1.0rc1`, `1.2.4.dev3+gabc`, `1.2.3.4` (fourth component), `1!2.0.0` (epoch). Applies to static versions too, which fixes fact 3. A version that is not PEP 440 (section 3.1) is written through unchanged, as today, and gets `KF-VERSION-NOT-PEP440` instead. |
| Windows `FILEVERSION` | Unchanged; `pep440_to_file_version` already handles every segment, and still degrades a non-PEP 440 version to `0.0.0.0`. |
| Filenames | Replace `+` with `_`. `+` is legal on every filesystem but becomes a space in a URL query string and trips naive upload scripts. This renames the artifact for a **static** local version too (`1.0+local`), so it gets a CHANGELOG entry. |

The Apple warning says the version was reduced, not that the build is wrong. A
dev build for the simulator is a normal thing to make, so `ok` stays `true`.
App Store Connect distinguishes uploads by `CFBundleVersion` (the `build`
counter), not by the short version, so two dev builds reducing to the same
`1.2.4` do not collide.

### 3.7 `doctor`

A new common check, **Version**, that never runs pip:

- Static: PASS, with the value.
- Dynamic: PASS, `dynamic via setuptools.build_meta (resolved at build time;
  the first build needs network)`.

The Windows resource check (`doctor.py:326`) shows `dynamic` instead of a value.
An earlier draft also checked whether the backend was installed locally; with
isolation as the default that no longer predicts anything.

### 3.8 Failure classification

New codes in `report/diagnostics.py`:

| Code | Exit | When |
|---|---|---|
| `KF-VERSION-UNRESOLVED` | 1 (config) | pip exited non-zero, or its report has no version. The message carries pip's captured stderr tail; `context` names the `backend` and whether the run was `isolated`. Remediation: fix the project's scm setup (not a git checkout, no tags, shallow clone), check network access to the package index, or pass `--app-version`. |
| `KF-VERSION-REDUCED` | — (WARNING) | The Apple short version differs from the version (section 3.6). `context`: `version`, `reduced`. |
| `KF-VERSION-NOT-PEP440` | — (WARNING) | A static version is not PEP 440; written through unchanged (section 3.1). `context`: `version`. |
| `KF-VERSION-FILE-NOT-REFRESHED` | — (WARNING) | `[tool.setuptools_scm].version_file` is configured, but the version came from row 1 or 2, so the backend did not rewrite it (section 3.9). `context`: `path`. |

The new codes need no wiring into `capabilities`: it publishes every
module-level code string in `report/diagnostics.py`. `data.version` needs no
schema bump: `report/envelope.py` bumps only for a non-additive change, and a
new `data` key is additive.

pip not being able to start at all is already covered: `spawn_failure("pip",
exc)` gives `KF-TOOLCHAIN-MISSING` / exit 3, as for `lock`. An invalid
override is an ordinary config error (exit 1); an invalid static version is a
warning (section 3.1).

**One code, exit 1, on purpose.** An isolated run that fails because the index
is unreachable is a machine problem (exit 3), and one that fails because the
project is not a git checkout is a config problem (exit 1). From outside, the
only way to tell them apart is pip's stderr wording, which is not a contract
(measured: `Failed to build ... when installing build dependencies`, section 8).
Classifying on it would be right today and silently wrong after a pip release.
An unspecific code is never wrong; the remediation names both causes. If agents
need the split later, add `KF-VERSION-BACKEND-UNAVAILABLE` (exit 3) keyed on
that phrase, with a test that pins the pip version it was observed on.

### 3.9 Side effects on the project tree

**kivyforge runs the project's build backend, and the backend may write into
the project tree, exactly as `pip install .` would. kivyforge does not undo
that.** An earlier draft promised to leave the tree "as found" by deleting new
`*.egg-info` folders after the call. The review showed that promise cannot be
kept, and the attempt has its own failure mode:

- An existing `egg-info` is rewritten in place (`PKG-INFO` gets the current
  version), so "as found" was already only "no folder added".
- setuptools-scm's `version_file` is rewritten in both modes (section 8).
- Other backends and plugins may write other files; kivyforge cannot know
  which, so a list of known writes is not a guarantee.
- Deleting "folders that appeared during the call" also deletes one that a
  concurrent `pip install -e .` or `uv sync` created in the same second.

So there is no cleanup. Known writes, for the docs:

| Written | When | Effect |
|---|---|---|
| `<name>.egg-info/` in the package root (project root, or `src/` in a src layout) | Isolated mode, setuptools: pip calls `get_requires_for_build_wheel`, which setuptools answers by running `egg_info` in place (section 8) | Same folder `pip install .` leaves; commonly gitignored. Cannot reach an artifact: every app copy excludes `*.egg-info` ([#115](https://github.com/ElliotGarbus/kivyforge/pull/115)). |
| setuptools-scm `version_file` (e.g. `src/myapp/_version.py`) | Both modes | Wanted: it usually sits in `app_dir`, ships, and carries the resolved version. Inside a bundle it is how the app can know its version, because `importlib.metadata` cannot work there. |
| Nothing | hatchling with hatch-vcs, no `version-file` configured (section 8) | Tree untouched. |

**The user-facing docs say this as plainly as the table does, outside any
"cleanup" framing: a build of a dynamic-version project can leave a clean
checkout dirty.** An untracked `egg-info` is the mild case. A tracked
`version_file` rewritten with a new version shows up in `git status` and can be
committed by accident; setuptools-scm's own header for that file says not to
track it, and the docs repeat that advice.

Resolution runs at the start of the verb, before anything copies `app_dir`, so
whatever the backend writes is in place before staging. That ordering is stated
so a later refactor keeps it.

**A stale `version_file` is documented, and warned about for setuptools-scm
only.** With row 1 or row 2 the backend never runs, so a `version_file` keeps
what the last backend run wrote, and the app can report a different version
than its plist. The documentation is the commitment: with `--app-version`, also
set the plugin's own override (`SETUPTOOLS_SCM_PRETEND_VERSION`) if the app
reads a version file, or read the version some other way.

A backend-neutral check is not implementable: neither the declaration of such a
file nor its format is standardized (`[tool.setuptools_scm].version_file`,
`[tool.hatch.build.hooks.vcs].version-file`, versioningit's own table, each
with its own template). For the common case, kivyforge emits
`KF-VERSION-FILE-NOT-REFRESHED` when `[tool.setuptools_scm].version_file` is
set and the version did not come from the backend. It does not read or compare
the file, whose contents a template decides. It is described as covering
setuptools-scm only; hatch-vcs and versioningit users get the documentation.

Running pip under the override just to refresh that file was rejected: it
spends the time and network the override exists to avoid, and it writes the
tree.

## 4. Dependencies

None added. pip is already a runtime dependency (`pip>=25.1`), and
`--dry-run --report` has been in pip since well before that floor.

## 5. Open questions

None blocking. The `run` cost question is settled (it resolves on every
launch that builds; section 3.2), and the `egg-info` cause is known (section
3.9).

## 6. Verification plan

- **Hermetic:** `resolve_version` takes the pip runner as a parameter, so tests
  inject a fake. Cover: the three precedence rows; set-and-dynamic both;
  invalid PEP 440 static version and override rejected; each of the five other
  read fields rejected when dynamic, and an unread dynamic field accepted;
  `lock`, `run --no-build` and `run --list-devices` never call pip;
  `--app-version` with `run --no-build` / `--list-devices` is a usage error
  and the environment variable is ignored there; isolation is the default and
  `--no-build-isolation` passes through; pip non-zero gives
  `KF-VERSION-UNRESOLVED` and exit 1; pip missing gives `KF-TOOLCHAIN-MISSING`
  and exit 3; `--json` stdout still one envelope; `version_code = "auto"`
  computed from the resolved version and failing before backend work, with the
  `version_code` line number in the error; `doctor` and `status` load a dynamic
  project with `version_code = "auto"` and never start pip; the flag beats
  `KIVYFORGE_APP_VERSION` when both are set; `lock --app-version` is a usage
  error (no such option); `dynamic` that is not a list of strings is rejected;
  a non-PEP 440 static version is written through and warns
  `KF-VERSION-NOT-PEP440`; `KF-VERSION-REDUCED` fires exactly when the Apple
  string differs (`1.0rc1`, `1.2.4.dev3+gabc`, `1.2.3.4`, `1!2.0.0` warn;
  `1.2.3` does not); `KF-VERSION-FILE-NOT-REFRESHED` fires for a configured
  setuptools-scm `version_file` under rows 1 and 2 and not under row 3; `+` in
  filenames; every section 2 consumer reads `ResolvedVersion`, not
  `config.project.version`.
- **pip and setuptools behaviour (exists):** `tests/test_pip_metadata_live.py`,
  opt-in with `--pip-metadata-live` (needs git and network). It pins what the
  design assumes, not kivyforge code: both modes report the scm version, the
  isolated mode writes `egg-info` (flat and src layouts) and the non-isolated
  mode does not, `get_requires_for_build_wheel` is the cause, a
  `setup_requires` project silently reports `0.0.0` non-isolated but the right
  version isolated, `--ignore-installed` reports the tree's version when an
  older copy of the project is installed, and a hatch-vcs project resolves and
  leaves the tree untouched. If a pip or backend release changes any of it,
  this test is where that shows. It belongs in a CI job that passes the flag.
- **Integration (`integration` marker):** a temp git repo with a real
  setuptools-scm project, through kivyforge's resolver. Tag `v1.2.3` gives
  `1.2.3`; one commit past it gives `1.2.4.dev1+g...`; no git gives
  `KF-VERSION-UNRESOLVED`. Needs network, so it belongs in the integration
  job, not the hermetic suite.
- **Install modes:** one dated run each under `uv tool install kivyforge`,
  pipx, and `uv run kf` in a uv project, logged in `test-matrix.md` §7.
- **Real toolchain:** one dated row per platform in `test-matrix.md` §7,
  confirming the plist / `versionName` / resource version on a built artifact
  from a dynamic-version example.
- **Docs and CHANGELOG:** the precedence table; the network note for the first
  build; `--no-build-isolation` with its `0.0.0` hazard; the pip-index note;
  `fetch-depth: 0` for CI; the Apple reduction rule; the side-effects table and
  the `version_file` advice. CHANGELOG under `[Unreleased]`: dynamic versions
  are accepted; `--app-version` and `--no-build-isolation` are new; Apple short
  versions are reduced to `MAJOR.MINOR.PATCH`; a `+` in a version becomes `_`
  in artifact filenames, which renames the artifact for a static local version
  such as `1.0+local`; a static version that is not PEP 440 now warns; dynamic
  `dependencies`, `name`, `description`, `authors` or `requires-python` are
  now errors (each behaviour change with a migration note).

## 7. Review changes (2026-10-12)

A review of the first draft found three blockers and five gaps. All were
checked against the code; all held. What changed:

| Finding | Change |
|---|---|
| A resolved version has no path to the backends, which reload config from `project_root` | Section 3.4: resolve once in the verb, pass a typed `ResolvedVersion` through `Platform.build`/`package`/`run` |
| Automatic `--no-build-isolation` is unsound, because `get_requires_for_build_wheel` can add requirements | Isolation is always the default; non-isolated is an explicit flag. Measured the silent `0.0.0` that justifies it (section 8) |
| The "tree left as found" claim is false | Cleanup dropped; side effects accepted and documented (section 3.9) |
| Dynamic `description` and `authors` are consumed too | Section 3.1 rejects every dynamic field the loader reads except `version` |
| Apple reduction ignored epochs and extra release components; invalid static versions unspecified | Section 3.6 warns on both; section 3.1 rejected non-PEP 440 static versions (reversed after the second review, below: they now warn) |
| `--app-version` silently ignored by `run --no-build` / `--list-devices` | Section 3.2: usage error |
| A backend-neutral stale-`version_file` warning is not implementable | Dropped; documented instead (section 3.9) |
| `ProjectMeta.version: str \| None` weakens types | `DeclaredVersion` in config, `ResolvedVersion` for consumers (sections 3.1, 3.4) |

A second review, partly of the first draft, agreed with the direction and with
the changes above where they overlapped (isolation, Apple epochs and fourth
components, `description` and `authors`). It added:

| Finding | Change |
|---|---|
| `version_code = "auto"` is an `int` computed at load, and `doctor`/`status`/`clean`/`lock` load that config | Section 3.1: `int \| AutoVersionCode`, computed at resolution, errors keep the file's line number |
| Warn whenever the Apple string differs from the version, rather than listing cases | Section 3.6 adopts that rule |
| Write a non-PEP 440 static version through unchanged | Adopted, reversing the first revision's rejection: section 3.1, plus a `KF-VERSION-NOT-PEP440` warning |
| `--app-version` only on `build`/`package`/`run`; flag beats environment variable | Section 3.2 |
| The `+` filename rule renames static local versions | CHANGELOG bullet (sections 3.6, 6) |
| Commit to documenting the stale `version_file`; a setuptools-scm-only warning is possible | Section 3.9: both, the warning described as setuptools-scm only |
| Say plainly that a build can leave a clean checkout dirty | Section 3.9 |
| Tests: `--ignore-installed`, a non-setuptools backend, `doctor`/`status` never start pip, flag vs environment, malformed `dynamic` | Section 6; the first two are in the live test and measured (section 8) |

One suggestion was not taken: a non-isolated fast path with an isolated retry
on failure. The `0.0.0` case in section 8 does not fail, so a retry never
fires there. Isolation stays the default, as that review also allowed.

## 8. Measurements (2026-10-12, macOS, pip 26.2.1, setuptools 84.0.0, setuptools-scm 10.3.4, Python 3.14.7)

Test project: the `pyproject.toml` at the top of this note with an empty
`[tool.setuptools_scm]` table, `git init`, tag `v1.2.3`, then one more commit.

| Run | Environment | Result | Time | Left in project root |
|---|---|---|---|---|
| Isolated (default) | kivyforge `.venv`; `import setuptools_scm` fails there | `1.2.4.dev1+g6c836d1e9` | 1.24 s (warm pip cache) | `myapp.egg-info/` |
| `--no-build-isolation` | Fresh venv with `setuptools` and `setuptools-scm` installed | `1.2.4.dev1+g6c836d1e9` | 0.38 s | nothing |
| Isolated, `--index-url http://127.0.0.1:9/simple` (unreachable index) | Same fresh venv | exit 1; `ERROR: Failed to build '...' when installing build dependencies` | — | — |

`tests/test_pip_metadata_live.py --pip-metadata-live` confirms the rows above,
adds the src layout (the isolated run writes `src/myapp.egg-info`), and shows
the cause directly: calling `get_requires_for_build_wheel` in the project
writes `myapp.egg-info`, and `prepare_metadata_for_build_wheel` alone does not.

With `version_file = "myapp/_version.py"` added to `[tool.setuptools_scm]`, the
isolated run left `myapp.egg-info/` and `myapp/_version.py`; the non-isolated
run left only `myapp/_version.py`, which holds the resolved version.

**The non-isolated hazard.** A legacy project: `[build-system] requires =
["setuptools>=64"]`, and `setup.py` calling `setup(..., use_scm_version=True,
setup_requires=["setuptools-scm"])`, tagged `v1.2.3`. In a venv holding only
setuptools, so `[build-system].requires` is satisfied:

| Run | Result |
|---|---|
| `--no-build-isolation` | exit 0, version **`0.0.0`** |
| Isolated | exit 0, version `1.2.3` |

**`--ignore-installed`.** The test project installed into the venv with
`pip install` (and separately with `pip install -e`), at the same version as
the tree and at an older one: pip reported the tree's version with and without
`--ignore-installed` in every case.

**hatch-vcs.** `[build-system] requires = ["hatchling", "hatch-vcs"]`,
`[tool.hatch.version] source = "vcs"`, src layout, one commit past `v1.2.3`,
isolated: `1.2.4.dev1+g0812e43b5` in 1.67 s, and `git status --ignored` empty
afterwards.

Not yet measured: a cold pip cache, Windows, Linux, and a project with no git
history.

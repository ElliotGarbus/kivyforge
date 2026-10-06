# Proposal — `-v` / `-vv` and `KIVYFORGE_VERBOSE`

> Status: **proposed 2026-10-05, not implemented.** Written in response to
> [issue #64](https://github.com/ElliotGarbus/kivyforge/issues/64) ("Allow passing
> extra flags to `gradle`?"). Every code claim was read out of the source on
> 2026-10-05; line numbers are deliberately omitted because the files move.

## Summary

- When Gradle fails it says "Run with `--stacktrace`" or "Run with `--info`", and
  a kivyforge user has no way to do that. `run_gradle()` always runs
  `gradlew --console=plain <tasks>` and takes nothing from the user.
- **Decision:** add a verbosity count, `-v` / `-vv`, to every verb, with
  `KIVYFORGE_VERBOSE` as the environment-variable form. For now it affects only
  Gradle:

  | Flag | `KIVYFORGE_VERBOSE` | What it adds |
  |---|---|---|
  | `-v` | `1` | `--stacktrace`, plus kivyforge prints the exact `gradlew` command and folder, so you can rerun it by hand |
  | `-vv` | `2` | everything in `-v`, plus `--info` |

- **Not doing:** a raw passthrough of Gradle flags (§4.1), `--stacktrace` on by
  default (§4.2), and a `-vvv` that maps to Gradle's `--debug` (§4.3).
- Anything beyond `-vv` is served by running `gradlew` directly in the generated
  `<app>-android/` project, which already works today (§1.3). The verbose flags
  are the easy button; the generated project is the escape hatch.
- **One PR:** the option, Android's Gradle, and `capabilities`. `lock` is left
  out on purpose; the progress work for issues #74 and #84 covers its need (§6).

## 1. What exists today

### 1.1 How Gradle is run

`kivyforge/platforms/android/gradlew.py` builds the command as
`[script, "--console=plain", *tasks]`, runs it with `stdin=DEVNULL`, and sends
Gradle's whole transcript to kivyforge's stderr through `stderr_for_child()`, so
`--json` stdout stays one document. Its `env_overrides` parameter is unused.

Since PR #87 (issues #74 and #84, see
[`download-progress-output.md`](download-progress-output.md)) it also takes the
build's `events`, and before starting Gradle it installs a missing pinned NDK or
CMake with the SDK's `sdkmanager` (`sdk_packages.py`), showing that download as
progress. So one `run_gradle` call can run two tools: `sdkmanager`, only when a
package is missing, then `gradlew`.

It has six call sites:

| Where | Gradle task(s) | Reached from | Passes `events` |
|---|---|---|---|
| `android_build` | `assembleDebug` or `bundleDebug` | `build --debug` (`run` too, via `android_build`) | yes |
| `_enforce_merged_manifest` | `lintRelease` + the merged-manifest task | `package` | yes |
| `android_package` | `assembleRelease` or `bundleRelease` | `package` | yes |
| `android_run` | `assembleRelease` | `run --release` | no |
| `run_smoke` | `connectedDebugAndroidTest` or `connectedReleaseAndroidTest` | `run --smoke` | no |
| `scripts/lint_newapi.py` | `lintDebug` | CI only, not a verb | no |

Without `events`, `run_gradle` falls back to `PROGRESS_ONLY_EVENTS`, which
writes progress to stderr directly.

`build` without `--debug` runs no Gradle at all; it only generates the project.
`kivyforge lock` runs Gradle too, in a scratch project, through
`GradleMavenResolver` in `lock/maven.py` — a separate code path, out of scope
here (§6).

kivyforge already streams **all** of Gradle's output. python-for-android keeps
only the last 20 lines (`shprint(..., _tail=20)`), so the gap here is not missing
output; it is the stack trace and `--info` detail Gradle omits by default.

### 1.2 There is no verbosity control anywhere

No verb takes `-v`. `-V` (capital) is `--version` on the root group. Shared
per-verb options live in `output_options` in `kivyforge/cli/_output.py`
(`--json`, `--no-color`), and its docstring already records why they sit on the
verbs rather than the group: a group option must come *before* the subcommand
(`kivyforge -v build`), and people type it at the end (`kivyforge build -v`).
The same reasoning applies here.

### 1.3 The two workarounds users have now

1. **Run Gradle in the generated project.** `<app>-android/` is self-contained —
   wrapper, `local.properties`, and release signing that reads its passwords
   from the environment at Gradle time — so
   `cd <app>-android && ./gradlew --console=plain <task> --stacktrace --info`
   works after a failed build. Edits there are overwritten on the next `build`.
2. **`org.gradle.logging.level`** through `[tool.kivy.android.gradle_properties]`.
   Gradle 8.11.1 (the pinned version) documents this key, so `"info"` or `"debug"`
   works for every build until removed. It has no `--stacktrace` equivalent.

Both were posted on issue #64. This proposal makes the common case one flag.

## 2. What Briefcase and Buildozer do

Neither offers a Gradle passthrough, and none of the three trackers
(Buildozer, python-for-android, Briefcase) has a request for one. Searched
2026-10-05 by title, body, and the comments of the threads that contain Gradle's
"Run with --stacktrace" text: about 30 issues per tracker contain that text, so
users of all three hit the same wall. A request worded differently could have
been missed.

**Briefcase.** One verbosity count applies to every tool it drives, formalised in
[beeware/briefcase#1503](https://github.com/beeware/briefcase/pull/1503):

| Level | Effect |
|---|---|
| `-v` | more of Briefcase's own messages |
| `-vv` | also logs every command run, with its environment |
| `-vvv` | also turns on each tool's debug mode: Gradle `--debug`, pip `-vvv`, cookiecutter debug |

It is typed per command (`briefcase build android -vv`). It never adds
`--stacktrace` or `--info`. The maintainers' standard reply to a Gradle failure
is "pass `-vv` to see the commands Briefcase ran, then run them yourself"
([briefcase#184](https://github.com/beeware/briefcase/issues/184),
[briefcase#671](https://github.com/beeware/briefcase/issues/671)), and users in
[briefcase#51](https://github.com/beeware/briefcase/issues/51) and
[briefcase#177](https://github.com/beeware/briefcase/issues/177) did exactly that
in the generated `android/` folder. Briefcase also writes a detailed log file on
failure ([briefcase#760](https://github.com/beeware/briefcase/pull/760)).

**Buildozer / python-for-android.** `log_level = 2` in `buildozer.spec` shows full
command output; it adds no Gradle flags. `p4a.extra_args` reaches
python-for-android, which always runs `gradlew clean <task>`. The standard reply
is "set `log_level = 2` and attach the full log".

**What we take:** verbosity as a single, tool-wide count, typed on the command;
logging the command so it can be rerun. **What we change:** a gentler Gradle
mapping, because Briefcase's only Gradle step is straight to `--debug` (§4.3).

## 3. Design

### 3.1 The option

A new shared decorator, `verbosity_option`, in `kivyforge/cli/_output.py`:

```python
click.option(
    "-v", "--verbose", "verbosity",
    count=True,
    envvar="KIVYFORGE_VERBOSE",
    help="More detail from the tools kivyforge runs; -vv for more. "
    "Currently affects Android's Gradle only. Also KIVYFORGE_VERBOSE=1|2.",
)
```

- **On every verb**, applied by `output_options` and separately to `run`, which
  does not use `output_options` because it has no `--json`. A flag that works on
  some verbs and is a usage error on others would be one more thing to remember;
  a flag that is accepted everywhere and documented as "currently Gradle only"
  is not.
- **Levels above 2 are treated as 2.** Click accepts any non-negative integer.
- **The flag replaces the variable; it does not add to it.** Verified against
  Click 8.4.2: `KIVYFORGE_VERBOSE=2 kivyforge build -v` gives level 1. This is
  Click's normal precedence (command line, then environment, then default) and
  is what lets a command turn verbosity down below a CI-wide setting.
- **Bad values fail loudly.** `KIVYFORGE_VERBOSE=abc` or `-1` is a Click usage
  error (exit 2) on every verb, before any work and before any `--json` envelope,
  like any other bad option. An empty value means 0.

### 3.2 What each level does to Gradle

| Level | Flags added to every `gradlew` invocation | kivyforge's own output |
|---|---|---|
| 0 | none (today's behaviour) | unchanged |
| 1 | `--stacktrace` | before each run, the folder and the exact command line |
| 2 | `--stacktrace --info` | same as 1 |

The flags go after `--console=plain` and before the task names. They apply to
**every** Gradle run in the verb, including both of `package`'s, because
`--stacktrace` and `--info` only add output and never change what is built.

If `[tool.kivy.android.gradle_properties]` sets `org.gradle.logging.level`, the
command-line `--info` wins for that run, which is Gradle's own precedence. Nothing
to reconcile.

### 3.3 Printing the command

At level 1 and above, each Gradle run is preceded by two progress lines on
stderr:

```text
[gradle] in C:\Users\me\hello\hello-android-android
[gradle] .\gradlew.bat --console=plain --stacktrace assembleDebug
```

- **Copy-pasteable on the host.** Quoted with `subprocess.list2cmdline` on
  Windows and `shlex.join` elsewhere; `.\gradlew.bat` on Windows, `./gradlew`
  elsewhere.
- **Exactly what kivyforge ran**, including the flags it added, so the rerun
  reproduces the run.
- **No secrets.** Signing passwords never appear on the command line (they are
  read by the generated build from environment variables), so there is nothing
  to redact. For release tasks the line is followed by a note naming the
  environment variables that must be set, not their values.
- **stderr only, through the callbacks.** Backends never print; the lines go
  through `events.on_progress`, using the `events` `run_gradle` already receives
  (§1.1). No new callback is needed. Under `--json`, stdout is unchanged.
- **`sdkmanager` too.** When `run_gradle` installs a missing NDK or CMake first
  (§1.1), `-v` prints that command the same way, before the `gradlew` lines.
  `-vv` adds nothing for `sdkmanager`: its output is already turned into a
  progress bar, and its transcript is used to explain a failed install.

### 3.4 The failure hint

When Gradle fails, kivyforge's own error message (in `GradleError`, today ending
"See the Gradle output above...") gains one line:

- at level 0: `For a stack trace, rerun with -v (or set KIVYFORGE_VERBOSE=1).`
- at level 1 and above: the folder and command from §3.3 again, because by the
  time Gradle fails they have usually scrolled far off the screen.

This replaces Gradle's own "Run with --stacktrace" advice, which a kivyforge user
cannot follow, with something they can. Messages are not a contract, so this
changes no `KF-*` code or exit status.

### 3.5 Getting the level to `run_gradle`

Through a `ContextVar`, the same way PR #92 routes downloads. `transfers_to()` in
`report/transfers.py` sets the verb's transfer sink for the verb's lifetime, and
the shared downloader reads it without any call site carrying a callback. The
level works identically:

- A `verbosity_to(level)` context manager and a `current_verbosity()` reader,
  next to `transfers_to` (in `report/`), defaulting to 0.
- The verb layer sets it where it already sets `transfers_to`: `reporting()`
  gains a `verbosity` argument, and `run`, which has no `reporting()`, sets it in
  its own wrapper beside its `transfers_to`.
- `run_gradle` and `ensure_sdk_packages` read `current_verbosity()`. No backend
  signature changes, and a backend that adopts `-v` later reads the same value.

Chosen for consistency (decided 2026-10-05): the codebase now has one way to
hand a verb-wide setting to code deep in a backend, and a second way would be one
more thing to learn.

**The risk this accepts, and how it is guarded.** A missing transfer sink is
harmless: `report_transfer` does nothing and a progress bar is lost. A missing
level is not: Gradle would run without `--stacktrace` though the user typed
`-v`, and the build would still pass, so nothing would notice. Two things keep
that from happening silently:

- **One CLI-level test per verb that runs Gradle** (`build`, `package`, `run`):
  invoke the verb with `-v` through click's test runner, with `run_gradle`'s
  subprocess faked, and assert `--stacktrace` reached the command. A verb that
  forgot to set the level fails this test instead of quietly running level 0.
- **Unit tests set the level explicitly** with `verbosity_to(...)`, never by
  relying on the default, and a test of the default asserts level 0 by name.

### 3.6 `capabilities` reports it

`kivyforge capabilities` is how an agent learns the CLI, so it states both
halves: which verbs *accept* `-v`, and which platforms *act on* it.

- Each entry in `verbs` gains `"verbose": true|false`, computed the way `"json"`
  already is — from whether the click command has a `verbosity` parameter.
- Each entry in `platforms` gains `"verbose": true|false`: whether that backend
  passes the level to its tools. Android is `true`; every other platform is
  `false` until it adopts `-v` (§6). It is declared on the `Platform` class, next
  to the other per-platform facts `capabilities` reads, so a backend that adopts
  `-v` flips one attribute and the report follows.
- The human output gains one line: `Verbose (-v) acts on: android`.

Both are additive keys, so the envelope schema version does not change. (Decided
2026-10-05.)

### 3.7 What `-v` and `-vv` mean on any platform

Only Android acts on the level in this PR, but the levels are a promise across
the whole CLI, so a platform that adopts them later follows two rules. (Decided
2026-10-05.)

- **`-v` never makes a successful run's output much longer.** At minimum it
  prints every command the backend runs, with its working directory, in the
  §3.3 form. It may also add detail that appears only on failure.
- **`-vv` may make it much longer.** It is for the tool's full, live output and
  its own verbose modes.

Printing the command is the floor because it is the one thing that helps on
every platform and costs little: it is what makes "rerun it yourself" possible,
which was the standard maintainer advice in both Briefcase and Buildozer (§2).

Applied to Android and, as an example of a later adopter, iOS:

| Platform | `-v` | `-vv` |
|---|---|---|
| Android (this PR) | the `gradlew` command; `--stacktrace` | adds `--info` |
| iOS (later) | the `xcodebuild` command | streams `xcodebuild`'s output live instead of capturing it |

For iOS the command is most of the value at `-v`. Failure output is already shown
in full, and `kivyforge open -p ios` builds in Xcode where errors are easier to
read, but the command shows which simulator, configuration, team ID and signing
identity kivyforge chose, and signing is where iOS users get stuck most.
Streaming is for someone who wants the full transcript as it happens, at the cost
of tens of thousands of lines, so it belongs at `-vv`. It is not the fix for a
build that *looks hung*. That problem is solved at the default level by the
pattern PR #87 introduced: a "still building (1m 30s)" line after 30 seconds with
nothing new to show ([`download-progress-output.md`](download-progress-output.md)).
An iOS build should get that line regardless of `-v`. Streaming would point
`xcodebuild`'s stdout and stderr at kivyforge's stderr, the way `run_gradle`
already does, rather than pumping lines, for the reasons
[`build-package-output-proposal.md`](build-package-output-proposal.md) §4.2 gives.

## 4. Alternatives considered

### 4.1 Raw passthrough (`--gradle-opt`), as issue #64 asks

The cheapest to write, and the most flexible. Rejected because the flags reach
places kivyforge depends on:

- **Release checks can be switched off.** `-x lintRelease` skips the lint gate
  `package` relies on to block a bad release.
- **Some flags hang or wait for input.** `--continuous` never returns; `--scan`
  asks for terms-of-service acceptance, which `stdin=DEVNULL` cannot answer. The
  repo rule is that nothing may wait for input.
- **Some flags produce wrong diagnoses.** `--dry-run` runs nothing, so
  kivyforge reports `KF-ARTIFACT-MISSING` and suggests AGP's layout moved. `-q`
  hides the output the user needed.
- **`package` runs Gradle twice**, and flags such as `-x` mean different things
  for each run.
- **Gradle upgrades become kivyforge breaking changes.** kivyforge pins Gradle; a
  flag removed in a later Gradle breaks users' scripts on a kivyforge upgrade.
- **It does not help a beginner**, who does not know which flags exist.

Everything a passthrough would offer is already available by running `gradlew`
in the generated project (§1.3), where kivyforge's checks do not claim to apply.
If specific flags are later requested repeatedly (`--offline`,
`--refresh-dependencies`), they can be added as a short approved list.

### 4.2 `--stacktrace` on by default

It changes nothing on success and would put the trace in every first bug report,
saving a round trip. Not chosen: Gradle prints the readable "What went wrong"
section first, and a Java stack trace of dozens of lines then pushes it off the
screen, which hurts the users least able to read the trace. Most failures (wrong
JDK, missing SDK package, network) are explained by "What went wrong" alone, and
`kivyforge doctor -p android` catches many before Gradle runs. The §3.4 hint makes
the trace one flag away.

Turning it on by default later is a one-line change that breaks nobody; taking
it away once users rely on it is harder.

### 4.3 `-vvv` mapping to Gradle `--debug`

Briefcase's choice. Not offered: the output is often tens of megabytes, and
Gradle's documentation warns that debug logging can expose sensitive
information. The few who need it can set `org.gradle.logging.level = "debug"`
or run `gradlew --debug` by hand.

### 4.4 A root-level option (`kivyforge -v build`)

One declaration instead of one per verb. Rejected for the reason
`output_options` already records: the natural `kivyforge build ... -v` would be
"No such option: -v", an error from the flag meant to help.

## 5. Implementation and tests

1. `verbosity_option` in `cli/_output.py`; applied via `output_options` and to
   `run`. Clamp to 2 in one place.
2. `verbosity_to()` / `current_verbosity()` beside `transfers_to` (§3.5).
   `reporting()` takes the level and sets it; `run`'s wrapper sets it too.
3. `run_gradle`: read `current_verbosity()` for the flag composition, echo the
   command through `events.on_progress` (for `sdkmanager` as well as `gradlew`),
   and add the hint to `GradleError`'s message. `ensure_sdk_packages` reads the
   level to print its command. `android_run` and `run_smoke` start passing
   `events`, so their echoed lines take the same route as the others. The CI
   script `scripts/lint_newapi.py` sets no level and so stays at 0.
4. Docs: `docs/guides/reference/cli.md` (the option),
   `docs/guides/reference/environment.md` (`KIVYFORGE_VERBOSE`), and a short
   "Gradle failed" entry in `docs/guides/troubleshooting/index.md` covering `-v`
   and the run-it-by-hand path. `docs/guides/reference/json-output.md` for the
   two new `capabilities` keys (§3.6).
5. `CHANGELOG.md` under `[Unreleased]`. No migration note: level 0 is today's
   behaviour exactly.

**Hermetic tests**, following `tests/platforms/android/test_gradlew.py`:

- the command at levels 0, 1, 2 and 7 (clamped), with flags in the right place;
- `-v`, `-vv`, `-v -v`, `KIVYFORGE_VERBOSE=2`, flag-overrides-variable, empty
  variable, and `abc` / `-1` exiting 2;
- the echoed command goes to stderr only, is quoted correctly for a path with a
  space, and `--json` stdout still parses as one envelope on success and on a
  Gradle failure (`test_build_package_json.py`);
- the hint text at level 0 and the repeated command at level 1;
- per verb that runs Gradle (`build`, `package`, `run`), `-v` through the CLI
  reaches the Gradle command as `--stacktrace` (§3.5);
- the encoding test (`tests/test_message_encoding.py`) covers the new literals
  without changes.

**Real-toolchain check.** One dated local run per host family that has a JDK —
Windows, Linux or WSL2, macOS — of a deliberately failing `build --debug -v` and
`-vv`, confirming Gradle prints the stack trace and that the echoed command,
pasted into the host's shell, reproduces the failure. Logged in
`test-matrix.md` §7. In CI, the `android_gradle` job's x86_64 leg runs its
existing debug build at `-v`, and the arm64_v8a leg keeps the default (§7,
decision 5).

## 6. Out of scope, for later

- **Other toolchains.** `xcodebuild`, `appimagetool` and the signing tools
  accept `-v` and ignore it; the help text and `cli.md` say so. Each can adopt
  it separately, following §3.7. Under §3.5 it reads `current_verbosity()`; no
  signatures change.
- **`lock`.** Considered and deliberately left out (2026-10-05). `lock` runs pip
  in three resolvers (the shared desktop one, Android's and iOS's), plus Swift
  Package Manager for iOS and a scratch Gradle project for Android Maven
  dependencies, all with output captured. The complaint behind it is
  [issue #84](https://github.com/ElliotGarbus/kivyforge/issues/84): `lock -p
  android` sat silent for ten minutes, and the user could not tell whether the
  network or the tool was stuck. That is a progress problem, and the progress
  work for #84 and [issue #74](https://github.com/ElliotGarbus/kivyforge/issues/74)
  (PR #87, [`download-progress-output.md`](download-progress-output.md)) answers
  it on every run, not only a rerun with `-v`. As of PR #87 that covers Android's
  `lock` only; the desktop and iOS lock backends adopt it through the same
  mechanism (`_LockOps.emits_progress`), not through `-v`. On failure, the
  resolvers already show the tool's output and name the requirement pip could
  not satisfy. Revisit only if lock failures that the progress output and that
  message do not explain turn up in issues.
- **kivyforge's own messages.** Briefcase's `-v` also adds its own detail.
  kivyforge's progress lines are already fairly complete; nothing is proposed.
- **A log file on failure** (Briefcase#760). The highest-value follow-up for bug
  reports: one attachable file instead of a pasted terminal. A separate proposal.

## 7. Decisions and open questions

Decided 2026-10-05:

1. **A `ContextVar`**, set by the verb beside PR #92's `transfers_to`, for
   consistency with it (§3.5). First decided as an explicit parameter; switched
   the same day once #92 introduced the pattern. Guarded by a CLI-level test per
   verb that runs Gradle.
2. **`capabilities` lists it**, per verb (accepted) and per platform (acted on)
   (§3.6).
3. **The two rules for every platform** (§3.7): `-v` prints commands and keeps a
   successful run's output short; `-vv` may make it long.
4. **`lock` is left out** (§6); the progress work for #74 and #84 covers it.
5. **CI runs `-v` on exactly one leg.** In the `android_gradle` job, the "Build
   the debug APK" step (`kivyforge build -p android --debug --abi "$ABI"`) gains
   `-v` on the **x86_64 leg only**; the arm64_v8a leg keeps running it at the
   default. Every other Gradle run in CI stays at the default too: `package` in
   both legs, the App Bundle job, the Windows-host job, and the two emulator
   smoke tests. So both levels of the most common command are exercised against
   real Gradle, and no task loses its default-path coverage. The default is what
   users run; putting `-v` everywhere would leave it untested.

   The test is the build passing: if kivyforge composed the flags wrong, Gradle
   would reject them and the build would fail. Cost, measured 2026-10-05 over the
   last five green runs on `main`: that step takes 72–103 s on x86_64, and at
   `-v` it does no extra work on success, since `--stacktrace` only changes
   failure output. `-vv` would lengthen the log by thousands of lines and is not
   used in CI.

No open questions remain.

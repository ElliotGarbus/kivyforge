# Proposal — `build` and `package` output

> Status: **proposal, awaiting decisions.** Written 2026-09-15 for roadmap item 3,
> after `doctor`, `status` and `lock` went through `kivyforge/report/`. Baseline
> read out of the code rather than recalled; the open questions in §7 are the ones
> worth answering before any of it is written.

`build` and `package` are the last two verbs in item 3 and the only ones where the
conversion is a design question rather than a mechanical edit. The first three
verbs each *computed* a result and merely described it with `click.echo`, so the
work was choosing a payload vocabulary. These two are different in kind: their
output is mostly a third party talking — Gradle, `xcodebuild`, `appimagetool` —
and the interesting question is not how to render our own lines but which of
someone else's belong in which stream.

## 1. Three structural facts, before any opinion

### 1.1 The artifact path is computed, then thrown away twice

Every backend's build and package function already returns the thing it produced:
`windows_build` returns the bundle, `linux_package` returns the `.AppImage`,
`android_package` returns the `.apk`/`.aab`. That value is then discarded at *both*
layers above it — `platforms/windows/__init__.py:77` calls `windows_build(...)`
and ignores the result, and `Platform.build`/`Platform.package` are declared
`-> None` in `platforms/base.py`. `cli/build.py` therefore cannot report an
artifact path even though the path exists three frames down.

This is the same debt shape `status` paid off: the information existed as data and
was destroyed at the seam because nothing above needed it *yet*. It also explains
a finding already recorded elsewhere —
[`abstraction-leak-retro.md`](../common/abstraction-leak-retro.md) §1.9, where
`cli/clean.py` hard-codes every backend's output paths in shared code. It has to,
because no backend publishes them. One structured result fixes both.

### 1.2 Three toolchains, three different stream behaviours

This is the fact that decides the design, and it is invisible if you only read the
`click.echo` sites.

| Toolchain | How it is invoked | Consequence today |
|---|---|---|
| Gradle (Android) | `subprocess.run(cmd, cwd=..., text=True)` — no capture, no redirect (`android/gradlew.py:30`) | Inherits kivyforge's stdout. Streams live, which is good, but writes **thousands of lines onto our stdout**, which nothing can intercept. |
| `xcodebuild` (iOS) | `runner(argv, capture_output=True, text=True)` (`ios/xcode/runner.py:31`) | Fully buffered. Stdout stays clean, but a multi-minute build prints **nothing at all**, and the output only ever surfaces on failure. |
| `appimagetool` (Linux) | `capture_output=True`, then forwarded through an injected `echo=` callback (`linux/appimage.py:126`, `linux/cli.py:83`) | Already structurally correct: captured, then re-emitted through a callback we control. |

**The Gradle row is a hard blocker for `--json`.** `kivyforge package -p android
--json > out.json` would today write all of Gradle's output into `out.json` ahead
of the envelope, producing a file that is not JSON. No amount of care in our own
call sites fixes that; the subprocess has our file descriptor.

**The iOS row is the opposite failure and CI cares about it too.** A job that
prints nothing for ten minutes looks hung, and some runners enforce a no-output
timeout. Buffering also means a failed build's diagnostics arrive all at once,
after the fact, instead of where they happened.

### 1.3 The volume asymmetry is roughly 20:1

Counted across the five backends (60 `click.echo` sites in `platforms/*/cli.py`):

| Backend | Own output on a successful `package` | Shape |
|---|---|---|
| Windows | 2 lines | `Built <path>`, then a 3-line `Packaged ...` note |
| macOS | 3–4 lines | plus `Developer ID signing with ...`, `signed N Mach-O binaries` |
| Linux | 2 lines + `appimagetool` forwarding | 4-line `Packaged ...` note |
| iOS | 4–5 lines | `Collecting artifacts`, `Generated`, `xcodebuild archive`, `Exported` |
| Android | ~20 lines **+ all of Gradle** | `[collect]`/`[stage]`/`[generate]`/`[gradle]`/`[policy]` prefixes |

Android already has a prefix convention that is effectively a register marker
(`[stage]`, `[gradle]`, `[policy]`) and the desktop backends have none, because
they have almost nothing to say. Any rule has to fit both without making Windows
verbose or Android unreadable.

## 2. What a CI job needs

1. **A path to the artifact, machine-readable.** The single most common CI step
   after a build is "upload this file". Today the path is announced in prose
   (`Packaged dist/linux/app-1.0-x86_64.AppImage.`) and every pipeline re-derives
   it from the naming convention, which makes the convention load-bearing for
   people who never read the spec.
2. **A hash and a size.** For upload deduplication, cache keys, and attestation.
3. **An exit code that distinguishes causes.** Right now everything is `1`, so
   "your `pyproject.toml` is wrong", "this runner has no NDK", and "the compile
   genuinely failed" are indistinguishable — and they want three different
   reactions (fix the repo, fix the image, look at the log).
4. **Live output, on stderr, always.** Including under `--json`. Both for the
   no-output timeout above and because the log is the only artifact of a failure.
5. **Not to have to parse anything on stdout.** Android breaks this today: Gradle
   inherits our stdout (§1.2), so `--json` there does not currently yield a
   parseable document at all.

## 3. What an agent needs, beyond the above

6. **Whether stripping actually happened.** This is not hypothetical: the two
   real launcher bugs found on 2026-09-13 and 2026-09-14 both turned on whether
   `strip_source` had run, and *no artifact reported it*. The T3 drivers are told
   by hand today — `--macos-stripped`, `--linux-stripped` — which means the
   assertion trusts the person who typed the flag. If `package --json` reported
   `byte_compile.strip_source`, item 5's automation could read it from the build
   that produced the artifact instead of being told.
7. **The signing tier as a field, not an adjective.** Today it is prose inside a
   sentence: `(ad-hoc signed)`, `(Developer ID notarized + stapled)`,
   `(onedir folder, unsigned (configure [tool.kivy.windows.signing] to sign))`.
   An agent deciding whether an artifact is distributable has to match strings.
8. **A command that launches the artifact.** The human notes currently explain
   how to run each shape in prose ("Run it with `./AppRun`", "double-clicking
   `MyApp.exe`", "chmod +x, then run"). Prose is the one thing an agent cannot
   use. The same knowledge as an argv is directly actionable.
9. **Warnings as diagnostics.** Android's `[policy] INFO:` lines and the
   "not byte-compiling: ..." line are decisions the build made, currently
   indistinguishable from progress chatter.

## 4. Proposal

### 4.1 Apply the existing register rule literally

The rule from `report/console.py` already answers most of this; it has just never
met a verb with a subprocess in it.

- **Product → stdout.** For `build`/`package` the product is small: what was
  produced, where, and what state it is in. In `--json` mode this is the envelope.
- **Progress → stderr, always, including under `--json`.** *All* third-party
  output is progress. So is every `[stage]`/`[collect]`/`[generate]`/`[gradle]`
  line, and iOS's `xcodebuild archive ...`.
- **The envelope supersedes the human product**, never the progress.

One consequence deserves stating because the naive conversion gets it backwards:
Android's `[stage]` lines must become `report.progress`, **not** `report.line`.
`report.line` is suppressed under `--json`, so a mechanical echo→line edit would
make the longest builds in the project go completely silent in exactly the mode a
CI job uses. Progress is the default for these two verbs; product is the exception.

### 4.2 Give the backends a result type

Mirror what `status` did. A frozen `BuildOutcome` in a new `kivyforge/outcome.py`
(or alongside `StatusReport` in `kivyforge/status.py` — see §7), returned by
`Platform.build` and `Platform.package` instead of `None`:

```python
@dataclass(frozen=True)
class Artifact:
    path: Path
    kind: str            # "appimage" | "apk" | "aab" | "app" | "ipa" | "folder" | "project"
    bytes: int | None = None
    sha256: str | None = None

@dataclass(frozen=True)
class BuildOutcome:
    action: str                       # "generated" | "built" | "packaged"
    artifacts: tuple[Artifact, ...]
    arch: tuple[str, ...] = ()        # or ABIs on Android
    python_version: str = ""
    fmt: str = ""                     # package only
    signing: SigningState | None = None
    byte_compile: ByteCompileState | None = None
    lock_verified: bool = True
    launch: tuple[str, ...] = ()      # argv that runs the artifact, if runnable
    notes: tuple[str, ...] = ()       # human-only prose; never in the envelope
```

`notes` is the escape hatch that keeps the human experience intact without
polluting the payload: the distribution paragraphs go there, are rendered in human
mode, and are excluded from JSON by construction rather than by remembering to.

This also lets `clean` ask each backend what it produces, retiring retro §1.9.

### 4.3 Route every subprocess through the seam

Adopt the Linux pattern everywhere, but **streaming rather than buffering**:

- `run_gradle` takes an `on_line` callback (defaulting to nothing) and is invoked
  with `stdout=PIPE, stderr=STDOUT`, pumped line by line to `report.progress`.
- `run_command` for `xcodebuild` gains the same, so a long archive is finally
  visible while it runs, and its failure output arrives in place.
- `appimagetool` keeps its `echo=` callback, now pointed at `report.progress`.

Streaming, not capturing, is the point: capture-then-forward would fix `--json`
correctness while making the iOS silence problem universal. The cost is a line
pump; there is no need for a reader thread if `stderr` is merged into `stdout`
(`stderr=STDOUT`), which is the right merge here because for a build tool the
distinction between its own two streams is noise to us — we are re-routing all of
it to *our* stderr regardless.

### 4.4 The payload

`build`:

```json
{
  "action": "generated",
  "artifacts": [{"path": "myapp-android", "kind": "project", "bytes": 41230}],
  "arch": ["arm64_v8a"],
  "python": "3.13.14",
  "lock": {"verified": true},
  "byte_compile": {"applied": false, "strip_source": false, "reason": "debug build"},
  "duration_s": 38.4
}
```

`package` adds `fmt`, `signing`, and `launch`:

```json
{
  "action": "packaged",
  "fmt": "appimage",
  "artifacts": [{
    "path": "dist/linux/dice-roller-1.0.0-x86_64.AppImage",
    "kind": "appimage", "bytes": 74183456, "sha256": "9f2c..."
  }],
  "arch": ["x86_64"],
  "python": "3.13.14",
  "byte_compile": {"applied": true, "strip_source": true, "interpreter": "python3.13"},
  "signing": {"tier": "unsigned"},
  "launch": ["./dist/linux/dice-roller-1.0.0-x86_64.AppImage"],
  "duration_s": 96.1
}
```

`signing.tier` is a closed vocabulary — `unsigned`, `ad-hoc`, `debug-keystore`,
`developer-id`, `authenticode`, `apple-distribution` — with tier-specific extras
alongside it (`identity`, `timestamped`, `notarized`, `stapled`,
`notary_submission_id`, `keystore_alias`). A closed set is what makes "is this
distributable?" a lookup instead of a judgement.

Paths stay **relative to the project root** and posix-separated, matching what the
human lines already print and what `status --json` does.

### 4.5 Diagnostics and exit codes to narrow

`BUILD_FAILURE` (`5`) exists and has never been raised. These two verbs are its
entire reason for existing:

| Situation | Code | Exit |
|---|---|---|
| Gradle / `xcodebuild` / `appimagetool` returned non-zero | `KF-BUILD-TOOL-FAILED`, `context={"tool","task"}` | `5` |
| Host cannot build this target | `KF-HOST-INCAPABLE` | `3` |
| Required toolchain absent (no JDK/NDK/clang) | `KF-TOOLCHAIN-MISSING` | `3` |
| Lock drift blocks the build | `KF-LOCK-DRIFT` | `4` |
| Bad config / bad flag combination | existing prose codes | `1` |
| Gradle said success but produced no artifact (`_require_artifact`) | `KF-ARTIFACT-MISSING` | `5` |
| `strip_source` requested but no interpreter found | `KF-BYTECOMPILE-NO-INTERP` (exists) as **WARNING** | `0` |
| Manifest policy notes (Android `[policy] INFO:`) | `KF-MANIFEST-POLICY`, INFO | `0` |
| Packaging unsigned when signing is configurable | `KF-SIGNING-UNCONFIGURED`, WARNING | `0` |

One code per *tool* is deliberately avoided in favour of one code with a `tool`
context field; the alternative invents vocabulary that grows with every toolchain.

Partial results should be recorded via `Report.record()` before the raise, so a
failed Android package still names the project directory and the Gradle task that
failed. That is what `record` was added for.

### 4.6 What to remove or demote

- **The distribution advice paragraphs** (Windows 3 lines, Linux 4, macOS 3) move
  to `BuildOutcome.notes`: still printed for humans, absent from the envelope.
  They are documentation that happens to be delivered at the end of a build.
- **Android's `[collect]`/`[stage]`/`[generate]`/`[gradle]` lines** stay exactly as
  they are, on stderr. The bracket prefixes are already a good convention and
  should not be redesigned as part of this.
- **`click.echo(proc.stdout)`** (`ios/cli.py:435`) — a raw subprocess dump onto
  stdout — becomes streamed progress.
- **`Launching ...` lines** belong to `run`, which is out of scope here.
- **Nothing else should be deleted.** The human output is well judged; the problem
  is that it is the *only* output.

### 4.7 What this leaves for `run`

`run` is deliberately excluded. It inherits stdout on purpose — the app's own
output should pass through untouched — and that is correct behaviour that a
`--json` conversion should not disturb. Worth a separate, smaller decision later.

## 5. Staging

1. `BuildOutcome`/`Artifact` types plus `Platform.build`/`package` returning them;
   backends fill them in; human output byte-identical. No `--json` yet.
2. The subprocess streaming change (`run_gradle`, `run_command`), still no `--json`
   — this is the risky one and it is worth landing alone.
3. `--json` for both verbs, envelopes pinned by golden tests.
4. Exit-code and diagnostic narrowing per §4.5.
5. Retire retro §1.9 by having `clean` ask the backends.

Steps 1 and 2 are independent and either can go first; 3 depends on both.

## 6. What this unblocks

Item 5's E2E automation is the direct beneficiary. Today a T3 driver is *told*
whether an artifact was stripped and which arch it is; with §4.4 it can read both
out of the build that produced the artifact. Given that the two most serious bugs
found this month were both "the artifact was not the shape the build thought it
was", closing that gap is worth more than the `--json` flag itself.

## 7. Open questions — these need a decision

1. **Where does `BuildOutcome` live?** A new `kivyforge/outcome.py`, or alongside
   `StatusReport` in `kivyforge/status.py`? *Recommend a new module*: `status.py`
   is about inspecting a project, this is about the result of an action, and
   `Artifact` here overlaps confusingly with `status.BuildArtifact` (which answers
   "is it built and how old", not "what did we just produce").
2. **Always hash the packaged artifact?** *Recommend yes for single-file outputs*
   (`.AppImage`, `.apk`, `.aab`, `.ipa`) since CI wants it and a few seconds on a
   multi-minute build is nothing, and *no for directory outputs* (`.app`, onedir
   folder, AppDir) where a tree hash is both expensive and ill-defined — report
   `bytes` only. An opt-out flag if hashing ever bites.
3. **Stream third-party output always, or only under `--json`?**
   *Recommend always*, so there is one behaviour to reason about and test. The
   alternative keeps Gradle's live inherited stdout for humans and only redirects
   under `--json`, which is less work but means the mode a CI job uses is the mode
   that gets the least testing.
4. **Do we add `--quiet` / `-v` now?** There is no verbosity control today. It is
   arguably in scope, since this is the moment every output site is being
   touched. *Recommend deferring* — the stdout/stderr split gives `2>/dev/null`
   as a usable quiet mode, and inventing levels before there is a complaint tends
   to produce the wrong levels.
5. **`duration_s` in the payload?** *Recommend yes.* It is free, CI dashboards
   want it, and it makes a regression in build time visible without instrumenting
   anything.
6. **Should `build` with no target on iOS still say "Project ready"?** It is the
   one place a verb's product is advice rather than an artifact. *Recommend*
   `action: "generated"` with the project directory as the artifact, and the
   sentence moving to `notes`.

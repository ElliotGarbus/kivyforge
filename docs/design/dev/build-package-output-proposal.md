# Proposal — `build` and `package` output

> Status: **decided, reviewed against the code, ready to implement per §5.**
> Written for roadmap item 3 after `doctor`, `status` and `lock` went through
> `kivyforge/report/`. Every code claim here was read out of the source rather than
> recalled, and the line references are current as of 2026-09-16.

`build` and `package` are the last two verbs in item 3 and the only ones where the
conversion is a design question rather than a mechanical edit. The first three
verbs each *computed* a result and merely described it with `click.echo`, so the
work was choosing a payload vocabulary. These two are different in kind: their
output is mostly a third party talking — Gradle, `xcodebuild`, `appimagetool` —
and the interesting question is not how to render our own lines but which of
someone else's belong in which stream.

The conclusion is that the stream problem is the whole job, and the payload is
almost nothing.

## 1. Three structural facts, before any opinion

### 1.1 The artifact path is computed, then thrown away twice

Every backend's build and package function already returns the thing it produced:
`windows_build` returns the bundle, `linux_package` returns the `.AppImage`,
`android_package` returns the `.apk`/`.aab`. That value is then discarded at *both*
layers above it — `platforms/windows/__init__.py:77` calls `windows_build(...)`
and ignores the result, and `Platform.build`/`Platform.package` are declared
`-> None` in `platforms/base.py:81,109`. `cli/build.py` therefore cannot report an
artifact path even though the path exists three frames down.

This is the same debt shape `status` paid off: the information existed as data and
was destroyed at the seam because nothing above needed it *yet*. It also explains
a finding already recorded elsewhere —
[`abstraction-leak-retro.md`](../common/abstraction-leak-retro.md) §1.9, where
`cli/clean.py` hard-codes every backend's output paths in shared code. It has to,
because no backend publishes them. Both leaks have the same root, though they do
*not* have the same fix — see the note at the end of §5, since `clean` needs those
paths without running a build and so cannot be served by a build's return value.

### 1.2 Three toolchains, three different stream behaviours

This is the fact that decides the design, and it is invisible if you only read the
`click.echo` sites.

| Toolchain | How it is invoked | Consequence today |
|---|---|---|
| Gradle (Android) | `subprocess.run(cmd, cwd=..., text=True)` — no capture, no redirect (`android/gradlew.py:30`) | Inherits kivyforge's stdout. Streams live, which is good, but writes **thousands of lines onto our stdout**, which nothing can intercept. |
| `xcodebuild` (iOS) | `runner(argv, capture_output=True, text=True)` (`ios/xcode/runner.py:31`) | Fully buffered. Stdout stays clean, but a multi-minute build prints **nothing at all**, and the output only ever surfaces on failure. |
| `appimagetool` (Linux) | `capture_output=True`, output **discarded on success** (`linux/appimage.py:126`) | Stdout stays clean, but nothing the tool says is ever shown on a successful package. On failure only `proc.stderr or proc.stdout` is folded into the raised message — one stream, not both. |

**A misreading worth heading off, because the code invites it.**
`build_appimage` takes an injected `echo=` callback (`appimage.py:80`,
wired to `click.echo` at `linux/cli.py:83`), which looks like the tool's output
being forwarded through a seam we control. It is not. That callback emits exactly
one line of *kivyforge's own* prose — `Packaging <name> with appimagetool
<version> ...` — and `appimagetool`'s actual stdout and stderr go into
`capture_output` and are dropped. The same `echo=` convention appears in
`linux/bundle.py:125` for staging progress. It is dependency injection so these
modules need not import `click`, and it is orthogonal to where third-party output
goes.

**The Gradle row is a hard blocker for `--json`.** `kivyforge package -p android
--json > out.json` would today write all of Gradle's output into `out.json` ahead
of the envelope, producing a file that is not JSON. No amount of care in our own
call sites fixes that; the subprocess has our file descriptor.

**The iOS row is the opposite failure and CI cares about it too.** A job that
prints nothing for ten minutes looks hung, and some runners enforce a no-output
timeout. Buffering also means a failed build's diagnostics arrive all at once,
after the fact, instead of where they happened. This one is nevertheless left alone
by this item, for reasons §4.2 gives.

### 1.3 The volume asymmetry is roughly 20:1

Counted across the five backends (60 `click.echo` sites in `platforms/*/cli.py`):

| Backend | Own output on a successful `package` | Shape |
|---|---|---|
| Windows | 1 line | a 3-line `Packaged ...` note; `windows_package` assembles directly rather than calling `windows_build`, so no `Built` line |
| macOS | 3–4 lines | plus `Developer ID signing with ...`, `signed N Mach-O binaries` |
| Linux | 2 lines (+1 `Packaging ... with appimagetool` progress line) | 4-line `Packaged ...` note |
| iOS | 4–5 lines | `Collecting artifacts`, `Generated`, `xcodebuild archive`, `Exported` |
| Android | ~20 lines **+ all of Gradle** | `[collect]`/`[stage]`/`[generate]`/`[gradle]`/`[policy]` prefixes |

Android already has a prefix convention that is effectively a register marker
(`[stage]`, `[gradle]`, `[policy]`) and the desktop backends have none, because
they have almost nothing to say. Any rule has to fit both without making Windows
verbose or Android unreadable.

## 2. The payload, decided by asking what consumes each field

A dozen fields suggest themselves here, and each is easy to justify with a sentence
of the form "CI wants X". Held to a stricter test — *name the thing in a pipeline or
an agent loop that reads this field and does something different because of it* —
two survive.

### 2.1 In: `artifacts[].path`

**CI role.** The step after a build is upload or publish, and today the pipeline
must know the naming convention to find the file:
`dist/linux/{app_slug}-{version}-{arch}.AppImage`,
`dist/windows/{bundle_dir_name}-{version}-{arch}`, or Android's AGP output layout.
When a convention changes, a glob matches nothing and the job either fails
obscurely or silently uploads zero files.

That these paths drift is not a hypothesis, and the evidence is in this repo.
`cli/clean.py` hard-codes every backend's output paths (retro §1.9) — our *own*
code re-derives them because nothing publishes them. And `android/cli.py`'s
`_require_artifact` guard exists precisely for the case where "AGP's output layout
moved under a new plugin version". We already expect the layout to move, which is
the argument against consumers deriving it.

**Agent role.** An agent that has just built something needs to act on it: run it,
inspect it, install it. The only source today is prose, and the sentence differs
per platform and per format.

This is the one load-bearing field.

### 2.2 In: `artifacts[].kind`

**Agent role.** A path alone does not reliably say what shape a thing is, because
several of ours have no extension. `dist/windows/Dice Roller-1.0.0-arm64` is a
runnable onedir folder; `dice-roller-android` and `dice-roller-ios` are project
directories that cannot be run at all; `Dice Roller.app` and `Dice Roller.AppDir`
are directories that *are* runnable. An agent deciding "execute this, or open it in
Xcode" cannot get that from the path, and guessing wrong costs a whole cycle.

**CI role.** Weaker — a pipeline usually knows what it asked for. `kind` earns its
place on the agent side.

Closed vocabulary: `appimage`, `apk`, `aab`, `app`, `ipa`, `folder`, `project`,
carried as an `Enum` rather than a `str` (§4.1).

### 2.3 Out, and why

Each of these was considered and cut. Recorded so they are not re-litigated:

- **`action`** (`generated`/`built`/`packaged`) — determined by the command and
  flags the caller already passed, so it reports back an input. The one case that
  looked interesting, `build -p ios` generating a project versus `--simulator`
  producing a binary, is fully covered by `kind` being `project`.
- **`fmt`** — same: the caller passed `-f`, and when it defaulted, what it
  actually wants is the resulting file, which `path` and `kind` now give it.
- **`signing.tier`** — the role is clear (a release pipeline refusing to publish
  something unsigned or un-notarized) but that consumer does not exist here;
  nothing in `.github/workflows` publishes built apps. Costing nothing to emit is
  not the same as being worth a schema promise, and a closed tier vocabulary is a
  large promise to make on a consumer's behalf before it shows up. The unsigned
  case stays visible through the `KF-SIGNING-UNCONFIGURED` warning (§4.4).
- **`bytes` and `sha256`** — the pipelines that look like they want a digest
  either take a path instead (`upload-artifact`), key off *inputs* rather than
  outputs (caches key off the lock), or compute it themselves
  (`attest-build-provenance`, `cosign`). Size was defended as an early warning for
  payload regressions, which is real but is a job for the T3 assertions, not for
  every consumer of every build.
- **`byte_compile.strip_source`** — cut for the reason that generalises best:
  the only candidate consumer was item 5's T3 driver, which currently gets
  `--macos-stripped` by hand. Feeding it the build's own claim would let the build
  grade its own homework, so it would weaken the assertion rather than automate
  it. **Any field whose only plausible consumer is a check verifying the same
  build that emitted it does not belong in the envelope.**
- **`launch` argv** — `kivyforge run` already is the actionable form of that
  knowledge; a field would be a second, weaker copy of an existing verb.
- **`duration_s`** — CI already times every step.
- **`arch`, `python`, `lock_verified`** — all derivable from inputs the caller
  holds (flags, config, the lock), and a successful build already implies the lock
  verified unless `--no-verify-lock` was passed.

### 2.4 The rule this settles on

> The envelope states as data what **kivyforge's own human-mode lines** already
> state as prose — and only where a consumer can act on the difference.

"kivyforge's own" is the load-bearing qualifier, because there are two kinds of
human-readable output in a build and the rule applies to exactly one of them:

- **Ours**, written by kivyforge through `report.line` — `Packaged
  dist/linux/dice-roller-1.0.0-x86_64.AppImage.` and its peers. This is the
  candidate pool for payload fields.
- **The toolchain's**, written by Gradle, `xcodebuild` and `appimagetool` for a
  human reading a build log. This is **never** a candidate. It is progress, and no
  part of it is parsed into a field — where it is shown at all it is shown verbatim
  and only on stderr (§4.2 decides which tools show it). Mining it for payload data
  is the specific thing §4.2 rejects, since anything that reads those lines in order
  to reshape them is also in a position to corrupt them.

Everything cut in §2.3 failed the second half of the rule rather than the first.
Fields are additive later; a field emitted before anything reads it is a guess that
has to be honoured forever.

## 3. Apply the existing register rule literally

The rule from `report/console.py` already answers the stream question; it has just
never met a verb with a subprocess in it.

- **Product → stdout.** For these verbs the product is: what was produced and
  where. Under `--json` it is the envelope.
- **Progress → stderr, always, including under `--json`.** A third-party build
  *transcript* is progress, whenever we show it at all — §4.2 leaves
  `appimagetool`'s discarded and `xcodebuild`'s buffered, and neither becomes
  product by being withheld. So is every `[stage]`/`[collect]`/`[generate]`/
  `[gradle]` line, and iOS's `xcodebuild archive ...`.
- **`--json` does not introduce a second path for build transcripts.** They use the
  same stderr path in human and JSON modes. The flag changes stdout only, swapping
  our own product lines for the envelope. So `kivyforge package -p android --json >
  out.json` puts nothing but JSON in the file while Gradle's log still scrolls past
  on the terminal, exactly as it does without the flag.

  "Bulk transcript" rather than "all third-party output" is the deliberate wording,
  and §4.2a explains why: a one-line `signtool` or `clang` error stays quoted inside
  the diagnostic message, and therefore inside JSON stdout, because for those tools
  the quoted line *is* the diagnosis. The rule is about volume, not provenance.

One consequence deserves stating because the naive conversion gets it backwards:
Android's `[stage]` lines must become `report.progress`, **not** `report.line`.
`report.line` is suppressed under `--json`, so a mechanical echo→line edit would
make the longest builds in the project go silent in exactly the mode a CI job
uses. Progress is the default for these two verbs; product is the exception.

## 4. Proposal

### 4.1 Give the backends a result type

Mirror what `status` did. Frozen, in a new `kivyforge/build_outcome.py`, returned
by `Platform.build` and `Platform.package` instead of `None`. A module of its own
rather than sharing `kivyforge/status.py`: `status.py` is about inspecting a
project, this is about the result of an action, and `Artifact` here would sit
confusingly next to `status.BuildArtifact`, which answers "is it built and how
old" rather than "what did we just produce".

```python
class ArtifactKind(Enum):
    """What shape a produced path is. Closed, for the reason ``LockState`` is."""

    APPIMAGE = "appimage"
    APK = "apk"
    AAB = "aab"
    APP = "app"          # .app bundle: macOS, and iOS simulator/device builds
    IPA = "ipa"
    FOLDER = "folder"    # Windows onedir, Linux AppDir
    PROJECT = "project"  # generated Xcode/Gradle project, not runnable


@dataclass(frozen=True)
class Artifact:
    path: Path                  # relative to project root, posix-rendered
    kind: ArtifactKind


@dataclass(frozen=True)
class BuildOutcome:
    artifacts: tuple[Artifact, ...]
    notes: tuple[str, ...] = ()  # human-only prose; never in the envelope
```

`kind` is an `Enum` rather than a `str` for the same reason `status.LockState` is
one: a typo in a backend would otherwise be a schema violation that only a
consumer ever notices, and the vocabulary is small and closed by design. It
serialises to its `value`.

With the payload cut to two fields, `BuildOutcome` is barely more than
`tuple[Artifact, ...]`. It is still worth the name for `notes`: the distribution
advice paragraphs (§4.5) go there, get rendered in human mode, and are excluded
from JSON by construction rather than by remembering to.

Paths stay **relative to the project root** and posix-separated, matching what four
of the five backends' human lines already print and the rule the T3 checks adopted
on 2026-09-15 for in-artifact paths. Android is the exception that has to be fixed
rather than accommodated — see step 1 in §5.

**This rule is scoped to these two verbs, because `status --json` does not follow
it.** Worth stating plainly rather than implying consistency that is not there:
every backend hands `BuildArtifact.probe()` an absolute path
(`windows/cli.py:176`, `linux/cli.py:172`, `macos/cli.py:198`, and the three
Android rows), and `BuildArtifact.as_dict()` only calls `path.as_posix()`
(`status.py:117-125`), which changes separators without relativising. So `status`
emits absolute posix paths today. Normalising it is a small, separate change —
worth doing for consistency, but not a dependency of this item, and claiming
alignment before it happens would be false.

### 4.1a How backends reach the report

`Report` stays out of the platforms, for the reason `status` established: backends
return data, the verb renders it. But a return value alone cannot carry everything
these two verbs produce, because **product lines are interleaved with progress and
their order is meaningful**:

- iOS prints `Generated <slug>-ios` (`ios/cli.py:203`) and then, on `--release`,
  runs `xcodebuild archive`, `-exportArchive`, and prints `Exported <ipa>`. Two
  product lines with minutes of progress between them.
- macOS prints `Built <app>`, then `Developer ID signing with ...`, then
  `signed N Mach-O binaries`, then `Packaged <app>` (`macos/cli.py:66,166-180`).

Rendering product only after `BuildOutcome` comes back would move iOS's `Generated`
from the middle of the run to the end, which is a worse build log for the sake of a
tidier seam. So product is an event too.

**Printing a product line and recording an artifact are two different decisions,
and they must be two callbacks.** Bundling them into one `on_product(artifact)` is
wrong twice over. An `Artifact` cannot reproduce the prose — `Generated`, `Built`,
`Exported`, and macOS's `Packaged <app> (Developer ID notarized + stapled).` plus
its two-line distribution advice are not derivable from a path and a kind. And more
seriously, **three package flows call a build function that prints, in a situation
where nothing should be recorded**:

| Flow | The inner line | Why recording it would be wrong |
|---|---|---|
| `macos_package` → `macos_build` (`macos/cli.py:66,155-163`) | `Built <app>` | It fires with `sign=False`; the bundle is *unsigned* at that moment. `package`'s product is the signed one, same path, minutes later. |
| `ios_package` → `prepare_build` (`ios/cli.py:203,477-485`) | `Generated <slug>-ios` | The project is `package`'s intermediate, not its product (§4.1b). |
| `android_package` → `android_build` (`android/cli.py:438-449,495`) | `[generate]`, and `Built <apk>` under `--debug` | Same: the project is an intermediate here. |

So:

**1. `on_line(message)` — product prose, in order.** Maps to `report.line`: stdout,
suppressed under `--json` per §3. Backends keep composing their own sentences,
which is what keeps the human output byte-identical.

**2. `on_artifact(artifact)` — recording only, no output.** Called at the moment a
product is finalised and verified. It satisfies §4.1b's rule by construction (a
backend cannot report a path it has not just written and checked), it puts
artifacts on `Report` before any later failure, and it means **`ToolchainError`
needs no `data=` argument** — the failure envelope already has whatever was
finalised, exactly as it already has diagnostics.

The nesting problem then solves itself in the wiring rather than with a flag:
**`on_artifact` is passed down only when the inner function's products are also the
invoked verb's products.** `macos_package`, `ios_package` and `android_package` pass
the inner call a no-op recorder and keep `on_line`, so the intermediate lines still
print exactly where they do today while nothing is recorded; each then calls
`on_artifact` itself once the real product exists. §4.1b's build-versus-package
asymmetry becomes one argument at three call sites instead of a condition threaded
through the backends.

**3. `on_progress(message)` and `on_note(code, message)` — the `lock` pattern
verbatim.** `cli/lock.py` does not hand `Report` to a backend; it passes
`on_warning=lambda msg: _warn(report, msg)`, and `_warn` — on the CLI side — does
both `report.progress(msg)` and `report.diagnose(Diagnostic(...))`. The backend
calls a plain callable and knows nothing about reports, codes or severities. The
`echo=` callbacks in `linux/appimage.py` and `linux/bundle.py` are already the
progress half of this shape. `code` is a constant from `report/diagnostics.py`, a
pure constants-and-dataclass module a backend can import without touching
`Report`; the closure decides severity and whether the note also prints.
`on_note` carries the three success-path diagnostics in §4.4.

**4. `BuildOutcome` as the return value** — the same artifacts plus `notes`. It is
the summary, not the channel: the verb emits from it on success, and it keeps the
backends unit-testable by assertion rather than by spy. §1.1's discarded return
value is paid off here.

**None of these four can be wired with a bare `click.echo`, and step 1 has to
define the adapters explicitly.** `click.echo(artifact)` prints a dataclass
`repr`; `click.echo(code, message)` binds `message` to Click's `file` parameter and
raises on the first note. Step 1's human-only wiring is therefore four small
module-level adapters — `_echo_line(text)`, `_echo_note(code, message)` printing
just the message, a `_discard(artifact)` no-op, and `click.echo` for progress —
and step 3 replaces them with report-backed closures.

Those closures also cannot be method references, because `Report` has no matching
surface: there is no `report.product`, and `report.diagnose` takes a `Diagnostic`
instance, not `(code, message)` (`report/console.py:127-185`). The mapping is
`on_line → report.line`, `on_progress → report.progress`, and `on_note → a closure
that builds the Diagnostic and calls report.diagnose`, exactly as `lock`'s `_warn`
does.

**One accumulator owns the artifact list, because there are two consumers of it and
they must not drift.** Every product has to reach both the live `Report` (so a later
failure still reports it) and the returned `BuildOutcome` (so success emits from the
summary), and `Report.record()` *replaces* rather than appends — `record(artifacts=…)`
is `self._data.update(fields)` (`report/console.py:152-165`), so calling it per
artifact would leave only the last one. Rather than ask every call site to remember
both updates and to re-serialise the whole list each time, `on_artifact` is backed by
a small verb-side accumulator that appends, re-records the complete list, and hands
back the `BuildOutcome` at the end. One place to get right, and the failure and
success payloads cannot disagree by construction.

`BuildOutcome` needs an explicit `as_dict()`, like `StatusReport` has. `Path` and
`Enum` are not JSON-serialisable, so relying on `json.dumps` to walk the dataclass
would fail at the first artifact; `as_dict()` is where `path.as_posix()` and
`kind.value` happen, and it is what the accumulator re-records.

Two more mechanics that are easy to miss:

- **Verbs should `report.record(artifacts=[])` before doing anything**, so a
  failure during target resolution or config loading still emits
  `"artifacts": []` rather than omitting the key. The matrix in §5 promises `[]`;
  this is what makes that true rather than aspirational.
- **Android's `@user_facing` decorator flattens everything.** It wraps
  `AndroidBuildError` with a bare `raise ToolchainError(str(exc))`
  (`android/cli.py:85-89`), discarding `code`, `exit_code`, `remediation` and
  `context`. It is the single funnel for every Android failure, so until it
  forwards those, no amount of care at the raise sites inside the backend reaches
  the envelope. Step 4 has to widen it.

### 4.1b Artifacts on a failed run: only what this invocation finalised

The obvious motivating case for §4.1a's failure channel — "a failed Android package
that already wrote `app-release.apk` should still name it" — is unsafe as stated,
and the reason generalises past Android.

No backend leaves a clean slate on failure, and the three packaging paths get there
three different ways:

- **Android** writes to fixed paths (`_release_output`:
  `app/build/outputs/apk/release/app-release.apk`) and nothing clears them, so an
  APK sitting there may be from a previous run.
- **Linux** builds to `.{name}.tmp-{pid}` and swaps on success precisely so a
  failure "leaves any previous .AppImage intact" (`appimage.py:104-137`). After a
  failed package the path holds the *old* artifact.
- **Windows** goes further and deliberately restores it: `_stage_dist_copy`
  reserves the prior package and `except BaseException: restore_previous(trash,
  dest)` puts it back when signing fails (`windows/cli.py:106-119`), so that
  rollback is a feature.

An `ok: false` envelope naming any of those paths would be telling a consumer
"here is what I produced" about a file that predates the run — worse than saying
nothing, because it is indistinguishable from success output and an agent would
ship it.

**The rule: `artifacts` lists only products this invocation finalised, and a
backend must have verified existence at the moment it reports them.** Calling
`on_artifact` at the point of finalisation (§4.1a) is what enforces this — a
backend cannot report a path it has not just written and checked.

That makes the partial-failure cases decidable rather than a judgement call:

| Failure point | `artifacts` |
|---|---|
| `build -p android`/`-p ios`, after project generation, before or during the compile | the fresh `project` — this run wrote it and it is a product of `build` |
| `build -p android --debug`, after `assembleDebug` succeeded, later step failed | `project` + `apk` |
| `package -p android`/`-p ios`, after project generation, Gradle or `xcodebuild` then failed | `[]` — the project is an *intermediate* for `package`, not its product |
| `package -p linux`/`-p windows`/`-p macos`, tool or signing failed | `[]`, and specifically not the preserved previous artifact |

The `build`-versus-`package` asymmetry on the same generated directory is the point
worth keeping: what counts as a product depends on what was asked for, not on what
happens to exist on disk.

This is the same discipline `_require_artifact` already applies on the success
path, and it is why that guard is the right model to extend rather than a special
case to work around.

### 4.2 Third-party output: change only what `--json` forces

Two principles govern this, and together they keep the change far smaller than the
§1.2 table suggests it will be:

1. **On success, preserve existing platform behaviour** unless stdout
   contamination has to be fixed for `--json`.
2. **On failure, preserve all available diagnostic output.**

Only Android fails the first test, because Gradle inherits our *stdout* (§1.2).
Where output does have to move, it moves by pointing the tool's stdout *and* stderr
at kivyforge's stderr file descriptor — not captured, not pumped, not prefixed, not
parsed.

The alternative is a line pump, reading each line and re-emitting it through
`report.progress`. That is the more natural-looking design and it is the wrong one,
for two reasons:

1. **A pump degrades the log, which is the artifact of a failure.** Measured on
   2026-09-16: a child writing raw UTF-8 bytes, read through a text-mode pump and
   re-written to a cp1252 console, arrives mangled — box-drawing and em dashes
   silently replaced. Passing the descriptor through delivers the bytes as sent. A
   byte-mode pump would also preserve them, but fd redirection removes the entire
   class of encoding bug instead of avoiding one instance of it, and it cannot
   deadlock or interleave wrongly with our own writes.
2. **We have nothing to add.** Once §2 establishes that no tool output becomes a
   payload field, there is no reason to read the lines at all. A pump only earns
   its keep if something transforms what passes through it, and nothing does.

It also preserves whatever the tool does when it detects a terminal, which a pipe
would flatten. Gradle is a partial exception, since `run_gradle` already passes
`--console=plain`; the gain there is fidelity and simplicity rather than colour.

Concretely, and the shortness of this list is the point:

- **Android changes.** `run_gradle` (`android/gradlew.py:30`) redirects instead of
  inheriting. This is the one change that makes `--json` produce a parseable
  document. Principle 2 is satisfied for free — the output still reaches the
  terminal, so the existing failure message's "See the Gradle output above" stays
  true.
- **iOS does not change.** `xcodebuild` is already captured, so there is no
  contamination for principle 1 to license fixing, and its failure path joins both
  streams (`ios/xcode/runner.py:33-38`) so principle 2 already holds. The cost is the
  silence noted in §1.2: a multi-minute archive prints nothing. That is a real
  risk on runners that enforce a no-output timeout and not a problem anyone here
  has hit, which puts it in the same category as the artifact hash — left alone
  until something asks. If it ever bites, the descriptor helper below makes it
  small.
- **The Linux success path does not change** either: `appimagetool`'s output stays
  captured and discarded. There is no contamination to fix, so principle 1 licenses
  nothing, and the argument for showing it is symmetry rather than a reported
  problem — even though compressing a ~70 MB squashfs is a real pause with no
  output. Redirecting it later is a two-line change once the descriptor helper
  below exists. The `echo=` callbacks in `linux/appimage.py` and `linux/bundle.py`
  stay too, repointed from `click.echo` at `report.progress`, since they carry our
  own lines rather than the tool's.
- **The Linux failure path changes**, under principle 2 — but by §4.2a's route, not
  by fixing the message in place. `appimage.py:134` raises with
  `proc.stderr or proc.stdout`, so whenever stderr holds anything the stdout half of
  the evidence is discarded; `ios/xcode/runner.py:33-38` carries a comment about
  exactly that trap and joins both streams to avoid it. The fix is that both streams
  go to `on_progress`, which preserves everything *and* keeps the transcript out of
  the JSON diagnostic. Joining them into the message instead would satisfy principle
  2 while breaking the stream rule.
- **Everything else that captures** (`codesign`, `otool`, `hdiutil`, `adb`, the
  resolvers) is *queried* for its output and must not change.

**One implementation note that will bite in tests.** `subprocess` needs a real
`fileno()`, and `sys.stderr` does not always have one — Click's `CliRunner` and
pytest's capture both replace it. This needs a small helper on the report seam
that hands back the descriptor when there is one and falls back to a pump when
there is not, rather than each call site guessing.

### 4.2a The failure path already puts tool output on stdout, and that has to stop

§3's rule has a second route for build transcripts that it does not account for,
and that route goes straight to stdout in JSON mode.

The tools we capture embed their output in the exception message —
`CommandError` joins xcodebuild's stdout and stderr into its message
(`ios/xcode/runner.py:20-27`), `AppDirError` interpolates `appimagetool`'s output —
and the backends then wrap those with `raise ToolchainError(str(exc))`.
`ToolchainError.as_diagnostic()` sets `message=self.format_message()`, so the
whole captured log lands in `diagnostics[].message` **on stdout**, inside the JSON
document. "A build transcript is progress, and progress is stderr" is contradicted
by the one path that matters most.

It is also a payload problem independent of the rule: a failing `xcodebuild` can
emit megabytes, and a diagnostic message is the wrong place for it. A consumer
reading `diagnostics[0].message` to decide what went wrong does not want a build
transcript, and JSON-escaping one is pure cost.

**The split: the diagnostic message is a summary; the transcript goes to stderr
only.** Where a backend has captured a build tool's output it writes that output to
`on_progress` before raising, and raises with a summary — which tool, which task,
which exit code, plus the `Fix:` line the convention already provides. The envelope
says *what* failed in a form worth branching on; stderr carries the evidence, in the
same place and format it would have had on a successful run.

**Scoped to the three bulk producers: Gradle, `xcodebuild`, `appimagetool`.** This
is the important qualifier, because `(proc.stderr or proc.stdout)` embedded in an
error message is a house convention with sixteen sites — `signtool`
(`windows/signing.py:149`), `codesign` and `otool` (`macos/machotools.py:190`),
`clang` (`macos/launcher.py:151`), `rcedit` (`windows/rcedit.py:115`), `keytool`,
`iconutil`, `notarytool`, `adb`, and the pip and Swift resolvers. Those stay exactly
as they are, and the rule does not extend to them, for a reason rather than for
convenience: they emit a line or two, and that line *is* the diagnosis. A
`signtool` error is not a transcript. Only the three tools whose output is measured
in thousands of lines have output that belongs somewhere other than a message.

So the rule is about volume, not provenance: **a diagnostic message may quote a
tool; it may not contain a build log.** That is a line an implementer can apply
without inventorying every `subprocess.run` in the codebase.

One thing this deliberately leaves alone: the `stderr or stdout` idiom itself
discards half the evidence at all sixteen sites, and `runner.py`'s comment explains
why that can hide the real failure. Fixing it everywhere is a worthwhile,
independent cleanup — a one-line change per site — and it is not this item. Within
this item it matters only where the bulk rule already replaces the message content.

### 4.3 The payload

`build -p android` with no `--debug`:

```json
{
  "schema": 1,
  "kivyforge": "3.0.0.dev0",
  "command": "build",
  "platform": "android",
  "ok": true,
  "data": {"artifacts": [{"path": "dice-roller-android", "kind": "project"}]},
  "diagnostics": []
}
```

`package -p linux`:

```json
{
  "schema": 1,
  "kivyforge": "3.0.0.dev0",
  "command": "package",
  "platform": "linux",
  "ok": true,
  "data": {
    "artifacts": [
      {"path": "dist/linux/dice-roller-1.0.0-x86_64.AppImage", "kind": "appimage"}
    ]
  },
  "diagnostics": []
}
```

`schema` leads and is an integer, `kivyforge` is `__version__`; both come from
`report/envelope.py` along with `command`, `platform`, `ok` and `diagnostics`.
`artifacts` inside `data` is the entire addition.

**Why a list.** Not for the reason that suggests itself. "Android with multiple ABIs
and iOS with an `.xcarchive` plus an `.ipa`" is false in both halves: Android puts
every ABI in *one* fat APK via `ndk.abiFilters` (`--abi` narrows that single file, it
does not split it), and iOS `package` announces only the `.ipa` — the `.xcarchive`
is an intermediate under `<slug>-ios/build/<scheme>.xcarchive` and there is no
`xcarchive` kind. The real justification is narrower:

- **`build -p android --debug` produces two products**: the generated project
  *and* the debug APK or AAB. `android_build` echoes `Built {out}` for the APK and
  then `return dest` for the project, so the APK path is discarded at the seam
  exactly as the desktop paths are (§1.1).
- **`package -p linux` produces one product whose `kind` varies**: `folder` for the
  AppDir under `-f folder`, `appimage` otherwise. One element, two vocabularies.

Neither case needs a list of *many*, but a field that is sometimes a scalar and
sometimes a list is worse to consume than a list that is usually one element, so a
list it is.

**iOS `package` emits only the `.ipa`.** That matches the single `Exported ...`
product line today and the §2.4 rule. The alternative — adding an `xcarchive` kind
and a second human line — would be claiming an artifact the human output never
mentions, for a consumer that has not asked for the intermediate.

**iOS `build --simulator`/`--device` gains a product line and an `app` artifact —
but only after step 1 pins where the `.app` is written.** This is the one place
where §2.4 has to be applied forwards rather than backwards, and it rests on a
detail that is easy to get wrong.

Today `_xcodebuild_step7` prints `xcodebuild build (simulator) ...` — progress —
and no product line at all. The `.app` is **not** under
`<slug>-ios/build/DerivedData/` for this path, despite `product_app_path` existing:
`_xcodebuild_step7` calls `build_command(...)` *without* `derived_data_path`
(`ios/cli.py:224-233`), so Xcode writes to its own global DerivedData under
`~/Library/Developer/Xcode/DerivedData/<project>-<hash>/`. Only `ios_run` pins the
project-local one (`ios/cli.py:387,410`). So there is no project-relative path to
report yet, and `relative_to(project_root)` would raise.

That makes this a three-part change, all in step 1:

1. Pass `derived_data_path=xb.build_dir / "DerivedData"` from `_xcodebuild_step7`,
   as `ios_run` already does. This is also a latent inconsistency worth closing on
   its own — `build --simulator` and `run` currently write the same product to two
   different places.
2. Verify the `.app` exists before announcing it, the way `_require_artifact` does
   on Android, rather than trusting `product_app_path`'s construction.
3. Then print `Built <relative .app>` and report the `app` artifact beside the
   `project` one.

Without step 1's first part the other two cannot be written honestly, which is why
this is sequenced rather than described as a payload detail.

Note the direction of the fix: the payload requirement exposed a genuine gap in the
*human* output, which had no product line either. The rule is about not inventing
data, not about freezing today's prose.

**iOS `build --release` produces the project *and* an `.ipa`.** Easy to miss,
because `--release` reads like a modifier on "build the project" while
`_xcodebuild_step7` in fact archives and exports, ending in
`Exported {xb.ipa_path...}` (`ios/cli.py:236-272`). So `build -p ios --release`
reports `project` plus `ipa`: the same `.ipa` that `package -p ios` produces, but
alongside the project rather than alone. It belongs in the step 3 matrix explicitly
rather than being inferred from `package`.

### 4.4 Diagnostics and exit codes

`BUILD_FAILURE` (`5`) is reserved in `report/exit_codes.py` and has never been
raised. These two verbs are its entire reason for existing.

| Situation | Code | Exit |
|---|---|---|
| Gradle / `xcodebuild` / `appimagetool` returned non-zero | `KF-BUILD-TOOL-FAILED`, `context={"tool","task"}` | `5` |
| Host cannot build this target (wrong OS) | `KF-HOST-INCAPABLE` (exists) | `3` |
| A tool could not be spawned at all (`FileNotFoundError`: `clang`, `codesign`, `otool`) | `KF-TOOLCHAIN-MISSING` | `3` |
| Lock drift blocks the build | `KF-LOCK-DRIFT` (exists) | `4` |
| Bad config or flag combination | untriaged raises keep `KF-ERROR` | `1` |
| Tool said success but produced no artifact (`_require_artifact`) | `KF-ARTIFACT-MISSING` | `5` |
| `byte_compile = true` and no compatible interpreter | `KF-BYTECOMPILE-NO-INTERP` (exists), ERROR | `1` |
| `byte_compile = "release"` (the default) and no compatible interpreter | `KF-BYTECOMPILE-NO-INTERP` (exists), WARNING | `0` |
| Manifest policy notes (Android `[policy] INFO:`) | `KF-MANIFEST-POLICY`, INFO | `0` |
| Packaging unsigned or ad-hoc signed when real signing is configurable | `KF-SIGNING-UNCONFIGURED`, WARNING | `0` |

What the narrowing buys is that four situations which are all `1` today become four
different answers: fix the file (`1`), fix the environment (`3`), re-lock (`4`), read
the log (`5`). Those want different reactions from a human and different branches
from an agent. `3` covers a wrong host OS and a tool that could not be spawned, but
not a toolchain Gradle discovers is missing — see the note below.

One code per *tool* is deliberately avoided in favour of one code with a `tool`
context field; the alternative invents vocabulary that grows with every toolchain.
Note that `ToolchainError` cannot express that yet: `as_diagnostic()` builds a
`Diagnostic` from `code`, `severity`, `message` and `remediation` and never passes
`context`, so step 4 has to add a `context=` constructor argument. Doctor populates
`context` itself and so did not need one.

**One code, two severities, on byte-compile.** A single WARNING row would conflate
two configurations that behave differently and must keep behaving differently.
`byte_compile = true` is an explicit demand and
`bundle.py:104` raises when it cannot be met; that is a config-or-environment
failure and must stay a failure. `byte_compile = "release"` is the *default*, and
it degrades to shipping source with a `[stage] not byte-compiling: ...` line
rather than breaking a build nobody configured. Same code, different severity and
exit — which is the intended use of a code, since the *meaning* is identical and
only the consequence differs.

Those `[stage] not byte-compiling` lines on Linux, macOS and Windows are already
progress-shaped and must become `report.progress`, not `report.line`. This is §3's
trap again, and byte-compile is where it is easiest to get wrong, because the line
reads like a conclusion.

**`KF-TOOLCHAIN-MISSING` is reachable at some sites and not others, and the table
means the reachable ones.** No up-front gate answers it: `check_host_capability`
compares `platform.system()` and nothing else on every backend,
`AndroidPlatform`'s is a deliberate no-op with a comment saying host *adequacy* is
doctor's job, and `_require_macos_host` gates the Xcode verbs on being on macOS
without checking that Xcode is installed. But an absent tool announces itself
conclusively when we try to spawn it, and two backends already catch exactly that:

- `macos/machotools.py:180-186` catches `FileNotFoundError` and raises "required
  macOS tool `<name>` not found. Install the Xcode command-line tools", covering
  `codesign` and `otool`.
- `macos/launcher.py:140-147` does the same for `clang`.

Those are already toolchain-missing determinations in prose, needing nothing but a
code and an exit status to become branchable. No preflight required.

**But spawn-failure coverage is uneven, and one gap is worse than a wrong code.**
`run_command` in `ios/xcode/runner.py:30-38` catches neither `FileNotFoundError` nor
`OSError`, so a host without `xcodebuild` raises straight through `ios_build` and
`ios_package` — and `reporting()` only catches `ToolchainError`
(`cli/_output.py:61`), so the result is a traceback with **no envelope at all**. For
a JSON consumer that is the worst available outcome: not a misclassified failure but
an unparseable one. Fixing it is a `try`/`except FileNotFoundError` in the one
funnel that every Xcode invocation already goes through.

A third group catches the parent `OSError` and so cannot distinguish "tool absent"
from any other spawn problem: `windows/signing.py:141` (`signtool`),
`windows/rcedit.py:108`, `linux/appimage.py:127` (`appimagetool`), and
`macos/notarize.py:133` — which does catch `FileNotFoundError` for `notarytool`.
Step 4 either narrows these to `except FileNotFoundError` ahead of the general
handler or records them as intentional exclusions. Either is fine; leaving it
unstated is not, because the difference is invisible until a CI image is missing a
tool.

**What stays out of reach is the Gradle-mediated case.** A missing JDK, SDK or NDK
is discovered *by Gradle*, inside a build that then fails as a build, so it arrives
as `KF-BUILD-TOOL-FAILED` at exit `5` — "read the log" — when the useful answer is
"fix the image" at `3`. Nothing in the exit status can fix that, because by the time
we see a non-zero Gradle exit the distinction is gone.

So step 4 assigns `KF-TOOLCHAIN-MISSING`/`3` to the `FileNotFoundError` sites, and
Android's toolchain gap stays open. Closing it needs a preflight on the Android build
path, which `doctor` already knows how to answer and which would pay for itself by
failing a bad runner in seconds instead of after a Gradle download. Worth doing, not
part of this item.

### 4.5 What moves, and what stays exactly as it is

- **The distribution advice paragraphs** (Windows 3 lines, Linux 4, macOS 3) move
  to `BuildOutcome.notes`: still printed for humans, absent from the envelope.
  They are documentation that happens to be delivered at the end of a build.
- **Android's `[collect]`/`[stage]`/`[generate]`/`[gradle]` lines** keep their
  wording. The bracket prefixes are already a good convention and redesigning them
  is not part of this. Their *stream* does change, though: `click.echo` puts them on
  stdout today, and step 3 moves every bracketed line to stderr along with the rest
  of the progress register. That is the second half of the same behaviour break as
  the Gradle redirection and belongs in the same release note (§5, step 2).
- **`click.echo(proc.stdout)`** (`ios/cli.py:435`) stays as it is. It reads like a
  raw subprocess dump onto stdout that this item should clean up, but it is in
  `ios_list_devices`, which belongs to a different verb, and there the device list
  *is* the product — so stdout is already the right stream for it.
- **`run` is out of scope.** It inherits stdout on purpose, so the app's own output
  passes through untouched, and that is correct behaviour a `--json` conversion
  should not disturb. Worth a separate, smaller decision later.
- **Nothing else is deleted.** The human output is well judged; the problem is
  that it is the *only* output.

There is no `--quiet` or `-v` in this proposal. Verbosity control is orthogonal to
structured product output and should be added only if a concrete use case requires it.

## 5. Staging

1. `ArtifactKind`/`Artifact`/`BuildOutcome`, `Platform.build`/`package` returning
   them, backends filling them in. No `--json` yet.

   Human output is **byte-identical except for two deliberate changes**, neither of
   which can be papered over in the payload:

   - **Android's product lines become relative.** `android/cli.py:449,532` print
     `Built {out}` / `Packaged {out}` on a resolved absolute `Path`, while all four
     other backends print `{path.relative_to(project_root)}`. Left alone, step 1
     would freeze absolute host paths into the schema and contradict §4.1's
     posix-relative rule. Normalising Android is the smaller change and it makes
     the five backends agree.
   - **iOS `build --simulator`/`--device` gains a `Built <.app>` line**, after
     verifying the product exists. This one adds a line rather than changing one.

   One behaviour change comes with it, invisible in the output but not in the
   filesystem: **iOS `_xcodebuild_step7` starts passing `derived_data_path`**,
   matching `ios_run`, so the simulator/device `.app` lands under
   `<slug>-ios/build/DerivedData` instead of Xcode's global cache. This is a
   prerequisite rather than a nicety — without it there is no project-relative path
   to report at all (§4.3).

   Four more pieces belong here because they are the same edit:
   `BuildOutcome.as_dict()` (§4.1a), the distribution advice paragraphs moving to
   `BuildOutcome.notes` (§4.5, rendered at the same point so the bytes do not move),
   the `on_line`/`on_artifact`/`on_progress`/`on_note` callbacks of §4.1a, and the
   artifacts-only-if-finalised rule of §4.1b — including passing a no-op recorder
   into the three nested build calls, since that is where the rule actually lives.

   The CLI's step-1 wiring is human-only, but it cannot be `click.echo` four times:
   `on_note` would bind its message to Click's `file` parameter and `on_artifact`
   would print a dataclass `repr` (§4.1a). So step 1 defines four small adapters —
   `_echo_line`, `_echo_note` (prints the message, drops the code), `_discard`, and
   `click.echo` for progress — which step 3 swaps for report-backed closures.

2. **The Gradle redirection**, and nothing else. Worth landing alone, since it
   changes what a human sees on every Android build.

   **This is a behaviour break for anyone capturing only stdout**, and it should be
   announced as one rather than discovered. `kivyforge package -p android >
   build.log` captures Gradle today and will not afterwards; such a job needs
   `2>&1` or must capture both streams. The same note has to cover the bracketed
   `[stage]`/`[gradle]` lines, which move from stdout to stderr in step 3 — one
   announcement, since to a caller "kivyforge's Android output moved to stderr" is a
   single change even though we land it in two steps.

   §4.2a's log-versus-diagnostic split **cannot land here**, which is worth stating
   because it looks like stream work. It needs somewhere to put the captured
   transcript, and `report.progress` does not exist for these verbs until step 3 —
   step 1 leaves the callbacks pointed at `click.echo` on *stdout*, so routing a
   megabyte of `xcodebuild` output through them would contaminate stdout to fix a
   contamination. It moves to step 3.

3. `--json` for both verbs. This is where step 1's adapters are replaced by
   report-backed closures — `on_line → report.line`, `on_progress →
   report.progress`, `on_note →` a closure building the `Diagnostic`, and
   `on_artifact →` the accumulator of §4.1a — where the bracketed Android lines land
   on stderr, and, because there is finally somewhere to put a transcript, where
   §4.2a's log split happens. Also `report.record(artifacts=[])` at the top of each
   verb (§4.1a).

   Note that `report.product` and `report.diagnose(code, message)` do not exist;
   `Report`'s surface is `line`/`progress`/`diagnose(Diagnostic)`
   (`report/console.py:127-185`), which is what the closures adapt to.

   Pinned by tests that **assert fields, not the serialised envelope**. `kivyforge`
   carries `__version__`, so a golden blob would fail on every version bump;
   `tests/cli/test_lock_json.py` and the `status` tests already assert per-field for
   exactly this reason and are the pattern to copy — plus the plumbing assertions in
   the table below, which are where the real risk sits.
4. Exit-code and diagnostic narrowing per §4.4 — **the whole table, not just the
   host gates**:

   - `ToolchainError` gains `context=`, since `as_diagnostic()` cannot express
     `{"tool", "task"}` today.
   - `KF-BUILD-TOOL-FAILED`/`5` at the three bulk-tool failure sites, carrying
     `context={"tool", "task"}`; `KF-ARTIFACT-MISSING`/`5` at `_require_artifact`
     and its per-platform equivalents; `KF-LOCK-DRIFT`/`4` at the lock-verification
     failures in all five backends.
   - The three success-path note codes of §4.4 wired through `on_note`:
     `KF-SIGNING-UNCONFIGURED`, and the byte-compile and staging notes.
   - The host gates: `_require_linux_host` (`linux/cli.py:190`),
     `_require_windows_host` (`windows/cli.py:272`) and the two `_require_macos_host`
     definitions (`macos/cli.py:226`, `ios/cli.py:337`) all
     `raise ToolchainError(str(exc))` from `HostCapabilityError`, landing on
     `KF-ERROR` and exit `1`. `lock` already solved this — `KF-HOST-INCAPABLE`, exit
     `3` — and these four sites should copy it rather than invent a second pattern.
   - `KF-TOOLCHAIN-MISSING`/`3` at the spawn-failure sites, including the
     `run_command` gap that currently emits no envelope at all (§4.4).

   **Android needs a design decision before any of this reaches it.** Saying
   `@user_facing` should "forward" `code` and `exit_code` presumes
   `AndroidBuildError` has them, and it does not — it is a plain `Exception`
   carrying only a message, which is exactly why the decorator can do no better
   than `str(exc)` today. So the work is: give `AndroidBuildError` optional
   structured fields, or split it into typed subclasses per failure family
   (`GradleFailed`, `ArtifactMissing`, `LockDrift`, `ContractViolation`), and only
   then teach the decorator to map them. Subclasses are probably the better fit,
   since the raise sites already group that way and the funnel becomes a small
   dispatch table rather than an argument-passing convention nobody can forget to
   follow. Either way it is a change to the backend's error vocabulary, not a
   two-line edit to a decorator, and it is the largest single piece of step 4.

Steps 1 and 2 are independent and either can go first; 3 depends on both. Step 3 is
the largest, because it is where every callback is repointed at once — and that is
deliberate: the alternative is a half-routed intermediate state where some output has
moved and some has not.

**Test shape for step 3: a per-verb `(command, flags) → artifacts[]` matrix.** One
golden envelope per verb is too coarse for five backends times two verbs times the
format and target flags, and the cases most likely to be wrong are the ones a
single example hides. The matrix has to pin at least:

| Invocation | `artifacts` |
|---|---|
| `build -p windows` / `-p macos` / `-p linux` | one: `folder`, `app`, `folder` |
| `build -p android` | one: `project` |
| `build -p android --debug` | **two**: `project` + `apk` (or `aab` with `-f aab`) |
| `build -p ios` (no target) | one: `project` |
| `build -p ios --simulator` / `--device` | **two**: `project` + `app` |
| `build -p ios --release` | **two**: `project` + `ipa` |
| `package -p linux -f appimage` / `-f folder` | one, `kind` differing: `appimage` / `folder` |
| `package -p android -f apk` / `-f aab` | one: `apk` / `aab` |
| `package -p ios` | one: `ipa` (never the `.xcarchive`) |
| `build -p android`/`-p ios` failing after generation | one: the fresh `project` |
| `package -p android`/`-p ios` failing after generation | `[]` — the project is an intermediate for `package` |
| `package -p linux`/`-p windows` failing in the tool or the signer | `[]`, and specifically *not* the preserved previous artifact |
| failure before target resolution | `[]`, from `report.record(artifacts=[])` |

The `--release`/`--debug`/`--simulator` rows are the ones a single golden example
would have missed. The four failure rows are the ones most likely to regress
silently, since a stale path looks exactly like a fresh one and the
`build`-versus-`package` asymmetry on the same directory is easy to get backwards.
Pin them in the style of `tests/cli/test_lock_json.py`.

**But the payload is not where this proposal is most likely to break.** The matrix
above checks the part that is easy to reason about. The risks are in the plumbing —
stream routing, descriptor handling, and the ordering of output produced from inside
nested calls — so the suite needs assertions aimed at those directly:

| Assertion | The failure it catches |
|---|---|
| `--json` stdout parses as exactly one JSON document, on success *and* on every failure class | The whole point of the flag. One stray `click.echo`, or a second `emit`, and every consumer breaks. |
| No product line appears on stderr and no progress line on stdout, per verb per platform | The §3 split is enforced at ~60 call sites by hand; nothing else notices a mistake. |
| Gradle redirection works both with a real `fileno()` and through the no-`fileno` fallback | §4.2's descriptor problem. `CliRunner` and pytest capture both replace stdout, so the fallback path is what tests exercise by default and production almost never uses — the reverse of the usual risk. |
| A failing `xcodebuild` and a failing `appimagetool` put their transcript on stderr and *only* a summary in `diagnostics[].message` | §4.2a. Regressing this reintroduces megabytes of JSON-escaped log. |
| `package -p macos`/`-p ios`/`-p android` still print their intermediate `Built`/`Generated` lines while recording no intermediate artifact | §4.1a's nesting rule — the one place where the human and machine registers deliberately disagree, and the easiest to wire wrong. |
| Human-mode output is byte-identical to the pre-change baseline, except the changes §5 names | Every step claims this; only a test enforces it. Capture a baseline before step 1. |

The ordering assertion matters most for iOS, where `Generated` sits minutes before
`Exported` with a `xcodebuild` run between them: that gap is the reason product is
an event at all (§4.1a), and a refactor that quietly moves the line to the end would
pass every payload test in the matrix above.

**Retiring retro §1.9 is *not* a step here**, tempting though it looks. The result
type does not let `clean` stop hard-coding output paths: `clean` needs those paths
*without* running anything, and
`BuildOutcome` only exists as the return value of a build that ran. Fixing §1.9
needs a separate declarative query on `Platform` — something like
`clean_targets(project_root, config) -> tuple[Path, ...]` — which shares no code
with this item and serves neither CI nor agents. It is a real debt and it belongs
in its own change. §1.1's observation that nothing publishes these paths still
stands as the diagnosis; the claim that one structured result cures it does not.

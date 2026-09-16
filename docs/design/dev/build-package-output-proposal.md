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
| Windows | 2 lines | `Built <path>`, then a 3-line `Packaged ...` note |
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
- **Progress → stderr, always, including under `--json`.** *All* third-party output
  is progress, whenever we show it at all — §4.2 leaves `appimagetool`'s discarded
  and `xcodebuild`'s buffered, and neither becomes product by being withheld. So is
  every `[stage]`/`[collect]`/`[generate]`/`[gradle]` line, and iOS's
  `xcodebuild archive ...`.
- **`--json` does not introduce a second tool-output path.** Third-party output
  uses the same stderr path in human and JSON modes. The flag changes stdout only,
  swapping our own product lines for the envelope. So `kivyforge package -p android
  --json > out.json` puts nothing but JSON in the file while Gradle's log still
  scrolls past on the terminal, exactly as it does without the flag.

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

Paths stay **relative to the project root** and posix-separated, matching what the
human lines already print, what `status --json` does, and the rule the T3 checks
adopted on 2026-09-15 for in-artifact paths. Android is the exception that has to
be fixed rather than accommodated — see step 1 in §5.

### 4.1a How backends reach the report

Information travels from a backend to the report by three routes, and picking only
the first is a trap: it leaves `Report`
withheld from the platforms — rightly — while §3 requires `[stage]` lines to become
`report.progress` and §4.4 puts INFO and WARNING diagnostics on the *success* path,
both of which are produced deep inside the backends. Neither could then arrive.

`lock` already solved this and the answer is to copy it rather than invent
anything.

**1. Artifacts, on success — a return value.** `Platform.build`/`package` return
`BuildOutcome`; the verb records and emits it.

**2. Artifacts, on failure — attached to the raise.** `Report` lives in
`cli/_output.py` and a verb that raises never reaches its own `emit`, so
`ToolchainError` grows an optional `data=` that `reporting()` merges with anything
already recorded. Subject to the safety rule below, which turns out to matter more
than the channel does.

**3. Progress and diagnostics — narrow callbacks, resolved verb-side.** This is
the `lock` pattern verbatim. `cli/lock.py` does not hand `Report` to a backend; it
passes `on_warning=lambda msg: _warn(report, msg)`, and `_warn` — on the CLI side —
does both `report.progress(msg)` and `report.diagnose(Diagnostic(...))`. The
backend calls a plain callable and knows nothing about reports, codes or
severities. The `echo=` callbacks in `linux/appimage.py` and `linux/bundle.py` are
already the progress half of the same shape.

Generalised to five backends with more than one diagnostic kind, that is
`on_progress(message)` for pass-through chatter and `on_note(code, message)` for
the three success-path diagnostics in §4.4. `code` is a constant from
`report/diagnostics.py`, which is a pure constants-and-dataclass module a backend
can import without touching `Report`. The verb-side closure decides severity and
whether the note also prints.

Two consequences worth stating. **`Report` still never enters the platforms**, so
`status`'s "backends return data, the verb renders" survives intact. And **a
diagnostic raised through the callback is already accumulated on `Report` before
any later failure**, so success-path warnings survive into a failure envelope with
no extra channel — which is exactly how `lock`'s stale-check diff reaches
`"data"` today.

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
backend must have verified existence at the moment it reports them.** On most
failures that means an empty list, and an empty list is the correct answer. The
`--debug` case still works — if `assembleDebug` succeeded and a later step failed,
that APK was finalised by this run — but it works because the backend knows it
wrote the file, not because the path happens to exist.

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
- **The Linux failure path changes**, under principle 2. `appimage.py:134` raises
  with `proc.stderr or proc.stdout`, so whenever stderr holds anything the stdout
  half of the evidence is thrown away. That is precisely the trap
  `ios/xcode/runner.py:33-38` carries a comment about: it joins both streams
  *because* picking one can hide the real failure behind a harmless warning. Linux
  should join both the same way.
- **Everything else that captures** (`codesign`, `otool`, `hdiutil`, `adb`, the
  resolvers) is *queried* for its output and must not change.

**One implementation note that will bite in tests.** `subprocess` needs a real
`fileno()`, and `sys.stderr` does not always have one — Click's `CliRunner` and
pytest's capture both replace it. This needs a small helper on the report seam
that hands back the descriptor when there is one and falls back to a pump when
there is not, rather than each call site guessing.

### 4.2a The failure path already puts tool output on stdout, and that has to stop

§3's rule has a second route for third-party output that it does not account for,
and that route goes straight to stdout in JSON mode.

The tools we capture embed their output in the exception message —
`CommandError` joins xcodebuild's stdout and stderr into its message
(`ios/xcode/runner.py:20-27`), `AppDirError` interpolates `appimagetool`'s output —
and the backends then wrap those with `raise ToolchainError(str(exc))`.
`ToolchainError.as_diagnostic()` sets `message=self.format_message()`, so the
whole captured log lands in `diagnostics[].message` **on stdout**, inside the JSON
document. "All third-party output is progress, and progress is stderr" is
contradicted by the one path that matters most.

It is also a payload problem independent of the rule: a failing `xcodebuild` can
emit megabytes, and a diagnostic message is the wrong place for it. A consumer
reading `diagnostics[0].message` to decide what went wrong does not want a build
transcript, and JSON-escaping one is pure cost.

**The split: the diagnostic message is a summary; the log goes to stderr only.**
Where a backend has captured output it writes that output to `report.progress`
before raising, and raises with a summary — which tool, which task, which exit
code, plus the `Fix:` line the convention already provides. Both registers keep
their meaning: the envelope says *what* failed in a form worth branching on, and
stderr carries the evidence, in the same place and format as it would have on a
successful run.

Two notes on scope. This lands in step 2 with the other stream work, not step 4 —
step 4 then revisits the same raise sites to attach `code`, `exit_code` and
`context`, so the two touch the same lines for different reasons. And it removes the
last asymmetry between the redirected tool (Gradle, whose output was never in our
hands) and the captured ones, so all three failure paths end up reading the same
way.

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
| Lock drift blocks the build | `KF-LOCK-DRIFT` (exists) | `4` |
| Bad config or flag combination | untriaged raises keep `KF-ERROR` | `1` |
| Tool said success but produced no artifact (`_require_artifact`) | `KF-ARTIFACT-MISSING` | `5` |
| `byte_compile = true` and no compatible interpreter | `KF-BYTECOMPILE-NO-INTERP` (exists), ERROR | `1` |
| `byte_compile = "release"` (the default) and no compatible interpreter | `KF-BYTECOMPILE-NO-INTERP` (exists), WARNING | `0` |
| Manifest policy notes (Android `[policy] INFO:`) | `KF-MANIFEST-POLICY`, INFO | `0` |
| Packaging unsigned or ad-hoc signed when real signing is configurable | `KF-SIGNING-UNCONFIGURED`, WARNING | `0` |

What the narrowing buys is that four situations which are all `1` today become
four different answers: fix the file (`1`), fix the host OS (`3`), re-lock (`4`),
read the log (`5`). Those want different reactions from a human and different
branches from an agent. Note that `3` is narrower than "fix the environment" — see
the `KF-TOOLCHAIN-MISSING` note below for what it does *not* cover yet.

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

**`KF-TOOLCHAIN-MISSING` is deliberately absent, because nothing can raise it yet.**
It belongs in a table like this one — exit `3`, "required toolchain absent (no
JDK/NDK/clang)" — and no code path can honestly reach it. Android looks like the
exception; checked properly, it is the rule:

- `check_host_capability` compares `platform.system()` and nothing else on every
  backend. It answers "is this the right OS", not "is the toolchain installed".
- `AndroidPlatform.check_host_capability` is deliberately a no-op, with a comment
  saying host *adequacy* is doctor's job.
- `_require_macos_host` gates the Xcode verbs on being on macOS; it does not check
  that Xcode, the command-line tools or a signing identity exist.

So a runner missing a JDK, an NDK or Xcode does not fail a gate on any platform. It
fails inside a subprocess, and the honest report for that is
`KF-BUILD-TOOL-FAILED` at exit `5` — "read the log" — where the useful answer would
have been "fix the image" at `3`.

That leaves exit `3` meaning exactly one thing after this item: wrong OS, via
`KF-HOST-INCAPABLE`. The narrowing is still worth doing — four answers beat one —
but `3` does not yet mean "fix the image", and the table above does not claim it
does.

Closing that properly needs preflights on the build paths, which `doctor` already
knows how to answer. That is a separate change with its own value (it would let a
CI job fail in seconds instead of after a Gradle download), and inventing
`KF-TOOLCHAIN-MISSING` here without a raise site would be reserving vocabulary for
work not yet done.

### 4.5 What moves, and what stays exactly as it is

- **The distribution advice paragraphs** (Windows 3 lines, Linux 4, macOS 3) move
  to `BuildOutcome.notes`: still printed for humans, absent from the envelope.
  They are documentation that happens to be delivered at the end of a build.
- **Android's `[collect]`/`[stage]`/`[generate]`/`[gradle]` lines** stay exactly as
  they read today, on stderr. The bracket prefixes are already a good convention
  and redesigning them is not part of this.
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

   Three more pieces belong here because they are the same edit: the distribution
   advice paragraphs moving to `BuildOutcome.notes` (§4.5, rendered at the same point
   so the bytes do not move), the `on_progress`/`on_note` callbacks of §4.1a, and the
   artifacts-only-if-finalised rule of §4.1b. Backends can take the callbacks while
   the CLI still passes `click.echo`, which keeps step 1 behaviour-preserving and
   leaves the rerouting to step 3.

2. The Gradle redirection, joining both streams in `appimage.py`'s failure message,
   and the §4.2a split that moves captured tool logs out of exception messages onto
   stderr. Still no `--json`. Worth landing alone, since it changes what a human
   sees on every Android build.

   **This is a behaviour break for anyone capturing only stdout**, and it should be
   announced as one rather than discovered. `kivyforge package -p android >
   build.log` captures Gradle today and will not afterwards; such a job needs
   `2>&1` or must capture both streams. The change is still right — inheriting
   stdout is what makes `--json` impossible — but "we moved your build log" is a
   release note, not an implementation detail.

3. `--json` for both verbs, pinned by tests that **assert fields, not the
   serialised envelope**. `kivyforge` carries `__version__`, so a golden blob would
   fail on every version bump; `tests/cli/test_lock_json.py` and the `status` tests
   already assert per-field for exactly this reason and are the pattern to copy.
4. Exit-code and diagnostic narrowing per §4.4. This includes the `context=`
   argument on `ToolchainError`, and narrowing the host gates: `_require_linux_host`
   (`linux/cli.py:190`), `_require_windows_host` (`windows/cli.py:272`) and the two
   `_require_macos_host` definitions (`macos/cli.py:226`, `ios/cli.py:337`) all
   `raise ToolchainError(str(exc))` from `HostCapabilityError`, landing on
   `KF-ERROR` and exit `1`. `lock` already solved this — `KF-HOST-INCAPABLE`, exit
   `3` — and these four sites should copy it rather than invent a second pattern.

Steps 1 and 2 are independent and either can go first; 3 depends on both. Step 2
carries §4.2a as well, which makes it the step that changes failure output *and*
success output — worth its own commit for that reason alone.

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
| any failure after a finalised product | only that product, per §4.1b |
| any failure before one | `[]` — and specifically *not* Linux's or Windows's preserved previous artifact |

The three `--release`/`--debug`/`--simulator` rows are the ones a single golden
example would have missed, and the last two rows are the ones most likely to
regress silently, since a stale path looks exactly like a fresh one. Pin them in the
style of `tests/cli/test_lock_json.py`.

**Retiring retro §1.9 is *not* a step here**, tempting though it looks. The result
type does not let `clean` stop hard-coding output paths: `clean` needs those paths
*without* running anything, and
`BuildOutcome` only exists as the return value of a build that ran. Fixing §1.9
needs a separate declarative query on `Platform` — something like
`clean_targets(project_root, config) -> tuple[Path, ...]` — which shares no code
with this item and serves neither CI nor agents. It is a real debt and it belongs
in its own change. §1.1's observation that nothing publishes these paths still
stands as the diagnosis; the claim that one structured result cures it does not.

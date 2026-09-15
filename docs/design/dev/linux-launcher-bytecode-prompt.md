# Agent prompt — the Linux launcher's bytecode-write behaviour is unmeasured

> **Run this in WSL2**, from the repo root of `modernization-rfc`. Written
> 2026-09-14 from the Windows host, which can build no Linux artifact and launch
> nothing — so everything below is either *read out of the source* or *inferred*,
> and the inferences are labelled as such.
>
> Point the agent at this file, or copy the "Prompt" section.
>
> Third in a chain of cross-host hand-offs, and the shape is deliberate:
> [`macos-ios-validation-prompt.md`](macos-ios-validation-prompt.md) produced
> [`macos-ios-validation-findings.md`](macos-ios-validation-findings.md); a WSL2
> agent read that findings file and queued
> [`macos-launcher-strip-source-prompt.md`](macos-launcher-strip-source-prompt.md)
> for the Mac; running *that* turned up a second defect, which is what this file
> is about. Each host has caught something the others structurally could not.

## Background — a fix on macOS that Linux has not been checked against

`kivyforge package -p macos` was shipping an unlaunchable `.app` for the same
reason `package -p linux` was shipping an unlaunchable AppImage: the launcher
named `<entry>.py`, and `strip_source` deletes it. Linux found and fixed this
first (`test-matrix.md` §7); macOS mirrored the fix in `c0477741`.

The interesting part is what the macOS fix *uncovered*. Its first successful
launch — the first time anything had ever started that bundle — immediately
wrote `__pycache__` into the embedded stdlib and invalidated the bundle's own
code signature (`codesign --verify`: "a sealed resource is missing or invalid").
The stdlib is shipped as `.py` on purpose, since `strip_source` is scoped to
`app`/`site-packages`, so merely importing it wrote caches beside the source.
The fix was `setenv("PYTHONDONTWRITEBYTECODE", "1", 1)` in the same launcher.

**Linux does not set it.** Verified by reading
`kivyforge/platforms/linux/launcher.py`: the `_APPRUN` template exports
`PYTHONHOME`, `PYTHONPATH`, `PYTHONNOUSERSITE`, the two `SDL_VIDEO_*_WMCLASS`
vars, and (in the native block) `PATH` and `LD_LIBRARY_PATH`. Nothing else.

The macOS docstring calls the reason "specific to macOS". That is true of the
*consequence* — only Apple seals a bundle with a signature that a self-write
breaks — but not of the *behaviour*. Python writes caches on Linux too, and
nobody has looked at where they land.

### What is actually at stake here — read this before deciding it is trivial

Two claims, both **unverified** (this is the whole errand):

1. **The `.AppImage` is probably immune.** A type-2 AppImage mounts its
   squashfs read-only, so the writes should fail with `EROFS`, and CPython
   tolerates a failed cache write silently. If so the cost is wasted syscalls
   per import, not corruption.
2. **The AppDir folder form is probably *not* immune.** `kivyforge package
   -f folder` leaves a real, writable directory at
   `build/linux/<display name>.AppDir`, and that is *also* the tree the T3
   driver inspects. Launching one plausibly deposits `__pycache__` into the
   artifact under test.

Neither would fail a check today, and it is worth being precise about why rather
than assuming we are covered. `_linux_payload_problems` only looks for
`__pycache__` inside `if stripped:` (`tests/artifact_checks.py`, the `cached`
branch), and its payload scope is `usr/app` + `usr/lib` — the stdlib lives under
`usr/python` and is deliberately excluded, with
`test_the_stdlib_keeping_its_source_is_not_a_fault` pinning that. So:

- **stripped payload** — sourceless `.pyc` in the legacy layout writes nothing,
  so `usr/app` stays clean. The *stdlib* under `usr/python` may still be
  polluted, and no check looks there.
- **unstripped payload** (`build`/`run`, `-f folder` without release) — imports
  would write `usr/app/__pycache__`, and the `cached` check does not run for
  unstripped builds, so nothing notices.

That is a gap in the checks as much as in the launcher, and the second half of
this errand.

### The other half — the startup cost nobody has measured

The macOS write is *evidence* that the embedded stdlib ships without usable
cached bytecode; if it had shipped with `.pyc`, importing would not have written
any. Linux ships the same python-build-standalone runtime, so Linux has been
paying full source-parse cost on every stdlib import since the beginning — and,
if claim 1 holds, has been paying it forever, because the writes it attempts can
never succeed on a read-only mount.

Setting `PYTHONDONTWRITEBYTECODE=1` makes that permanent and explicit rather
than accidental. The better long-term fix is to **byte-compile the embedded
stdlib at build time**, which would get a clean artifact *and* a fast start, and
would demote the environment variable to belt-and-braces. That is cross-platform
work (macOS wants it too) and is explicitly **not** what this prompt asks you to
implement. It asks you to *measure* it, because Linux is the cheapest host to
measure it on, and a number is what turns "we should probably" into a roadmap
item worth scheduling.

---

## Prompt

You are closing out a launcher follow-up on Linux. Base: `modernization-rfc` at
`1b2fa6ef` or later. **Evidence before code** — the two claims in Background are
inferences from a host that cannot run any of this, and the first thing you owe
is a measurement that confirms or kills them.

### Step 0 — read before touching anything

Read [`test-matrix.md`](test-matrix.md) (§5, §7, and the three rules at the top),
the `_APPRUN` template and its comments in
`kivyforge/platforms/linux/launcher.py`, and the `PYTHONDONTWRITEBYTECODE`
comment in `kivyforge/platforms/macos/launcher.py` (`c0477741`). Do not take
this file's Background as a substitute for any of them.

Also note `1b2fa6ef`, which fixed nine failures your T3 checks produced on the
Windows host: the AppRun executable-bit check cannot be answered on NTFS, and
problem messages were interpolating `Path` objects so in-artifact paths came out
`usr\app\main.py`. **`windows_tests` runs the full suite unfiltered on
windows-latest**, so anything hermetic you add runs there too. Keep new checks
host-portable, and render in-artifact paths with `as_posix()`.

### Step 1 — measure, before changing anything

Build both shapes and find out where bytecode actually lands.

```bash
cd examples/desktop/dice-roller
kivyforge package -p linux -f folder          # writable AppDir, release/stripped
APPDIR="build/linux/Dice Roller.AppDir"       # note the space
find "$APPDIR" -name __pycache__ -type d      # baseline: expect none in the payload
"$APPDIR/AppRun"                              # launch it, then close the window
find "$APPDIR" -name __pycache__ -type d      # did launching pollute the artifact?
```

Record which directories appear, and specifically whether any land under
`usr/app`/`usr/lib` (payload) versus `usr/python` (stdlib). Then repeat for the
unstripped shape (`kivyforge build -p linux`, which passes `release=False`),
where the payload still has `.py` for imports to write beside.

Then the AppImage, to settle claim 1:

```bash
kivyforge package -p linux                    # default: .AppImage
./build/linux/*.AppImage                      # launch, close
```

A read-only mount cannot be inspected after exit, so prove it from the running
process instead — e.g. launch it and check `/proc/<pid>/mounts` for the `ro`
flag on the mountpoint, or simply confirm no cache appears in an extracted copy
that you then launch from a read-only bind mount. Any method that produces
evidence is fine; asserting "squashfs is read-only, therefore fine" is not.

**If launching the folder-form AppDir pollutes it, say so plainly** — that means
the T3 driver has been inspecting artifacts that a launch can mutate, which is
worth a line in §7 on its own.

### Step 2 — the fix

Add to the `_APPRUN` template in `kivyforge/platforms/linux/launcher.py`, beside
`PYTHONNOUSERSITE`:

```sh
export PYTHONDONTWRITEBYTECODE=1
```

Comment it with what **Step 1 actually measured**, not with the macOS rationale
copied across. The macOS reason is a broken code signature; Linux has no
signature, so if your evidence says the real reason is "keeps a folder-form
AppDir from mutating when launched, and makes the futile write attempts on a
read-only mount explicit", write that. If Step 1 shows nothing is polluted
anywhere, then this is symmetry and intent only — still worth doing, but say so
honestly rather than implying a bug was fixed.

Do not add it to the native-binaries block; it is unconditional.

### Step 3 — close the check-side gap

`_linux_payload_problems` only looks for `__pycache__` under `if stripped:`.
Decide whether an unstripped payload carrying `__pycache__` is worth reporting.
The argument for: post-fix it can only appear if something wrote into the
artifact after the build, which is exactly the thing Step 2 sets out to prevent,
so it is a cheap regression net. The argument against: for an unstripped build
`__pycache__` is *normal* Python behaviour and flagging it is noise.

Either answer is defensible — pick one and record why. If you add it, phrase the
message so it accuses the *launch*, not the build.

### Step 4 — measure the startup cost

This is the number that decides whether build-time stdlib compilation gets
scheduled. Use the bundled interpreter with the same environment `AppRun` sets:

```bash
APPDIR="build/linux/Dice Roller.AppDir"
PY="$APPDIR/usr/python/bin/python3"
export PYTHONHOME="$APPDIR/usr/python"
export PYTHONPATH="$APPDIR/usr/app:$APPDIR/usr/lib"
export PYTHONNOUSERSITE=1

# Cold: no cached bytecode anywhere in the runtime.
find "$APPDIR/usr/python" -name __pycache__ -type d -prune -exec rm -rf {} +
for i in 1 2 3; do /usr/bin/time -f 'cold %e' "$PY" -P -c 'import kivy'; done

# Warm: what a build-time compileall would have shipped.
"$PY" -m compileall -q "$APPDIR/usr/python/lib/python3."*
for i in 1 2 3; do /usr/bin/time -f 'warm %e' "$PY" -P -c 'import kivy'; done
```

Report both, and `-X importtime` for the cold case if the delta is large enough
to want a breakdown. `import kivy` is the right probe — it is what the app
actually pays on startup, not a synthetic `import sys`.

Do the measurement on a `compileall`-warmed copy, then **discard it**: a
hand-compiled runtime is not what the build produces, and leaving it around
would make later runs measure a state no user ever has.

### Step 5 — tests

In `tests/platforms/linux/test_launcher.py`, assert the rendered `AppRun`
exports `PYTHONDONTWRITEBYTECODE=1`. Mirror the naming of the macOS guard
(`test_never_writes_bytecode_into_the_signed_bundle`) but not its justification —
the Linux name should say what Linux is protecting.

If Step 3 added a check, unit-test it in `tests/test_artifact_checks.py` against
a synthetic AppDir, both polarities. Keep it host-portable per Step 0.

Then the full unfiltered suite plus `ruff check` and `ruff format --check`.

### Step 6 — update the record

1. **`test-matrix.md` §7** — a dated row: what Step 1 measured, the Step 2
   change, and the Step 4 numbers. The numbers are the durable part; a future
   reader deciding whether to compile the stdlib at build time should not have
   to re-derive them.
2. **`test-matrix.md` §5** — add build-time stdlib byte-compilation as a known
   gap if Step 4 says it is worth real time, with the measured delta attached.
   If the delta is negligible, say *that* instead and close the question.
3. **Roadmap** — only if Step 4 justifies it. A measured cost is a roadmap item;
   a suspected one is not.

Write a findings file if the run turns up anything this prompt did not predict.
Two of the three hand-offs in this chain did.

## Acceptance

- [ ] Step 1 evidence recorded for all three shapes: stripped folder, unstripped
      folder, `.AppImage` — including which subtree any `__pycache__` landed in.
- [ ] Claim 1 and claim 2 each explicitly confirmed or refuted, from evidence.
- [ ] `AppRun` exports `PYTHONDONTWRITEBYTECODE=1`, commented with the measured
      Linux reason rather than the macOS one.
- [ ] The unstripped-`__pycache__` check question answered either way, with the
      reasoning recorded.
- [ ] Cold and warm startup numbers reported, `compileall`-warmed copy discarded.
- [ ] Full suite + lint clean, and anything new is host-portable.
- [ ] §7 updated; §5 and the roadmap updated or explicitly closed.

## Do not

- **Do not byte-compile the embedded stdlib in this change.** It is the likely
  right answer and it is cross-platform (macOS wants it too, and its launcher
  comment should be revisited at the same time). Measure it here, schedule it
  separately.
- **Do not reach for `-B`.** The env var is what macOS uses and what a user can
  override for debugging; a hardcoded interpreter flag cannot be turned off.
- **Do not narrow `strip_source` to cover the stdlib** as a way around this.
  Shipping the stdlib as source is deliberate, and conflating the two settings
  would couple an unrelated knob to this bug.
- **Do not copy the macOS comment verbatim.** Linux has no code signature; a
  comment claiming otherwise is worse than no comment.
- **Do not assume the AppImage case from first principles.** "squashfs is
  read-only" is the hypothesis, not the finding.
- **Do not add host-dependent assertions.** `windows_tests` runs your hermetic
  tests on NTFS — see `1b2fa6ef` for the nine failures that taught us this.
- **Do not commit `examples/desktop/dice-roller/pylock.linux.toml`.** Desktop
  example locks are gitignored on purpose
  ([`common/03-lockfile-concept.md`](../common/03-lockfile-concept.md)
  §"Example-repo lock policy").

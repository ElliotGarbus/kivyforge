# Linux launcher bytecode findings

Validation run against `modernization-rfc` per
[`linux-launcher-bytecode-prompt.md`](linux-launcher-bytecode-prompt.md), in
WSL2. Date: 2026-09-15.

Fourth in the cross-host chain that began with
[`macos-ios-validation-prompt.md`](macos-ios-validation-prompt.md). Both claims
the prompt asked about were confirmed, and three things it did not predict came
out of the measurements.

## Environment

| Item | Value |
|------|-------|
| Host | Ubuntu 26.04 LTS on WSL2 (kernel 6.18.33.2-microsoft-standard-WSL2) |
| Host Python | 3.14.4 |
| Bundled runtime | CPython 3.13.14 (python-build-standalone) |
| kivyforge | 3.0.0.dev0 (editable install) |
| Branch | `modernization-rfc` @ `7f4e2269` |
| Example | `examples/desktop/dice-roller` |

Method for every launch below: run the artifact for 15 s under `timeout`, which
is long past Kivy's "Start application main loop", then compare a `find -name
'*.pyc'` listing taken before and after.

## Step 1 — where bytecode actually lands

| Shape | Built with | `.pyc` before | Written by launch | Where |
|---|---|---|---|---|
| Stripped folder AppDir | `package -p linux -f folder` | 377 | **75** | all under `usr/python` |
| Unstripped folder AppDir | `build -p linux` | 3 | **209** | 100 payload, 109 stdlib |
| `.AppImage` | `package -p linux` | 377 | **0** | — |

### Claim 1 — "the `.AppImage` is probably immune" — confirmed

Proven rather than reasoned, as the prompt insisted. Two independent pieces:

```
/proc/<pid>/mounts  →  /tmp/.mount_dice-rHLfjgM  fuse.dice-roller-...AppImage
                       ro,nosuid,nodev,relatime,user_id=1000,group_id=1000
```

and, after roughly a minute of the app running and importing, the live mount
still held exactly the `41` stdlib `.pyc` and `6` `__pycache__` directories it
was built with. The comparison is what makes this evidence rather than a
restatement of the `ro` flag: the *same application performing the same imports*
gained 75 files in the folder form and zero here.

Incidentally, **WSL2 does have `/dev/fuse`** on this host, so the `.AppImage`
mounted and ran directly. Earlier Linux work in §7 used `--appimage-extract`
on the assumption that it could not; that assumption was wrong, and future
Linux verification can launch the real artifact rather than an unpacked copy.

### Claim 2 — "the folder form is probably not" — confirmed, and worse

The stripped folder AppDir behaved as the prompt guessed: 75 files, all in the
stdlib, nothing in the payload, because a sourceless `.pyc` payload gives
imports nothing to write beside.

The unstripped case was the bad one. `kivyforge build -p linux` stages 336 `.py`
and zero `.pyc`; launching it left **209** new files, of which **100 landed in
the payload itself** — `usr/app/__pycache__/main.cpython-313.pyc` plus 99 under
`usr/lib`. Since the folder form is also what the T3 driver inspects via
`--linux-appdir`, **launching an artifact under test had been mutating it.**

### Not predicted — the build pollutes its own output before any launch

The 377-vs-3 baseline in the table above is not incidental. A stripped AppDir
ships **41 stdlib `.pyc` in 6 `__pycache__` directories that no user action
created**, and an unstripped one ships 3.

The difference is `byte_compile`. It shells out to the *staged* interpreter to
compile the payload, and that subprocess's own imports — `encodings`,
`collections`, `importlib`, `pathlib`, `re` — write caches into `usr/python` on
the way. `build` never invokes it, which is why its baseline is almost empty.

Three consequences worth stating:

- The launcher fix cannot reach this. `AppRun` governs launches; these files are
  written at build time, by a different process.
- That subtree is not reproducible. Which 41 files appear is decided by whatever
  `compileall` happened to import, not by anything declared.
- On macOS the same code path runs *before* `codesign`, so those caches are
  currently sealed into the signature. Harmless there, and a reason not to
  change shared code from a host that cannot verify the signing side.

The fix is one line — `PYTHONDONTWRITEBYTECODE=1` in the subprocess environment
— and it is safe, verified directly: the variable suppresses implicit caching
on import but not an explicit `compileall`, which writes through `py_compile`.
Deliberately **not applied here**; filed as `test-matrix.md` §5.10 and roadmap
item 9, to land together with build-time stdlib compilation.

## Step 2 — the fix, and what it costs

`AppRun` now exports `PYTHONDONTWRITEBYTECODE=1`. Re-measured after the change:

| Shape | `.pyc` before | after | payload `__pycache__` |
|---|---|---|---|
| Stripped folder | 377 | **377** | 0 |
| Unstripped folder | 3 | **3** | **0** (was 100) |

Both still reach "Start application main loop", so nothing was traded for it at
runtime — but something *was* traded at startup, and the prompt did not predict
this either. The folder form had been buying warm-start performance by mutating
itself on first launch. Suppressing that makes it permanently cold, which is
the state the `.AppImage` has always been in. The fix is right and the artifact
is now honest; the cost it exposes is Step 4.

The launcher comment deliberately does not reuse the macOS rationale. macOS is
protecting a code signature; Linux seals nothing, and a comment claiming
otherwise would be worse than no comment. What Linux is protecting is an
artifact that a checker can be pointed at.

## Step 3 — the check-side gap

`_linux_payload_problems` only looked for `__pycache__` under `if stripped:`.
The prompt framed this as a judgement call — cheap regression net, or noise
because `__pycache__` is normal Python behaviour?

The measurement decides it. `__pycache__` is normal in a *working tree*; it is
never normal in a freshly staged AppDir, because the build either compiles the
payload with `compileall` or leaves it alone, and neither produces one. The
unstripped baseline is exactly 336 `.py` and 0 `.pyc`. So its presence is not
Python being Python — it is evidence the artifact was written to after the
build.

Added, with the message phrased to accuse the launch rather than the build, and
unit-tested in both polarities.

## Step 4 — the startup cost

`import kivy` under the bundled 3.13.14 with `AppRun`'s environment, 5 runs each:

```
cold (no stdlib cache, writes suppressed)   0.21 0.21 0.20 0.21 0.22
warm (after compileall over the stdlib)     0.04 0.04 0.04 0.05 0.04
```

**~5×, ~170 ms on every launch.** `-X importtime` on the cold case attributes it
to source parsing, not to anything kivyforge controls:

| Module | self (ms) |
|---|---|
| `typing` | 28.0 |
| `inspect` | 17.2 |
| `enum` | 12.2 |
| `logging` | 9.4 |
| `shutil` | 8.8 |

Cold is measured with `-B` so each run stays genuinely cold, which also makes it
an exact model of the `.AppImage`'s permanent state — and, since Step 2, of the
folder form's too. The warmed tree was a copy in `/tmp`, discarded afterwards so
no later run measures a state no user ever has.

## Conclusions

1. **Both claims confirmed.** The `.AppImage` is immune because its squashfs is
   `ro`; the folder form was not, and the unstripped case was polluting the
   payload, not just the stdlib.
2. **The T3 driver had been inspecting a mutable artifact.** Anyone who launched
   an AppDir before checking it was checking something the launch had changed.
3. **The build pollutes its own output**, independently of any launch, and the
   launcher fix cannot reach it. Small, safe, deliberately deferred because the
   code is shared with macOS.
4. **The fix has a real cost and that is the useful part.** It removes the only
   mechanism that was hiding a ~170 ms per-launch penalty. Build-time stdlib
   compilation moves from "probably worth doing" to the thing that pays for
   this fix — roadmap item 9.
5. **WSL2 can run AppImages directly here**, correcting an assumption in the
   earlier Linux work.

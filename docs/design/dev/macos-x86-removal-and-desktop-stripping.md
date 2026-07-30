# Plan: drop Intel macOS, then add desktop source stripping

> **Status: done (2026-07-29).** Two sequenced changes.
> **Phase A** removes `x86_64` from macOS and the iOS Simulator entirely — as a
> host *and* as a target. **Phase B** adds `byte_compile` / `strip_source` to the
> three desktop backends, matching what Android already does.
>
> A is first because it deletes the one special case in B's design.

## Why drop Intel macOS

Intel macOS is short-lived, and legacy tools already cover it; a new tool does
not need to carry it. The dates:

| When | What ends |
|---|---|
| macOS 27 (fall 2026) | Won't install on Intel hardware — Intel **hosts** end |
| ~Aug/fall 2027 | GitHub's `macos-*-intel` runners sunset — no native CI for the Intel slice |
| macOS 28 (fall 2027) | Rosetta removed — Intel binaries can't run on Apple Silicon at all |

The end state, if we kept it, is shipping a universal2 artifact whose Intel half
cannot be executed or validated on any available machine. The iOS Simulator
`x86_64` slice dies for the same reason: it only ever had value on an Intel Mac
host.

kivyforge is unreleased (`3.0.0.dev0`, not on PyPI), so this is the cheapest it
will ever be to take.

## The seam that matters

Wheel-tag handling and build-target handling are **separate concerns**, and only
the second one narrows.

- **`VALID_WHEEL_ARCHS`** — which wheel tags we *accept* — **keeps `universal2`**.
  A universal2 wheel is a perfectly good arm64 wheel, and Kivy 2.3.1 ships
  exactly that. `MacosProfile.wheel_covers()` already handles this generically
  and needs no change; a thin `x86_64` wheel naturally stops matching once
  `archs` is `("arm64",)`.
- **`VALID_MACOS_ARCHS`** — which archs we *build for* — drops to `{"arm64"}`.

Getting this backwards would reject most macOS wheels on PyPI.

## Phase A — remove macOS + iOS-Simulator x86_64

**A1 — Config constants + loader.**
`VALID_MACOS_ARCHS = {"arm64"}`, `DEFAULT_MACOS_ARCHS = ("arm64",)`,
`VALID_SIMULATOR_ARCHS = {"arm64"}`, `DEFAULT_SIMULATOR_ARCHS = ("arm64",)`.
The loader rejects `x86_64` for both with a message naming the reason and the
one-line fix. `VALID_WHEEL_ARCHS` is untouched (see the seam above).

**A2 — CLI `--arch` choices.**
These are a *union across platforms*: `["arm64", "x86_64", "universal2",
"arm64_v8a"]`. Only `universal2` is macOS-only and gets deleted from the
`click.Choice` lists in `cli/build.py`, `cli/package.py`, `cli/run.py`.
**`x86_64` stays** — it is the Linux arch and an Android ABI. macOS's own
rejection lives in macOS-specific validation, not the shared Choice.

**A3 — Delete the multi-arch assembly machinery.**
With one valid arch these are unreachable: `resolve_assembly_archs`'s
`universal2` branch, the lipo merge in `runtime_stage`/`wheels_stage`, the
multi-arch launcher compile, and `machotools.lipo` itself. Deleted rather than
left dormant — Apple is not adding a third macOS arch, so this code could never
be exercised or tested again. Largest and riskiest part of Phase A.

**A4 — Doctor.** Arch-coverage and native-binary-arch checks collapse to
single-arch.

**A5 — Lock layer.** Nearly free: `variants()` derives from `archs`, so it
yields one. `wheel_arch()` keeps parsing `x86_64` for diagnostics.

**A6 — Examples.** Four macOS overlays carry `archs = ["arm64", "x86_64"]`
(`desktop-viewer`, `dice-roller`, `hello-native`, `notes`). The
`archs = ["x86_64"]` lines in those same files are the **Linux** overlays —
leave them alone.

**A7 — Tests.** The largest surface: `tests/platforms/macos/` (bundle,
machotools, runtime_stage, wheels_stage, doctor, cli, `lock/*`),
`tests/cli/test_build.py`, and the iOS simulator arch tests.
`test_machotools.py` largely disappears with lipo.

**A8 — Docs.** macos-spec, the iOS specs' simulator-arch references, the README
targets table (which today lists macOS archs and a build host without connecting
them), and CHANGELOG.

> **Breaking config change.** Any project with `archs = ["arm64", "x86_64"]` (or
> a two-arch `simulator_archs`) fails to load until edited. CHANGELOG must carry
> the one-line fix.

## Phase B — desktop source stripping

Android already has `byte_compile` / `strip_source` / `strip_native_libs` in
`[tool.kivy.android.build_settings]`; the three desktop backends have nothing,
and ship raw `.py` unconditionally. For comparison: PyInstaller never ships
`.py`; Flet compiles to `.pyc` and deletes sources **by default** since v0.86;
Briefcase ships cleartext source with an open request to change that.

### Compiler selection

**Never depend on emulation** — Rosetta, Windows x64-on-ARM, and `qemu-user`
differ wildly in availability and lifespan, and we never need them: `.pyc` is
arch-independent, so we only need *a* CPython of the matching minor, not the
target's own interpreter.

1. **Staged interpreter**, if `target_arch == host_arch` — `<bundle>/python/python.exe`,
   macOS `Contents/Resources/python`, Linux `usr/python`. By construction the
   exact CPython that will import the `.pyc`. After Phase A this is *always*
   true on macOS.
2. **Host interpreter** kivyforge already runs under, if its CPython minor
   matches — a `sys.version_info` check, not a filesystem search. Reachable only
   for future cross-arch builds (win-arm64, linux-aarch64).
3. **Degrade** — warn and ship source under the default tri-state; hard-error
   under an explicit `byte_compile = true`.

Android's `_byte_compile_interpreter()` search is **not** ported: desktop
host-gating makes it unnecessary. Phase A removes the universal2 fat-binary
special case, leaving no platform-specific branches at all.

### Settled decisions

- **Strip scope: app + site-packages only. stdlib is not stripped.** Keeps
  tracebacks and `inspect`/`linecache` intact. PBS already ships stdlib
  `__pycache__`, so it is compiled either way; stripping it would mean
  recompiling in legacy layout for a size win that isn't worth the debuggability
  cost.
- **`"release"` means `package`, not `build`.** Not a new convention:
  `windows_package` already documents that signing "targets the dist copy
  only… the build tree stays unsigned as the dev-run target." Stripping follows
  the same rule.
  - Fix the stale wording in `platforms/windows/bundle.py`, whose module
    docstring calls the onedir "itself a shipped distributable (portable use)" —
    true of the *format*, misleading as *policy*.

### Work

- Extract Android's `_byte_compile` / `_compile_tree` into a shared
  `kivyforge/bundle/pycompile.py`. They are already ~90% platform-agnostic and
  handle the PEP 3147 trap correctly (sourceless imports need `foo.pyc` at the
  source path, never in `__pycache__/`), plus `UNCHECKED_HASH` invalidation and
  `stripdir` so host paths and mtimes stay out of shipped `.pyc`. Android call
  sites keep identical behavior.
- A shared `DesktopBuildSettings` with **only** `byte_compile` + `strip_source`
  (`strip_native_libs`/`minify`/`multidex` are Android-only).
- Three config schemas × (model + loader + validation + `init` + tests + docs) —
  the bulk of the work.
- One bundler call each, after wheels + app sources are staged. **Ordering
  constraint on macOS: before `sign_bundle_adhoc`**, since signing seals the
  bundle and later file changes invalidate the signature.

### Payload locations

| | Windows | macOS | Linux |
|---|---|---|---|
| app | `app/` | `Contents/Resources/app` | `usr/app` |
| site-packages | `python/Lib/site-packages` | `Contents/Resources/lib` | `usr/lib` |
| stdlib *(not stripped)* | `python/Lib` | `Contents/Resources/python/…` | `usr/python/…` |

## Effort

- **Phase A** — ~1–1.5 days, most of it tests; risk concentrated in A3.
- **Phase B** — ~1 day, mostly the repetitive three-schema surface.

## Follow-up, not in either phase

Nothing in the codebase distinguishes "arch we can build *for*" from "arch we can
build *on*." Phase A removes the case that made the distinction urgent, but the
gap returns with win-arm64 and linux-aarch64. Worth a `doctor` note and a docs
line when either lands.

# Plan: iOS byte-compile / strip_source

> **Status: done (2026-07-30).** Extends `[tool.kivy.<platform>.build_settings]`
> (Android, then Windows/Linux/macOS — see
> [macos-x86-removal-and-desktop-stripping.md](macos-x86-removal-and-desktop-stripping.md))
> to the one remaining backend without it: iOS.

## Why iOS, and why app sources over pip-deps

Every other backend now strips app + third-party deps together. iOS had
neither. Initial scoping considered pip-deps only (mechanically the easy
part — a real, host-controlled directory, same shape as desktop
site-packages), but that protects the wrong thing: pip-deps are third-party
packages already public on PyPI, so compiling them defeats nothing a casual
`pip download` doesn't already reveal. The app's own source is the only part
of the payload that is the developer's IP, and it is the part every other
platform already strips. Doing pip-deps alone would have made iOS the one
platform where `unzip`-ing the shipped artifact reveals full app source. The
goal (the user's framing) is "keep honest people honest" — casual extraction,
not defeating a determined reverse engineer with a disassembler, which no
`.pyc` on any platform here actually stops. Under that threat model, app
source is the one that matters.

## The architectural wrinkle: `app/` is a symlink, not a copy

iOS ships two separable pure-Python payloads:

- **`pip-deps-{device,simulator}/`** — third-party wheels installed via `pip
  install --target`, a real host-owned tree (`kivyforge/artifacts/collect.py`).
  Mechanically identical to desktop's site-packages staging.
- **`<app>-ios/app`** — today, always a **symlink** into the user's own
  `[tool.kivy].app_dir` (`kivyforge/platforms/ios/staging.py`, spec 06
  "symlink, not copy"), for fast edit-rebuild dev iteration. Byte-compiling
  and stripping through that symlink would delete `.py` files from the
  user's actual working tree — a correctness hazard, not a style question.

**Resolution:** follow the same `release`-only default every other backend
already uses. `build`/`run` keep the symlink, unchanged, zero risk. `package`
(`target == "release"`) materializes a **real, disposable copy** of
`app_dir` instead of a symlink, then compiles/strips that copy — never the
user's source. This isn't as novel as it sounds: the Xcode-time
`install_python` script (from python.org's own `Python.xcframework`) already
dereferences the symlink into real files when it copies things into
`$CODESIGNING_FOLDER_PATH` for *every* build — a shipped `.ipa` never
actually contains a symlink either way. This just moves that materialization
earlier (host-side, before `xcodebuild`) for release builds, and compiles on
the way.

## Naming collision

`IosConfig.build_settings: dict[str, str]` (the free-form
`[tool.kivy.ios.xcode.build_settings]` Xcode passthrough) already occupies
the obvious name. The new table nests under the existing, already-required
`[tool.kivy.ios.python]` table instead: `[tool.kivy.ios.python.build_settings]`
→ `IosConfig.python_build_settings: DesktopBuildSettings` (the same shared
dataclass desktop already uses — no new dataclass needed).

## Compiler selection — simpler than desktop, not harder

Desktop's ladder prefers the bundle's own staged interpreter when it can run
natively on the host. iOS has no such rung: `Python.xcframework` is a
linkable library, not a standalone executable — there is nothing to shell out
to, on either the device or simulator slice, regardless of arch match. So the
ladder collapses to two rungs: the interpreter running `kivyforge` itself, if
its CPython minor matches `[tool.kivy.ios.python].version` (a `.pyc`'s magic
number is keyed to minor only, never architecture); otherwise degrade
(`"release"` warns and ships source, `true` fails the build). This reuses
`select_compiler()` from `kivyforge/bundle/pycompile.py` unchanged — iOS just
always passes `native=False`.

## Work

- `kivyforge/config/model.py` — `IosConfig.python_build_settings:
  DesktopBuildSettings`.
- `kivyforge/config/loader.py` — generalized `_parse_desktop_build_settings`
  to take an already-unwrapped `table` + explicit `base` key-path (previously
  `overlay, platform`), so it can parse both `<platform>.build_settings`
  (desktop) and the new nested `ios.python.build_settings`; added
  `_parse_ios_python_build_settings` to read the latter.
- `kivyforge/artifacts/collect.py` — `_compile_pip_deps`, called per slice
  between `_install_wheels` and `_stamp_collected`; `collect_artifacts` grew
  `release`, `build_settings`, and `echo` parameters (all optional, backward
  compatible).
- `kivyforge/platforms/ios/staging.py` — `create_staging` grew `release`,
  `python_version`, `echo` parameters. `release=True` routes to
  `_materialize_app_copy` (copy + compile) instead of `_refresh_app_symlink`.
  `_refresh_app_symlink` now also reclaims a leftover release-mode copy
  (removes the real directory and replaces it with a symlink) so switching
  from `package` back to `build`/`run` works without a manual clean.
- `kivyforge/platforms/ios/cli.py::prepare_build` — computes
  `release = target == "release"` and threads it (plus `lock.python_xcframework.version`
  and `click.echo`) into both `create_staging` and `collect_artifacts`. No
  change to the shared CLI verb layer — `target` already carried the signal.

## Payload locations

| | app | pip-deps |
|---|---|---|
| dev (`build`/`run`) | symlink to `app_dir`, untouched | installed, uncompiled |
| release (`package`) | real copy, compiled/stripped per `build_settings` | compiled/stripped per `build_settings` |
| stdlib *(never touched, either mode)* | `Python.xcframework` (opaque, prebuilt) | — |

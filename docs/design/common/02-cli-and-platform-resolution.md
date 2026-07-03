# 02 — CLI + Platform Resolution

kivyforge exposes a single command, `toolchain`, with a small set of verbs that are **uniform across platforms**. The platform-specific behavior of each verb (what `build` invokes, what `package` emits) lives in each platform's own doc; this document defines the cross-platform verb model, how a target platform is selected, and the `package` verb's role.

## Program name

`toolchain` — the invoked command, implemented as a Click group (`kivyforge.cli:main`). Run `toolchain` commands from the directory that contains your `pyproject.toml`; all verbs look for it in the **current working directory only** (no parent-directory traversal).

`toolchain --help` prints a one-line description per verb; `toolchain <verb> --help` prints per-verb help including the platform-specific flags.

## Selecting the target platform

Platform-aware verbs need to know *which* target they operate on. The selector is a uniform flag:

- `--platform <name>` (alias `-p <name>`) — validated with `click.Choice` against the registered platforms (`ios`, `macos`, `android`, `windows`, `linux` as each lands).

It is **explicit by design**. A positional target argument was rejected as error-prone; a user who doesn't want to type the flag on every command sets the environment variable instead (below).

### Resolution chain

When a platform-aware verb runs, the target is resolved in this order:

1. **`--platform` / `-p` argument** — highest precedence; wins whenever present.
2. **`KIVYFORGE_PLATFORM` environment variable** — a "mode"-like default for a shell session or CI job, without compromising the multi-platform nature of `pyproject.toml`.
3. **Host platform** — if the machine's own OS maps to a registered, *configured* platform, use it.

If none of these yields a configured target, `toolchain` **errors with an actionable message** rather than guessing. There is no single-overlay auto-fallback and no interactive prompt:

```
Error: no target platform resolved.
  Pass one explicitly:      kivyforge build --platform macos
  Or set a session default: export KIVYFORGE_PLATFORM=macos
  (Configured platforms in this pyproject.toml: ios, macos)
```

"Configured" means the `pyproject.toml` actually declares that platform's overlay (e.g. `[tool.kivy.macos]`). The host-platform step (3) only succeeds when the host's OS both maps to a registered backend *and* has a configured overlay.

### Target selection vs. host capability

Two independent checks:

- **Target selection** (above) decides *what* you are building for.
- **Host capability** decides *whether this machine can build it*. Some targets require a specific host (iOS requires macOS + Xcode; the Android emulator needs a virtualization-capable host; etc.). This is a separate, backend-supplied check surfaced by `kivyforge doctor` and enforced by `build`/`package` with an actionable error — distinct from "is this platform configured in my project?".

## Verbs

The verb set is uniform; each platform backend implements the platform-specific behavior.

| Verb | Purpose |
|------|---------|
| `init` | Seed `[tool.kivy]` + the target's `[tool.kivy.<platform>]` overlay into `pyproject.toml`. |
| `lock` | Resolve `[project].dependencies` (and any native declarations) for the resolved target; write `pylock.<platform>.toml`. `--check` for CI pre-flight. |
| `build` | Acquire the runtime + pinned artifacts and materialize the native project for the resolved target. The **development loop** verb. |
| `run` | Build (unless `--no-build`), then install/launch on a device, simulator/emulator, or the host, as the platform supports. |
| `package` | Produce the distributable, signed **runnable artifact** (see below). |
| `open` | Open the generated native project in the platform IDE, where applicable (e.g. Xcode on iOS). |
| `upgrade` | Re-download pinned runtime/native artifacts per the existing lock. |
| `clean [--cache]` | Remove generated artifacts; with `--cache`, also flush the download cache. |
| `status` | Read-only project snapshot: identity, runtime version, lock sync, build state. |
| `doctor` | Environment + project health check, including host-capability checks for the resolved target. |

`build` vs. `package`:

- **`build`** is the fast dev-loop verb: get the app running for iteration (open in the IDE, launch on a simulator, run on the host). It may stop at a project ready to open, or run/launch, per platform.
- **`package`** produces the finished distributable artifact for the target and **signs it** (signing must operate on the bundled binaries, so it stays inside kivyforge). Wrapping that artifact into an installer/container is out of scope (see [06 — packaging scope](06-packaging-scope.md)).

### The `package` verb and the `-f` format slot

`package` takes an optional format selector `-f <format>` / `--format <format>` naming the artifact shape, when a platform offers more than one:

- **iOS** — the Xcode-built app / `.ipa` (App Store submission external).
- **macOS** — `-f app` (a `.app` bundle). `.dmg`/installer external.
- **Windows** — application folder + launcher `.exe` (onedir). MSI/Inno/NSIS external.
- **Linux** — user-selectable: `-f folder` (run-from-folder app dir + launcher) or `-f appimage` (self-contained portable). `.deb`/`.rpm`/Flatpak external.
- **Android** — `.apk` / `.aab` (both artifact and installable unit; store submission external).

A platform with a single artifact shape (e.g. macOS `app` today) defaults `-f` to that shape; where a platform has no universal bundle convention (Linux), `-f` earns its keep as a required-ish selector.

## Environment variables

| Variable | Effect |
|----------|--------|
| `KIVYFORGE_PLATFORM` | Session/CI default target (step 2 of the resolution chain). |
| Platform-specific overrides (e.g. `KIVYFORGE_TEAM_ID`, `KIVYFORGE_SIGNING_IDENTITY` on iOS) | Documented per platform; used for signing config that isn't committed to `pyproject.toml`. |

## Per-platform CLI behavior

The platform-specific behavior of each verb is documented alongside the platform:

- **iOS** — [iOS CLI behavior](../platforms/ios/cli-ios.md) (build flags, `xcodebuild` integration, `run`/`open`, `doctor` checks, `kivy.mobile`, legacy-verb disposition).
- **macOS** — [macOS spec](../platforms/macos/macos-spec.md).

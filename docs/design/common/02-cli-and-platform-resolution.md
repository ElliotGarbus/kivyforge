# 02 — CLI + Platform Resolution

kivyforge exposes a single command, `kivyforge` (alias `kf`), with a small set of verbs that are **uniform across platforms**. The platform-specific behavior of each verb (what `build` invokes, what `package` emits) lives in each platform's own doc; this document defines the cross-platform verb model, how a target platform is selected, and the `package` verb's role.

## Program name

`kivyforge` — the invoked command, implemented as a Click group (`kivyforge.cli:main`). A short alias `kf` is installed as a second console script pointing at the same entry point. Run `kivyforge` commands from the directory that contains your `pyproject.toml`; all verbs look for it in the **current working directory only** (no parent-directory traversal).

`kivyforge --help` prints a one-line description per verb; `kivyforge <verb> --help` prints per-verb help including the platform-specific flags.

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

## Machine-readable output (`--json`)

*Landed as roadmap item 3, 2026-09-14/17. Authoritative source: `kivyforge/report/` (`envelope.py`, `diagnostics.py`, `exit_codes.py`, `console.py`) — this section states the contract, not a second copy of it.*

Every verb but `run` accepts `--json`. `run` hands the child app process kivyforge's own stdout/stderr directly, which is the point of the verb, so an envelope has nowhere to go without interleaving with the app's own output.

**The stdout/stderr split is the load-bearing rule.** Product goes to stdout; progress, staging lines, and third-party tool output (Gradle, `xcodebuild`, `appimagetool`) go to stderr — always, including under `--json`. Under `--json`, stdout is *exactly one* envelope and nothing else, on success and on every failure class, so `kivyforge build -p android --json > build.json` stays parseable while the human still watches progress on the terminal.

**Envelope shape** (`envelope.py`), identical across every verb:

```json
{
  "schema": 1,
  "kivyforge": "3.0.0.dev0",
  "command": "doctor",
  "platform": "linux",
  "ok": true,
  "data": {},
  "diagnostics": []
}
```

`schema` is an integer, bumped only for a non-additive change (adding a key inside `data` is not one). `data` and `diagnostics` are always present, even empty — never `null`, never omitted.

**Exit codes** (`exit_codes.py`) are a stable, reserved taxonomy — a caller branches on the number, not on parsing the message:

| Code | Meaning | Typical reaction |
|---|---|---|
| 0 | success | continue |
| 1 | config / user error | edit `pyproject.toml` and retry |
| 2 | usage error (click's, not ours) | fix the command line |
| 3 | environment / toolchain missing | install something, retry unchanged |
| 4 | lock drift | run `kivyforge lock -p <platform>` |
| 5 | build failure | read the build log on stderr |

`2` is reserved permanently for click's own `UsageError` — kivyforge never assigns it deliberately, so "you typed the flag wrong" and "this machine lacks a toolchain" stay distinguishable.

**Diagnostics** (`diagnostics.py`) are `{"code", "severity", "message"}`, plus optional `"remediation"` and `"context"` (omitted, not emitted empty, when there is nothing to say). `severity` is one of `error` / `warning` / `info`. **A diagnostic on an `ok: true` run is a warning, not a failure** — an unsigned package (`KF-SIGNING-UNCONFIGURED`), a `byte_compile` that silently degraded to shipping source (`KF-BYTECOMPILE-NO-INTERP`), a resolver judgement call (`KF-LOCK-WARNING`). The code is the contract; the message is reworded freely across releases and must never be matched on.

**`data.artifacts`** (`build`/`package`) is a list of `{"path", "kind"}` pairs, relative to the project root and always posix-spelled regardless of host. It lists only what *this invocation* finalised and verified — a failed run's `artifacts` is `[]` even when a previous run's output is still sitting on disk, because naming a stale file is worse than naming nothing (it is indistinguishable from success).

**Discovery:** `kivyforge capabilities --json` needs no project, lock, or network. It publishes the platform/arch/format matrix, the host-capability matrix (which host can build which target — computed by calling each backend's own capability check, not a hand-kept table), the verb list with its `--json` support, and both vocabularies above. It is the first call an agent should make, before assuming anything about what this kivyforge version or this host can do.

**Colour:** `--no-color` (or `NO_COLOR`/`FORCE_COLOR`) disables Rich styling and terminal-width detection, for a log file or CI transcript where a stray SGR code is as unwelcome as colour. Human-mode output is otherwise unaffected by `--json`'s presence, except that it is suppressed — the envelope supersedes it.

## Environment variables

| Variable | Effect |
|----------|--------|
| `KIVYFORGE_PLATFORM` | Session/CI default target (step 2 of the resolution chain). |
| Platform-specific overrides (e.g. `KIVYFORGE_TEAM_ID`, `KIVYFORGE_SIGNING_IDENTITY` on iOS) | Documented per platform; used for signing config that isn't committed to `pyproject.toml`. |

## Per-platform CLI behavior

The platform-specific behavior of each verb is documented alongside the platform:

- **iOS** — [iOS CLI behavior](../platforms/ios/04-cli-ios.md) (build flags, `xcodebuild` integration, `run`/`open`, `doctor` checks, `kivy.mobile`).
- **macOS** — [macOS spec](../platforms/macos/macos-spec.md).
- **Linux** — [Linux spec](../platforms/linux/linux-spec.md).
- **Windows** — [Windows spec](../platforms/windows/windows-spec.md).

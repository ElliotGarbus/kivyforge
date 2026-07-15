# Windows — Design Spec

The Windows backend produces a self-contained, distributable application as a
**run-from-folder onedir bundle** (`package -f folder`): a native launcher
`.exe` next to a bundled relocatable CPython, the app's resolved wheels, and
the user's source — the Windows analog of the Linux AppDir. Like macOS and
Linux it rides the shared wheel+runtime lock engine and the
[`RuntimeProvider` pattern](../../common/07-runtime-provider-pattern.md);
unlike them, the launcher is a **prebuilt** native binary (never compiled on
the user's machine) and the artifact layout is load-bearing for Kivy's
Windows DLL discovery.

> **Status: implemented.** The Windows backend ships
> (`kivyforge {lock,build,run,package,doctor} -p windows`); this spec now tracks
> the shipped design. The **v1 baseline is public Kivy 2.3.1 / SDL2** (`kivy_deps.sdl2`
> et al.), because Kivy 3.0 has no public desktop wheels yet; the design keeps
> wheel staging and the bootstrap **generic over `share/*/bin`** so the SDL3 /
> Kivy 3 path is purely additive when a wheel ships. Decisions here were settled
> against Kivy source (2.3.1 and 3.0), python-build-standalone's Windows builds,
> and the prior art in distlib / Briefcase / PyInstaller (see the
> [bootloader](bootloader-windows.md) and [signing](signing-windows.md)
> companion docs). Implementation follows the sequencing below; findings from
> the clean-VM spike will be recorded as `docs/design/dev/windows-dll-findings.md`
> (the `resolver-findings.md` pattern).

Companion documents:

- [bootloader-windows.md](bootloader-windows.md) — the native launcher `.exe`:
  prebuilt distribution model, windowed subsystem, spawn-and-wait process
  model, wide-char/path handling.
- [signing-windows.md](signing-windows.md) — Authenticode signing: the
  `Signer` protocol, thumbprint identity, Inno Setup composition, self-signed
  dev/CI flow.
- [signing-prerequisites-windows.md](signing-prerequisites-windows.md) — the
  user-facing checklist for signing your app: cert into the store, thumbprint,
  `signtool`, config, timestamp reachability.

## Sequencing

Implementation happens in this order, because each step's failure mode is
indistinguishable from the next step's bugs:

1. **De-risk DLL discovery.** Prove `import kivy` +
   `from kivy.core.window import Window` from a relocated PBS tree on a
   **clean VM** (no Python installed, no VCRedist). This is independent of,
   and prior to, everything else — a perfect bootloader that starts an
   interpreter which can't import Kivy looks exactly like a bootloader bug.
   See ["DLL discovery"](#dll-discovery--prove-this-first) for the
   verification chain; results land in `docs/design/dev/windows-dll-findings.md`.
2. **Build the bootloader.** Native, prebuilt, windowed-subsystem,
   spawn-and-wait. See [bootloader-windows.md](bootloader-windows.md).
3. **Wire the signing hook.** Can be built and tested against a self-signed
   cert at any point, at zero cost. See [signing-windows.md](signing-windows.md).

## Scope

In scope for the Windows backend:

- `[tool.kivy.windows]` overlay parsing + a `WindowsConfig` dataclass.
- `pylock.windows.toml` resolution (Windows PBS runtime + `win_amd64`-tagged
  wheels) via the shared wheel+runtime lock engine.
- A onedir bundle generator (prebuilt launcher `.exe`, bundled Python prefix +
  wheels + app source, generated bootstrap module).
- A declared **native-binaries channel** (`[tool.kivy.windows.native.binaries]`)
  for non-wheel DLLs and helper executables — fetched, SHA-256-verified,
  staged into `<bundle>\bin`, and registered by the bootstrap (see
  ["Native binaries that are not wheels"](#native-binaries-that-are-not-wheels)).
- `init` / `build` / `run` (launch the `.exe`) / `package -f folder` /
  `status`.
- An **optional, first-class Authenticode signing hook** (off by default; see
  [signing-windows.md](signing-windows.md)).
- Windows `doctor` checks.

Out of scope (deferred / external):

- **Console-subsystem apps.** kivyforge is a Kivy/GUI tool; the launcher is
  windowed-only (fixed at link time — see the
  [bootloader doc](bootloader-windows.md#windowed-subsystem-only)). Revisit
  only on user demand.
- **PyInstaller-style onefile** — rejected **permanently**, not deferred. A
  self-extracting single `.exe` unpacks to `%TEMP%` on every launch (slow cold
  start, AV suspicion), and its embedded payload binaries cannot be signed
  post-build — PyInstaller has to re-sign at build time for exactly this
  reason. onedir keeps every file real and signable, which keeps payload-DLL
  signing *possible* if ever needed (a Smart App Control concern only, not
  planned).
- **Installers — permanently external, a scope decision (not deferred
  pending demand).** kivyforge's boundary is the signed runnable artifact:
  the onedir folder + launcher `.exe`, per
  [common packaging scope](../../common/06-packaging-scope.md) (the same
  permanent line as `.dmg` on macOS). The Windows installer ecosystem is
  mature and market-segmented — Inno Setup / NSIS for consumer distribution,
  WiX/MSI for enterprise GPO deployment, MSIX for the Store/sandboxing — and
  integrating any of them would create little value over pointing users at
  the right tool for their market. A consequence, stated so it reads as a
  decision rather than an omission: unlike Linux (where AppImage puts an
  in-scope single-file portable next to the folder artifact), Windows has
  **no in-scope single-file distributable** — the folder *is* the artifact;
  ship it zipped, or feed it to your installer tool. The
  [signing doc](signing-windows.md#orchestration-kivyforge--inno-are-composed-not-redundant)
  documents how an external Inno step composes with kivyforge's signed
  output (sequencing + one credential path) — user-facing guidance, the
  analog of the macOS spec's `.dmg` notarization snippet. A corollary worth
  stating: **Microsoft Store commerce** (in-app purchases/subscriptions via
  the `Windows.Services.Store` WinRT APIs) requires *package identity*, which
  only an installed MSIX provides — so Store payments are structurally
  downstream of the packaging step kivyforge doesn't own, and there is no
  hook for kivyforge to provide even in principle. An app that needs them
  calls the WinRT APIs from Python (the `winrt`/`winsdk` packages are
  ordinary wheels that flow through the lock) inside an externally-built
  MSIX. Payments *outside* the Store (Stripe, Paddle, etc.) are plain HTTP
  APIs — ordinary Python dependencies, nothing for kivyforge to integrate.
- **Auto-update frameworks** (Squirrel/Velopack, WinSparkle) — external,
  alongside installers and for the same reason: they own the install/update
  lifecycle, which sits past kivyforge's artifact boundary. A user who wants
  in-app update *checking* can declare WinSparkle (a plain DLL) via the
  [native-binaries channel](#native-binaries-that-are-not-wheels); frameworks
  that own installation (Squirrel/Velopack) replace the external installer
  step entirely and are that pipeline's concern.
- **win-arm64** — deferred pending demand *and* availability of Kivy binary
  dep wheels (SDL3) plus PBS arm64 Windows builds. The config stays
  list-shaped so it is purely additive later — the same "defer pending
  demand" pattern as Linux aarch64.

## `[tool.kivy.windows]` overlay

An additive overlay on top of the shared `[project]` + `[tool.kivy]` tables
(see [common pyproject spec](../../common/01-pyproject-kivy-spec.md)). Only
fields that differ from the cross-platform defaults or are Windows-specific
appear here.

```toml
[tool.kivy.windows]
schema_version = 1
app_id = "Example.MyApp"         # AppUserModelID: taskbar grouping / pinning identity
archs = ["amd64"]                # only amd64 allowed this phase

[tool.kivy.windows.python]
version = "3.15.0"               # bundled Python runtime version

[tool.kivy.windows.icons]
source = "assets/icon.png"       # 1024×1024 PNG → multi-size .ico for the launcher

[tool.kivy.windows.signing]      # optional; omitted = unsigned artifact
thumbprint = "A1B2C3..."         # SHA-1 thumbprint of a cert in the Windows cert store
# store_scope = "current_user"   # default; "machine" selects LocalMachine\My (signtool /sm)
# timestamp_url = "http://timestamp.digicert.com"  # default shown

[tool.kivy.windows.native.binaries]
# Empty by default. Non-wheel native binaries (vendor SDK DLLs, helper exes);
# fetched + SHA-256-verified at lock, staged into <bundle>\bin, registered by
# the bootstrap. `source` is always explicit — a URL or repo-relative path.
# sdk    = { version = "2.1.0", source = "https://vendor.example/sdk-2.1.0-win64.zip" }
# ffmpeg = { version = "7.1",   source = "binaries/windows/ffmpeg.exe" }

# extra_index_urls / find_links / exclude behave as on iOS/macOS/Linux.
```

Proposed field set (finalized in implementation):

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `schema_version` | integer | yes | — | Windows overlay schema version; independent of other platforms'. |
| `app_id` | string | yes | — | The explicit [AppUserModelID](https://learn.microsoft.com/en-us/windows/win32/shell/appids). The generated bootstrap sets it via `SetCurrentProcessExplicitAppUserModelID` before window creation so the taskbar button groups (and pins) under the app rather than `python.exe`. **Validation enforces only Microsoft's hard constraints — no spaces, ≤128 characters — as a config-time `ConfigError`.** The conventional pascal-cased, period-delimited form (`Company.Product`) is a *recommendation*, surfaced as a `doctor` **WARNING**, not an invented hard failure; hyphens are permitted. (This is a distinct identifier from the Linux reverse-DNS `app_id` and the macOS `bundle_id`, so it does not adopt their format rules.) |
| `archs` | list of string | no | `["amd64"]` | Target architecture set. Only `amd64` is allowed this phase (`win_amd64` wheel tag; PBS triple `x86_64-pc-windows-msvc`). List-shaped so `arm64` is purely additive later. As on Linux there is no fat binary — each arch would be a separate bundle. |
| `extra_index_urls` | list of string | no | `[]` | Supplemental wheel indexes (`win_amd64` tags), same semantics as iOS/macOS/Linux. |
| `find_links` | list of string | no | `[]` | Repo-relative vendored-wheel directories for `lock`. |
| `exclude` | list of string | no | `[]` | Prune unused transitive deps from the resolved graph. |

Icons: `[tool.kivy.windows.icons].source` (1024×1024 PNG) is rendered into a
multi-size `.ico` (256/48/32/16, the sizes Explorer and the taskbar consume)
using Pillow (the same opt-in extra as Linux icon resizing). The `.ico` is
patched into the launcher's icon resource per-app — see the
[bootloader doc](bootloader-windows.md#per-app-parameterization-resource-patching)
for the patching-tool decision (open item). The launcher's **version
resource** (product name, file version, copyright) is derived from
`[project].name` / `[project].version` / `[tool.kivy].display_name` — no
separate overlay fields; declared metadata is the single source of truth.

Signing: `[tool.kivy.windows.signing]` is optional; without it `package`
ships the artifact unsigned (the documented v1 default). `thumbprint`
references a certificate **in the Windows certificate store** — never a
`.pfx` path or password — so the same configuration works whether the
credential is an imported pfx, a hardware token, or a cloud signer.
`store_scope` selects which store both `signtool` **and** the `doctor`
certificate lookup inspect: `current_user` (the default → `Cert:\CurrentUser\My`)
or `machine` (→ `Cert:\LocalMachine\My`, which also adds `signtool /sm`). Keeping
one setting for both sides prevents the classic mismatch where the certificate
is found in one store but signed against the other. See
[signing-windows.md](signing-windows.md).

Native binaries: `[tool.kivy.windows.native.binaries]` declares non-wheel
DLLs / helper executables; empty by default. Full semantics in
["Native binaries that are not wheels"](#native-binaries-that-are-not-wheels).

Shared `[tool.kivy]` keys consumed: `display_name` (→ the version resource's
product name and the packaged folder name), `app_dir`, `entry_point`.
`orientation` is not meaningful on desktop and is ignored.

## Python runtime acquisition

**Decision: [`python-build-standalone`](https://github.com/astral-sh/python-build-standalone)
(PBS)**, behind the shared
[`RuntimeProvider` abstraction](../../common/07-runtime-provider-pattern.md) —
the same relocatable-CPython strategy as macOS and Linux, using the
**`x86_64-pc-windows-msvc`** `install_only` build. PBS's GitHub metadata
fetcher is triple-agnostic, so this is the same one-line specialization of the
generic `PbsProvider` that Linux was.

**Rejected: the official python.org
[Windows embeddable package](https://docs.python.org/3/using/windows.html#the-embeddable-package).**
The common runtime-provider doc flagged it as the one official relocatable
artifact among the desktop platforms and deferred the decision here. Its gaps
are permanent and structural, not fixable configuration:

- **Not a normal prefix** — no `share/` data-scheme target, a zipped stdlib,
  no headers, no import library. The DLL-discovery invariant below requires a
  normal prefix so wheel-installed data (`share/<dep>/bin`) lands where
  `kivy_deps.*`'s `sys.prefix`-keyed self-registration looks for it; the
  embeddable package's minimized shape has nowhere for it to go.
- **`._pth` isolation** — `import site` is disabled by default and `sys.path`
  is frozen by the `._pth` file, changing `sys.prefix` semantics. Kivy's
  Windows dependency discovery keys off a normal `sys.prefix` (see below), so
  the embeddable package's core design works *against* the one mechanism the
  bundle depends on.

Its one advantage — PSF Authenticode-signed binaries — is a one-time gap that
the optional signing sweep closes by signing the tree itself.

PBS's **normal prefix layout is load-bearing** for Kivy's DLL discovery. The
staging step must not flatten, prune, or `._pth`-isolate it. Uniformity is the
win: one relocatable-Python mental model across all desktop platforms, with
Windows divergence contained to a single provider implementation
(`platforms/windows/lock/runtime.py`, the arch→triple map).

The [python/prebuilt-cpython watch item](../../common/07-runtime-provider-pattern.md#watch-item-official-prebuilt-cpython-pythonprebuilt-cpython)
applies to Windows exactly as to macOS/Linux: when an official relocatable
Windows build with a normal prefix ships, the backend adds a provider and a
re-lock adopts it.

## `pylock.windows.toml`

Same pattern as macOS/Linux (see
[common lockfile concept](../../common/03-lockfile-concept.md)): PEP 751
`[[packages]]` for wheels + a single `[tool.kivyforge]` extension table
holding the runtime pin and provenance. The platform is identified by the
filename (`WheelRuntimeLock.platform` is already typed for `"windows"`).

Windows wheels use the **`win_amd64`** platform tag — a single stable tag with
no macOS-version or manylinux-ladder dimension, so resolution is the simplest
of the desktop family: each compiled dependency must resolve a `win_amd64`
wheel (or `py3-none-any`); a miss is the usual fail-fast at lock time naming
the package. **`kivy_deps.*` packages resolve as ordinary wheels** — Kivy's
own `win_amd64` wheel declares them (e.g. `kivy_deps.sdl2` / `kivy_deps.sdl3`) as conditional
dependencies, so they appear in `[[packages]]` with URL + SHA-256 pins like
everything else; the backend needs no special knowledge of them at lock time.
Where they land at *build* time is the critical part (next section).

Declared `[tool.kivy.windows.native.binaries]` entries are pinned in a
`[[tool.kivyforge.native_binaries]]` array (`name`/`version`/`source`/
`sha256`), mirroring the iOS `[[tool.kivyforge.xcframeworks]]` pattern — see
["Native binaries that are not wheels"](#native-binaries-that-are-not-wheels).

## onedir bundle layout — and the DLL-discovery invariant

`build` (and `package -f folder`) produce:

```
build/windows/MyApp/
├── MyApp.exe                       ← prebuilt launcher (resource-patched per app)
├── _kivyforge_bootstrap.py         ← generated bootstrap module (fixed name)
├── app.ico                         ← generated multi-size icon (only when icons.source set)
├── app/                            ← user code (from [tool.kivy].app_dir)
├── bin/                            ← declared native binaries (native.binaries);
│                                     absent when the table is empty
└── python/                         ← PBS runtime prefix — carried WHOLE
    ├── python.exe
    ├── python3xx.dll, vcruntime140.dll, ...
    ├── DLLs/  Lib/                 ← stdlib
    ├── Lib/site-packages/          ← installed wheels (wheel-scheme installer, see below)
    └── share/sdl2/bin/             ← SDL2.dll + codec DLLs (kivy_deps.sdl2; share/sdl3/bin on Kivy 3)
```

The layout convention (`<bundle>\python\`, `<bundle>\app\`, `<bundle>\bin\`,
the fixed bootstrap name) is **frozen by design**: it is what lets one
prebuilt bootloader binary serve every app with no per-app compilation (see
the [bootloader doc](bootloader-windows.md#prebuilt-and-vendored-not-compiled-on-demand)).

### What Kivy actually does (Kivy source; SDL2 on v1, SDL3 on Kivy 3)

Kivy's Windows binary deps ship in **`kivy_deps.*`** wheels
(`kivy_deps.sdl2` + `kivy_deps.glew` on the v1 Kivy 2.3.1 baseline;
`kivy_deps.sdl3` on Kivy 3). They do **not** land in site-packages — the
wheel's **data scheme** places them under the prefix:

```
<prefix>\share\<dep>\bin\          (e.g. share\sdl2\bin\ or share\sdl3\bin\)
    SDL2.dll / SDL3.dll, image/mixer/ttf, + transitive codecs (ogg, vorbis,
    opus, mpg123, FLAC, ...)
```

Each `kivy_deps.<dep>/__init__.py` self-registers its directory at import time
(illustrated with SDL3; SDL2 is identical modulo the name):

```python
for d in [sys.prefix, site.USER_BASE]:
    p = join(d, 'share', 'sdl3', 'bin')
    if isdir(p):
        os.environ["PATH"] = p + os.pathsep + os.environ["PATH"]
        if hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(p)
        dep_bins.append(p)
```

Kivy's `__init__` imports every `kivy_deps.*` package at `import kivy` time,
firing this block. (The `PATH` prepend is dead weight on 3.8+;
`add_dll_directory` is the line that works.) **Everything keys off
`sys.prefix`, computed at runtime — no baked absolute paths.** It is *built*
to survive relocation. The backend does not reimplement it; it satisfies its
two conditions:

1. **`PYTHONHOME` → correct `sys.prefix`.** The launcher sets `PYTHONHOME` to
   `<bundle>\python` (the same env setup as the macOS/Linux launchers). This
   works only because PBS keeps a normal prefix layout — another reason the
   embeddable package (whose `._pth` isolation changes `sys.prefix` behavior)
   was the wrong call.
2. **Preserve the `share\<dep>\bin` tree under the prefix.** The DLLs live in
   `share\`, **not** in site-packages. A staging step that copies only
   site-packages *silently drops every SDL DLL* — `isdir(p)` is then False,
   nothing registers, and Kivy dies importing the window provider with an
   error that looks exactly like a bootloader bug.

**The real invariant, stated precisely (this replaces the earlier "pip
`--prefix` is load-bearing" framing):** the wheel **data scheme**
(`<wheel>.data/data/...`) must be installed to the **prefix root**, so
`share\<dep>\bin` ends up at `<prefix>\share\<dep>\bin`. That is a property of
*where wheel schemes install*, not of *which tool installs them* — so the
Windows `wheels_stage` uses a **deterministic, no-`pip` wheel-scheme
installer** and the bundle carries the whole prefix. The installer routes each
locked wheel's schemes explicitly:

| Wheel content | Installed to |
|---|---|
| package root + `.data/purelib` + `.data/platlib` | `python\Lib\site-packages` |
| `.data/data` | the prefix root `python\` (so `share\<dep>\bin` survives) |
| `.data/scripts` | `python\Scripts` |
| `.data/headers` | `python\Include` |

It never resolves dependencies, never shells to `pip`, and never applies the
host interpreter's compatibility rules — it installs exactly the locked wheels.
This is a controlled divergence from macOS/Linux (whose wheels stage into a
separate `lib/` on `PYTHONPATH` with no prefix `share/` to satisfy), contained
to this one module; the shared macOS/Linux unpack is untouched.

Any other binary dep package follows the identical `share\<name>\bin` +
self-registering `__init__` convention, so this one layout rule covers them
uniformly — and the bootstrap's directory discovery is **generic over
`share\*\bin`**, so SDL2, SDL3, and any future dep are handled without a
hard-coded name.

### The generated bootstrap module

The launcher always runs `python\python.exe <bundle>\_kivyforge_bootstrap.py`
(fixed name — the per-app variability lives in this generated file, not in
the binary). The bootstrap:

- sets the explicit AppUserModelID (`[tool.kivy.windows].app_id`) via
  `SetCurrentProcessExplicitAppUserModelID` (ctypes) *before* any window
  exists, so the taskbar groups under the app;
- discovers every `python\share\*\bin` directory **generically** (not a
  hard-coded `sdl3`) and registers each with `os.add_dll_directory` **before**
  `import kivy` — defense-in-depth that decouples the bundle from Kivy's
  internals. Layout is the real fix (if condition 2 above is unmet, there is
  nothing to discover); this is decoration, kept because it is a few lines and
  survives a hypothetical upstream change to a `kivy_deps` package's
  self-registration;
- when `<bundle>\bin` exists (declared
  [native binaries](#native-binaries-that-are-not-wheels)): registers it with
  `os.add_dll_directory` and prepends it to the process `PATH` — so user code
  loads declared DLLs by name (`ctypes.WinDLL("sdk.dll")`) and runs declared
  helpers by name (`subprocess.run(["ffmpeg", ...])`);
- **retains every `os.add_dll_directory()` handle for the process lifetime.**
  The call returns a handle that *removes* the directory from the search path
  when it is closed or garbage-collected; the bootstrap keeps references (e.g.
  in a module-level list) so a registered directory is never silently dropped
  mid-run;
- puts `<bundle>\app` on `sys.path`, sets the working directory to it, and runs
  `[tool.kivy].entry_point` as `__main__` (via `runpy.run_module`), so a standard
  `if __name__ == "__main__": App().run()` guard fires — matching the macOS/Linux
  launchers, which exec the interpreter directly on the entry script.

### What the binary deps do *not* cover

- **The VC++ runtime.** The SDL DLLs, the codecs, and CPython's own extension
  modules link `vcruntime140.dll` / `vcruntime140_1.dll` / `msvcp140.dll` —
  and these are **not** in `share\<dep>\bin`. The spike must verify PBS bundles
  them next to `python.exe` (open item); if not, the bundler places them
  **app-local** next to `python.exe`. Never rely on a system VCRedist being
  present — that is the classic clean-machine failure. (A bonus of the
  spawn-and-wait launcher model: the child process *is* `python.exe`, so
  `python.exe`'s directory is on the default DLL search path for transitive
  resolution. An in-process embedding host would have lost this — see the
  [bootloader doc](bootloader-windows.md#spawn-and-wait-not-exec).)
- **The GL backend.** ANGLE vs. desktop GL. **RESOLVED on the v1 Kivy 2.3.1 /
  SDL2 baseline: the shipped default is desktop GL via GLEW** — a built bundle
  logs `Backend used <glew>` (OpenGL 4.6). Both `kivy_deps.glew` and
  `kivy_deps.angle` are pulled in and staged, so ANGLE
  (`KIVY_GL_BACKEND=angle_sdl2`) is present as a fallback but is not selected by
  default. On Kivy 3 / SDL3 this may differ (3.0's `setup.py` defaults
  `use_angle_gl_backend` to darwin/ios only). ANGLE (GLES→D3D11) remains the
  more robust choice for hostile environments — old drivers, RDP sessions, and
  VMs where raw GL context creation fails with a black screen — so it is worth
  documenting as an opt-in in the FAQ.

### Native binaries that are not wheels

Some apps need native binaries that no wheel delivers: vendor SDK DLLs
(hardware dongles, camera/scanner/payment-terminal SDKs, `sentry-native`,
WinSparkle) or helper executables (a bundled `ffmpeg.exe`). The
**`[tool.kivy.windows.native.binaries]`** table is the declared channel for
them — the desktop sibling of iOS's `[tool.kivy.ios.native.xcframeworks]`,
with the same name → `{ version, source }` shape and the same explicit-source
rules (a direct download URL, or a repo-relative path for a vendored
artifact; absolute paths and paths escaping the project are rejected):

```toml
[tool.kivy.windows.native.binaries]
sdk    = { version = "2.1.0", source = "https://vendor.example/sdk-2.1.0-win64.zip" }
ffmpeg = { version = "7.1",   source = "binaries/windows/ffmpeg.exe" }
```

What kivyforge does with a declared entry, per pipeline stage:

- **`lock`** — reads the artifact, resolves its SHA-256, and pins
  `name`/`version`/`source`/`sha256` in `pylock.windows.toml` (a
  `[[tool.kivyforge.native_binaries]]` array, mirroring the iOS
  `[[tool.kivyforge.xcframeworks]]` pattern). Declared binaries get the same
  integrity discipline as wheels and the runtime — a vendor SDK fetched from
  a URL is verified on every re-fetch.
- **`build`** — fetches through the shared download/cache/verify machinery
  and stages into **`<bundle>\bin\`**: a single file is copied as-is; a
  `.zip` source is extracted there preserving its internal structure.
- **bootstrap** — registers `<bundle>\bin` via `os.add_dll_directory` and
  prepends it to the process `PATH` (before the app imports). User code
  therefore loads by name — `ctypes.WinDLL("sdk.dll")`,
  `subprocess.run(["ffmpeg", ...])` — with no path gymnastics.
- **`doctor`** — checks each declared source exists/is reachable and that
  each staged PE's **machine type matches the target arch** (an x86 DLL in
  an amd64 app is a classic silent failure that surfaces only as a cryptic
  load error at runtime).
- **signing** — v1 signs only the launcher; a full payload sweep that would
  also cover `bin\` is **not planned** (it only matters under Smart App Control
  / WDAC). onedir keeps that possible regardless: every declared file — helper
  `.exe`s included — stays real and individually signable. This matters for
  helper `.exe`s specifically, because a spawned unsigned executable is judged
  by SmartScreen heuristics and Smart App Control on its own, separate from the
  launcher's reputation.

**The boundary, stated so the channel can't creep:** kivyforge fetches,
verifies, stages, registers, and signs declared binaries. It does **not**
resolve their dependencies, fix their imports, or otherwise repair a binary
that expects DLLs it didn't ship with — that is the vendor's job (the
consume-prebuilt-artifacts principle). A declared DLL whose own dependencies
are also declared works, because everything in `bin\` resolves against
`bin\`; a DLL that needs something *else* is the user's diagnostic
(`Dependencies.exe`, as above).

**The escape hatch remains:** files dropped under `app_dir` are still copied
wholesale into `<bundle>\app\`, but get none of the handling above — no
pinning, no registration (load by absolute path or your own
`os.add_dll_directory`), no arch check. Fine for a quick experiment; declare
it once it matters.

## DLL discovery — *prove this first*

The verification chain, run **on a clean VM** (no Python, no VCRedist), in
order:

```
python\python.exe -c "import sys; print(sys.prefix)"
python\python.exe -c "import kivy_deps.sdl2 as d; print(d.dep_bins)"    # sdl3 on Kivy 3
python\python.exe -c "import kivy; from kivy.core.window import Window; print(Window)"
```

1. Confirms the prefix resolves into the bundle.
2. Confirms `dep_bins` is **non-empty** and points inside the bundle.
3. The real test — forces the SDL window provider `.pyd` to load and resolve
   its full DLL chain.

On failure, use **`Dependencies.exe`** (the maintained Dependency Walker
replacement) or `dumpbin /dependents` against the failing `.pyd` / `SDL2.dll`
to identify the missing DLL rather than guessing.

**Command 3 passing on a clean VM is the green light to start bootloader
work.** Findings (PBS VC-runtime bundling, the GL backend answer, any layout
surprises) are recorded in `docs/design/dev/windows-dll-findings.md`.

> **Resolved.** This gate is satisfied: the backend is implemented and apps
> build and run end to end on Windows, with the bundle vendoring its own Python
> and VC runtime. The chain above is retained as a reproducible recipe for
> re-confirming host-independence, not as an open item — see
> [windows-dll-findings.md → Part 2](../../dev/windows-dll-findings.md#part-2--clean-vm-dll-discovery-spike-satisfied).

## Launcher

The bundle's entry point is a **native, prebuilt, windowed-subsystem
launcher `.exe`** that spawns the bundled interpreter and waits for it —
designed in full in [bootloader-windows.md](bootloader-windows.md). The
one-paragraph summary: compiled once in CI (never on user machines — no MSVC
requirement), parameterized per app by resource patching (icon + version
resource) and the generated bootstrap module, `CreateProcessW` +
Job-object + wait (Windows has no true `exec`), wide-char argv throughout,
self-location via `GetModuleFileNameW`, and the same
`PYTHONHOME`/`PYTHONPATH`/`PYTHONNOUSERSITE` env contract as the macOS and
Linux launchers.

## `init` / `build` / `run` / `package` / `status`

- **`init`** — seeds the `[tool.kivy.windows]` overlay (and `[tool.kivy]` if
  absent) into `pyproject.toml` using the same text-surgery renderer as
  macOS/Linux (`render_windows_tables` alongside `render_macos_tables` /
  `render_linux_tables` in `cli/init_writer.py`): `schema_version`, an
  `app_id` TODO stub, `archs`, the desktop default Python version, a
  commented icon stub, a commented `[tool.kivy.windows.signing]` thumbprint
  stub, a commented `[tool.kivy.windows.native.binaries]` stub (the iOS
  swift-packages-stub pattern — inert until uncommented), and the documented
  Kivy `exclude` block when kivy is a direct dependency.
- **`build`** — resolve (if needed), acquire the runtime and wheels, and
  assemble the onedir tree under `build/windows/<display_name>` (runtime stage →
  wheel-scheme install → declared-native-binaries stage → app copy → bootstrap
  generation → launcher placement + resource patch). The `build` tree is the
  **unsigned** iterative `run` target and is never mutated by signing.
- **`run`** — build (unless `--no-build`), then execute the launcher so the
  developer sees stdout/stderr + tracebacks. The launcher is windowed-subsystem
  (no console of its own); the console handoff is explicit rather than assumed:
  the launcher calls `AttachConsole(ATTACH_PARENT_PROCESS)` and, when a parent
  console exists (the `kivyforge run` path), **explicitly inherits
  stdin/stdout/stderr** for the child so tracebacks land in the terminal — see
  the [bootloader doc](bootloader-windows.md#windowed-subsystem-only). (On a
  double-click launch there is no parent console; the child is created with
  `CREATE_NO_WINDOW` so no console flashes.)
- **`package -f folder`** — **copies** the `build/windows` tree into the
  finished distributable at `dist/windows/<safe-name>-<version>-amd64/`
  (`<safe-name>` is `display_name` run through the Windows filename sanitizer),
  **optionally signing that copy only** when `[tool.kivy.windows.signing]` is
  configured (see [signing-windows.md](signing-windows.md)). The `build` tree is
  preserved unsigned. `-f folder` is the only format — installers are
  permanently external (see ["Scope"](#scope)). **Why a separate `dist/` copy
  rather than signing in place** (as macOS does its `.app`): the Windows onedir
  tree plays two roles at once — it is both the churny iterative `run`-in-place
  dev target *and* a first-class shipped deliverable (the raw folder is a
  mainstream end-user format, portable/zip, and the feedstock for an external
  Inno step). macOS's atomic `.app` is the terminal unit signed in place;
  Linux's AppDir is a build substrate whose real distributable (the AppImage)
  kivyforge emits to `dist/`. On Windows the folder itself is the distributable
  *and* the dev artifact, so `dist/windows` holds a clean, signed, versioned
  copy while `build/windows` stays the unsigned dev tree.
- **`status`** — the standard read-only snapshot (identity, runtime version,
  lock sync, build state), implemented as the `Platform.status` method like
  the other three backends, locating the built artifact by `display_name`
  under `build/windows/`.

Windows-only options (e.g. a future `--no-sign` override) stay inside
`platforms/windows/cli.py` — per the
[abstraction-leak retro](../../common/abstraction-leak-retro.md), the shared
`Platform.build`/`run`/`package` signatures are not widened further for
Windows. The desktop backends' `reject_ios_only_target` guard applies
unchanged.

## The finished distributable — where it lands and what's next (user-facing)

**Where it lands.** `kivyforge package -p windows` copies the assembled onedir
into:

```
dist\windows\<safe-name>-<version>-amd64\
├── <Name>.exe          ← the launcher — double-click this to run the app
├── _kivyforge_bootstrap.py
├── app.ico             (only when icons.source is set)
├── app\                ← your code
├── bin\                (only when native.binaries is declared)
└── python\             ← the bundled CPython runtime + wheels + SDL/codec DLLs
```

`<safe-name>` is `[tool.kivy].display_name` run through the Windows filename
sanitizer; `<version>` is `[project].version`. **The folder itself is the
deliverable** — there is no single-file distributable on Windows (a scope
decision, not a gap; see ["Scope"](#scope)). The parallel
`build\windows\<display_name>\` tree is the unsigned, churny `run`-in-place dev
target; `dist\windows\...` is a clean, versioned, optionally-signed copy you
actually ship (see the [`package` split](#init--build--run--package--status)).

**How it runs.** Double-clicking `<Name>.exe` launches the app. The bundle is
**fully relocatable** — self-location via `GetModuleFileNameW` and a
runtime-computed `sys.prefix` mean no absolute paths are baked in (see ["DLL
discovery"](#dll-discovery--prove-this-first)) — so the whole folder can be
moved, copied, or renamed anywhere on the target machine and still run.

**What the recipient's machine needs: nothing preinstalled.** No Python, no
Kivy/SDL, and **no VC++ Redistributable** — the bundle carries the relocated
PBS prefix, the resolved wheels, the SDL/codec DLLs, and the VC runtime
app-local by construction. The one residual friction is trust, not
dependencies: an unsigned or low-reputation launcher trips SmartScreen's
"Windows protected your PC" wall (the v1 default) — see ["Signing"](#signing).

**Next steps — three exits, all past kivyforge's artifact boundary:**

1. **Ship the folder as-is (portable).** Zip it (`Compress-Archive`) or drop it
   on a share/USB stick; the recipient unzips and double-clicks `<Name>.exe`.
   No installer, no admin rights, no registry writes. The raw/zipped folder is
   a mainstream end-user format.
2. **Wrap it in an installer** for Start-menu shortcuts, an uninstaller,
   per-user/machine placement, or auto-update. Feed the folder to Inno Setup /
   NSIS / WiX (MSI) / MSIX — **permanently external** (see ["Scope"](#scope)).
   The signing doc's
   [orchestration section](signing-windows.md#orchestration-kivyforge--inno-are-composed-not-redundant)
   specifies the sign-the-folder-first sequencing and one-credential path so
   kivyforge's signing and the installer's signing compose without
   double-signing.
3. **Sign it first** (recommended before either of the above for public
   distribution). Configure [`[tool.kivy.windows.signing]`](#toolkivywindows-overlay)
   and `package` signs (and RFC-3161 timestamps) the launcher in the `dist\`
   copy only — see ["Signing"](#signing) and
   [signing-prerequisites-windows.md](signing-prerequisites-windows.md).

## Windows file locking (write-in-place) + Dev Drive

Windows cannot reliably *rename* a freshly written tree, so `build` and
`package` never do. Both write the onedir directly into its final location and
only ever rename the **previous** (long-since-scanned) tree aside, restoring it
if the write fails (`platforms/windows/fsswap.py`: `reserve_previous` /
`restore_previous` / `discard_reserved`, with `rename_with_retry` for the
reserve step).

**Why.** A Windows rename internally opens the target with `DELETE` access, and
that open fails unless **every** other open handle on the file was opened with
`FILE_SHARE_DELETE` — a flag the C runtime and most apps omit (Raymond Chen,
[*Renaming a file is a multi-step process*](https://devblogs.microsoft.com/oldnewthing/20211022-00/?p=105822)).
Two forces make a just-written tree hostile to rename:

- **Antivirus.** Defender's minifilter scans each newly created `.exe`/`.dll`/
  `.pyd` and holds it open during the scan; a cold *first-sight* cloud lookup
  can exceed any sane retry window, and the extracted CPython + wheels tree is
  thousands of new files.
- **Async close.** `CloseHandle` triggers `IRP_MJ_CLEANUP` immediately but the
  final `IRP_MJ_CLOSE` (which frees the file object) can lag, so a rename right
  after "closing" can still hit a sharing violation. Microsoft's own guidance
  for this is to retry briefly.

**Failure taxonomy.** Transient locks (`ERROR_SHARING_VIOLATION` / WinError 32,
scanner or close-lag) are ridden out by `rename_with_retry`'s bounded backoff.
A lock that persists past the retry window (`ERROR_ACCESS_DENIED` / WinError 5)
is almost always a human holding the tree — Explorer or a terminal sitting in
the folder, or a **running copy of the app** (a running `.exe`'s image is locked
by the OS and can never be renamed). That case is unfixable in code, so
`reserve_previous` raises `WindowsBundleError` with an actionable message
(close the window / quit the app / delete the folder and retry) rather than a
bare `WinError 5` traceback.

**Recommended dev/CI mitigation: Dev Drive.** For repositories that hit lock
churn, put working directories (and the `build/`/`dist/` output) on a Windows 11
**Dev Drive** (ReFS) with Defender **performance mode**. A trusted Dev Drive
switches `WdFilter.sys` from synchronous blocking scans to asynchronous
*deferred* scanning, so file creates complete immediately and the scan runs in
the background — directly removing the "scanner holds the new file open"
contention while keeping real-time protection on. Microsoft recommends this over
folder/process exclusions, which disable scanning entirely. See
[Set up a Dev Drive](https://learn.microsoft.com/en-us/windows/dev-drive/) and
[Protect Dev Drive using performance mode](https://learn.microsoft.com/en-us/defender-endpoint/microsoft-defender-endpoint-antivirus-performance-mode).
kivyforge does **not** add Defender exclusions on the user's behalf.

*Setup (Windows 11; needs ~50 GB free, ReFS).* A Dev Drive can only be created
**at format time** — an existing NTFS volume can't be converted in place. Create
one via **Settings → System → Storage → Advanced storage settings → Disks &
volumes → Create dev drive** (new VHD, resized free space, or unallocated
space), or from an elevated PowerShell over free space:

```powershell
Format-Volume -DriveLetter D -DevDrive
```

New Dev Drives are **trusted by default**, and Defender performance mode is then
on automatically. Verify/enable (elevated):

```powershell
fsutil devdrv query D:                       # confirm "Trusted" (needed for perf mode)
fsutil devdrv trust D:                        # only if untrusted (e.g. a VHD moved hosts)
Set-MpPreference -PerformanceModeStatus Enabled   # requires real-time protection ON
```

Trust/filter policy is stored **per machine**, so a VHD moved to another box
reverts to an ordinary volume until re-trusted. Then keep the repo *and* the
`build/`/`dist/` output on the Dev Drive; `kivyforge doctor -p windows` will
report the volume as `ReFS (Dev Drive)` instead of the NTFS advisory.

**`doctor` pre-flight.** Two Windows checks surface this before a build is wasted
(see the [`doctor` table](#doctor-checks-windows)): **Build output not locked**
attempts the exact tree-rename `build`/`package` will do and WARNs if a running
instance or an open Explorer/terminal window holds it; **Build volume** reports
the output filesystem and recommends a Dev Drive on NTFS. Neither can *clear* an
active lock — `doctor` is read-only pre-flight — but they name the cause and the
mitigation ahead of the failure.

## Signing

Designed in full in [signing-windows.md](signing-windows.md). The policy
summary: **v1 ships kivyforge's own binaries and the default artifact
unsigned** (the developer audience tolerates the SmartScreen wall; defer
pending demand), but the signing hook is a **first-class, optional pipeline
step from day one** — for a packaging tool, signing the *output* is a feature
users need. Identity is a **thumbprint into the Windows certificate store**
(never a pfx path/password in config), executed via `signtool`, developed and
CI-tested against a self-signed certificate.

## `doctor` checks (Windows)

| Check | Scope | What it validates |
|-------|-------|-------------------|
| Host is Windows | environment | The Windows backend requires a Windows host (host-capability check). |
| Long-path support | environment | WARN if the `LongPathsEnabled` registry value is off — deep install trees can exceed the 260-char `MAX_PATH` limit; hint the registry fix. |
| kivyforge version | environment | Self-version; warn if newer on PyPI (best-effort). |
| App source directory | project | `[tool.kivy].app_dir` resolves to an existing directory. |
| `app_id` valid | project | FAIL only on Microsoft's hard constraints (no spaces, ≤128 chars) — also a config-time hard error, surfaced here with remediation. **WARN** (not FAIL) when the value is valid but does not follow the conventional pascal-cased, period-delimited `Company.Product` style. |
| Architecture coverage | project | Every compiled dep resolves a `win_amd64` wheel; FAIL names the package. |
| App icon | project | If `[tool.kivy.windows.icons].source` is set, FAIL unless a valid 1024×1024 PNG. SKIP if unset. |
| Native binaries: sources | project | Each `[tool.kivy.windows.native.binaries]` `source` exists (repo-relative path) or its host is reachable (URL). SKIP when the table is empty. |
| Native binaries: collision | project | No two declared entries (or archive members) stage to the same `bin\` path under a **case-insensitive** comparison, and no member uses a Windows reserved device name or alternate-data-stream (`:`) path. SKIP when the table is empty. |
| Native binaries: arch | project | Each staged PE in `<bundle>\bin` has a machine type matching the target arch (an x86 DLL in an amd64 app fails only at load time, cryptically). SKIP when the table is empty or the bundle isn't built. |
| Build output not locked | project | Pre-flights the exact rename `build`/`package` performs on `build\windows\<app>`: WARN if the tree is held open (a running instance, or Explorer/a shell in the folder) so the assemble step can't replace it (`WinError 5`). SKIP when nothing is built. Transient/user-fixable, so WARN not FAIL. See ["Windows file locking"](#windows-file-locking-write-in-place--dev-drive). |
| Build volume | project | Advisory (always PASS/SKIP, never noise): reports the build volume's filesystem and, on NTFS, recommends a Windows 11 **Dev Drive** (ReFS) with Defender performance mode for repeated rename-lock churn. |
| signtool available | environment | `signtool.exe` findable (Windows SDK). SKIP when `[tool.kivy.windows.signing]` is unconfigured; FAIL when signing is configured but the tool is missing. |
| Signing certificate | project | When configured, the thumbprint matches exactly one code-signing certificate in the **configured `store_scope` store** — the same store `signtool` will sign against (`Cert:\CurrentUser\My` by default, `Cert:\LocalMachine\My` when `store_scope = "machine"`). SKIP when unconfigured. |
| find_links directories | project | If set, each entry is an existing directory containing `.whl` files. |
| Required hosts reachable | project | The lockfile hosts (PBS + wheel indexes + native-binary URLs), plus the timestamp server when signing is configured. |

`doctor` reports each check as PASS / WARN / FAIL with a remediation hint;
exit code is non-zero only on FAIL.

Config-time (`kivyforge lock`/`build`/`package`, not `doctor`): an `app_id`
that violates Microsoft's hard constraints (contains a space, or exceeds 128
characters) is a hard `ConfigError`. Style-only deviations are never a config
error — they surface as the `doctor` WARN above.

## Host requirements

- A Windows (amd64) host. **No MSVC Build Tools, no compiler** — the launcher
  is prebuilt (this is a design constraint, not an accident; see the
  [bootloader doc](bootloader-windows.md#prebuilt-and-vendored-not-compiled-on-demand)).
- For signing only: `signtool.exe` (ships with the Windows SDK / Visual
  Studio build tools — required only when `[tool.kivy.windows.signing]` is
  configured).
- End-user machines need nothing preinstalled: no Python, no VCRedist. The
  bundle is self-contained by construction (relocated PBS prefix + staged VC
  runtime); apps build and run end to end on Windows, and the optional
  clean-VM spike can confirm host-independence on a pristine box.

## Module layout

Everything Windows-specific lives under the self-contained
`kivyforge/platforms/windows/` package (platform-first consolidation, same as
Linux):

- `kivyforge/platforms/windows/__init__.py` — the `WindowsPlatform` backend
  (`host_system = "Windows"`, `package_formats = ("folder",)`) with its
  `build`/`run`/`package`/`status`/`doctor` verb methods (each lazily imports
  the module below). Registered in `platforms/__init__.py`; `cli/lock.py`
  gains the `windows` `_LockOps` branch.
- `kivyforge/platforms/windows/` (bundler modules) — the onedir bundler
  (`bundle.py` orchestrates the stages), `runtime_stage.py`, `wheels_stage.py`
  (the no-`pip` wheel-scheme installer), and `native_stage.py` (a thin wrapper
  over the shared `artifacts/native_stage_util.stage_binaries()` helper), plus
  the supporting helpers: `petools.py` (PE machine-type check), `icons.py`
  (PNG → multi-size `.ico`), `naming.py` (`windows_safe_name` — reserved-name /
  illegal-character-safe artifact names), `assets.py` (locate + SHA-256-verify
  the vendored binaries against `vendor/SHA256SUMS`), `rcedit.py` (the
  `ResourcePatch` model + `rcedit` resource patching), and `fsswap.py` for
  Windows-safe write-in-place publishing (see ["Windows file
  locking"](#windows-file-locking-write-in-place--dev-drive)).
- `kivyforge/platforms/windows/launcher/` — the launcher subpackage:
  `launcher.c` (the in-repo C source), `build_launcher.py` (the deterministic
  build/verify that recompiles and byte-compares against the vendored binary),
  and `__init__.py` (per-app assembly-time work — generating
  `_kivyforge_bootstrap.py`, then copying + resource-patching the vendored
  launcher into `<bundle>\<name>.exe`).
- `kivyforge/platforms/windows/vendor/` — the prebuilt, pinned assets consumed
  at assembly time: `launcher-amd64.exe` and `rcedit-x64.exe`, their
  `SHA256SUMS` manifest, `TOOLSET.txt` (the MSVC toolset the launcher was
  vendored against — see the CI `revendor_launcher` job), the `rcedit`
  `LICENSE`/`NOTICE`, and `fetch_rcedit.py` (re-fetch/verify helper).
- `kivyforge/platforms/windows/lock/` — the lock profile + runtime provider
  (`profile.py`, `runtime.py` with the `x86_64-pc-windows-msvc` triple map),
  built on the shared `kivyforge/lock/wheelruntime/` engine.
- `kivyforge/platforms/windows/signing.py` — the `Signer` protocol +
  `signtool` backend (see [signing-windows.md](signing-windows.md)).
- `kivyforge/platforms/windows/cli.py` — Windows implementation of the shared
  verbs (dispatched from `WindowsPlatform`).
- `kivyforge/platforms/windows/doctor.py` — Windows `doctor` checks, reusing
  `kivyforge/doctor/checks_common.py`.

The launcher's C source and its CI build/re-vendor workflow live in the repo
(under the backend package) alongside the vendored binary it reproduces.

## Open items

Spike-only questions remain; the previously-open *design* choices are now
settled (recorded under "Settled decisions" in the
[implementation plan](../../../../.cursor/plans/kivyforge_windows_backend.plan.md)):

- [x] **Verify PBS Windows binaries: signed or not?** RESOLVED — **unsigned.**
      `Get-AuthenticodeSignature` over a built bundle reports PBS's core
      `python.exe` / `python3.dll` / `python3xx.dll` (and all Kivy/SDL payload
      `.pyd`/DLLs) as `NotSigned`; the only `Valid` signatures in the tree are
      incidental — the PSF-signed Tcl/Tk DLLs (`tcl86t.dll`, `tk86t.dll`) and
      Microsoft-signed VC runtime (`msvcp140.dll`, `vcruntime140*.dll`) +
      `d3dcompiler_47.dll`. So the payload is effectively unsigned; signing it
      would only affect Smart App Control / WDAC machines and is not planned.
      See [windows-dll-findings.md](../../dev/windows-dll-findings.md).
- [x] **Verify PBS bundles `vcruntime140.dll` / `vcruntime140_1.dll` /
      `msvcp140.dll`** next to `python.exe`. RESOLVED (Phase 4): PBS ships
      `vcruntime140.dll` + `vcruntime140_1.dll` but **not** `msvcp140.dll`;
      `runtime_stage.ensure_vc_runtime` verifies the two core DLLs and places
      `msvcp140.dll` app-local best-effort. See
      [windows-dll-findings.md](../../dev/windows-dll-findings.md).
- [x] **Pin down the baseline Windows GL backend** (ANGLE vs desktop GL for
      Kivy 2.3.1 / SDL2). RESOLVED: the shipped baseline uses **desktop GL via
      GLEW** — a built bundle logs `Backend used <glew>` (OpenGL 4.6). Both
      `kivy_deps.glew` and `kivy_deps.angle` are pulled in and staged, so ANGLE
      (`KIVY_GL_BACKEND=angle_sdl2`) is available as a fallback but not the
      default. See [windows-dll-findings.md](../../dev/windows-dll-findings.md).

Settled (no longer open):

- **Bootloader binary distribution — VENDORED.** The audited amd64 launcher is
  vendored in the package with a license/notice, a pinned SHA-256, and
  package-data entries; the C source and a **deterministic CI rebuild** (which
  byte-compares against the vendored binary) live in-repo.
- **Icon/version resource patching — `rcedit`.** Vendored alongside the
  launcher (license/notice + pinned SHA-256). Patching runs on `windows-latest`.
- **distlib / `simple_launcher` license** — moot: kivyforge ships its **own**
  launcher C source (distlib is a *design* reference only), so nothing of its
  code or binaries is vendored.

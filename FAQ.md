# FAQ for kivyforge

## Introduction

kivyforge is a declarative, PEP 621-aligned build toolchain for
[Kivy](https://kivy.org) (and other Python) apps — the successor to kivy-ios,
python-for-android, and buildozer. You describe your app once in `pyproject.toml`
and kivyforge packages it for the platform you target. The goal is to support
every platform Kivy runs on, and all five — **Android, iOS, Linux, macOS, and
Windows** — are implemented. On iOS the toolchain resolves dependencies into a
lockfile, downloads the official `Python.xcframework` plus prebuilt iOS wheels,
and generates an [Xcode](https://developer.apple.com/xcode/) `.xcodeproj`; on
Android it does the same with the per-ABI python.org Android runtime and Android
wheels and generates a Gradle/[AGP](https://developer.android.com/build) project
that produces a signed `.apk`/`.aab`; the desktop backends bundle a relocatable
CPython plus wheels into a `.app` (macOS), an AppImage/AppDir (Linux), or a
run-from-folder `onedir` (Windows).

For the full workflow see the [README](README.md); for design and reference
details see the [design docs](docs/design/common/00-overview.md). When something looks
wrong, `kivyforge doctor` runs environment and project health checks and is a
good first stop.

## FAQ

### `kivyforge: command not found`

The `kivyforge` script (and its `kf` alias) is installed into your virtual
environment. Activate it (`. .venv/bin/activate`) and make sure kivyforge is
installed (`pip install -e ".[dev]"` from the repo).

### Error: SDK "iphonesimulator" cannot be located

The active Xcode path is not set correctly. Point `xcode-select` at your Xcode:

    sudo xcode-select --switch /Applications/Xcode.app

If the command line tools are missing, install them with `xcode-select --install`.

### `kivyforge build` says the lock is out of sync

Your `pyproject.toml` changed since `pylock.ios.toml` was generated. Re-resolve:

    kivyforge lock

In CI, `kivyforge lock --check` exits non-zero when the lock is stale (it writes
nothing). Use `--no-verify-lock` on `build` only if you intentionally want to
skip the drift check.

### Downloading `Python.xcframework` fails with HTTP 404

`[tool.kivy.ios.python].version` must match a build that python.org actually
publishes. iOS support is new, so during the preview period you may need a
prerelease such as `3.15.0b4` rather than a final `3.15.0`. Set the version to a
published release and re-run `kivyforge lock`.

### "invalid character in Bundle Identifier"

A bundle identifier is a UTI: only letters, digits, hyphen (`-`), and period
(`.`) are allowed — no underscores. Fix `[tool.kivy.ios].bundle_id`, e.g. use
`org.example.hello-world` instead of `org.example.hello_world`.

### I edited my Python source but the app didn't change

Editing Python source does **not** require `kivyforge build`: the generated
project links your source directory (`app/` is a symlink to `app_dir`), so just
relaunch — `kivyforge run --simulator`, or ⌘R in Xcode. Re-run `kivyforge build`
only when you change app config or need to regenerate the project, and
`kivyforge clean` to reset the generated `<app>-ios/` folder for a fresh build.

### Where are downloaded artifacts stored?

`Python.xcframework` and other xcframeworks are cached under
`~/Library/Caches/kivy-ios/artifacts/` and shared across projects. Flush the
cache with `kivyforge clean --cache`, or force a fresh download for one build
with `kivyforge build --no-cache`.

### Can I bundle a plain Python app without Kivy?

Yes. List no Kivy in `dependencies` and the toolchain bundles a pure-Python app
(this is what `examples/mobile/hello-world` does). It runs Python directly with no UI —
ideal as a smoke test of the toolchain or for validating pure-Python code
on-device. To ship an actual app you still need a UI layer: Kivy (via SDL), or a
native bridge such as `rubicon-objc`/`pyobjus` that your Python code drives.

### macOS Developer ID signing fails with `errSecInternalComponent`

If `kivyforge package -p macos` (with `[tool.kivy.macos.signing]` configured)
fails on every Mach-O with `errSecInternalComponent` — even after retrying,
even on files that ad-hoc sign fine — your login keychain's private key ACL is
likely corrupted rather than the error being transient. This has been observed
after using Keychain Access's "reset my default keychain" flow; the corruption
can persist across reboots and re-issuing the certificate.

Check for the smoking gun:

    security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k <password> login.keychain-db

If this aborts with `SecKeychainItemCopyAccess: The specified item is no
longer valid`, the fix is to stop fighting the corrupted keychain and isolate
signing into a fresh one:

    security create-keychain -p <new-password> signing.keychain-db
    security list-keychains -d user -s signing.keychain-db login.keychain-db
    security unlock-keychain -p <new-password> signing.keychain-db
    security set-keychain-settings signing.keychain-db
    security default-keychain -s signing.keychain-db
    # In Xcode: Settings → Accounts → Manage Certificates → + → Developer ID Application
    # (it's created in signing.keychain-db since that's now default)
    security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k <new-password> signing.keychain-db
    security default-keychain -s login.keychain-db   # restore normal default

If `codesign` then reports `ambiguous` (a same-named certificate matches in
both keychains), delete the broken copy from `login.keychain-db` (Keychain
Access → Certificates tab, right-click → Delete) so only the working one in
`signing.keychain-db` remains. Recreate your `xcrun notarytool
store-credentials` profile too if it was wiped by the same reset — pass
`--keychain ~/Library/Keychains/signing.keychain-db` to keep it alongside the
signing identity, immune to future login-keychain resets. See the
["Developer ID sign + notarize + staple"](docs/design/platforms/macos/macos-spec.md#developer-id-sign--notarize--staple)
section of the macOS spec for the full config reference.

This isolated-keychain approach isn't a workaround unique to kivyforge — it's
Apple's own recommendation. Apple DTS's
[The Care and Feeding of Developer ID](https://developer.apple.com/forums/thread/732320)
suggests keeping a Developer ID identity in its own keychain (separate
password/locking policy from the login keychain) precisely because these
identities are hard to replace, and also recommends exporting a `.p12` backup
so a corrupted or reset keychain never puts you in this position again. For
the general `errSecInternalComponent` failure mode (locked keychains, ACL
prompts, SSH/CI contexts) — as opposed to the specific corrupted-item case
above — see Apple DTS's
[Resolving errSecInternalComponent errors during code signing](https://developer.apple.com/forums/thread/712005).

`kivyforge doctor` checks for this proactively: the `Signing identity` check
WARNs if your configured identity is found in `login.keychain-db`, before you
ever hit a corrupted-ACL failure.

### Why does the Python `multiprocessing`/`subprocess` module not work?

The iOS application model does not support spawning subprocesses in a
cross-platform-compatible way. The platform focuses on minimizing processor
usage (and therefore power consumption) and promotes an
[alternative concurrency model](https://developer.apple.com/library/archive/documentation/General/Conceptual/ConcurrencyProgrammingGuide/Introduction/Introduction.html).
Use threads or async concurrency instead.

### My Linux AppImage fails with a libfuse2 / "dlopen(): error loading libfuse.so.2" error

kivyforge builds AppImages with a **pinned static-FUSE (type2) runtime**
embedded (`appimagetool --runtime-file`), so a correctly built kivyforge
AppImage does **not** need the host's `libfuse2`. If you still hit a FUSE error
(e.g. an old runtime, a container, or a locked-down CI box), use the universal
no-FUSE fallback — the AppImage extracts itself to a temp dir and runs from
there:

    ./MyApp-1.0.0-x86_64.AppImage --appimage-extract-and-run
    # or, equivalently:
    APPIMAGE_EXTRACT_AND_RUN=1 ./MyApp-1.0.0-x86_64.AppImage

kivyforge already sets `APPIMAGE_EXTRACT_AND_RUN=1` when it invokes
`appimagetool` at *build* time, so building an AppImage never needs FUSE on the
build host (WSL2 / containers / CI just work).

### Can I build and run the Linux backend under WSL2?

Yes — the Linux backend is developed and tested on WSL2 Ubuntu.
[WSLg](https://github.com/microsoft/wslg) provides an X11/Wayland session and
OpenGL (Mesa via D3D12), so `kivyforge run -p linux` opens a real window. If GL
misbehaves, force software rendering with `LIBGL_ALWAYS_SOFTWARE=1`. A harmless
`libmtdev.so.1: cannot open shared object file` warning from Kivy just means the
host has no multitouch device; it does not stop the app.

### How do I build or test on a headless Linux box (CI, no display)?

Locking and building need no display — only `run` (and launching the packaged
AppImage) opens a window. For headless smoke tests, wrap the run under a virtual
framebuffer with software GL:

    xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 ./MyApp-1.0.0-x86_64.AppImage

`kivyforge doctor -p linux` reports a WARN with this hint when neither `DISPLAY`
nor `WAYLAND_DISPLAY` is set.

### What is the Linux "glibc floor", and why does it matter?

A kivyforge AppImage bundles Python and your wheels, but it never bundles the C
library, `libGL`/`libEGL`, or a display server — those come from the host. The
bundled [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
runtime is a gnu/glibc build with a **glibc ≥ 2.17** floor (manylinux2014-class),
so the AppImage runs on any host that new or newer. The artifact's *effective*
floor is `max(runtime floor, highest manylinux level among your locked wheels)`;
`kivyforge doctor -p linux` prints it. You can raise the floor deliberately with
`[tool.kivy.linux].glibc_floor = "2.28"` to admit newer-manylinux-only wheels —
at the cost of requiring a newer host. Setting it *below* 2.17 is a config
error. **musl** hosts (Alpine) are out of scope: the gnu runtime won't run
there, and Kivy publishes no musllinux wheels.

### My Windows app shows a "Windows protected your PC" (SmartScreen) warning

That is Microsoft **SmartScreen**, and it is expected for a new, unsigned (or
newly-signed, low-reputation) executable — it is not a kivyforge bug. kivyforge
ships the default artifact **unsigned**, so recipients see the blue prompt and
must click *More info → Run anyway*. Two ways to reduce it: (1) configure
Authenticode signing (`[tool.kivy.windows.signing]` with a certificate-store
`thumbprint`) so `kivyforge package` signs + timestamps the launcher — a standard
OV certificate still needs to *build reputation* before the prompt stops; an
**EV** certificate clears it immediately. (2) Distribute through a channel users
already trust. SmartScreen reputation is per-signature and accrues over
downloads; there is no way to bypass it from inside the bundle.

### `kivyforge build -p windows` fails with a long-path (`MAX_PATH`) error

A full python-build-standalone prefix nested under `build\windows\<App>\python\`
can exceed the legacy 260-character `MAX_PATH` limit. Enable long paths on the
build host: set `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled`
to `1` (an elevated PowerShell one-liner: `New-ItemProperty -Path
"HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value
1 -PropertyType DWORD -Force`), then reboot. `kivyforge doctor -p windows` WARNs
when it is off. Building closer to the drive root (a short project path) also
helps.

### Do I need to install the Visual C++ runtime to run a kivyforge Windows app?

No. The bundled python-build-standalone runtime ships the core VC++ runtime DLLs
(`vcruntime140.dll`, `vcruntime140_1.dll`) inside the `onedir`, and kivyforge
stages them beside `python.exe` so the app never depends on a system-wide "VC++
Redistributable" install. (`msvcp140.dll`, the C++ standard library, is not in
PBS; kivyforge stages it best-effort from the build host when a wheel needs it —
most pure-Kivy apps don't.) The whole point of the `onedir` is that every DLL the
app needs is a real, shipped file.

### The Windows app opens a black console window / no window at all

The launcher is a **windowed-subsystem** `.exe`: double-clicking it in Explorer
opens your Kivy window with **no console flash**. If you see a console, you are
probably launching `python.exe` directly instead of the generated launcher — run
the `<App>.exe` beside it. Conversely, `kivyforge run -p windows` deliberately
*attaches* the app to your terminal so you can see stdout/stderr and tracebacks
during development; that is the diagnostic path, not the double-click path. If the
window never appears, run `<App>.exe` from a terminal (or use `kivyforge run`) to
see the traceback — a missing GL/ANGLE backend or an import error in your app
surfaces there.

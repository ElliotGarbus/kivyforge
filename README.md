# kivyforge


[![Backers on Open Collective](https://opencollective.com/kivy/backers/badge.svg)](https://opencollective.com/kivy)
[![Sponsors on Open Collective](https://opencollective.com/kivy/sponsors/badge.svg)](https://opencollective.com/kivy)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](code_of_conduct.md)

![PyPI - Version](https://img.shields.io/pypi/v/kivyforge)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/kivyforge)

[![kivyforge](https://github.com/ElliotGarbus/kivyforge/actions/workflows/kivyforge.yml/badge.svg)](https://github.com/ElliotGarbus/kivyforge/actions/workflows/kivyforge.yml)

kivyforge is a declarative, [PEP 621](https://peps.python.org/pep-0621/)-aligned
build toolchain for [Kivy](https://kivy.org) (and other Python) apps. You
describe your app once in `pyproject.toml`; kivyforge resolves your dependencies
into a lockfile and packages the app for the platform you target. It is the
successor to **kivy-ios**, **python-for-android**, and **buildozer**, unifying
their per-platform workflows behind a single declarative configuration.

The goal is one toolchain for every platform Kivy runs on — **Android, iOS,
Linux, macOS, and Windows**.

> **Status: early development — iOS + macOS + Linux + Windows + Android.**
> kivyforge targets **iOS** (resolve into `pylock.ios.toml`, download the official
> [`Python.xcframework`](https://www.python.org/downloads/) + prebuilt iOS
> wheels, generate an [Xcode](https://developer.apple.com/xcode/) project),
> **macOS** (resolve into `pylock.macos.toml`, bundle a relocatable
> [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
> CPython + wheels into a signed, double-clickable `.app`), **Linux** (resolve
> into `pylock.linux.toml`, bundle a PBS gnu/glibc CPython + manylinux wheels into
> an [AppImage](https://appimage.org/) — with a run-from-folder AppDir substrate),
> **Windows** (resolve into `pylock.windows.toml`, bundle a PBS MSVC CPython +
> `win_amd64` wheels into a run-from-folder `onedir` with a windowed launcher
> `.exe`, optionally Authenticode-signed), and **Android** (resolve into
> `pylock.android.toml`, assemble the official
> [python.org Android runtime](https://www.python.org/downloads/android/) +
> per-ABI `android_*` wheels into a generated Gradle project, and produce a
> signed `.apk`/`.aab` — with pyjnius as a prebuilt wheel, no per-app
> compilation). If you need a shipping toolchain today, use kivy-ios 2.x,
> python-for-android, or buildozer.

### Currently supported targets

| Target | Architectures | Output | Signing | Build host |
|---|---|---|---|---|
| [iOS](https://www.apple.com/ios/) device | arm64 (iPhone / iPad) | generated Xcode project → `.app` | Apple Developer signing via Xcode | macOS + [Xcode](https://developer.apple.com/xcode/) |
| iOS Simulator | arm64, x86_64 | generated Xcode project → `.app` | none required | macOS + Xcode |
| [Android](https://www.android.com/) device / emulator | `arm64_v8a`, `x86_64` | generated Gradle/AGP project → `.apk` / `.aab` | auto debug keystore, or release keystore (v1–v4 schemes) | Windows, macOS, or Linux + JDK/Android SDK/NDK |
| [macOS](https://www.apple.com/macos/) | arm64, x86_64, or universal2 (both) | `.app` | ad-hoc (default) **or** Developer ID sign + notarize + staple | macOS |
| [Linux](https://appimage.org/) | x86_64 (glibc ≥ 2.17) | `.AppImage` / AppDir | none | Linux |
| [Windows](https://learn.microsoft.com/windows/) | amd64 | `onedir` folder + windowed launcher `.exe` | optional Authenticode (unsigned by default) | Windows |

Desktop targets (macOS / Linux / Windows) bundle a self-contained runtime +
wheels; on Linux, libGL/EGL and X11/Wayland come from the host. Building for iOS
requires a Mac with Xcode; Android builds on any of the three desktop hosts.

kivyforge builds on the work of the [Kivy Team](https://kivy.org/about.html).

## Requirements

Each target platform has its own host requirements. **Building for iOS requires
macOS** (Xcode-based), so the iOS workflow below is useful only on a Mac:

- macOS with [Xcode](https://developer.apple.com/xcode/) installed, either from
  the [Mac App Store](https://apps.apple.com/app/xcode/id497799835) or from the
  command line:

      xcode-select --install

- Accept the Xcode license once:

      sudo xcodebuild -license

## Installation

Use a Python virtual environment (host Python 3.13+). This is required: it
isolates the toolchain and keeps its lockfile resolution from being polluted by
packages in your system Python.

      python3 -m venv .venv
      . .venv/bin/activate

Install kivyforge from this repository (it is not yet published to PyPI):

      pip install -e ".[dev]"

> **Mobile examples need no local wheel-building.** Kivy (2.3.1 and 3.0),
> pyobjus, and pyjnius resolve from the
> [kivy-mobile-wheels](https://github.com/ElliotGarbus/kivy-mobile-wheels)
> index — a companion repo of first-party iOS/Android cross-builds published as
> a static PEP 503 index — so `kivyforge lock` just works against any mobile
> example. `scripts/build_ios_wheels.sh` / `scripts/build_pyobjus_ios_wheels.sh`
> remain for cross-building your own iOS wheels locally (e.g. to vendor one via
> a `path` lock instead of the index); neither is required to run the examples.
>
> **Desktop needs no wheel-building either.** The desktop examples under
> [`examples/desktop/`](examples/desktop/) build straight from PyPI — Kivy
> 2.3.1 ships universal2 macOS wheels, so there is no macOS wheel-building
> step. Kivy 3.0 has no public desktop wheels yet, which is why desktop
> examples stay on 2.3.1; the iOS mobile examples need 3.0 for its structural
> mobile changes, while the Android examples run either generation (2.3.1/SDL2
> for most, 3.0/SDL3 for `hello-sdl3`) depending on which bootstrap they gate.

> **Detailed documentation.** For the full design and reference docs — the
> cross-platform model, the `pyproject.toml` / `pylock.<platform>.toml` schemas,
> artifact distribution, the CLI shape, and the per-platform backends (iOS,
> macOS, Linux, Windows) — start with the
> [kivyforge design overview](docs/design/common/00-overview.md).

## Quick start (iOS)

The workflow below targets iOS; see Quick start (Android), (macOS), (Linux),
and (Windows) further down for the other backends. Run every command from the
directory that contains your app's `pyproject.toml`.

      # 1. Seed [tool.kivy] / [tool.kivy.ios] config into pyproject.toml
      kivyforge init

      # 2. Resolve dependencies into pylock.ios.toml
      kivyforge lock

      # 3. Download artifacts and generate <app>-ios/<app>.xcodeproj
      kivyforge build

      # 4a. Open the project in Xcode and press Run...
      kivyforge open

      # 4b. ...or build, install, and launch on the simulator from the CLI
      kivyforge build --simulator
      kivyforge run --simulator

## Quick start (macOS)

macOS needs only the Xcode command-line tools (`codesign`), not the full Xcode
IDE. The macOS backend bundles a relocatable CPython + your wheels into a signed
`.app`:

      # 1. Seed [tool.kivy] / [tool.kivy.macos] config (or add the overlay by hand)
      kivyforge init            # then add a [tool.kivy.macos] table

      # 2. Resolve dependencies + pin the runtime into pylock.macos.toml
      kivyforge lock -p macos

      # 3. Build the .app (universal2 by default; --arch arm64 for a thin build)
      kivyforge build -p macos

      # 4a. Launch it (foreground, so you see stdout/tracebacks)
      kivyforge run -p macos

      # 4b. ...or produce the finished, signed distributable
      kivyforge package -p macos      # -> build/macos/<App>.app

`package` is config-driven: with no signing config it ships the **ad-hoc**-signed
`.app` (runs locally; downloaded copies hit Gatekeeper). For distribution to
other Macs, configure `[tool.kivy.macos.signing]` with a *Developer ID
Application* identity (paid Apple Developer Program) and a `notary_profile`
(created with `xcrun notarytool store-credentials`) — then the same command
deep-signs with Hardened Runtime, **notarizes, and staples** the `.app` so
Gatekeeper trusts it everywhere. `--no-notarize` skips the submission. (Hit
`errSecInternalComponent` from `codesign`? See the
[FAQ entry](FAQ.md#macos-developer-id-signing-fails-with-errsecinternalcomponent)
on corrupted keychain ACLs.)

`kivyforge doctor -p macos` reports environment + project health (host, codesign,
arch coverage, runtime floor, signing identity, notary setup, reachable hosts).

## Quick start (Linux)

The Linux backend bundles a relocatable CPython + your manylinux wheels into an
[AppImage](https://appimage.org/) (the default) or a run-from-folder **AppDir**.
It needs a Linux host (the runtime is a gnu/glibc build); no compiler or FUSE is
required at build time.

      # 1. Add a [tool.kivy.linux] table to pyproject.toml (app_id, icons, ...)

      # 2. Resolve dependencies + pin the runtime into pylock.linux.toml
      kivyforge lock -p linux

      # 3. Build the AppDir (build/linux/<App>.AppDir)
      kivyforge build -p linux

      # 4a. Launch it (runs ./AppRun directly — the fast dev loop, no FUSE)
      kivyforge run -p linux

      # 4b. ...or produce the distributable
      kivyforge package -p linux              # -> dist/linux/<app>-<ver>-x86_64.AppImage
      kivyforge package -p linux -f folder    # -> the AppDir itself

The AppImage embeds a **static-FUSE runtime**, so recipients need no `libfuse2`;
`./<App>.AppImage --appimage-extract-and-run` is the universal no-FUSE fallback.
The **host contract** is explicit: the bundle never vendors libGL/libEGL or a
display server, so the host must provide glibc ≥ the artifact's effective floor,
`libGL.so.1`/`libEGL.so.1`, and an X11 or Wayland session.

`kivyforge doctor -p linux` reports environment + project health (Linux/glibc
host, GL libraries, display session, glibc floor, arch coverage, generated
`.desktop` validity, reachable hosts).

## Quick start (Windows)

The Windows backend bundles a relocatable CPython + your `win_amd64` wheels into
a run-from-folder **`onedir`**: a windowed launcher `.exe` beside a full
python-build-standalone prefix, your app source, and any declared native
binaries. It needs a Windows host (the runtime is an MSVC amd64 build and the
resource/signing tools are Windows-only); no compiler is required at build time.

      # 1. Add a [tool.kivy.windows] table to pyproject.toml (app_id, icons, ...)

      # 2. Resolve dependencies + pin the runtime into pylock.windows.toml
      kivyforge lock -p windows

      # 3. Build the onedir bundle (build\windows\<App>\)
      kivyforge build -p windows

      # 4a. Launch it (runs the launcher .exe in the foreground — the dev loop)
      kivyforge run -p windows

      # 4b. ...or produce the distributable (copied to dist\windows\)
      kivyforge package -p windows            # -> dist\windows\<app>-<ver>-amd64\

Double-clicking the launcher opens the app with **no console flash**; `kivyforge
run` attaches it to the terminal so stdout/stderr and tracebacks are visible. The
`onedir` folder keeps every file real and signable — installers stay external.
**Authenticode signing** is optional and off by default: configure
`[tool.kivy.windows.signing]` with a certificate-store `thumbprint` and `package`
signs (and RFC-3161 timestamps) the launcher in the `dist\windows` copy.

`kivyforge doctor -p windows` reports environment + project health (Windows host,
long-path support, `app_id` style, arch coverage, icon, native-binary
sources/collisions/arch, build-output lock, build volume (Dev Drive advisory),
reachable hosts, signtool + signing certificate).

## Quick start (Android)

The Android backend assembles the official
[python.org Android runtime](https://www.python.org/downloads/android/) + your
`android_*` wheels into a generated **Gradle/AGP** project and produces a
signed **`.apk`** (sideload/CI) or **`.aab`** (Play upload) — a wheel-assembly
and Gradle-drive backend, no python-for-android recipe system, no per-app C
compilation. It needs a JDK, the Android SDK, and the NDK, but builds on
Windows, macOS, or Linux. 64-bit only (`arm64_v8a`, `x86_64`).

      # 1. Add a [tool.kivy.android] table to pyproject.toml (package, sdl, ...)

      # 2. Resolve dependencies + pin the runtime into pylock.android.toml
      kivyforge lock -p android

      # 3. Build the Gradle project + assemble the APK (build/android/<app>/)
      kivyforge build -p android --debug

      # 4a. Install and launch on a connected device or emulator
      kivyforge run -p android --emulator

      # 4b. ...or produce the signed release distributable
      kivyforge package -p android            # -> dist/android/<app>-<ver>.apk

`sdl = 2` targets Kivy 2.3.1 (SDL2, stable); `sdl = 3` targets Kivy 3.0 (SDL3,
pre-release) — mutually exclusive per app, and the SDL Java glue + `libSDL*.so`
must come from the same release (`kivyforge build` fails fast on a mismatch
rather than the silent black-screen failure that would otherwise produce).
Debug builds sign with an auto-managed debug keystore; `package` requires a
configured release keystore (`[tool.kivy.android.signing]`, passwords from
environment variables, never in `pyproject.toml`).

`kivyforge doctor -p android` reports environment + project health
(JDK/SDK/build-tools/NDK/emulator/adb, the SDL↔Kivy pairing, the pyjnius
`invoke0` contract, a hermetic 16 KB page-alignment scanner, ABI coverage,
signing, lock-host reachability). `kivyforge run --smoke` runs a generated
instrumented contract test on a real device/emulator — validated on an x86_64
API-31 emulator and a Pixel 8a (Android 16 / API 36) for both SDL2 and SDL3.

See the runnable examples for complete, copy-pasteable walk-throughs. They are
split by runtime requirement — **desktop uses Kivy 2.3.1 from PyPI, mobile
resolves Kivy (2.3.1 and 3.0) from the
[kivy-mobile-wheels](https://github.com/ElliotGarbus/kivy-mobile-wheels)
index**:

**Desktop** ([`examples/desktop/`](examples/desktop/)) — macOS/Linux/Windows:

- [`dice-roller`](examples/desktop/dice-roller/) — minimal Kivy UI that **builds &
  runs on macOS, Linux, and Windows today** from PyPI (Kivy 2.3.1).
- [`notes`](examples/desktop/notes/) — Kivy app with a pure-Python dependency
  (`platformdirs`); builds on macOS, Linux, and Windows from PyPI.
- [`desktop-viewer`](examples/desktop/desktop-viewer/) — a **macOS-only** Kivy app
  (resizable window, ⌘ keyboard shortcuts, and Finder's native open panel via
  `osascript`); no Linux/Windows overlay.
- [`hello-native`](examples/desktop/hello-native/) — ships **non-wheel** native
  binaries (a helper executable + a shared library) via
  `[tool.kivy.<platform>.native.binaries]`; builds and runs on macOS, Linux, and
  Windows (`greet.dll` loaded by name, `roll.exe` run by name).

**Mobile** ([`examples/mobile/`](examples/mobile/)) — iOS and Android, Kivy 3.0
where the platform requires it:

*iOS:*

- [`hello-world`](examples/mobile/hello-world/) — Kivy-free toolchain smoke test;
  no dependencies, no wheels (builds on iOS via the python.org `Python.xcframework`;
  the first example to bring up a new backend).
- [`hello-kivy`](examples/mobile/hello-kivy/) — minimal Kivy 3.0 UI.
- [`mobile-geometry`](examples/mobile/mobile-geometry/) — showcases the
  `kivy.mobile` runtime-geometry API (DPI, safe-area insets, keyboard height).
- [`svg-explorer`](examples/mobile/svg-explorer/) — interactive SVG viewer
  (multitouch pan/zoom/rotate).
- [`pyobjus-ball`](examples/mobile/pyobjus-ball/) — calls native iOS APIs
  (CoreMotion, UIScreen) from Python via the Objective-C runtime.
- [`pyobjus-deviceinfo`](examples/mobile/pyobjus-deviceinfo/) — reads native iOS
  device info (model, system version, battery) via pyobjus; a CPython 3.15
  pre-release example.
- [`keychain-spm`](examples/mobile/keychain-spm/) — declares a remote Swift Package
  (`KeychainAccess`), pins it with `kivyforge lock`, and calls it from Python
  through a local `@objc` shim package.

*Android:*

- [`hello-android`](examples/mobile/hello-android/) — the smallest kivyforge
  Android app (a single `Label`); the Kivy 2.3.1 / SDL2 on-device gate.
- [`hello-sdl3`](examples/mobile/hello-sdl3/) — the same app on **Kivy 3.0 /
  SDL3**; deliberately identical to `hello-android` apart from the SDL
  generation, and the SDL3 on-device gate.
- [`pyjnius-deviceinfo`](examples/mobile/pyjnius-deviceinfo/) — reads Android
  device info (`Build`, `BatteryManager`, display metrics) via pyjnius, no
  Java written.
- [`qr-maven`](examples/mobile/qr-maven/) — renders a QR code with Google's
  ZXing, resolved as a Gradle/Maven coordinate (channel 4) and driven from
  Python via a pyjnius `invoke0` round-trip.

## Configuring your app

Your app is described declaratively in `pyproject.toml`. Standard
[PEP 621](https://peps.python.org/pep-0621/) `[project]` metadata supplies the
name, version, and runtime `dependencies`; shared, platform-neutral settings live
under `[tool.kivy]`, and iOS-specific settings live under `[tool.kivy.ios]`
(other platforms will add their own `[tool.kivy.<platform>]` tables):

```toml
[project]
name = "hello-world"
version = "0.1.0"
requires-python = ">=3.15.0b2"
dependencies = []                       # PyPI/local deps resolved into the lockfile

[tool.kivy]
display_name = "Hello World"            # name shown under the icon
app_dir = "src"                         # folder containing your Python source
entry_point = "main"                    # module imported at launch (main.py)
orientation = ["portrait"]

[tool.kivy.ios]
bundle_id = "org.example.hello-world"   # reverse-DNS; UTI characters only (no underscores)
build = 1
deployment_target = "13.0"
# find_links = ["../../wheels/ios"]     # repo-relative wheel directory for lock
# exclude = ["docutils", "pygments"]    # drop transitive deps you don't use at runtime

[tool.kivy.ios.python]
version = "3.15.0b2"                     # python.org Python.xcframework version

[tool.kivy.ios.signing]
team_id = ""                            # Apple Developer Team ID (device / release builds)
identity = "Apple Development"
auto_signing = true
```

`kivyforge build` syncs your `app_dir` into the generated `<app>-ios/` tree on
every run, so make changes in your source folder (e.g. `src/`), never in the
generated project.

Kivy's wheel declares dependencies that are not all needed at runtime on iOS.
The `exclude` list trims them; the
[hello-kivy example](examples/mobile/hello-kivy/pyproject.toml) documents what each one
is for, so you can re-enable only the few that map to widgets you actually use
(e.g. `docutils` for `RSTDocument`, `pygments` for `CodeInput`, or `requests`
for `UrlRequest`).

## Commands

The verbs are platform-neutral; the descriptions and artifacts below reflect the
iOS target available today.

      kivyforge init       Seed [tool.kivy] / [tool.kivy.ios] into pyproject.toml
      kivyforge lock       Generate pylock.ios.toml from pyproject.toml
      kivyforge build      Download artifacts, generate the Xcode project, build
      kivyforge run        Build (unless --no-build), install, and launch the app
      kivyforge open       Open <app>-ios/<app>.xcodeproj in Xcode
      kivyforge status     Show app identity, Python version, lock sync, build state
      kivyforge clean      Remove generated artifacts in the project folder
      kivyforge upgrade    Re-fetch pinned Python.xcframework / xcframework artifacts
      kivyforge doctor     Run environment and project health checks

Run `kivyforge <command> -h` (or `kf <command> -h`) for the full set of
options on any verb. A few common ones:

- `kivyforge lock --check` — CI pre-flight; exits non-zero if the lock is stale.
- `kivyforge build --simulator | --device | --release` — pick the build flavor.
- `kivyforge run --list-devices` — list available simulators and devices.
- `kivyforge clean --cache` — also flush the artifact download cache.

Downloaded artifacts (`Python.xcframework` and other xcframeworks) are cached
under `~/Library/Caches/kivy-ios/artifacts/` and shared across projects.

## Typical workflow

A normal session is a one-time setup followed by a tight edit → run loop.
The generated project **links** your source directory (`app/` is a symlink to
`app_dir`), so editing Python source needs no rebuild — just relaunch. You only
re-run `kivyforge lock` when dependencies change, and `kivyforge build` when you
change app config (or need to regenerate the Xcode project).

```mermaid
flowchart TD
    A["kivyforge init<br/>seed pyproject.toml"] --> B["Edit pyproject.toml<br/>dependencies + app config"]
    B --> C["Write your app<br/>src/main.py"]
    C --> D["kivyforge lock<br/>→ pylock.ios.toml"]
    D --> E["kivyforge build<br/>fetch artifacts + generate .xcodeproj"]
    E --> F{"Launch it"}
    F -->|from the CLI| G["kivyforge run --simulator"]
    F -->|from Xcode| H["kivyforge open → ⌘R"]
    G --> I(["Iterate"])
    H --> I
    I -->|changed Python source| F
    I -->|changed app config| E
    I -->|changed dependencies| D
```

Supporting commands fit around this loop: `kivyforge status` shows whether your
lock and build are current, `kivyforge doctor` diagnoses environment problems,
`kivyforge upgrade` re-fetches the pinned runtime, and `kivyforge clean` resets
the generated project when you want a fresh build.

## Development

Clone the repository and install it into a virtual environment:

      git clone https://github.com/ElliotGarbus/kivyforge.git
      cd kivyforge/
      python3 -m venv .venv
      . .venv/bin/activate
      pip install -e ".[dev]"

Run the test suite and the linter:

      pytest
      ruff check .

## FAQ

For troubleshooting advice and other frequently asked questions, consult
the latest 
[kivyforge FAQ](https://github.com/ElliotGarbus/kivyforge/blob/master/FAQ.md).

## License

kivyforge is [MIT licensed](LICENSE), and builds on work actively developed by a
great community and supported by many projects managed by the 
[Kivy Organization](https://www.kivy.org/about.html).

## Support

Are you having trouble using kivyforge or any of its related projects in the Kivy
ecosystem?
Is there an error you don’t understand? Are you trying to figure out how to use 
it? We have volunteers who can help!

The best channels to contact us for support are listed in the latest 
[Contact Us](https://github.com/ElliotGarbus/kivyforge/blob/master/CONTACT.md) document.

## Contributing

kivyforge builds on the [Kivy](https://kivy.org) ecosystem - a large group of
products used by many thousands of developers for free, but it
is built entirely by the contributions of volunteers. We welcome (and rely on) 
users who want to give back to the community by contributing to the project.

Contributions can come in many forms. See the latest 
[Contribution Guidelines](https://github.com/ElliotGarbus/kivyforge/blob/master/CONTRIBUTING.md)
for how you can help us.

## Code of Conduct

In the interest of fostering an open and welcoming community, we as 
contributors and maintainers need to ensure participation in our project and 
our sister projects is a harassment-free and positive experience for everyone. 
It is vital that all interaction is conducted in a manner conveying respect, 
open-mindedness and gratitude.

Please consult the [latest Kivy Code of Conduct](https://github.com/kivy/kivy/blob/master/CODE_OF_CONDUCT.md).

## Contributors

This project exists thanks to 
[all the people who contribute](https://github.com/ElliotGarbus/kivyforge/graphs/contributors).
[[Become a contributor](CONTRIBUTING.md)].

<img src="https://contrib.nn.ci/api?repo=ElliotGarbus/kivyforge&pages=5&no_bot=true&radius=22&cols=18">

## Backers

Thank you to [all of our backers](https://opencollective.com/kivy)! 
🙏 [[Become a backer](https://opencollective.com/kivy#backer)]

<img src="https://opencollective.com/kivy/backers.svg?width=890&avatarHeight=44&button=false">

## Sponsors

Special thanks to 
[all of our sponsors, past and present](https://opencollective.com/kivy).
Support this project by 
[[becoming a sponsor](https://opencollective.com/kivy#sponsor)].

Here are our top current sponsors. Please click through to see their websites,
and support them as they support us. 

<!--- See https://github.com/orgs/kivy/discussions/15 for explanation of this code. -->
<a href="https://opencollective.com/kivy/sponsor/0/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/0/avatar.svg"></a>
<a href="https://opencollective.com/kivy/sponsor/1/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/1/avatar.svg"></a>
<a href="https://opencollective.com/kivy/sponsor/2/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/2/avatar.svg"></a>
<a href="https://opencollective.com/kivy/sponsor/3/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/3/avatar.svg"></a>

<a href="https://opencollective.com/kivy/sponsor/4/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/4/avatar.svg"></a>
<a href="https://opencollective.com/kivy/sponsor/5/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/5/avatar.svg"></a>
<a href="https://opencollective.com/kivy/sponsor/6/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/6/avatar.svg"></a>
<a href="https://opencollective.com/kivy/sponsor/7/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/7/avatar.svg"></a>

<a href="https://opencollective.com/kivy/sponsor/8/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/8/avatar.svg"></a>
<a href="https://opencollective.com/kivy/sponsor/9/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/9/avatar.svg"></a>
<a href="https://opencollective.com/kivy/sponsor/10/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/10/avatar.svg"></a>
<a href="https://opencollective.com/kivy/sponsor/11/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/11/avatar.svg"></a>

<a href="https://opencollective.com/kivy/sponsor/12/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/12/avatar.svg"></a>
<a href="https://opencollective.com/kivy/sponsor/13/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/13/avatar.svg"></a>
<a href="https://opencollective.com/kivy/sponsor/14/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/14/avatar.svg"></a>
<a href="https://opencollective.com/kivy/sponsor/15/website" target="_blank"><img src="https://opencollective.com/kivy/sponsor/15/avatar.svg"></a>

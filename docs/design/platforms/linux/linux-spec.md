# Linux — Design Spec

The Linux backend produces a self-contained, distributable application. The
**primary artifact is an [AppImage](https://appimage.org/)** (`package -f
appimage`, the default): a single executable file the user can `chmod +x` and
run on any mainstream distribution. The **run-from-folder AppDir**
(`package -f folder`) is the required substrate the AppImage wraps — it is also
the no-FUSE / CI / container-safe path and the debugging substrate. Like macOS
it bundles a relocatable CPython, the app's resolved wheels, and the user's
source; unlike macOS there is no code-signing analog on Linux.

> **Status: implemented.** The Linux backend ships: `[tool.kivy.linux]`
> parsing, `pylock.linux.toml` resolution (python-build-standalone
> `x86_64-unknown-linux-gnu` runtime + manylinux-tagged wheels), the AppDir
> generator (`AppRun` shell launcher, generated `.desktop` + hicolor icons),
> `build` / `run` / `package -f appimage|folder`, and Linux `doctor` checks.
> Developed and verified on WSL2 Ubuntu (x86_64). A couple of details differ
> from the original plan and are flagged inline (the resolver requests the full
> manylinux tag ladder in one pip invocation rather than relying on pip's
> `--platform` expansion, and the effective glibc floor is derived on demand
> rather than stored as a distinct lock field).

## Scope

In scope for the Linux backend:

- `[tool.kivy.linux]` overlay parsing + a `LinuxConfig` dataclass.
- `pylock.linux.toml` resolution (Linux Python runtime + manylinux-tagged wheels).
- An AppDir bundle generator (`AppRun` launcher, bundled Python + wheels + app
  source, generated `.desktop` entry + hicolor icons).
- `build` / `run` (launch `./AppRun`) and `package -f appimage` (default) /
  `-f folder`.
- Linux `doctor` checks.

Out of scope for the Linux backend (deferred / external):

- **`.deb` / `.rpm` native packages** — external; recommend
  [`fpm`](https://github.com/jordansissel/fpm). Revisited only on a concrete
  user-demand signal ("package for my distro's repo").
- **Flatpak** — external; recommend `flatpak-builder`. Revisited on a
  Flathub / sandboxing / immutable-distro demand signal.
- **Opt-in first-run self-integration** (a prompt to copy the `.desktop`/icon
  into `~/.local/share/applications/` using `$APPIMAGE`/`$APPDIR`) — designed
  here as a fast-follow, not built this phase (see
  ["Desktop integration"](#desktop-integration)).
- **aarch64** — the config stays list-shaped so it is purely additive later
  (PBS ships `aarch64-unknown-linux-gnu`; Kivy has manylinux aarch64 wheels),
  but there is no ARM verification host this phase.
- **musl / Alpine** — static PBS musl builds can't `dlopen()` extensions, and
  Kivy publishes no musllinux wheels. Out of scope.
- **AppImage update metadata / zsync**, and **signing** — no Linux signing
  analog is in scope.

## `[tool.kivy.linux]` overlay

An additive overlay on top of the shared `[project]` + `[tool.kivy]` tables (see
[common pyproject spec](../../common/01-pyproject-kivy-spec.md)). Only fields
that differ from the cross-platform defaults or are Linux-specific appear here.

```toml
[tool.kivy.linux]
schema_version = 1
app_id = "org.example.myapp"     # reverse-DNS; .desktop basename, Icon=, StartupWMClass
glibc_floor = "2.17"             # optional; drives the manylinux resolve tag (see below)
archs = ["x86_64"]               # only x86_64 allowed this phase

[tool.kivy.linux.python]
version = "3.15.0"               # bundled Python runtime version

[tool.kivy.linux.icons]
source = "assets/icon.png"       # 1024×1024 PNG → root icon + hicolor sizes

[tool.kivy.linux.desktop]
categories = ["Utility"]         # freedesktop main categories for the .desktop entry

# extra_index_urls / find_links / exclude behave as on iOS/macOS.
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `schema_version` | integer | yes | — | Linux overlay schema version; independent of other platforms'. |
| `app_id` | string | yes | — | Reverse-DNS identifier. Names the `.desktop` file (`<app_id>.desktop`), the `Icon=` key, and the window `StartupWMClass` / Wayland app-id. Only letters, digits, hyphen, period allowed (a valid `.desktop` basename); an invalid `app_id` is a hard `ConfigError` (mirrors the macOS `bundle_id` fail-fast). |
| `glibc_floor` | string | no | *(runtime floor, 2.17)* | The Linux analog of macOS `minimum_system_version`. `None` means the runtime's own glibc floor (2.17) applies. Setting it *higher* (e.g. `"2.28"`) admits newer-manylinux-only wheels at the cost of raising the artifact's host floor. A value *below* the runtime floor is the same config-time error macOS raises via `floor_error`. |
| `archs` | list of string | no | `["x86_64"]` | Target architecture set. Only `x86_64` is allowed this phase. The field stays list-shaped so `aarch64` is purely additive later. Unlike macOS there is **no fat binary** — each arch would be a separate AppImage. |
| `extra_index_urls` | list of string | no | `[]` | Supplemental wheel indexes (manylinux tags), same semantics as iOS/macOS. |
| `find_links` | list of string | no | `[]` | Repo-relative vendored-wheel directories for `lock`. |
| `exclude` | list of string | no | `[]` | Prune unused transitive deps from the resolved graph. |

Icons: `[tool.kivy.linux.icons].source` (1024×1024 PNG) is resized into the
freedesktop **hicolor** size set plus the root `<app_id>.png` AppImage requires.
Resizing uses [Pillow](https://python-pillow.org/) (the `kivyforge[linux]`
extra); it is pure-manylinux and ubiquitous. Splash screens are not a desktop
concept and have no subtable.

> **Implementation note — default icon when `source` is unset.** `appimagetool`
> refuses to build unless the icon named by the `.desktop` `Icon=` key exists at
> the AppDir root, so an icon is *not* optional at package time even when the
> project configures none. When `source` is unset, kivyforge therefore writes a
> plain generated solid-colour `<app_id>.png` (root + a 256px hicolor entry)
> using **only the standard library** (`zlib`), so Pillow stays an opt-in extra
> needed only for resizing a real source image.

> **`.DirIcon`.** kivyforge also writes `.DirIcon` (a copy of the root
> `<app_id>.png`) at the AppDir root. `appimagetool` derives `.DirIcon` from the
> `.desktop` `Icon=` key at package time, but the **`-f folder` artifact** is
> consumed directly by file managers / AppImage tooling that read `.DirIcon` for
> the directory icon, so the backend emits it for a consistent icon across both
> artifacts. It is a plain copy (not a symlink) to keep the folder artifact
> self-contained and relocatable.

Desktop entry: `[tool.kivy.linux.desktop].categories` supplies the freedesktop
main categories written into the `.desktop` `Categories=` key (default
`Utility`).

Shared `[tool.kivy]` keys consumed: `display_name` (→ `.desktop` `Name=`),
`app_dir`, `entry_point`. `orientation` is not meaningful on desktop and is
ignored.

## Python runtime acquisition

Linux uses the same relocatable-CPython strategy as macOS — the shared
[`RuntimeProvider` abstraction](../../common/07-runtime-provider-pattern.md)
backed by [`python-build-standalone`](https://github.com/astral-sh/python-build-standalone)
(PBS) — with the **`x86_64-unknown-linux-gnu`** `install_only` build. PBS's
GitHub metadata fetcher is triple-agnostic, so this is a one-line
specialization of the generic `PbsProvider` (baseline microarchitecture, not
the `_v2`/`_v3` variants).

The linux-gnu `install_only` archive is the same unix-prefix layout as the
darwin ones (`bin/`, `lib/python3.x/`) and uses `$ORIGIN`-relative rpaths, so it
is relocatable as-shipped — **no patchelf pass**, and the shared normalization
applies unchanged. There is **no `lipo` merge**: Linux ships one arch per
AppImage.

This inherits a **glibc ≥ 2.17 floor** (manylinux2014-class) from PBS's
build host, with no old-distro build host of our own. **musl is out of scope.**

### No compiled build step

The AppDir entry point (`AppRun`) is a POSIX shell script (see
["Launcher"](#launcher)), so kivyforge builds **no native code at package
time** — no manylinux/low-glibc build container is needed. (If a compiled shim
ever became necessary it would have to be built in a manylinux2014-class
container so it couldn't raise the bundle's glibc floor above the runtime's.
Recorded here as a conditional, not a task.)

## `pylock.linux.toml`

Same pattern as macOS (see [common lockfile concept](../../common/03-lockfile-concept.md)):
PEP 751 `[[packages]]` for wheels + a single `[tool.kivyforge]` extension table
holding the runtime pin and provenance. The platform is identified by the
filename. Linux wheels use manylinux platform tags; `kivyforge lock` resolves
wheels honoring the glibc floor, records the arch set, and pins the matching
per-arch runtime artifact.

### manylinux resolution — the tag ladder

> **Implementation note — spike finding.** The original plan assumed pip
> expands the manylinux hierarchy downward from a single requested
> `--platform manylinux_2_17_x86_64` (matching `manylinux2014`, `manylinux2010`,
> `manylinux1`, and lower `manylinux_2_y`). **This is not how pip 26.x
> behaves.** With an explicit `--platform`, pip matches only that exact tag
> (plus its legacy alias — `manylinux2014` ⇄ `manylinux_2_17`, etc.) and does
> **not** accept wheels built for an older glibc. Empirically, requesting
> `--platform manylinux_2_39_x86_64` found no match for a package whose newest
> wheel was tagged `manylinux_2_28` — no downward expansion.

The resolver therefore requests the **full manylinux ladder at or below the
floor in one pip invocation**. For a floor of glibc 2.17 that is the perennial
tags `manylinux_2_5_x86_64` … `manylinux_2_17_x86_64` plus the legacy aliases
(`manylinux1`, `manylinux2010`, `manylinux2014`) that map at or below the floor.
Passing several `--platform` flags to a single `pip install --dry-run --report`
run resolves **one consistent version set** while accepting a wheel that matches
any requested tag — so a package that ships only a `manylinux1` wheel and one
that ships `manylinux2014` are both locked at the newest version whose wheel
runs on the floor. A wheel that needs a *newer* glibc than the floor
(`manylinux_2_28` when the floor is 2.17) is correctly excluded; if that leaves
a compiled dependency uncovered, `lock` fails fast and names the package (raise
`glibc_floor`, or supply `extra_index_urls`/`find_links`).

The `Variant` seam carries the primary tag plus these extra request tags; the
generic resolver passes them all to pip. macOS is unaffected (its variants
carry a single tag).

### Coverage rule

A wheel's (possibly compound, dot-joined) platform tag covers `x86_64` when any
of its sub-tags is a manylinux tag (legacy `manylinux1`/`manylinux2010`/
`manylinux2014` or perennial `manylinux_2_y`) for `x86_64`, or the plain
`linux_x86_64` tag. `musllinux_*` never covers. `py3-none-any` is pure-Python
and always complete (handled by the shared core).

Plain `linux_x86_64` (non-manylinux) wheels are **accepted only from
`find_links`** with a warning that the tag makes no glibc promise — they are the
user's own vendored wheels and portability is their call.

### Effective glibc floor

`[tool.kivyforge.python_runtime].floor` records the runtime's own glibc floor
(2.17). The artifact's **effective** host requirement is
`max(runtime floor, highest locked wheel manylinux level)` — it is **derived on
demand** from the locked wheels (by `doctor` and the docs) rather than stored as
a separate field, keeping the shared lock model platform-agnostic.

> **The recorded runtime floor (2.17) is a pinned assumption, not a derived
> value.** PBS's `install_only` archives expose no structured glibc metadata, and
> `kivyforge lock` records only the runtime's URL + SHA-256 (it does not download
> the archive), so there is nothing to inspect at lock time. The floor is
> therefore a constant tracked in kivyforge (`DEFAULT_GLIBC_FLOOR`) and versioned
> with releases: **if PBS raises its linux-gnu build baseline above glibc 2.17,
> that constant must be bumped in the same release**, or the lock/doctor would
> advertise compatibility the binary no longer meets. A deeper safeguard —
> ELF-inspecting the staged `bin/python3` version-needs at build time to *prove*
> the floor — is a deferred fast-follow, recorded here rather than built.

## AppDir / AppImage layout

**The folder artifact *is* an AppDir** — one tree serves `-f folder`,
`-f appimage`, and the dev loop:

```
build/linux/MyApp.AppDir/
├── AppRun                          ← POSIX sh launcher (generated)
├── <app_id>.desktop                ← generated from [project] + [tool.kivy.linux]
├── <app_id>.png                    ← root icon (appimagetool requirement)
├── .DirIcon                        ← copy of the root icon (folder-artifact icon)
└── usr/
    ├── app/                        ← user code (from [tool.kivy].app_dir)
    ├── lib/                        ← installed wheels (site-packages)
    ├── python/                     ← PBS runtime (bin/, lib/python3.x/)
    └── share/icons/hicolor/<N>x<N>/apps/<app_id>.png
```

### Launcher

`AppRun` is a POSIX shell script — AppImage does not require an ELF `AppRun`,
and Linux has no analog of the Finder/LaunchServices problem that forced the
compiled Mach-O stub on macOS. It resolves its own directory via
`readlink -f`, then exports:

- `PYTHONHOME=$HERE/usr/python`
- `PYTHONPATH=$HERE/usr/app:$HERE/usr/lib`
- `PYTHONNOUSERSITE=1` (isolate from `~/.local` / user site config)
- `SDL_VIDEO_X11_WMCLASS=<app_id>` and its Wayland analog
  (`SDL_VIDEO_WAYLAND_WMCLASS`) so the window's WM_CLASS matches the
  `.desktop`'s `StartupWMClass` and the app groups under its own icon

and `exec`s `"$HERE/usr/python/bin/python3" "$HERE/usr/app/<entry_point>.py"
"$@"`. A dotted `entry_point` (e.g. `pkg.start`, per the shared
[`app_dir`/`entry_point` contract](../../common/01-pyproject-kivy-spec.md#app_dir--entry_point-interaction))
maps to the nested source path `usr/app/pkg/start.py`. There is **no
`LD_LIBRARY_PATH`**: PBS rpaths are `$ORIGIN`-relative and
manylinux wheels vendor their native libs (auditwheel), so the environment stays
clean for the host's own libGL.

### Desktop integration

The `.desktop` entry is **generated** from `pyproject.toml` at package time (the
Linux analog of `Info.plist`/`.icns`):

- `Name` ← `display_name`
- `Exec=AppRun %f`
- `Icon=<app_id>`
- `Categories` ← `[tool.kivy.linux.desktop].categories` (default `Utility;`)
- `StartupWMClass=<app_id>`, `Terminal=false`, `Type=Application`

It must pass `desktop-file-validate` (also a `doctor` check).

**Opt-in first-run self-integration** (a prompt to copy the `.desktop`/icon into
`~/.local/share/applications/` after the user agrees, using `$APPIMAGE`/
`$APPDIR`) is a designed **fast-follow**, not built this phase.

## `build` / `run` / `package`

- **`build`** — resolve (if needed), acquire the runtime and wheels, and
  assemble the AppDir tree.
- **`run`** — build (unless `--no-build`), then execute `./AppRun` directly in
  the foreground so the developer sees stdout/stderr + tracebacks. The fast dev
  loop needs no AppImage and no FUSE.
- **`package -f appimage`** (default) — wrap the AppDir into a single
  `.AppImage` executable. **`package -f folder`** emits the AppDir directory
  itself (the substrate / fallback).

### AppImage tooling

`package -f appimage` acquires two pinned build tools through the existing
`kivyforge/artifacts` download / cache / SHA-256-verify machinery:

- a pinned **`appimagetool`** static build, and
- a pinned **type2 static-FUSE runtime** file (`--runtime-file`).

Embedding a static-FUSE runtime means users aren't hit by the
libfuse2-vs-libfuse3 packaging mess on current distros (Ubuntu 24.04's
`libfuse2t64` rename, etc.). These pins live as **constants in kivyforge**,
versioned with kivyforge releases — they are build tools, not app dependencies,
so they do not belong in the app's lockfile.

Invocation runs with `APPIMAGE_EXTRACT_AND_RUN=1` so the *build host* needs no
FUSE either (WSL2 / containers / CI just work):

```
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 appimagetool \
    --runtime-file <type2-runtime> MyApp.AppDir <output>
```

Output: `dist/linux/<Name>-<version>-x86_64.AppImage`, `chmod +x`.
Update-embedding / zsync is out of scope.

### FUSE / host contract (user-facing)

The embedded static-FUSE type2 runtime means the *shipped* AppImage needs no
host **`libfuse2` package** — that removes the libfuse2-vs-libfuse3 packaging
pain, **not** the kernel's FUSE support. To self-mount, the runtime still needs
the kernel **`/dev/fuse`** device available at launch; a locked-down environment
(hardened container, some CI, restrictive sandbox) that lacks `/dev/fuse` will
fail to mount. `--appimage-extract-and-run` (or `APPIMAGE_EXTRACT_AND_RUN=1`) is
the universal, no-kernel-FUSE fallback and is surfaced in the `package` output
and docs. So precisely: no `libfuse2` *package* is ever required; kernel FUSE is
required only for the default self-mount path, and extract-and-run needs neither.

`libGL`/`libEGL` and an X11 or Wayland session come **from the host** — nobody
vendors these. The docs and `doctor` state this as an explicit requirement so it
never surfaces as an opaque runtime crash. The artifact's host contract is:
glibc ≥ the effective floor, `libGL`/`libEGL` present, and an X11/Wayland
session.

## No code signing

Linux has no analog of the macOS ad-hoc-signing floor (nothing refuses to run an
unsigned ELF), so the backend does no signing. Distribution trust on Linux is a
distro-repository / GPG-on-the-package concern handled by the external native
packaging tools, out of kivyforge's scope.

## `doctor` checks (Linux)

| Check | Scope | What it validates |
|-------|-------|-------------------|
| Host is Linux (glibc) | environment | Linux host; WARN on a musl host (the PBS gnu runtime won't run there). |
| GL libraries present | environment | `libGL.so.1` / `libEGL.so.1` findable (`ldconfig -p`); WARN with the host-contract message + distro package hints. |
| Display session | environment | `DISPLAY` / `WAYLAND_DISPLAY` set; WARN if headless with the `xvfb-run` hint. |
| kivyforge version | environment | Self-version; warn if newer on PyPI (best-effort). |
| App source directory | project | `[tool.kivy].app_dir` resolves to an existing directory. |
| glibc floor vs. runtime | project | `[tool.kivy.linux].glibc_floor` ≥ the runtime's 2.17 floor; reports the artifact's effective floor derived from the lock. |
| Architecture coverage | project | Every compiled dep resolves a manylinux `x86_64` wheel honoring the floor; FAIL names the package. |
| App icon | project | If `[tool.kivy.linux.icons].source` is set, FAIL unless a valid 1024×1024 PNG. SKIP if unset. |
| Desktop entry valid | project | The generated `.desktop` passes `desktop-file-validate`. SKIP if the tool isn't installed (optional); FAIL on actual validation errors. |
| find_links directories | project | If set, each entry is an existing directory containing `.whl` files. |
| Required hosts reachable | project | The lockfile hosts plus the pinned appimagetool / type2-runtime asset hosts. |

`doctor` reports each check as PASS / WARN / FAIL with a remediation hint; exit
code is non-zero only on FAIL.

Config-time (`kivyforge lock`/`build`/`package`, not `doctor`): an invalid
`app_id` (not a valid `.desktop` basename) is a hard `ConfigError`, mirroring
the macOS `bundle_id` fail-fast.

## Host requirements

- A Linux host with glibc (the gnu PBS runtime; musl hosts are unsupported).
- For `run` / interactive testing: `libGL`/`libEGL` and an X11 or Wayland
  session (on WSL2 this is WSLg; `LIBGL_ALWAYS_SOFTWARE=1` is the software-GL
  fallback and `xvfb-run` the headless path).
- No `libfuse2` **package** is required to *build* an AppImage
  (`APPIMAGE_EXTRACT_AND_RUN=1`) or to *run* the shipped one (the embedded
  static-FUSE runtime is statically linked). Kernel FUSE (`/dev/fuse`) is still
  needed for the shipped AppImage's default self-mount; where it is unavailable,
  run with `--appimage-extract-and-run` (or `APPIMAGE_EXTRACT_AND_RUN=1`), which
  needs no FUSE at all.
- `desktop-file-validate` (from `desktop-file-utils`) is optional — used by the
  `doctor` check when present.

## Module layout

Everything Linux-specific lives under the self-contained `kivyforge/platforms/linux/`
package (platform-first consolidation):

- `kivyforge/platforms/linux/__init__.py` — the `LinuxPlatform` backend
  (`host_system = "Linux"`, `package_formats = ("appimage", "folder")`) with its
  `build`/`run`/`package`/`doctor` verb methods (each lazily imports the module
  below).
- `kivyforge/platforms/linux/` (bundler modules) — the AppDir bundler + AppImage
  packaging (`bundle.py`, `runtime_stage.py`, `wheels_stage.py`, `launcher.py`,
  `desktop.py`, `icons.py`, `appimage.py`).
- `kivyforge/platforms/linux/lock/` — the lock profile + runtime provider
  (`profile.py`, `runtime.py`), built on the shared `kivyforge/lock/` wheel+runtime
  engine.
- `kivyforge/platforms/linux/cli.py` — Linux implementation of the shared
  `build`/`run`/`package` verbs (dispatched from `LinuxPlatform`).
- `kivyforge/platforms/linux/doctor.py` — Linux `doctor` checks + `linux_doctor`
  orchestration, reusing the neutral checks in `kivyforge/doctor/checks_common.py`.

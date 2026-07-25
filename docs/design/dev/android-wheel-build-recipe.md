# Android wheel-build recipe (first-party Kivy + SDL2 line)

> **Status: complete and validated on-device.** The official SDL2 line and the
> first-party Kivy 2.3.1 wheels are built, verified (16 KB alignment, flat
> `.libs/`, sonames intact) and proven to run: the contract smoke test passes
> on both locked ABIs, and the app renders on a Pixel 8a (Android 16, arm64).
> Companion to
> [android-loadmodel-findings](android-loadmodel-findings.md) and the
> [pyjnius spike findings](pyjnius-android-wheel-spike-findings.md).

kivyforge consumes **prebuilt Android wheels**; it runs no from-source pipeline
(android/03). This document records how the *vendored* wheels are produced
out-of-band, so they are reproducible and auditable rather than folklore.

## Host prerequisites

- Linux or macOS (cibuildwheel's Android support is POSIX-only; WSL2 counts).
- Android SDK + **NDK r27.3.13750724**, JDK 17, `ANDROID_HOME` exported.
- `cibuildwheel` (4.x, with `--platform android`), CMake + Ninja (the SDK's
  `cmake;3.22.1` package provides both).
- **`/system/bin/sh` must exist on the build host:**

  ```bash
  sudo mkdir -p /system/bin && sudo ln -s /bin/sh /system/bin/sh
  ```

  CPython chooses the shell for `subprocess(..., shell=True)` via
  `hasattr(sys, "getandroidapilevel")`. cibuildwheel's cross-build interpreter
  **is** the Android CPython, so any `setup.py` that shells out (Kivy's
  `pkgconfig()` helper does, at the very first build hook) looks for Android's
  shell path on the Linux host and dies with
  `FileNotFoundError: '/system/bin/sh'`. This affects **any** package that
  shells out during an Android wheel build, not just Kivy. Reversible with
  `sudo rm -rf /system`.

## Step 1 — the official SDL2 line (DONE, verified)

SDL2 does **not** publish an Android binary package (only SDL3 does:
`SDL3-devel-<ver>-android.zip`), so the SDL2 line is built from libsdl.org
release **source** tarballs.

| Component | Version | Source SHA-256 |
|---|---|---|
| SDL2 | 2.32.10 | `5f5993c530f084535c65a6879e9b26ad441169b3e25d789d83287040a9ca5165` |
| SDL2_image | 2.8.12 | `393f5efb50536ec13ca4f4affb69cc9966d3c3f969e6c5e701faddf9f9785381` |
| SDL2_mixer | 2.8.2 | `938dff531d00ace2296557a6599abe6f34599e2f34f0a4a08a397e2ccac8b8f7` |
| SDL2_ttf | 2.24.0 | `0b2bf1e7b6568adbdbc9bb924643f79d9dedafe061fa1ed687d1d9ac4e453bfd` |

Built per ABI (`arm64-v8a`, `x86_64`) with the NDK CMake toolchain,
`ANDROID_PLATFORM=android-24`, and **`-Wl,-z,max-page-size=16384`** on every
linker flag variable (NDK r27 does **not** default to 16 KB alignment; the
explicit flag is the wheel-build policy from the pyjnius spike, Step 7).

Two gotchas worth recording:

- **The NDK toolchain confines `find_package` to its sysroot**, so the
  satellites cannot see an out-of-sysroot SDL2 prefix. Pass
  `CMAKE_FIND_ROOT_PATH=<prefix>;<sysroot>` plus
  `CMAKE_FIND_ROOT_PATH_MODE_{INCLUDE,LIBRARY,PACKAGE}=BOTH`, and hand the
  satellites `SDL2_LIBRARY`/`SDL2_INCLUDE_DIR` explicitly.
- **The release tarballs ship an empty `external/`** for SDL2_image and
  SDL2_mixer (their vendored deps are git submodules). Build with the
  **built-in** decoders instead — `SDL2IMAGE_BACKEND_STB=ON` (PNG/JPG),
  `SDL2MIXER_MP3_DRMP3` / `FLAC_DRFLAC` / `VORBIS=STB` — and disable the
  codecs that need external libraries. SDL2_ttf *does* bundle freetype.

**Result — all 8 libraries verified at `p_align = 0x4000` (16 KB):**

```
arm64-v8a / x86_64:  libSDL2.so  libSDL2_image.so  libSDL2_mixer.so  libSDL2_ttf.so
```

The install also emits `lib/pkgconfig/{sdl2,SDL2_image,SDL2_mixer,SDL2_ttf}.pc`,
which is exactly how Kivy discovers SDL2 (below).

### Bonus: the official Java glue

The SDL2 source tarball carries the canonical
`android-project/app/src/main/java/org/libsdl/app/*.java` (9 files). These
should **replace** the p4a-derived glue currently vendored in
`platforms/android/bootstrap/templates/sdl2/`, removing the last
python-for-android dependency from the kivyforge bootstrap. The glue revision
must match the shipped `libSDL2.so` — building both from the same tarball
guarantees that by construction.

## Step 2 — Kivy 2.3.1 (blocked on host prep, then re-run)

Official sdist from PyPI, hash-verified against the published digest:

| Package | Version | sdist SHA-256 |
|---|---|---|
| Kivy | 2.3.1 | `0833949e3502cdb4abcf9c1da4384674045ad7d85644313aa1ee7573f3b4f9d9` |

Kivy 2.3.1's Android build contract, read from its own `setup.py`:

- `KIVY_CROSS_PLATFORM=android` → `platform = 'android'` (setup.py:182).
- `USE_SDL2=1` is **required**: SDL2 is deliberately *not* auto-detected on
  Android (`can_autodetect_sdl2` excludes it, setup.py:523).
- SDL2 is then discovered via **pkg-config** (`sdl2 SDL2_ttf SDL2_image
  SDL2_mixer`). Pin **`PKG_CONFIG_LIBDIR`** (not just `PKG_CONFIG_PATH`) at the
  per-ABI cross prefix so a host SDL2 can never leak into the cross build.
- The sdist ships 45 `.pyx` against 9 `.c`, so **Cython is required** at build
  time (`cython>=0.29.1,<=3.0.11` per its `[build-system]`).

Per-ABI invocation (`PKG_CONFIG_LIBDIR` differs per ABI, so run cibuildwheel
once per ABI with `--only`):

```
CIBW_BUILD_FRONTEND=build          # Android does not support the pip frontend
CIBW_ENVIRONMENT_ANDROID="KIVY_CROSS_PLATFORM=android USE_SDL2=1 \
  PKG_CONFIG_LIBDIR=<prefix>/<abi>/lib/pkgconfig \
  LDFLAGS='-Wl,-z,max-page-size=16384 -L<prefix>/<abi>/lib' \
  CFLAGS='-I<prefix>/<abi>/include -I<prefix>/<abi>/include/SDL2' \
  ANDROID_API_LEVEL=24"
cibuildwheel --only cp314-android_<abi> --output-dir <out> <kivy-src>
```

### Result (verified)

| Wheel | SHA-256 |
|---|---|
| `Kivy-2.3.1-cp314-cp314-android_24_arm64_v8a.whl` | `685323b4b64ea83078145e86a644158db10ba9ce62de758c3d78148addbef7f1` |
| `Kivy-2.3.1-cp314-cp314-android_24_x86_64.whl` | `6ab89ca283393864b9a2e710e8c2400800e7160d34528280d5cf2406ce9357c2` |

Both: **42 `.so`, all at `p_align = 0x4000`**, flat top-level `.libs/` holding
the four official SDL2 libraries with **sonames unchanged**, and Kivy's
extensions carrying plain `DT_NEEDED` on `libSDL2.so`.

Two non-obvious build settings were required:

- **`KIVY_SDL2_PATH`, not pkg-config.** cibuildwheel *overrides*
  `PKG_CONFIG_LIBDIR` with its own Android-Python prefix (and routes through a
  relocating `pkgconf-pypi` wrapper), so Kivy's pkg-config probe can never see
  an externally built SDL2 — it reports `use_sdl2 = 0` and then fails with
  `'SDL.h' file not found`. Kivy's documented manual path
  (`determine_sdl2()`, setup.py:756) takes a pathsep list used for **both**
  `include_dirs` and `library_dirs`:
  `KIVY_SDL2_PATH=<prefix>/include/SDL2:<prefix>/lib`.
- **auditwheel repair must be DISABLED** (`CIBW_REPAIR_WHEEL_COMMAND_ANDROID=""`).
  auditwheel grafts dependencies into `<pkg>.libs/` and **renames them with a
  hash suffix** (`libSDL2-1664d2a2.so`). Android's
  `System.loadLibrary("SDL2")` resolves the *exact* filename `libSDL2.so`, so a
  repaired wheel builds and passes every alignment check yet throws
  `UnsatisfiedLinkError` at app start. This is why android/03 mandates a flat
  `.libs/` with unchanged sonames — a rule that is load-bearing, not stylistic.
  The SDL family is grafted in afterwards by the recipe.

Also confirmed: **cibuildwheel's Android target already passes
`-Wl,-z,max-page-size=16384`** by default, so extensions come out 16 KB-aligned
without forcing it (this is the "CPython's implicit LDFLAGS" the pyjnius spike
observed). Passing `LDFLAGS`/`CFLAGS` via `CIBW_ENVIRONMENT_ANDROID` **replaces**
rather than augments cibuildwheel's own — don't rely on it for include/lib paths.

## RESOLVED — the lock was host-dependent (pip marker evaluation)

> **Discovered by this wheel.** The earlier interim wheel carried hand-written
> minimal metadata (`Requires-Dist: filetype`) and masked it.

Real Kivy metadata declares Windows-only dependencies with markers:

```
Requires-Dist: kivy-deps.angle~=0.4.0; sys_platform == "win32"
Requires-Dist: kivy-deps.sdl2~=0.8.0;  sys_platform == "win32"
Requires-Dist: pypiwin32;              sys_platform == "win32"
```

**pip evaluates environment markers against the running interpreter, not the
`--platform` target.** So on a **Windows** host `sys_platform == "win32"` is
true and `kivyforge lock -p android` fails:

```
ERROR: Could not find a version that satisfies the requirement
       kivy-deps.angle~=0.4.0; sys_platform == "win32" (from kivy)
```

The identical resolve **succeeded on Linux/macOS**. This contradicted android/06's
promise that the Android backend builds from Windows, macOS *or* Linux, and it
meant a lock's contents could differ by host — breaking the host-independence
the resolver docstring claims.

`[tool.kivy.android].exclude` does **not** help: it prunes the *resolved* graph,
while this failed during resolution.

### The fix that shipped

The follow-up originally sketched here was to resolve with `--no-deps` and walk
the dependency graph inside kivyforge. That was rejected: it would have meant
reimplementing pip's resolution — backtracking, conflict reporting and PEP 738
tag expansion — to fix one wrong input.

Instead kivyforge corrects **the input**. `lock/_pip_shim.py` replaces
`packaging.markers.default_environment` — the single function every
`Marker.evaluate()` consults — with the target environment from
`lock/markers.py`, then hands off to pip untouched. pip still performs the
entire resolution; it simply now answers "what platform am I resolving for?"
with Android:

```python
sys_platform     = "android"     # CPython 3.13+ / PEP 738
platform_system  = "Android"
os_name          = "posix"
platform_machine = "aarch64" | "x86_64" | "armv7l" | "i686"   # per ABI
```

`platform_machine` is per-ABI, so a machine-gated dependency resolves correctly
for each slice. The shim **fails loudly** if the pip internal it depends on is
missing, rather than falling back to host markers — a silent fallback would
reintroduce precisely this bug.

Two related host-dependencies were fixed alongside it:

- **Recorded dependency edges** were raw `Requires-Dist` names, so the lock
  claimed Kivy depended on `pytest`, `sphinx` and `kivy-deps.angle`, and `idna`
  on `ruff`/`mypy`. `android_dep_names()` now evaluates each marker against the
  same environment (with `extra` empty, dropping extra-gated edges).
- **Line endings.** The lock writer inherited the host's default, so a re-lock
  on the other OS rewrote all 124 lines. It now always writes LF.

**Verified:** the same `kivyforge lock -p android` run on Windows and on Linux
now produces byte-identical output apart from the `generated_at` timestamp.
`[tool.kivy.android].exclude` remains a post-resolution prune, unchanged.

## Step 3 — post-build verification (mandatory)

1. **16 KB alignment across the whole wheel** — every `.so`, both Kivy's own
   extensions *and* the grafted SDL family, must report `p_align = 0x4000`.
   `kivyforge doctor -p android` runs exactly this check
   (`platforms/android/elf.py`); it is what caught the interim wheel.
2. **Flat `.libs/`** — kivyforge stages a wheel's native payload from a *flat*
   top-level `.libs/` (android/03). Note `auditwheel`'s own convention is
   `<pkg>.libs/`; if the repair step produces that, the wheel must be
   normalized (or the stager widened) — decide deliberately, do not assume.
3. **Wheel tag** — `android_24_<abi>`; the tag API level is a floor and must be
   `<= min_sdk`.

## Open items

- Kivy 2.3.1 wheel: blocked only on the `/system/bin/sh` host prep above.
- **SDL3 / Kivy 3.0**: SDL3 *does* ship `SDL3-devel-<ver>-android.zip` with
  prebuilt per-ABI binaries + headers, which makes the `sdl = 3` path
  materially cheaper than the SDL2 one — no source build required, and the
  matching SDL3 Java glue ships with it.
- cp315 wheels once CPython 3.15 is GA and `android_*` wheels exist.

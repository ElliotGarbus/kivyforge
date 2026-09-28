# Findings — 32-bit Android (`armeabi-v7a`) support

> **Status:** investigation only, 2026-09-27. No code changed. kivyforge stays
> 64-bit only for now; this records what supporting 32-bit would take, what
> upstream offers today, and what would change the answer.
>
> **Prompted by** a request from kengoon on the Kivy Discord: enough of his
> users in Nigeria are on 32-bit devices that he wants to support them.

## Summary

- **Near term, the answer is Buildozer / python-for-android.** It already
  builds CPython 3.14 for `armeabi-v7a` and packages 32- and 64-bit into one
  App Bundle. kivyforge is not needed for that user today.
- **The runtime is the root blocker, and cibuildwheel is a symptom of it.**
  No one publishes a 32-bit CPython 3.12+ for Android. cibuildwheel's Android
  backend only downloads prebuilt Python tarballs, and has no 32-bit one to
  download.
- **Upstream may fix the root.** On 2026-09-27 the Chaquopy maintainer (Malcolm
  Smith, who also maintains CPython's Android support and wrote cibuildwheel's
  Android backend) opened
  [chaquopy#1476](https://github.com/chaquo/chaquopy/issues/1476), considering
  reintroducing `armeabi-v7a` for Python 3.12+ and asking for usage data.
- **If that happens, 32-bit in kivyforge becomes reasonable.** The CPython
  builds, their security releases, and (very likely) cibuildwheel support
  would move upstream. What remains is extending `kivy-mobile-wheels` and
  kivyforge, plus device-only launch testing.

## What kivyforge assumes today

- The runtime comes from python.org only: `PythonOrgAndroidProvider`
  (`kivyforge/platforms/android/lock/python_meta.py`) reads the release
  listing at `https://www.python.org/ftp/python/{version}/`.
- The ABI vocabulary is `VALID_ANDROID_ABIS = {"arm64_v8a", "x86_64"}`
  (`kivyforge/config/model.py`). The config loader rejects `armeabi_v7a` and
  `x86` by name, and android/01 §ABIs calls 32-bit "out of scope, permanently
  for this schema".
- App Bundles are **already supported**: `package -p android -f aab` runs
  Gradle's `bundleRelease`, and building several ABIs into one package is the
  default. Neither is verified in CI yet (see "What support would require").
- Inside an APK only the native `.so` files are per ABI (`lib/<abi>/`). The
  Python stdlib and app live in one shared `assets/_python_bundle`, with one
  Java bootstrap and one manifest.

## Findings

### 1. Chaquopy: 32-bit exists only through Python 3.11

Checked against the files actually published on Maven Central
(`com/chaquo/python/target/`), not only the docs:

| Chaquopy build | `armeabi-v7a` | `x86` | 64-bit |
|---|---|---|---|
| 3.11.14-0 (2025-11-20) | yes (5.7 MB) | yes | yes |
| 3.12.12-0 | **no** | no | yes |
| 3.14.0-0 | **no** | no | yes |

The docs agree: "Python 3.11 and older supports both 32-bit and 64-bit ABIs.
Python 3.12 and newer supports only 64-bit." 32-bit was removed in
[chaquopy#709](https://github.com/chaquo/chaquopy/issues/709) (2022), based on
Play Console ABI statistics. Chaquopy plans to drop 3.10 and 3.11 in autumn
2027, which ends even the 3.11 32-bit build.

The 3.11 build is **not usable by kivyforge as-is**: kivyforge's Android
pipeline and wheels are Python 3.14, and Chaquopy's archive layout differs
from python.org's.

### 2. chaquopy#1476: reintroduction under consideration

Opened 2026-09-27 by mhsmith, milestone 17.2, no comments at the time of
writing. Quoting it:

> "armeabi-v7a continues to be used in low-end devices, and the current RAM
> price explosion is only going to extend that. We might want to consider
> reintroducing it for Python 3.12 and later. See #709, and get some current
> usage data."

`x86` (32-bit) will be dropped regardless. Real-world ABI data from Play
Console (Reach and Devices > Overview > ABI) is exactly what the issue asks
for. kengoon was pointed at it.

### 3. BeeWare: no separate runtime, but the dependencies exist

Briefcase builds Android apps on Chaquopy, so it has the same limit
(`armeabi-v7a` on Python 3.11 and older only).
[`beeware/cpython-android-source-deps`](https://github.com/beeware/cpython-android-source-deps)
publishes prebuilt CPython dependencies (bzip2, libffi, OpenSSL, sqlite, xz,
zstd) for **all four** Android triplets, `arm-linux-androideabi` included, and
is actively maintained (OpenSSL 3.5.8, 2026-08-26).

### 4. CPython can still target 32-bit ARM

CPython 3.14's `Android/android.py` lists
`HOSTS = ["aarch64-linux-android", "arm-linux-androideabi",
"i686-linux-android", "x86_64-linux-android"]`. So the build tooling and its
dependencies exist for 32-bit ARM. CPython does not test that target, so
expect some porting fixes. Not built here.

### 5. python-for-android already builds 32-bit Python 3.14

- It compiles CPython from source per architecture. Both `master` and the
  latest release (v2026.05.09) pin **CPython 3.14.2**, and nothing in the
  `python3` recipe excludes 32-bit ARM.
- Buildozer's default `android.archs` is `arm64-v8a, armeabi-v7a`.
- It builds App Bundles: `android.release_artifact = aab` in Buildozer, or
  `p4a aab ... --arch=arm64-v8a --arch=armeabi-v7a --release`, which "produce[s]
  an `.aab` file that contains binaries for both `armeabi-v7a` and `arm64-v8a`
  ABIs".

*(An earlier version of this investigation said python-for-android ships
Python 3.11. That was wrong.)*

### 6. cibuildwheel's 64-bit limit comes from the missing runtime

cibuildwheel's Android backend (`cibuildwheel/platforms/android.py`) does not
build Python. It downloads a target Python tarball by URL and sha256 from
`resources/build-platforms.toml`, then cross-compiles against it with that
tarball's own `android.py env`. The tarball list covers only 64-bit:
cp314/cp315 from python.org, and cp313 **from Chaquopy's Maven repository** in
the same format.

Given a 32-bit tarball, a cibuildwheel patch would be small:

1. add `armeabi_v7a` to the Android architectures in `architecture.py`;
2. map it to `arm-linux-androideabi` in `ANDROID_TRIPLET`;
3. add a `cp314-android_armeabi_v7a` entry with its URL and sha256.

Two traps, where the triplet is reused but 32-bit ARM spells it differently:
CMake's processor would come out as `arm` (it expects `armv7-a`), and the Rust
target would be `arm-linux-androideabi` (Rust calls it
`armv7-linux-androideabi`). Tests run in an emulator, so 32-bit would be
build-only.

### 7. `kivy-mobile-wheels`: SDL is buildable today; Kivy and pyjnius wait

| Piece | How it is built | Needs cibuildwheel? |
|---|---|---|
| SDL2 (`recipes/android/sdl2.sh`) | NDK CMake toolchain, `-DANDROID_ABI="$ABI"` | no |
| SDL3 (`sdl3.sh`) | NDK CMake, plus unpacking SDL's official AAR | no |
| Kivy (`kivy-2.3.1-sdl2.sh`, `kivy-3.0-sdl3.sh`) | `CIBW_BUILD=cp314-android_<abi>` | **yes** |
| pyjnius (`pyjnius.sh`) | same pattern | **yes** |
| SDL Java glue | Java source | no, architecture-independent |

The only thing stopping 32-bit SDL today is the recipes' own guard
(`case "$ABI" in arm64-v8a|x86_64) ;;`). Also needed: `sdl3.sh`'s ABI-to-triplet
map, confirming SDL3's AAR still ships `armeabi-v7a` (not checked), and an
audit of `graft_libs.py` / `check_needed.py` for 64-bit ELF assumptions. The
workflow matrix is `abi: [arm64-v8a, x86_64]` (`build-android.yml`).

### 8. Mixing kivyforge (64-bit) and python-for-android (32-bit) in one package

**Not possible.** Only `lib/<abi>/` is per ABI. The Java bootstrap, manifest
and `assets/_python_bundle` exist once, and the two toolchains' versions are
incompatible.

The workable form is **two packages under one app identity**:

- the same package name and signing key;
- the 64-bit build with the **higher** version code, since a device gets the
  compatible build with the highest one and nearly every arm64 phone also runs
  32-bit (e.g. `1_000_000 + n` for 32-bit, `2_000_000 + n` for 64-bit);
- kivyforge's `version_code` and Buildozer's `android.numeric_version`.

This is fine outside Google Play. **On Play**, new apps must upload an App
Bundle, Google steers away from multiple APKs, and whether one release can
hold two separately built bundles was not confirmed. Since python-for-android
alone produces one bundle covering both ABIs, the split is only worth it if
the app needs something kivyforge offers.

## What support would require

**If we own it (no upstream change):**

- Build and host a 32-bit CPython 3.14 tarball with `android.py`; expect
  porting fixes.
- Maintain a cibuildwheel patch adding `armeabi_v7a`, carried forward to each
  cibuildwheel release.
- Add 32-bit builds to `kivy-mobile-wheels`: Kivy, pyjnius, SDL2/SDL3.
- Rebuild everything for every CPython security release and every Kivy, SDL,
  pyjnius and cibuildwheel release.
- Change kivyforge: the ABI list and loader, the adb ABI map, the `--abi`
  choices, the wheel tag `android_<api>_armeabi_v7a` in the lock builder, a
  second runtime provider (the lock already pins each ABI's runtime by URL,
  sha256 and minimum API), the three spellings of the target (`armeabi-v7a`,
  `arm-linux-androideabi`, `armv7a-linux-androideabi<api>`) in the CMake
  launcher, 32-bit ARM ELF checks, ABI choice in `run` (arm64 phones also list
  `armeabi-v7a`), doctor, and the docs that call 32-bit permanently out of
  scope.
- Testing: CI can build and check the package (T2/T3). There is no practical
  32-bit emulator, so launching (T4) is real-device only, a permanent manual
  row in the test matrix.

**If Chaquopy brings 32-bit back:** the tarball, the CPython security
rebuilds and (very likely) the cibuildwheel support move upstream. Wheels do
not need rebuilding for CPython patch releases, since the binary interface is
stable within a minor version. What remains is a third ABI in
`kivy-mobile-wheels` and the kivyforge changes above, several of which are
needed for 64-bit anyway.

**Needed regardless:** the Android T3 check (`android_apk_problems`) assumes
one ABI per package, and no CI job builds or inspects an `.aab`. A 32+64-bit
package is multi-ABI by definition.

**Unaffected:** byte-compiling and stripping (`.pyc` is
architecture-independent), Play's 64-bit rule (a 32+64 bundle satisfies it),
the 16 KB page-size requirement (64-bit only), and the native load model.

## Recommendation

1. **Now:** users who need 32-bit use Buildozer / python-for-android.
2. **Ecosystem:** support chaquopy#1476 with real ABI data.
3. **kivyforge:** do not start owning a 32-bit CPython. Revisit when either
   trigger below fires.

## Triggers to revisit

- chaquopy#1476 is decided. If 32-bit returns for 3.12+, next check whether
  cibuildwheel adds `armeabi_v7a`.
- Measured demand: Play ABI data showing a meaningful share of users on
  devices that cannot run arm64.

## Sources

- [Chaquopy Maven: target versions](https://repo.maven.apache.org/maven2/com/chaquo/python/target/)
  ([3.11.14-0](https://repo.maven.apache.org/maven2/com/chaquo/python/target/3.11.14-0/),
  [3.12.12-0](https://repo.maven.apache.org/maven2/com/chaquo/python/target/3.12.12-0/),
  [3.14.0-0](https://repo.maven.apache.org/maven2/com/chaquo/python/target/3.14.0-0/))
- [Chaquopy docs: Android ABIs](https://chaquo.com/chaquopy/doc/current/android.html)
- [chaquopy#1476](https://github.com/chaquo/chaquopy/issues/1476),
  [chaquopy#709](https://github.com/chaquo/chaquopy/issues/709)
- [Briefcase: Android Gradle reference](https://briefcase.beeware.org/en/stable/reference/platforms/android/gradle/)
- [beeware/cpython-android-source-deps](https://github.com/beeware/cpython-android-source-deps)
- [CPython 3.14 `Android/android.py`](https://github.com/python/cpython/blob/3.14/Android/android.py)
- [PEP 738](https://peps.python.org/pep-0738/)
- [python-for-android quickstart (App Bundle)](https://github.com/kivy/python-for-android/blob/master/doc/source/quickstart.rst),
  [`python3` recipe](https://github.com/kivy/python-for-android/blob/master/pythonforandroid/recipes/python3/__init__.py)
- [Buildozer `default.spec`](https://github.com/kivy/buildozer/blob/master/buildozer/default.spec)
- cibuildwheel: [`platforms/android.py`](https://github.com/pypa/cibuildwheel/blob/main/cibuildwheel/platforms/android.py),
  [`architecture.py`](https://github.com/pypa/cibuildwheel/blob/main/cibuildwheel/architecture.py),
  [`resources/build-platforms.toml`](https://github.com/pypa/cibuildwheel/blob/main/cibuildwheel/resources/build-platforms.toml)
- [Multiple APK support](https://developer.android.com/google/play/publishing/multiple-apks),
  [64-bit requirement](https://developer.android.com/google/play/requirements/64-bit)
  (Android Developers)

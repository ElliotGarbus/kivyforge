# Android wheels + CPython Android tier — Phase 0 findings + spike scoping

**Questions this note answers:**

1. Is kivyforge's core architectural bet — *resolve to a lockfile of prebuilt,
   ABI-tagged wheels + a prebuilt relocatable runtime, then **assemble** (never
   compile on the build machine)* — viable on Android in 2026?
2. Where does the Android **CPython runtime** come from (the PBS analog)?
3. What is the state of **Android wheels** for the Kivy native stack —
   especially **pyjnius**, the load-bearing Java bridge?
4. What must the **pyjnius Android-wheel spike** actually prove before we commit
   the Android backend spec to the wheel-assembly model?

> **Bottom line.** The wheel-assembly model is **viable in principle today** —
> Android is a CPython tier-3 platform, PyPI serves `android_*` wheels, pip
> installs them, and cibuildwheel builds them. The **one blocking unknown** is
> the Kivy native stack, and within it **pyjnius is the long pole**: it is not
> published as an Android wheel and it is *not self-contained* (it link-binds to
> the app's `libmain.so` and the app-provided JVM `JNIEnv`). So the correct next
> step is a **scoped pyjnius-wheel spike** (handed to the pyjnius repo — see
> [pyjnius-android-wheel-spike.md](pyjnius-android-wheel-spike.md)), whose
> outcome decides whether the Android backend looks like the desktop backends
> (assemble prebuilt wheels) or like p4a (compile from source).

_All facts below carry a date; the mobile-Python landscape is moving fast, so
re-verify before acting on anything more than a few months old. Captured
2026-07._

---

## 1. CPython Android tier (settled)

- **Android is a Tier 3 CPython platform** via **[PEP 738](https://peps.python.org/pep-0738/)**,
  shipped in **Python 3.13 (Oct 2024)**; **3.14 (stable)** and the **upcoming
  3.15** (pre-release now; final Oct 2026) continue the tier. It is in
  CPython's own build/release process, not a third-party patch set.
- **64-bit + 32-bit ABIs**, per the PyPA
  [platform-compatibility-tags spec](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/#android):
  `arm64_v8a`, `armeabi_v7a`, `x86_64`, `x86`.
- Bionic libc (not glibc); Android is POSIX-ish but not "just Linux."

## 2. The Android runtime source — python.org, exactly like iOS

**This is a net positive: kivyforge already ships this pattern on
iOS.** Android does not need a novel runtime story — it reuses the iOS one.

- **python.org publishes an official Android runtime** — the **"Android
  embeddable package"** (`aarch64` + `x86_64`), shipped alongside normal CPython
  releases (e.g. **Python 3.14.6, 2026-06-10**, at
  <https://www.python.org/downloads/android/>). A first-party, versioned,
  relocatable runtime — the Android analog of the Windows embeddable package.
- **kivyforge already consumes an official python.org platform build on iOS.**
  The iOS runtime provider — `PythonOrgProvider` in
  `platforms/ios/lock/python_meta.py` — pins the official python.org
  `Python.xcframework`
  (`https://www.python.org/ftp/python/{version}/python-{version}-iOS-XCframework.tar.gz`,
  3.15.0b1+) by **URL + SHA-256** and reads its OS floor straight from the
  archive. Android is the **same pattern with a different artifact**, so there is
  an established in-repo template to copy rather than a new risk to absorb.
- **Runtime source per platform:** desktop (macOS/Linux/Windows) → PBS; **iOS →
  python.org xcframework; Android → python.org embeddable package.** Android
  simply joins iOS on the python.org side.
- python-build-standalone has **no Android build** (astral-sh/python-build-standalone
  [#895](https://github.com/astral-sh/python-build-standalone/issues/895),
  [#176](https://github.com/astral-sh/python-build-standalone/issues/176), open
  2025-12), so there is nothing to wait on; if PBS ever adds Android it is merely
  an alternative provider.
- **Action for the spec:** add an **Android runtime provider modeled on the iOS
  `PythonOrgProvider`** — pin the python.org Android embeddable package by URL +
  hash — rather than extending the desktop `PbsProvider`.

## 3. Android wheels — the ecosystem is ready in principle

- **Tag format:** `android_<apilevel>_<abi>`, e.g. `android_24_arm64_v8a`,
  `android_24_x86_64`. `apilevel` is the *minimum* API (like the macOS
  deployment-target tag); an app with min-API N can install wheels tagged ≤ N.
- **PyPI accepts and serves** iOS/Android wheels (changes landed 2025).
- **pip installs them** since **pip 25.1** (2025), including cross-download:
  `pip install --platform android_24_arm64_v8a --only-binary=:all: … <pkg>`.
- **cibuildwheel builds them** — Android support added in **3.1 (2025)**, matured
  through **4.x (2026)** (auditwheel grafting, pkg-config/Fortran, NumPy, 3.15):
  - Host must be **Linux x86_64 / macOS** with an Android SDK; it drives the NDK
    via `sdkmanager`.
  - **`ANDROID_API_LEVEL` defaults to 24** (first level with RUNPATH, which
    auditwheel needs to graft external `.so`s; ~99% device coverage).
  - Build frontend must be **`build` / `build[uv]` / `uv`** — **not `pip`**.
  - Tests run on a **Gradle-managed emulator testbed** (from CPython), only for
    the *build machine's* architecture (other ABIs build but skip testing).
- **Reproducibility caveat (carry-forward from the Windows retrospective):** the
  **NDK/SDK/build-tools versions drift** exactly like the MSVC toolset did. Any
  Android wheel/runtime pin needs a documented re-pin path and NDK-version
  pinning from day one.

## 4. The Kivy native stack — the actual blocker

The general ecosystem is ready; **the Kivy-specific wheels largely are not yet on
PyPI**, and pyjnius has a structural obstacle.

### pyjnius (the long pole)

- **No PyPI Android wheel exists** (2026). Evidence: p4a
  [#3342](https://github.com/kivy/python-for-android/issues/3342) shows
  `pip3 install pyjnius==1.7.0 --only-binary=:all: --platform=android_21_arm64_v8a`
  → *"No matching distribution found."* p4a still **builds pyjnius from source**
  per project.
- **pyjnius is not self-contained** — the crux of the spike:
  - It **links `-lmain`**, i.e. against the app's `libmain.so` produced by the
    p4a/SDL/Qt **bootstrap**; with the Qt bootstrap the lib is
    `libmain_<abi>.so` (p4a
    [#3220](https://github.com/kivy/python-for-android/issues/3220)). p4a
    [PR #3308](https://github.com/kivy/python-for-android/pull/3308) (merged
    2026-05) introduced **`PYJNIUS_ANDROID_LIBMAIN`** (fallback `"main"`) to cope.
  - It obtains the JVM **`JNIEnv` from the running app** (e.g.
    `SDL_AndroidGetJNIEnv` / `WebView_AndroidGetJNIEnv`), i.e. from a symbol the
    bootstrap provides.
  - It needs **Java-side glue on the app classpath** (e.g. the
    `NativeInvocationHandler` used to implement Java interfaces from Python),
    which a `.whl` cannot dex into the APK by itself.
- **Why this matters:** a standalone, app-agnostic pyjnius wheel must **defer the
  JVM / `libmain` binding to runtime** (weak/undefined symbols resolved at load,
  `dlsym`/`JNI_GetCreatedJavaVMs`, or a tiny app-provided shim) instead of
  link-time, **and** define how its Java glue reaches the APK's dex. If that is
  clean, the whole Kivy stack (Kivy, SDL) almost certainly wheelifies; if it is
  intractable, the Android backend cannot be pure "assemble prebuilt wheels."

### Kivy / SDL / others

- Community prebuilt Android-wheel indexes exist and p4a can now consume them —
  p4a **v2026.05.09** added prebuilt-wheel support
  ([PR #3280](https://github.com/kivy/python-for-android/pull/3280):
  `--extra-index-url`, `--use-prebuilt-version-for`, `--skip-prebuilt`,
  `--save-wheel-dir`), pulling from indexes like **Chaquopy**
  (`https://chaquo.com/pypi-13.1/`) and community p4a-wheels. So the ecosystem is
  **mid-transition**: wheels increasingly exist, but via extra indexes, not
  routinely on PyPI, and not yet audited for the standalone-wheel properties
  kivyforge needs.
- **Chaquopy 17** tracks Python 3.14 — a useful reference wheel repository and a
  proof that the Kivy-adjacent native stack *can* be prebuilt.

## 5. Implications for the kivyforge Android backend

If the pyjnius spike succeeds, the Android backend maps cleanly onto the shared
core, with these platform specifics:

- **Runtime provider:** python.org Android embeddable package (§2), modeled on
  the existing iOS `PythonOrgProvider` — the same first-party-python.org pattern,
  not PBS.
- **Lock profile:** `android_<api>_<abi>` tags; an **ABI matrix**
  (`arm64_v8a`, `x86_64` at least — mirrors the `arm64-windows` multi-arch work).
  Decide the min-API pin (24 is the ecosystem default) and treat it like the
  macOS deployment target.
- **Wheel source policy:** prefer PyPI; allow extra indexes (Chaquopy / community)
  as pinned, hash-verified sources — the same "vendored/pinned, never resolve
  live" rule as desktop.
- **Assembly target:** an Android app project (Gradle) → **`.apk`** (sideload/CI)
  and **`.aab`** (Play). This is a bigger, more declarative surface than a
  desktop folder (manifest/permissions/resource merge, activity → Python
  bootstrap, `.so` ABI layout + 16 KB page alignment).
- **Signing:** APK/AAB signing is **mandatory** (keystore + `apksigner`, v1–v4
  schemes, Play App Signing) — expect more required setup + `doctor` checks than
  Authenticode.
- **Native lib discovery / load order** is the DLL-discovery analog
  (`System.loadLibrary`, `android:extractNativeLibs`, RUNPATH/auditwheel).

If the spike **fails** (pyjnius cannot be a clean standalone wheel), the backend
must instead orchestrate a **from-source build** (p4a-style recipes) — a
materially different spec and scope. **This is why the spike gates the spec.**

## 6. Recommendation

1. **Run the pyjnius Android-wheel spike first** — scoped brief in
   [pyjnius-android-wheel-spike.md](pyjnius-android-wheel-spike.md), designed to
   be handed to an agent working in the **pyjnius** repository. It is the single
   load-bearing unknown.
2. In parallel, it is safe to draft the **Android spec skeleton** for the
   *known-knowns* (runtime provider from python.org, ABI matrix, APK/AAB scope
   boundary, keystore signing, manifest/permission surface), leaving the
   wheel-vs-source architectural choice as the one open decision the spike
   resolves.

## References

- PEP 738 — <https://peps.python.org/pep-0738/>
- Platform compatibility tags (Android) —
  <https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/#android>
- CPython Android downloads — <https://www.python.org/downloads/android/>
- cibuildwheel Android — <https://cibuildwheel.pypa.io/en/stable/platforms/#android>
- pip Android support — <https://github.com/pypa/pip/issues/13299>
- PBS Android request — <https://github.com/astral-sh/python-build-standalone/issues/895>
- pyjnius no-wheel evidence — <https://github.com/kivy/python-for-android/issues/3342>
- pyjnius `libmain` linkage — <https://github.com/kivy/python-for-android/pull/3308>,
  <https://github.com/kivy/python-for-android/issues/3220>
- p4a prebuilt-wheel support — <https://github.com/kivy/python-for-android/pull/3280>

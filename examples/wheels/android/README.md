# Vendored Android wheels

The Android backend consumes locally cross-built **Kivy 2.3.1** and **pyjnius**
wheels via `find_links` + a `path` pin until first-party wheels reach PyPI
(see [docs/design/platforms/android/03-artifact-distribution-android.md]).

**The `.whl` files are not committed** (`.gitignore`, matching
`examples/wheels/ios/`) — binaries stay out of the repo. Build them with
[docs/design/dev/android-wheel-build-recipe.md](../../../docs/design/dev/android-wheel-build-recipe.md),
which is written to be reproducible: pinned source tarballs with SHA-256s,
the exact cibuildwheel environment, and the post-build verification.

| Wheel | Provenance | 16 KB-aligned? |
|-------|-----------|----------------|
| `pyjnius-1.7.0-cp314-cp314-android_24_*` | cibuildwheel (spike branch `ElliotGarbus/pyjnius@spike/android-universal-wheel`); Java-free, SDL-agnostic, `-Wl,-z,max-page-size=16384` pinned | ✅ yes |
| `Kivy-2.3.1-cp314-cp314-android_24_*` | **first-party** cibuildwheel cross-build against the official SDL 2.32.10 line, flat `.libs/` with sonames unchanged | ✅ yes |

Expected hashes for the Kivy wheels the committed `pylock.android.toml` pins:

| File | sha256 |
|------|--------|
| `Kivy-2.3.1-cp314-cp314-android_24_arm64_v8a.whl` | `685323b4b64ea83078145e86a644158db10ba9ce62de758c3d78148addbef7f1` |
| `Kivy-2.3.1-cp314-cp314-android_24_x86_64.whl` | `6ab89ca283393864b9a2e710e8c2400800e7160d34528280d5cf2406ce9357c2` |
| `pyjnius-1.7.0-cp314-cp314-android_24_arm64_v8a.whl` | `232b830e12e334909bec4c797e3e6d12f98d1c119dd622bcb570a942143e99c8` |
| `pyjnius-1.7.0-cp314-cp314-android_24_x86_64.whl` | `96b35a63ba4427527fa34ad66a6d1d0881ee7b029fcfb38f9314cf4f0b28fcff` |

A wheel whose hash differs from the lock is rejected at build time, so
rebuilding from the recipe requires re-running `kivyforge lock -p android
--update` (the build is not bit-reproducible).

> **Validated on-device.** The contract smoke test passes on an x86_64
> emulator (API 31) and a Pixel 8a (Android 16 / API 36), and the app renders
> on the Pixel — see
> [docs/design/dev/android-loadmodel-findings.md](../../../docs/design/dev/android-loadmodel-findings.md).
>
> **Sharp edge:** the SDL Java glue in
> `kivyforge/platforms/android/bootstrap/templates/sdl2/` and the `libSDL2.so`
> inside the Kivy wheel are a matched pair. `SDLActivity` compares them and, on
> a mismatch, aborts `onCreate` *silently* — black screen, nothing in logcat,
> no Python. `kivyforge build` now fails fast on this, but if you rebuild the
> wheel against a different SDL release you must re-vendor the glue from the
> same tarball.

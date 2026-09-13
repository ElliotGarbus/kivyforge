# 09 — Native-integration

How a **Python package declares the native material it needs** — Maven
coordinates, permissions, manifest components, SPM packages, `Info.plist` keys,
and any glue source — so kivyforge can stage it, instead of every app author
transcribing it by hand from a README.

> **The specification lives at
> [ElliotGarbus/native-integration](https://github.com/ElliotGarbus/native-integration)
> (`SPEC.md`), and it is the only normative document.** It sits outside kivyforge
> deliberately, so other toolchains can adopt it — a convention only one tool
> reads is not worth defining.

**This file used to hold a 500-line adoption record.** It was written before the
spec stabilised, the spec then moved ahead of it through two external reviews and
ten worked integration cases, and the two drifted. Rather than maintain a second
account of the same design, it is now a pointer: read `SPEC.md`, and treat
anything you remember from this document as superseded.

## Why kivyforge wants it

`pip install` carries a package's Python half and drops everything else. When
`libfoo` needs a Maven coordinate and a permission, the dependency graph delivers
neither — the app author reads a README and hand-copies the rest into their own
`pyproject.toml`. Every app repeats the transcription, every version bump risks
silent drift, and when `libfoo` is a *transitive* dependency the person on the
hook may not know it is in the tree. The gap is sharper on iOS, where a missing
Android permission yields a catchable denial but a missing usage-description
string terminates the app.

Android and iOS only. Desktop is the build host, not a target profile.

## Status in kivyforge

**Not implemented.** Adoption is roadmap item 8, and its scope, sizing, and queue
position are tracked in [`../dev/roadmap.md`](../dev/roadmap.md) — read against
`SPEC.md`, not against this file.

Two **bootstrap seams** are in the tree already, because both are places a
sidecar must never be able to reach and it was cheaper to reserve them early than
to take them back later:

- `<application android:name>` is a singleton slot the generated bootstrap owns,
  so two SDKs that both want startup work can coexist — see
  `RESERVED_APPLICATION_ATTRS` in
  `kivyforge/platforms/android/generate/manifest.py` (SPEC.md §6.1).
- The iOS inittab table has a dispatch point for package-contributed native
  modules, currently holding only its terminator — see `render_native_modules_h`
  in `kivyforge/platforms/ios/sources.py` (SPEC.md §7.7).

Both cite the spec directly, which is the pattern to follow: code references
`SPEC.md`, never this document.

`[tool.kivy.android.proguard]` also shipped alongside these as an app-authored
R8 keep-rule channel. It is a normal config surface rather than a sidecar seam,
and it is documented with the rest of the Android schema in
[`01-pyproject-android.md`](../platforms/android/01-pyproject-android.md) and
[`04-gradle-project-generation.md`](../platforms/android/04-gradle-project-generation.md).

# Agent prompt — `[tool.kivy.android.proguard]`: R8 keep rules

> **Run this on a host with the JDK, the Android SDK/NDK and an x86_64 AVD**
> (or a device), from the repo root. Any host works. Written 2026-11-18 against
> `main` at `af8c8dad`; you need that commit or later.
>
> Point the agent at this file, or copy the "Prompt" section.

## Background — specified, never implemented

`[tool.kivy.android.proguard]` was specified on 2026-08-07 (`7637df85`), but
that commit changed only the design docs. No release reads the table. Since
"unknown keys under `[tool.kivy]` are errors" (CHANGELOG), the loader rejects
it:

```
Error: unknown key 'proguard' in [tool.kivy.android] (line 47)
```

The generated `app/proguard-rules.pro` holds only the baseline, written in
`kivyforge/platforms/android/generate/project.py`: one
`-keep class <ns>.** { *; }` for each of `ANDROID_BOOTSTRAP_NAMESPACES` in
`kivyforge/config/model.py` (`org.jnius`, `org.kivy.android`,
`org.renpy.android`, `org.libsdl.app`). So an app that reaches any other Java
class through pyjnius has no way to keep it. It must leave
`[tool.kivy.android.build_settings].minify` off, or its release build fails at
run time with `ClassNotFoundException`.

That now blocks a real user. Kivy 3's Android video provider
(`kivy.core.video.video_android`) drives androidx.media3 ExoPlayer entirely
through pyjnius. With R8 on, an app needs
`-keep class androidx.media3.** { *; }`, and Kivy's docs currently have to tell
kivyforge users to leave `minify` off.

The spec is normative and complete; implement it, don't redesign it:

- [01-pyproject-android §`[tool.kivy.android.proguard]`](../platforms/android/01-pyproject-android.md#toolkivyandroidproguard--r8-keep-rules):
  the `keep` and `rules_files` fields; `rules_files` pinned by SHA-256 "exactly
  like `include_files`"; consulted only when `minify` is on.
- [04-gradle-project-generation §"R8 / `proguard-rules.pro`"](../platforms/android/04-gradle-project-generation.md#r8--proguard-rulespro):
  how the file is composed. The baseline comes first, then `keep` verbatim,
  then each rules file in order, each block under a comment naming its origin.
  It is regenerated on every build, and kivyforge does not synthesize rules
  or merge consumer rules.
- [06-cli-android, doctor table, "R8 keep rules"](../platforms/android/06-cli-android.md):
  the doctor check (WARN and FAIL cases).

Out of scope: keep rules contributed by packages through the native-integration
sidecar (`400622be`, roadmap item 8). This change is only the app-authored
table.

## Prompt

Implement `[tool.kivy.android.proguard]` as specified in
`docs/design/platforms/android/01-pyproject-android.md`,
`04-gradle-project-generation.md` (§"R8 / `proguard-rules.pro`") and the "R8
keep rules" row of the doctor table in `06-cli-android.md`. Read those three
sections and `AGENTS.md` first. The spec is normative. Where it is silent,
follow the `include_files` precedent and say what you chose.

1. **Config.** Add the table to the Android model (`AndroidConfig` in
   `kivyforge/config/model.py`), parse it in `_parse_android` in
   `kivyforge/config/loader.py`, and register it in the `ANDROID` key tree in
   `kivyforge/config/keys.py`. The unknown-key check must then accept
   `proguard.keep` and `proguard.rules_files`, but still reject a misspelt
   sub-key such as `proguard.kepp`, with its line and a suggestion.
   - `keep` is a list of strings; a wrong type is a configuration error naming
     the line.
   - Each `rules_files` entry must exist and stay inside the project, checked
     with the same path rules as `include_files`.
2. **Lock.** Pin each `rules_files` file's SHA-256 in the lock, as
   `include_files` does: see `hash_pins` / `pins_current` / `refresh` in
   `kivyforge/artifacts/include_files.py`, `LockedIncludeFile` in
   `kivyforge/lock/model.py`, and the overlay fields in
   `kivyforge/lock/inputs.py`. `build` refuses a file that changed since
   locking with `LockDrift` (`KF-LOCK-DRIFT`). Decide whether the inline `keep`
   strings belong in the lock inputs (they don't change what `lock` resolves),
   and say which you chose and why.
3. **Generation.** Compose `app/proguard-rules.pro` in the spec's order, each
   block under a comment naming its origin (the baseline, the `keep` list, each
   rules file by its project-relative path). Keep the output deterministic. A
   table declared with `minify = false` must be harmless. Write the file the
   same way either way, so that switching `minify` changes only the Gradle
   flag.
4. **Doctor.** Add the "R8 keep rules" check from 06's table: WARN, FAIL and
   SKIP exactly as written there.
   - I also recommend widening the WARN to apps that declare
     `[tool.kivy.android.gradle].dependencies`, `native.aars` or `native.jars`,
     with `minify` on and no rules. A Maven or AAR library reached only from
     Python is as invisible to R8 as the app's own Java; Media3 and ZXing are
     both that case.
   - If you widen it, update 06's row to match. If you don't, say why.
5. **Tests**, hermetic, in the existing files where they fit
   (`tests/platforms/android/test_generate.py`, the loader and lock tests,
   `test_doctor.py`):
   - parsing, type errors and unknown sub-keys;
   - path escape and missing file;
   - pinning, drift, and refresh by `lock`;
   - the exact composed file, in order and with the origin comments;
   - each doctor verdict.
   Then run the loop in `AGENTS.md`: `pytest` (coverage gate), `ruff check`,
   `ruff format --check`.
6. **Prove it on an emulator or device.** This is the point of the change, and
   unit tests can't show it. Use `examples/mobile/qr-maven`, which reaches ZXing
   only through pyjnius:
   - Set `[tool.kivy.android.build_settings] minify = true` with no rules.
     `kivyforge run -p android --release --emulator --abi x86_64` must fail at
     run time when the app touches ZXing (`ClassNotFoundException` for
     `com.google.zxing...`, or whatever R8 actually produces: record it).
     Confirm with the APK's dex too (see the helper behind
     `tests/platforms/android/test_dex_classes.py`) that the ZXing classes are
     gone.
   - Add `keep = ["-keep class com.google.zxing.** { *; }"]`. The same command
     must reach the app's `QR_OK` line, and the classes must be in the dex.
   - Repeat the second run with the rule moved into a `rules_files` entry.
   - Then edit that file without re-locking, and check that `build` stops with
     the drift error.
   - Don't commit the `minify`/`keep` change to `qr-maven`: it is a shipped
     example, and `examples/verify-android.ps1` builds it from its committed
     lock. Do this on a scratch copy, or revert it.
7. **Docs.**
   - Drop the "specified, not implemented" status notes in 01, 04 and 06.
   - Add the table to `docs/guides/reference/pyproject/android.md`.
   - Add a short "Release builds with R8" section to
     `docs/guides/guides/android/java-libraries.md`. It should say when
     `minify` needs keep rules (anything reached only from Python), show the
     ZXing example, and say how to check a release build (`run --release`).
   - Add a CHANGELOG `[Unreleased]` entry: the table is now read; it was
     previously rejected, and before that silently dropped.
   - Add the dated device run to `test-matrix.md` §7.

Done when:
- the table loads, locks, generates and is checked by doctor as specified;
- the hermetic tests and the `AGENTS.md` loop pass;
- the qr-maven release build fails without the rule and runs with it, through
  both `keep` and `rules_files`, on an emulator or device, and that run is
  recorded in `test-matrix.md`;
- the docs no longer call the table unimplemented.

Report what you chose where the spec was silent (lock inputs for `keep`,
the doctor WARN's scope), the exact runtime error R8 produced in step 6, and
anything you could not verify.

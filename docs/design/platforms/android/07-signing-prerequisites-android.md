# Android — Signing Prerequisites (how to sign your kivyforge output)

> **Status: design.** The Android sibling of
> [signing-prerequisites-ios](../ios/08-signing-prerequisites-ios.md),
> [signing-prerequisites-macos](../macos/signing-prerequisites-macos.md), and
> [signing-prerequisites-windows](../windows/signing-prerequisites-windows.md).

This is the user-facing checklist for producing a **signed** Android build with
kivyforge. Unlike Windows (Authenticode, off by default) or iOS (Xcode owns
signing), Android signing is **mandatory** — every APK/AAB must be signed to
install — and kivyforge **owns** it: it generates the Gradle signing config and
invokes `apksigner`/`jarsigner` through Gradle. The *design* behind this — the
`[tool.kivy.android.signing]` field map, the `package -f` pipeline, and the
scheme toggles — lives in the [Android pyproject spec](01-pyproject-android.md#toolkivyandroidsigning)
and the [Android CLI spec](06-cli-android.md#kivyforge-package); this document
enumerates what a user must set up **before** a signed release build.

> **Debug builds need no setup.** `kivyforge build --debug` and `kivyforge run`
> sign automatically with the standard Android **debug keystore** (auto-created at
> `~/.android/debug.keystore`). The whole dev loop — build, install, run on an
> emulator or device — works with **no keystore configuration at all**. Everything
> below is for **release** distribution (`kivyforge package`).

## Two signing models

1. **Self-managed signing (sideload / self-distribution).** You hold the signing
   key; the `.apk`/`.aab` is signed with it and installs directly. You are
   responsible for keeping the key safe forever — losing it means you can't update
   the app under the same identity.
2. **Play App Signing (Google Play, recommended for the store).** You sign the
   `.aab` with an **upload key**; Google holds the real **app signing key** and
   re-signs the APKs it generates. If you lose the upload key, Google can reset it
   — a major safety improvement over self-managed keys. kivyforge's job is the
   same either way: produce an `.aab` signed with your upload key.

## Prerequisites

Complete these on the build host before a signed release build. The host may be
**Windows, macOS, or Linux**.

1. **A JDK (17+) and the Android SDK.** `kivyforge doctor` checks both, plus that
   `sdkmanager --licenses` are accepted and the `compile_sdk` platform +
   build-tools (which provide `apksigner`) are installed.

2. **A signing keystore + key.** Create one with `keytool` (bundled with the JDK)
   — this is your upload key for Play, or your app key for self-distribution:

   ```bash
   keytool -genkeypair -v \
     -keystore release.keystore \
     -alias upload \
     -keyalg RSA -keysize 4096 -validity 10000 \
     -storetype PKCS12
   ```

   Answer the prompts (name/org/etc.) and choose strong passwords. **A validity
   long enough to outlast the app's life** (10000 days ≈ 27 years) is standard, so
   the key doesn't expire mid-lifetime.

3. **Keep the keystore out of the repo history.** Commit it only to a private repo,
   or (better) keep it out of git entirely and provide it via CI secrets. **Never**
   commit a production keystore to a public repository. A repo-relative `keystore`
   path is fine for a private repo or a CI checkout that materializes the file from
   a secret.

4. **Provide the passwords via environment variables**, never in `pyproject.toml`:

   ```bash
   export KIVYFORGE_KEYSTORE_PASSWORD=...    # keystore (store) password
   export KIVYFORGE_KEY_PASSWORD=...         # key password (defaults to store pw if unset)
   ```

5. **Add the signing table to `pyproject.toml`** (or supply the equivalents by
   flag/env for CI):

   ```toml
   [tool.kivy.android.signing]
   keystore = "release.keystore"       # repo-relative or absolute
   key_alias = "upload"
   # store_password_env / key_password_env default to the KIVYFORGE_* names above
   v1_signing = false                  # JAR signing (v1); never needed at kivyforge's minSdk floor of 24
   v2_signing = true                   # whole-file (Android 7+)
   v3_signing = true                   # key rotation (Android 9+)
   v4_signing = false                  # incremental install (Android 11+)
   ```

   `keystore`/`key_alias` can also come from `--keystore` / `--key-alias` — the
   recommended path for CI and team projects that don't commit signing config.

6. **For Play App Signing, enrol once in the Play Console** (App integrity → App
   signing) and upload your first `.aab`. From then on you sign every upload with
   the **upload key** above; Google manages the app signing key.

## Sign

```bash
kivyforge doctor -p android                 # verify JDK, SDK, keystore, alias, passwords
kivyforge package -p android -f apk          # signed .apk (sideload / CI)
kivyforge package -p android -f aab          # signed .aab (Play upload)
```

Run `doctor` first — its **Signing (release)** check confirms the keystore exists,
the alias is present (`keytool -list`), and the password env vars are set, and it
fails fast **before** Gradle if not. `kivyforge package` also performs a
signing pre-flight (see [cli-android §`kivyforge package`](06-cli-android.md#kivyforge-package)).

## What gets signed (scope)

- **kivyforge signs the shippable artifact** — the whole `.apk`/`.aab`, including
  the bundled native libraries (`libpython`, the SDL family, wheel `.so`s) and the
  dexed bootstrap — via Gradle's signing config, using your key. An **`.apk`** is
  signed with `apksigner` (APK Signature Schemes v1–v4 per your toggles); an
  **`.aab`** is JAR-signed with `jarsigner`. The v2–v4 schemes apply to the APKs
  Play (or `bundletool`) generates from the bundle, not to the `.aab` container
  itself — so for a Play upload the enabled schemes describe how the *installed
  APKs* end up signed, and with Play App Signing that final APK signing is done by
  Google with the app key.
- **Individual `.so`s are not separately signed.** Android verifies the APK
  signature over the whole package; there is no per-library signing (unlike
  macOS/iOS Mach-O signing). This is the platform model, not a kivyforge choice.
- **Debug builds are signed with the debug keystore** — no account, key, or config
  needed. Only **release** needs the setup above.
- **Store submission is out of scope.** kivyforge produces the signed `.aab`;
  uploading it to the Play Console (and Play's re-signing) is external, per
  [common packaging scope](../../common/06-packaging-scope.md).

## Develop & test without any keystore setup

- **Emulator / device debug** (`kivyforge run`, `kivyforge build --debug`) needs
  **no keystore configuration** — the debug keystore is auto-managed. The full
  build → install → run loop works with zero signing setup.
- You only need a real keystore when you produce a **release** artifact for
  distribution (`kivyforge package`).

## Key safety (read this)

- **Back up your keystore and passwords** in a secure secret store. For
  self-managed signing, **a lost key is unrecoverable** — you can never ship a
  same-identity update again. Play App Signing mitigates this (Google can reset a
  lost *upload* key), which is why it is recommended for store apps.
- **Rotate with v3 if needed.** APK Signature Scheme v3 (`v3_signing = true`, the
  default) supports key rotation; keep it on so a future rotation is possible.

## Related

- [06-cli-android.md](06-cli-android.md#kivyforge-package) — the `package -f apk|aab` pipeline, the signing pre-flight, and the `doctor` checks.
- [01-pyproject-android.md](01-pyproject-android.md#toolkivyandroidsigning) — the `[tool.kivy.android.signing]` field reference and the v1–v4 scheme toggles.
- [08-signing-prerequisites-ios.md](../ios/08-signing-prerequisites-ios.md), [signing-prerequisites-windows.md](../windows/signing-prerequisites-windows.md) — the sibling checklists for the other targets.

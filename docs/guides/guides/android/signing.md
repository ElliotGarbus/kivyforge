---
title: Sign and publish to Google Play
sources:
  - docs/design/platforms/android/07-signing-prerequisites-android.md
  - docs/design/platforms/android/06-cli-android.md
  - kivyforge/platforms/android/signing.py
  - kivyforge/platforms/android/cli.py
---

# Sign and publish to Google Play

Android installs only signed apps. Debug builds are signed automatically; a
release build needs your own key. On this page, you create a key, produce a
signed APK (Android Package) or AAB (Android App Bundle), and upload the AAB to
Google Play.

## Before you begin

- [Configure your Android app](configure.md) and confirm that
  `kivyforge doctor -p android` reports no failures.
- Have a JDK, which provides `keytool`.

!!! note
    Debug builds need none of this. `kivyforge build --debug` and
    `kivyforge run` use the standard Android debug keystore.

## Choose a signing model

Self-managed signing
:   You hold the only key. If you lose it, you can never publish an update to
    the same app.

Play App Signing
:   You sign the AAB with an *upload key*. Google holds the app signing key and
    signs what it delivers to devices. If you lose the upload key, Google can
    reset it.

kivyforge does the same thing in both models: it signs the release artifact
with the key you give it.

## Create a keystore and package

1. Create a keystore:

    ```bash
    keytool -genkeypair -v -keystore release.keystore -alias upload -keyalg RSA -keysize 4096 -validity 10000 -storetype PKCS12
    ```

    `-validity 10000` (about 27 years) keeps the key valid for the life of the
    app. Keep the keystore out of your public repository.

2. Set the passwords as environment variables. Never put them in
   `pyproject.toml`.

    === "PowerShell"
        ```powershell
        $env:KIVYFORGE_KEYSTORE_PASSWORD = "STORE_PASSWORD"
        $env:KIVYFORGE_KEY_PASSWORD = "KEY_PASSWORD"
        ```

    === "bash"
        ```bash
        export KIVYFORGE_KEYSTORE_PASSWORD=STORE_PASSWORD
        export KIVYFORGE_KEY_PASSWORD=KEY_PASSWORD
        ```

    Replace `STORE_PASSWORD` and `KEY_PASSWORD` with the passwords you chose in
    `keytool`. If `KIVYFORGE_KEY_PASSWORD` is unset, the keystore password is
    used for the key. To read the passwords from other variables, set
    `store_password_env` and `key_password_env` in the signing table.

3. Declare the signing table:

    ```toml
    [tool.kivy.android.signing]
    keystore = "release.keystore"
    key_alias = "upload"
    ```

    `keystore` is relative to your project or absolute. Instead of the table,
    you can pass `--keystore` and `--key-alias` to `kivyforge package`, which
    suits CI jobs that write the keystore from a secret. If you edit
    `pyproject.toml`, run `kivyforge lock -p android` again.

4. Check the signing setup:

    ```bash
    kivyforge doctor -p android
    ```

    When the signing table is declared, `doctor` confirms that the keystore
    exists, the password variable is set, and the alias is in the keystore.

5. Package a signed artifact:

    ```bash
    kivyforge package -p android -f aab
    ```

    Use `-f aab` for Google Play and `-f apk` (the default) to install the app
    directly. Add `--abi arm64_v8a` or `--abi x86_64` to package a single ABI.

Before it signs anything, `package` checks the signing setup, runs a curated set
of Android Lint checks, and applies a manifest policy to the merged release
manifest. A finding in either blocks the release.

## Verify

`package` prints the path of the artifact it produced:

- APK: `<app>-android/app/build/outputs/apk/release/app-release.apk`
- AAB: `<app>-android/app/build/outputs/bundle/release/app-release.aab`

`<app>` is your `[project].name`. With `--json`, the same path is in
`data.artifacts`.

## Publish to Google Play

Uploading happens in the Play Console, outside kivyforge:

1. Enroll the app in Play App Signing (**App integrity** > **App signing**).
2. Upload the AAB to a release track.
3. Sign every later upload with the same upload key.

!!! danger "Back up your key"
    With self-managed signing, a lost key cannot be recovered. Store the
    keystore and its passwords in a secure secret store.

## What's next

- [Supported Android versions](supported-versions.md): keep `target_sdk` current
  for Google Play.
- [Drive kivyforge from CI or an agent](../cross-platform/ci-and-agents.md).
- [Signing prerequisites](../../troubleshooting/signing-prerequisites.md) for
  every platform.

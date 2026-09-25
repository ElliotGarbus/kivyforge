---
title: Signing prerequisites
sources:
  - docs/design/platforms/android/07-signing-prerequisites-android.md
  - docs/design/platforms/ios/08-signing-prerequisites-ios.md
  - docs/design/platforms/macos/signing-prerequisites-macos.md
  - docs/design/platforms/windows/signing-prerequisites-windows.md
  - kivyforge/config/model.py
  - kivyforge/platforms/android/signing.py
---

# Signing prerequisites

Each platform signs apps differently and needs its own one-time setup before
kivyforge can produce a signed build. This page lists what each platform needs
and links to the full guide.

Before a signed build, run `kivyforge doctor -p PLATFORM`, replacing `PLATFORM`
with the target. It checks most of the setup on this page and fails fast, before
a full build.

## At a glance

| Platform | Without setup | For distribution, you need |
|---|---|---|
| Android | `build --debug` signs with the Android debug key. `package` fails. | A release keystore and key, with the passwords in environment variables |
| iOS | Simulator builds need no signing. | An Apple Developer account in Xcode, a Team ID, and a signing certificate |
| macOS | `package` signs ad hoc. | A Developer ID Application certificate and, to notarize, a notary profile |
| Windows | `package` leaves the app unsigned. | A code-signing certificate in the Windows certificate store, and `signtool` |

## Android

Debug builds need no setup. To sign a release with `package`, you need:

- A JDK, the Android SDK, and the NDK.
- A release keystore and key, created with `keytool`. Keep the keystore out of
  public version control.
- The keystore password in `KIVYFORGE_KEYSTORE_PASSWORD`, and the key password in
  `KIVYFORGE_KEY_PASSWORD` if it differs.
- The keystore path and key alias, in `[tool.kivy.android.signing]` or passed as
  `--keystore` and `--key-alias`.

Full guide: [Sign and publish to Google Play](../guides/android/signing.md).

## iOS

The simulator needs no signing. To run on a device or distribute, you need:

- The full Xcode app, not only the command-line tools.
- An Apple ID added to Xcode. A free Apple ID is enough to run on your own
  device; distributing an `.ipa` needs a paid Apple Developer Program membership.
- A signing certificate in your keychain.
- Your Team ID, in `[tool.kivy.ios.signing].team_id`, passed as `--team-id`, or
  set in `KIVYFORGE_TEAM_ID`.

Full guide: [Sign the app](../guides/ios/signing.md).

## macOS

Ad hoc signing needs no setup. For Developer ID distribution, you need:

- A paid Apple Developer Program membership.
- A Developer ID Application certificate in a keychain. A dedicated keychain is
  recommended.
- The Xcode command-line tools.
- To notarize, a notary profile stored with `xcrun notarytool store-credentials`.
- A `[tool.kivy.macos.signing]` table that names the identity and, to notarize,
  the notary profile.

Full guide: [Sign, notarize, and staple](../guides/macos/signing.md).

## Windows

Signing is optional. To sign, you need:

- A code-signing certificate imported into the Windows certificate store.
- The certificate's SHA-1 thumbprint.
- `signtool.exe` on `PATH`. It ships with the Windows SDK.
- Network access to an RFC 3161 timestamp server. The default is
  `http://timestamp.digicert.com`.
- A `[tool.kivy.windows.signing]` table with the thumbprint.

Full guide: [Sign with Authenticode](../guides/windows/signing.md).

## What's next

- [Diagnose a failing build](index.md)
- [Environment variables](../reference/environment.md), for signing secrets

---
title: Sign, notarize, and staple a macOS app
sources:
  - docs/design/platforms/macos/signing-prerequisites-macos.md
  - docs/design/platforms/macos/macos-spec.md
  - FAQ.md
---

# Sign, notarize, and staple a macOS app

To distribute a macOS app outside the App Store so that it opens without a
Gatekeeper warning, you sign it with a Developer ID certificate, notarize it with
Apple, and staple the notarization ticket to it. When you configure a Developer ID
identity and a notary profile, `kivyforge package -p macos` does all three.

## Before you begin

- A paid Apple Developer Program membership. A free Apple ID cannot create
  Developer ID certificates.
- A **Developer ID Application** certificate and its private key in a keychain.
- The Xcode command-line tools, which provide `codesign` and `xcrun notarytool`.
- An app that [builds with `kivyforge package -p macos`](build.md).

## Sign and notarize the app

1. Store your notary credentials in the keychain as a named profile. Use an
   app-specific password, not your Apple ID password:

    ```bash
    xcrun notarytool store-credentials PROFILE_NAME --apple-id APPLE_ID --team-id TEAM_ID --password APP_SPECIFIC_PASSWORD
    ```

    Replace `PROFILE_NAME` with a name for the profile, such as
    `kivyforge-notary`; `APPLE_ID` with your Apple ID email address; `TEAM_ID`
    with your Team ID; and `APP_SPECIFIC_PASSWORD` with an app-specific password
    generated for your Apple ID.

2. Add the signing table to your `pyproject.toml`:

    ```toml
    [tool.kivy.macos.signing]
    identity = "Developer ID Application: NAME (TEAM_ID)"
    team_id = "TEAM_ID"
    notary_profile = "PROFILE_NAME"
    ```

    Replace `NAME (TEAM_ID)` with the name of your certificate as it appears in
    Keychain Access, and `PROFILE_NAME` with the profile from the previous step.

    - `identity` alone gives a Developer ID signature without notarization.
    - `identity` and `notary_profile` together give sign, notarize, and staple.

3. Check the setup:

    ```bash
    kivyforge doctor -p macos
    ```

    `doctor` checks that `codesign` is available, that exactly one keychain
    certificate matches `identity`, that the identity is a Developer ID type,
    and that `notarytool` is installed. It checks the notary profile's
    credentials only when you submit.

4. Package the app:

    ```bash
    kivyforge package -p macos
    ```

    `package` signs every Mach-O binary in the bundle from the inside out,
    submits the app to Apple's notary service, waits for the result, and staples
    the ticket to the `.app`. Notarization needs outbound network access and can
    take several minutes.

To override the configuration for one run, pass `--signing-identity` or
`--notary-profile`. To sign without notarizing even when a profile is
configured, pass `--no-notarize`.

## Verify

`package` ends with a line such as
`Packaged build/macos/APP_NAME.app (Developer ID notarized + stapled).` To confirm
with Apple's own tools that Gatekeeper accepts the app and that the ticket is
stapled:

```bash
spctl --assess --type execute --verbose "build/macos/APP_NAME.app"
xcrun stapler validate "build/macos/APP_NAME.app"
```

Replace `APP_NAME` with your app's display name.

## What gets signed

kivyforge signs every Mach-O binary inside the `.app`: the launcher, the bundled
Python runtime, every wheel extension module, and any
[native binaries](../cross-platform/native-binaries.md) you declare. Each
signature uses the Hardened Runtime and a secure timestamp, which notarization
requires.

The app's signature carries these entitlements, merged with your
`[tool.kivy.macos.entitlements]` table. Your values win.

| Entitlement | Default | Why |
|---|---|---|
| `com.apple.security.cs.allow-unsigned-executable-memory` | `true` | `ctypes` and `cffi` allocate writable, executable memory. |
| `com.apple.security.cs.disable-library-validation` | `true` | The app loads wheel binaries signed by other teams. |

kivyforge rejects `com.apple.security.get-task-allow = true` when an `identity`
is set, because notarization always rejects it.

## Troubleshooting

### `errSecInternalComponent` on every Mach-O

If signing fails on every binary with `errSecInternalComponent`, even after you
retry, the private key's access control list in your login keychain may be
corrupted. Apple recommends keeping a Developer ID identity in its own keychain
for this reason, and `kivyforge doctor` warns when your identity is in
`login.keychain-db`.

To move signing to a dedicated keychain:

1. Create and unlock a new keychain, add it to the search list, and make it the
   default:

    ```bash
    security create-keychain -p KEYCHAIN_PASSWORD signing.keychain-db
    security list-keychains -d user -s signing.keychain-db login.keychain-db
    security unlock-keychain -p KEYCHAIN_PASSWORD signing.keychain-db
    security set-keychain-settings signing.keychain-db
    security default-keychain -s signing.keychain-db
    ```

    Replace `KEYCHAIN_PASSWORD` with a password for the new keychain.

2. In Xcode, open **Settings > Accounts > Manage Certificates** and create a new
   **Developer ID Application** certificate. Xcode stores it in the default
   keychain, which is now `signing.keychain-db`.

3. Allow `codesign` to use the key, then restore your login keychain as the
   default:

    ```bash
    security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k KEYCHAIN_PASSWORD signing.keychain-db
    security default-keychain -s login.keychain-db
    ```

4. If `doctor` or `codesign` reports that the identity is ambiguous, delete the
   old certificate from `login.keychain-db` in Keychain Access.

## What's next

- [Package a macOS app in a .dmg](dmg.md) around the notarized app.
- [`[tool.kivy.macos]` reference](../../reference/pyproject/macos.md).
- [Signing prerequisites](../../troubleshooting/signing-prerequisites.md) for
  every platform.

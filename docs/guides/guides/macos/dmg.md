---
title: Package a macOS app in a .dmg
sources:
  - docs/design/platforms/macos/macos-spec.md
  - docs/design/common/06-packaging-scope.md
---

# Package a macOS app in a .dmg

kivyforge does not create `.dmg` disk images. Its macOS output is the signed
`.app` bundle, the only macOS package format. If you want to distribute the app in
a `.dmg`, you build the image yourself with macOS tools after kivyforge finishes.
This page shows one way to do that with `hdiutil`, which ships with macOS.

!!! note
    Every step after the first uses Apple's tools, not kivyforge. kivyforge
    does not run, check, or report on them.

## Before you begin

- An app that is [signed and notarized](signing.md). Notarize the app first,
  then sign and notarize the `.dmg` as well.
- Your Developer ID Application identity and notary profile.

## Create the .dmg

1. Build the notarized app with kivyforge:

    ```bash
    kivyforge package -p macos
    ```

    The app is at `build/macos/APP_NAME.app`, where `APP_NAME` is your app's
    display name. `package --json` reports the exact path in `data.artifacts`.

2. Stage the app in a folder, with a link to `/Applications` so users can drag
   the app there:

    ```bash
    mkdir -p dmg-staging
    cp -R "build/macos/APP_NAME.app" dmg-staging/
    ln -s /Applications dmg-staging/Applications
    ```

3. Create a compressed disk image from the folder:

    ```bash
    hdiutil create -volname "APP_NAME" -srcfolder dmg-staging -ov -format UDZO "APP_NAME.dmg"
    ```

4. Sign the disk image:

    ```bash
    codesign --sign "DEVELOPER_ID_IDENTITY" --timestamp "APP_NAME.dmg"
    ```

    Replace `DEVELOPER_ID_IDENTITY` with the same identity you set in
    `[tool.kivy.macos.signing].identity`.

5. Notarize the disk image and staple the ticket to it:

    ```bash
    xcrun notarytool submit "APP_NAME.dmg" --keychain-profile PROFILE_NAME --wait
    xcrun stapler staple "APP_NAME.dmg"
    ```

    Replace `PROFILE_NAME` with your notary profile name.

For a styled window with a background image and icon positions, use a dedicated
tool such as [create-dmg](https://github.com/create-dmg/create-dmg) in place of
steps 2 and 3.

## Verify

Check that Gatekeeper accepts the disk image:

```bash
spctl --assess --type open --context context:primary-signature --verbose "APP_NAME.dmg"
```

Then download the `.dmg` on another Mac, open it, and confirm that the app
launches without a Gatekeeper warning.

## What's next

- [Sign, notarize, and staple a macOS app](signing.md).
- [Build versus package](../../concepts/build-vs-package.md), which explains
  where kivyforge's output ends.
- [Build a macOS .app](build.md).

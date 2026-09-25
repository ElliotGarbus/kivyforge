---
title: Sign your iOS app
sources:
  - docs/design/platforms/ios/08-signing-prerequisites-ios.md
  - docs/design/platforms/ios/04-cli-ios.md
---

# Sign your iOS app

On iOS, Xcode owns signing. kivyforge writes the signing build settings from your
`[tool.kivy.ios.signing]` table and runs `xcodebuild`; it runs no `codesign` step
of its own. Device builds and release exports are signed. Simulator builds are
not, so if you only run on the Simulator, you can skip this page.

## Before you begin

- A Mac with the full Xcode IDE, launched once to finish its setup.
- An Apple account added to Xcode (**Xcode > Settings > Accounts**):
    - A free Apple ID is enough to run a debug build on your own device.
    - A paid Apple Developer Program membership is required to export an IPA
      (iOS App Store Package) for distribution.
- A signing certificate in your keychain. With automatic signing, the default,
  Xcode creates or downloads it after you add your account.
- Your Team ID, from the Apple Developer website or Xcode.

## Configure signing

1. Add the signing table to your `pyproject.toml`:

    ```toml
    [tool.kivy.ios.signing]
    team_id = "TEAM_ID"
    auto_signing = true
    ```

    Replace `TEAM_ID` with your 10-character Team ID. For a free Apple ID, use
    your personal team's ID.

    - `team_id` is required for device builds and release exports.
    - `auto_signing = true` lets Xcode register the App ID and download a
      provisioning profile for you. kivyforge passes `-allowProvisioningUpdates`
      to `xcodebuild` so that this works from the command line.
    - For manual signing, set `auto_signing = false`, set `identity` to an
      existing certificate, and set `provisioning_profile` to the name or UUID of
      an installed profile (or a path to its `.mobileprovision` file). See the
      [`provisioning_profile` reference](../../reference/pyproject/ios.md#toolkivyiossigning).

    !!! warning "Pinning a profile requires manual signing"
        Xcode refuses a pinned profile under automatic signing, so kivyforge
        stops a device or release build that sets `provisioning_profile` with
        `auto_signing = true`. The profile must also be one you created at
        [developer.apple.com](https://developer.apple.com/account/resources/profiles/list).
        Profiles named `iOS Team Provisioning Profile: ...` are the ones
        automatic signing installs; they are Xcode-managed, and manual signing
        rejects them. `kivyforge doctor -p ios` checks both.

2. Check the setup:

    ```bash
    kivyforge doctor -p ios
    ```

!!! tip "Keep the Team ID out of `pyproject.toml`"
    You can supply the Team ID with the `--team-id` option of `build` and
    `package`, or with the `KIVYFORGE_TEAM_ID` environment variable, which also
    works for `run`. The option wins over the variable, and the variable wins over
    `pyproject.toml`. This is the recommended setup for CI. The signing identity
    works the same way, with `--signing-identity` and
    `KIVYFORGE_SIGNING_IDENTITY`.

## Build a signed debug app for a device

```bash
kivyforge build -p ios --device
```

To also install and launch it, use `kivyforge run -p ios --device`. See
[Run your iOS app](run.md).

## Export a signed IPA

```bash
kivyforge package -p ios
```

`package` archives the app and exports a signed `.ipa` to
`<app>-ios/build/<app>.ipa`. `kivyforge build -p ios --release` does the same.
Choose the export method with `--export-method`: `app-store` (the default),
`ad-hoc`, or `development`.

!!! warning "Signing identity for a release"
    The `identity` key in `pyproject.toml` applies only to device debug builds.
    For a release export, kivyforge does not pass it to Xcode, so that automatic
    signing picks the distribution certificate that matches the export method.
    To force a specific certificate for a release, pass `--signing-identity` or
    set `KIVYFORGE_SIGNING_IDENTITY`.

Uploading the `.ipa` to App Store Connect is outside kivyforge.

## Entitlements

If `[tool.kivy.ios.entitlements]` declares keys, such as HealthKit, App Groups,
or push notifications, enable the matching capability on your App ID on the Apple
Developer website and regenerate the provisioning profile.

When you pin a `provisioning_profile` (manual signing), kivyforge compares the
declared keys with what the profile grants before it signs a device or release
build. A key the profile does not grant stops the build, because it would fail
to sign. `kivyforge doctor -p ios` runs the same comparison.

With automatic signing and no pinned profile, there is nothing to compare
against: Xcode fetches or creates the profile during the build.

## Verify

`kivyforge package -p ios --json` exits with status `0`, and `data.artifacts`
names the `.ipa`.

## What's next

- [Run your iOS app on the simulator or a device](run.md).
- [Signing prerequisites](../../troubleshooting/signing-prerequisites.md) for
  every platform.
- [`[tool.kivy.ios]` reference](../../reference/pyproject/ios.md).

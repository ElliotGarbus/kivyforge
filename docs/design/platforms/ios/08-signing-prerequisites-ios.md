# iOS — Signing Prerequisites (how to sign your kivyforge output)

This is the user-facing checklist for producing a **code-signed** iOS build with
kivyforge. iOS is categorically different from the desktop targets: **Xcode owns
signing** — kivyforge generates the `.xcodeproj`, sets the signing build
settings from `[tool.kivy.ios.signing]`, and invokes `xcodebuild`, but it runs no
`codesign` pipeline of its own. Signing is required for **on-device** and
**release** builds and is **skipped** for the simulator. The *design* behind this
— the build-setting mapping, the `--release` archive/export pipeline, and
automatic signing — lives in the [iOS CLI spec](04-cli-ios.md#kivyforge-build) and
the [`[tool.kivy.ios.signing]` reference](01-pyproject-ios.md#toolkivyiossigning);
this document only enumerates what a user must set up **before** running a signed
`build`.

> **Prerequisites are Apple/Xcode setup, not a kivyforge cert pipeline.** Unlike
> Windows (signtool + a cert in the store) or macOS (Developer ID + notary
> profile), iOS signing is standard Xcode signing. kivyforge's job is to pass the
> right values through to `xcodebuild`; the account, certificate, and
> provisioning setup below is what any Xcode iOS project needs.

## Prerequisites

Complete these on the macOS build host before a signed build.

1. **A macOS host with the full Xcode IDE** (not just the command-line tools).
   iOS builds go through `xcodebuild`, and `kivyforge open` hands off to Xcode
   for the device-select → ⌘R loop. Install Xcode and run it once to accept the
   license and finish component installation.

2. **An Apple Developer account, added to Xcode** (*Settings → Accounts*):
   - *For on-device debug* (`build --device`): a **free** Apple ID works via
     Xcode's free provisioning — enough to run on your own registered device.
   - *For distribution* (`build --release` → `.ipa` for App Store / TestFlight /
     ad-hoc): a **paid** Apple Developer Program membership is required.

3. **A signing certificate in your keychain.** With automatic signing (the
   default), Xcode creates/fetches these for you once your account is added:
   - `Apple Development` — used for `--device` debug builds (the pyproject
     default `identity`).
   - A **Distribution** certificate — used for `--release`; automatic signing
     picks the one matching your `--export-method`. Do **not** pin
     `identity = "Apple Development"` onto a release (it requests the wrong
     profile type); leave it unset for `--release`.

4. **Your Apple Developer Team ID.** Required for `--device` and `--release`
   (it becomes `DEVELOPMENT_TEAM`). Find it in the
   [Developer portal](https://developer.apple.com/account) (Membership details)
   or in Xcode. `build` fails fast **before** invoking `xcodebuild` if a signed
   target has no resolvable `team_id`.

5. **Add the signing table to `pyproject.toml`** (or supply the equivalents by
   flag/env for CI):

   ```toml
   [tool.kivy.ios.signing]
   team_id = "ABCDE12345"        # required for --device / --release
   # identity = "Apple Development"   # default; applies to --device debug only
   # provisioning_profile = ""        # name or UUID; empty = automatic
   auto_signing = true            # Xcode automatic signing (CODE_SIGN_STYLE = Automatic)
   ```

   `team_id` and `identity` can also come from `--team-id` / `--signing-identity`
   or the `KIVYFORGE_TEAM_ID` / `KIVYFORGE_SIGNING_IDENTITY` env vars — the
   recommended path for CI and team projects that don't commit signing config.

6. **Decide automatic vs. manual signing:**
   - `auto_signing = true` (default) → every signing `xcodebuild` invocation gets
     `-allowProvisioningUpdates`, so Xcode registers the App ID and
     fetches-or-creates a matching provisioning profile invisibly. This is why an
     account must be *added to Xcode* (step 2) — bare `xcodebuild` can't do it
     otherwise.
   - `auto_signing = false` → **manual** signing: you must supply a pinned
     `identity` **and** a `provisioning_profile` (name or UUID) that already
     exists in your account. kivyforge won't mutate provisioning state.

7. **For a release export, pick the method.** `--release` accepts
   `--export-method app-store|ad-hoc|development` (default `app-store`). This maps
   to the generated `ExportOptions.plist` `method` and, with `team_id`, drives the
   `.ipa` export.

## Sign

```bash
kivyforge doctor -p ios                 # verify Xcode, the identity/profile, host reachability
kivyforge build -p ios --device         # signed on-device debug build
kivyforge build -p ios --release        # archive + export a signed .ipa
```

Run `doctor` first — it pre-checks the setup above. The signing-relevant checks
are **Signing identity** (when `auto_signing = false`, the named identity is
present in the keychain) and **Provisioning profile** (when
`provisioning_profile` is set, it exists). `--simulator` and the bare, no-flag
`build` (which stops after generating the project) skip signing entirely and need
none of this. See the [iOS CLI doctor table](04-cli-ios.md#kivyforge-doctor).

## What gets signed (scope)

- **Xcode signs the build**, not kivyforge. During the Xcode build/archive the
  app binary and every **Embed Frameworks** entry — the per-module `.framework`s
  `install_python` generates, `Python.framework`, and any
  `[tool.kivy.ios.native.xcframeworks]` — are code-signed with your identity.
- **kivyforge's contribution is configuration**: it writes `CODE_SIGN_STYLE`,
  `CODE_SIGN_IDENTITY`, `DEVELOPMENT_TEAM`, and `PROVISIONING_PROFILE_SPECIFIER`
  from `[tool.kivy.ios.signing]`, adds `-allowProvisioningUpdates` when
  `auto_signing` is on, and generates `ExportOptions.plist` for `--release`.
- **`--simulator` is unsigned** — the simulator SDK requires no code signing, so
  the fast dev loop needs no account, certificate, or team.

## Development & test without a paid account

- **Simulator** (`build --simulator`, then `open` + ⌘R on a simulator) requires
  **no signing at all** — the whole build/run loop works with no Apple account.
- **On-device debug** works with a **free** Apple ID via Xcode free provisioning:
  set `team_id` to your personal team, keep `auto_signing = true`, and
  `build --device`. Only **distribution** (`--release` → `.ipa`) needs the paid
  Program.

## Related

- [04-cli-ios.md](04-cli-ios.md) — the iOS CLI spec: `build` signing flags/pre-flight,
  the `--release` archive/export pipeline, and the
  [doctor checks](04-cli-ios.md#kivyforge-doctor).
- [01-pyproject-ios.md](01-pyproject-ios.md#toolkivyiossigning) — the
  `[tool.kivy.ios.signing]` field reference and the generated build-setting map.
- [signing-prerequisites-macos.md](../macos/signing-prerequisites-macos.md) and
  [signing-prerequisites-windows.md](../windows/signing-prerequisites-windows.md)
  — the sibling checklists for the desktop targets.

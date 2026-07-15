# macOS — Signing Prerequisites (how to sign & notarize your kivyforge output)

This is the user-facing checklist for producing a **Developer ID-signed,
notarized, and stapled** macOS `.app` with kivyforge. Signing has two tiers, and
the higher one is **opt-in**: with no configuration, `kivyforge package -p macos`
still produces an **ad-hoc-signed** `.app` (the mandatory Apple-Silicon floor —
the app runs, but a downloaded copy is Gatekeeper-blocked). Configuring a
*Developer ID* identity upgrades `package` to the full **sign + notarize +
staple** distribution path. The *design* behind this — the deep-sign walk,
Hardened Runtime, entitlements, and the notary workflow — lives in the
[macOS spec's Code signing section](macos-spec.md#code-signing); this document
only enumerates what a user must set up **before** running `package`.

> **Status: implemented and verified.** The Developer ID sign + notarize +
> staple path ships and has been exercised end-to-end on real hardware with a
> paid-account *Developer ID Application* certificate. Everything below is what
> that path expects.

## Prerequisites (Developer ID distribution)

Complete these on the macOS build host before signing for distribution. If you
only need the ad-hoc floor, skip to
[Development & test with ad-hoc signing](#development--test-with-ad-hoc-signing).

1. **A paid Apple Developer Program membership.** A free Apple ID **cannot**
   issue Developer ID certificates or use the notary service. Notarized
   distribution outside the App Store requires the paid Program.

2. **A *Developer ID Application* certificate (with its private key) in a
   keychain.** This is the certificate type the notary service accepts — an
   `Apple Development` certificate is rejected. Issue it from Xcode
   (*Settings → Accounts → Manage Certificates → +*) or the Developer portal.

   - *Recommended:* keep the Developer ID identity in a **dedicated keychain**
     rather than `login.keychain-db`, per Apple DTS's
     [Care and Feeding of Developer ID](https://developer.apple.com/forums/thread/732320) —
     unrelated login-keychain churn can corrupt the signing key's ACL (see the
     [`errSecInternalComponent` troubleshooting](macos-spec.md#developer-id-sign--notarize--staple)
     in the spec and the [FAQ](../../../../FAQ.md#macos-developer-id-signing-fails-with-errsecinternalcomponent)).
   - The identity must resolve to **exactly one** certificate in your keychain
     search list — `codesign` refuses to disambiguate a name present in two.

3. **The Xcode command-line tools.** They provide `codesign`, `xcrun`
   (`notarytool`, `stapler`), and `clang` (kivyforge compiles the launcher stub).
   The full Xcode IDE is **not** required for a macOS `.app` (unlike iOS).

4. **A notary keychain profile.** Notary credentials never live in
   `pyproject.toml`; you store them once in the keychain and reference the
   profile by name:

   ```bash
   xcrun notarytool store-credentials kivyforge-notary \
       --apple-id you@example.com --team-id ABC1234XYZ --password <app-specific>
   ```

   Use an **app-specific password** (from appleid.apple.com), not your Apple ID
   password. If you put the Developer ID identity in a dedicated keychain (step 2),
   add `--keychain <name>.keychain-db` here too so everything lives in one place.

5. **Add the signing table to `pyproject.toml`:**

   ```toml
   [tool.kivy.macos.signing]
   identity = "Developer ID Application: Jane Doe (ABC1234XYZ)"  # required for Developer ID
   team_id = "ABC1234XYZ"                                        # informational
   notary_profile = "kivyforge-notary"                          # the profile from step 4

   [tool.kivy.macos.entitlements]   # optional; merged over the hardened defaults (user wins)
   # "com.apple.security.device.camera" = true
   ```

   - `identity` alone → **Developer ID deep sign** (no notarization).
   - `identity` + `notary_profile` → **sign + notarize + staple** (the default).
   - Do **not** set `com.apple.security.get-task-allow = true` in entitlements
     while signing is configured — notarization always rejects it, and kivyforge
     fails fast at config-load time rather than after a slow notary round-trip.

6. **Ensure the notary service is reachable.** `xcrun notarytool submit --wait`
   uploads the zipped `.app` to Apple and polls for the ticket, so the build
   host needs outbound network at package time. Profile *validity* is only truly
   confirmed on this round-trip.

## Sign

```bash
kivyforge doctor -p macos      # verify codesign, the identity, notary setup, host reachability
kivyforge package -p macos     # deep-sign + notarize + staple the .app
```

Run `doctor` first — it pre-checks exactly the setup above and catches the common
mistakes before a full package + notary round-trip. The relevant checks are
**Codesign available**, **Signing identity** (the identity resolves to exactly
one cert; WARN if it lives only in `login.keychain-db`), **Signing identity
type** (WARN unless it's a `Developer ID` certificate), **Notary setup**
(`xcrun notarytool` is available when `notary_profile` is set), and **Required
hosts reachable**. It also WARNs if kivyforge is running as root (a common
`errSecInternalComponent` cause). See the
[spec's doctor table](macos-spec.md#doctor-checks-macos).

## What gets signed (scope)

- **Every Mach-O inside the `.app`** — the launcher stub, the bundled runtime's
  `python3`/`libpython`/`.dylib`s, every wheel `.so`, and any declared native
  binaries under `Contents/Resources/bin/`. The deep sign walks the bundle by
  file magic and signs **inside-out** (deepest first, the `.app` seal last).
- **With Hardened Runtime** (`--options runtime`) and a secure `--timestamp` on
  every signature — both are notarization requirements.
- **The `.app` seal carries the merged entitlements** (the hardened Python
  defaults —  `allow-unsigned-executable-memory`, `disable-library-validation` —
  plus your `[tool.kivy.macos.entitlements]` layered on top).
- **`build` / `run` stay ad-hoc regardless of config.** Developer ID signing and
  its keychain prompts / notary round-trips belong to the `package` verb, not the
  dev loop.
- **`.dmg` creation and its signing/notarization are out of scope** (permanently).
  Wrap the already-notarized `.app` with an external tool; the spec shows the
  copy-pasteable `codesign`/`notarytool`/`stapler` commands for the container.

## Development & test with ad-hoc signing

Ad-hoc signing is the **mandatory floor** and needs **no Apple Developer
account** — arm64 executables must be at least ad-hoc signed or the kernel
refuses to run them. With no `[tool.kivy.macos.signing]` table, `package`
produces an ad-hoc `.app`:

```
codesign --sign - MyApp.app   # what kivyforge does under the hood
```

It provides *integrity*, not *trust*: the app runs locally and when shared
without a quarantine attribute, but a **downloaded** (quarantined) copy is
Gatekeeper-blocked and needs right-click → Open (or
`xattr -dr com.apple.quarantine MyApp.app`). This is enough to exercise the whole
bundle/build/run pipeline; it just can't be distributed to end users cleanly.

## Related

- [macos-spec.md](macos-spec.md) — the macOS backend spec, including the full
  [Code signing](macos-spec.md#code-signing) design (ad-hoc floor, Developer ID
  deep sign, notarize + staple, entitlements) and the
  [doctor table](macos-spec.md#doctor-checks-macos).
- [FAQ.md](../../../../FAQ.md#macos-developer-id-signing-fails-with-errsecinternalcomponent)
  — the `errSecInternalComponent` keychain-corruption troubleshooting.
- [signing-prerequisites-windows.md](../windows/signing-prerequisites-windows.md)
  — the sibling checklist for Windows Authenticode signing.

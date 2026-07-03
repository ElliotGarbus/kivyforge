# 06 — Packaging Scope

kivyforge draws a deliberate line between **producing the runnable application artifact** (in scope, including signing) and **wrapping that artifact into an installer or container** (out of scope, delegated to dedicated external tools). This document states the principle, the per-platform artifact each backend produces, and the recommended external tools for the installer step.

## The principle

> **kivyforge builds and signs the runnable application artifact. Wrapping it into an installer/container is out of scope.**

The seam is clean: kivyforge emits the finished, signed artifact; an external tool ingests it to produce a distribution container. Two consequences:

- **Signing stays inside kivyforge.** Signing must operate on the *bundled binaries* (the app's own Mach-O/PE/ELF plus the Python runtime and every bundled `.so`/`.dylib`/`.dll`). That is intrinsic to producing a correct artifact, so kivyforge owns it. Only the installer/container step is external.
- **Installers/containers are a separate, mature ecosystem.** `.dmg`, MSI, `.deb`/`.rpm`, Flatpak, and store submission are well served by dedicated tools. Re-implementing them would add surface area with little benefit; kivyforge stops at the artifact and points users at the right tool.

## Per-platform runnable artifact

| Platform | In-scope runnable artifact (kivyforge produces + signs) | Out of scope (external tools) |
|----------|----------------------------------------------------------|-------------------------------|
| iOS | Xcode-built app / `.ipa` | App Store submission |
| macOS | `.app` bundle (`package -f app`) | `.dmg`/installer; store submission |
| Windows | application folder + launcher `.exe` (onedir bundle) | MSI / Inno Setup / NSIS installer |
| Linux | user-selectable via `package -f`: `folder` or `appimage` | `.deb` / `.rpm` / Flatpak |
| Android | `.apk` / `.aab` (artifact *and* installable unit) | Play Store submission |

Android is the one case where the runnable artifact and the installable unit are the same thing — an `.apk`/`.aab` is both — so producing it is fully in scope (only store submission is external).

## Recommended external tools (installer/container step)

These are recommendations for the step *after* kivyforge, applied to the artifact kivyforge already produced and signed:

- **macOS `.dmg`** — `create-dmg`, `dmgbuild`, or a GUI tool such as DropDMG. (kivyforge never builds `.dmg` files.)
- **Windows installer** — WiX/MSI, Inno Setup, or NSIS, wrapping the onedir folder + `.exe`.
- **Linux native packages** — `fpm` (`.deb`/`.rpm`), `appimagetool` (if hand-rolling AppImage beyond `package -f appimage`), or `flatpak-builder` (Flatpak).
- **App/Play Store submission** — the vendor's own upload path (Transporter/App Store Connect, Play Console).

## Signing across the seam

Signing is per-platform and stays with kivyforge because it operates on the bundled binaries:

- **iOS** — Xcode-driven signing (team ID / identity / provisioning), including `.ipa` export methods. See [iOS CLI](../platforms/ios/cli-ios.md).
- **macOS** — starts with **ad-hoc** signing (the mandatory Apple-Silicon floor: arm64 executables must be at least ad-hoc signed or the kernel refuses to run them). Full Developer ID **sign + notarize + staple** of the `.app` is a later workstream (see the [macOS spec](../platforms/macos/macos-spec.md)). Notarizing an external `.dmg` is a post-packaging step on a container kivyforge does not build; the docs provide a copy-paste snippet for users who distribute a `.dmg`.
- **Windows** — Authenticode signing of the artifact (`signtool`) is in scope with the artifact step; the installer is signed separately by the external installer tool.
- **Android** — app signing is in scope (the `.apk`/`.aab` is the shippable unit).

## Why draw the line here

- **A clean, testable seam.** "Produce a signed, runnable artifact" is a crisp, verifiable output; "make an installer" branches into many platform- and org-specific conventions.
- **Reuse over reinvention.** The installer/container ecosystems are mature and often already part of a team's release pipeline.
- **Focus.** kivyforge's value is the hard part — turning a declarative `pyproject.toml` into a correct, signed, runnable app across platforms — not repackaging that app into every possible distribution format.

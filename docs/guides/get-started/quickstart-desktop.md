---
title: "Quickstart: build a desktop app"
sources:
  - docs/design/common/02-cli-and-platform-resolution.md
  - examples/desktop/dice-roller/pyproject.toml
  - docs/design/platforms/macos/macos-spec.md
  - docs/design/platforms/linux/linux-spec.md
  - docs/design/platforms/windows/windows-spec.md
---

# Quickstart: build a desktop app

In this quickstart you lock, build, run, and package a small Kivy app for the
operating system you are on: a `.app` bundle on macOS, an AppImage on Linux, or
an onedir folder (a folder that holds the app and a launcher `.exe`) on Windows.
The first run spends most of its time downloading the Python runtime and wheels.

## Before you begin

- A macOS (Apple Silicon), Linux, or Windows machine. You build for the
  operating system you are on, so no cross-compilation toolchain is needed.
- kivyforge, installed as described in [Install kivyforge](install.md). The
  example app sets an icon, so on Linux install the `linux` extra and on Windows
  the `windows` extra. On macOS, also install the Xcode command-line tools.
- [git](https://git-scm.com/), to fetch the example app.

## Step 1: Get the example app

Clone the repository and change into the `dice-roller` example, which is already
configured for macOS, Linux, and Windows:

```bash
git clone https://github.com/ElliotGarbus/kivyforge.git
cd kivyforge/examples/desktop/dice-roller
```

Run every command from this directory. kivyforge reads the `pyproject.toml` in
the current directory and does not search parent directories.

## Step 2: Adjust the example for your machine

The example carries two settings that match its author's machine. Edit
`pyproject.toml` now, before you lock, because any later edit makes the
lockfile out of date:

- **macOS:** delete the whole `[tool.kivy.macos.signing]` table (the
  `identity`, `team_id`, and `notary_profile` lines). It names the author's
  Developer ID certificate, which is not in your keychain. Without it,
  kivyforge ad-hoc signs the app.
- **Linux on an ARM machine** (for example a Raspberry Pi): in
  `[tool.kivy.linux]`, change `archs = ["x86_64"]` to `archs = ["aarch64"]`.

On Windows, and on x86_64 Linux, skip this step.

## Step 3: Check your environment

`doctor` verifies that this host can build the target and that the toolchain is
present. It picks the target from your operating system, because the example
configures an overlay for it, so you do not need `-p`.

```bash
kivyforge doctor
```

Fix anything it reports as `FAIL` before you continue. `WARN` items are safe to
leave for now.

## Step 4: Lock the dependencies

Resolve the app's dependencies for your platform and write the lockfile:

```bash
kivyforge lock
```

This writes `pylock.macos.toml`, `pylock.linux.toml`, or `pylock.windows.toml`,
with every artifact pinned by URL and SHA-256. See
[Lockfiles](../concepts/lockfiles.md) for what that means.

## Step 5: Build and run

Build the app and launch it:

```bash
kivyforge run
```

`run` builds the app, then starts it. A window titled **Dice Roller** opens.
Select **Roll** to roll the dice. This is the development loop: edit the Python
source under `src/`, then run `kivyforge run` again.

The build lands in `build/macos/Dice Roller.app`,
`build/linux/Dice Roller.AppDir`, or `build/windows/Dice Roller`, depending on
your platform.

!!! tip
    To build without launching, use `kivyforge build`. To remove the generated
    output and start fresh, run `kivyforge clean`.

## Step 6: Package the distributable

Produce the finished artifact for your platform:

```bash
kivyforge package
```

What you get depends on your platform:

=== "macOS"
    An ad-hoc signed `build/macos/Dice Roller.app`. To distribute it outside
    your own machine, configure Developer ID signing; see
    [Sign, notarize, and staple](../guides/macos/signing.md).

=== "Linux"
    A self-contained `dist/linux/dice-roller-0.1.0-x86_64.AppImage` (the arch
    in the name follows `archs`). For a run-from-folder AppDir instead, run
    `kivyforge package -f folder`.

=== "Windows"
    An unsigned onedir folder at `dist/windows/Dice Roller-0.1.0-amd64`. Double-click
    `Dice Roller.exe` inside it to start the app. To sign it, see
    [Sign with Authenticode](../guides/windows/signing.md).

## Verify

`package` prints a `Packaged ...` line naming the artifact, relative to the
project root. To get the same information as structured data, run:

```bash
kivyforge package --json
```

The `data.artifacts` array lists what this run produced, as `{"path", "kind"}`
entries. A warning in `diagnostics` that the package is unsigned or ad-hoc
signed is expected here.

## What's next

- [Project configuration](../concepts/configuration.md): make it your own app.
- [Build versus package](../concepts/build-vs-package.md): when to use each verb.
- Ship it: [macOS](../guides/macos/build.md), [Windows](../guides/windows/build.md),
  or [Linux](../guides/linux/build.md).

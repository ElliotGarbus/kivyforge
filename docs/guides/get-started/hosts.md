---
title: Which host builds which target
sources:
  - docs/design/common/02-cli-and-platform-resolution.md
  - kivyforge/capabilities.py
  - README.md
---

# Which host builds which target

Not every operating system can build every target. Check this before you pick a
target.

The table below is generated from kivyforge's own host checks, the same ones
`kivyforge build` and `kivyforge package` enforce. To read it on your machine,
run `kivyforge capabilities`, or `kivyforge capabilities --json` for a
machine-readable version.

## Host support matrix

<!-- kf:host-matrix -->

## How to read this

- **Yes** means the host can build that target.
- **No** means it cannot. `build` and `package` fail fast with
  `KF-HOST-INCAPABLE` (exit code 3) instead of producing something broken.

The key constraints:

- **iOS builds require macOS with Xcode.** There is no way to build an iOS app
  from Windows or Linux.
- **macOS apps build on macOS.** The only target architecture is `arm64`
  (Apple Silicon).
- **Android builds run on any desktop host** (Windows, macOS, or Linux) that has
  a JDK, the Android SDK, and the Android NDK installed.
- **Windows apps build on Windows**, and **Linux apps build on Linux.**

A **Yes** says the operating system can build the target. Whether the toolchain
is installed is a separate question: `kivyforge doctor -p PLATFORM` answers it.
Replace `PLATFORM` with the target name.

## Target selection versus host capability

These are two independent questions:

- *What are you building for?* That is target selection, covered in
  [Choose a target platform](../concepts/choose-platform.md).
- *Can this machine build it?* That is host capability, the table above.

## What's next

- [Choose a target platform](../concepts/choose-platform.md).
- [Install kivyforge](install.md), then build for a target you can run here.
- [Diagnose a failing build](../troubleshooting/index.md).

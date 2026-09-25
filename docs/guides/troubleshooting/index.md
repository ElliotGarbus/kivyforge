---
title: Diagnose a failing build
sources:
  - kivyforge/report/exit_codes.py
  - kivyforge/report/diagnostics.py
  - kivyforge/platforms/android/doctor.py
  - kivyforge/platforms/ios/doctor.py
  - kivyforge/platforms/macos/doctor.py
  - kivyforge/platforms/windows/doctor.py
  - kivyforge/platforms/linux/doctor.py
  - FAQ.md
---

# Diagnose a failing build

When a command fails, kivyforge tells you what kind of failure it is and what to
do next. This page shows where to start, how to read the result, and how to
capture the full build log.

## Start with doctor

`doctor` checks the host environment and the project for the target platform.
Run it first:

```bash
kivyforge doctor -p PLATFORM
```

Replace `PLATFORM` with the target, for example `android`.

Fix every check reported as **FAIL**; `doctor` exits non-zero only when at least
one check fails. **WARN** results don't block a build, but read them. The checks
depend on the target:

| Target | What `doctor` checks |
|---|---|
| Android | JDK, Android SDK, build-tools, NDK, SDK licenses, `adb` and emulator, Kivy and SDL match, release signing, icon and splash assets, manifest policy, ABI (application binary interface) coverage, 16 KB page alignment |
| iOS | Xcode and command-line tools, simulator runtimes, signing identity, provisioning profile and entitlements, icon, privacy manifests, host reachability |
| macOS | `codesign`, signing identity and certificate type, notarization setup, architecture coverage, runtime floor, icon, native binaries, host reachability |
| Windows | Long-path support, AppUserModelID, icon, native binaries, locked build output, `signtool` and signing certificate, host reachability |
| Linux | GL libraries, display session, glibc floor, architecture coverage, icon, `.desktop` entry, native binaries, host reachability |

To skip the checks that need the network, pass `--offline`.

## Read the exit code, then the diagnostic

The exit code tells you the kind of failure:

| Exit code | What to do |
|---|---|
| `1` | Fix `pyproject.toml` or the command, then retry. |
| `3` | Install the missing tool, or use a host that can build the target, then retry. |
| `4` | Re-lock with `kivyforge lock -p PLATFORM`. |
| `5` | Read the build log on stderr. |

With `--json`, `diagnostics[].code` names the specific cause. See
[Exit and diagnostic codes](../reference/codes.md) for every code and its
remediation.

## Common failures

| Code | What happened | Fix |
|---|---|---|
| `KF-LOCK-DRIFT` | `pyproject.toml` changed since the lock was written. | Run `kivyforge lock -p PLATFORM`. |
| `KF-LOCK-MISSING` | The target has no lockfile. | Run `kivyforge lock -p PLATFORM`. |
| `KF-TOOLCHAIN-MISSING` | A required tool is not installed. | Install the tool the message names. |
| `KF-HOST-INCAPABLE` | This host can't build the target, for example iOS on Windows. | Build on a [supported host](../get-started/hosts.md). |
| `KF-BUILD-TOOL-FAILED` | Gradle, `xcodebuild`, or `appimagetool` ran and failed. | Read the build log on stderr. |
| `KF-SIGNING-UNCONFIGURED` | A warning: the package shipped unsigned or ad-hoc signed. | [Configure signing](signing-prerequisites.md), or ship unsigned on purpose. |

## Capture the build log

kivyforge writes the result to stdout and everything else, including the
toolchain's own log, to stderr. To capture both in one file:

=== "PowerShell"
    ```powershell
    kivyforge package -p android *> build.log
    ```

=== "bash"
    ```bash
    kivyforge package -p android > build.log 2>&1
    ```

If you redirect only stdout, the file doesn't contain the build log.

## Platform-specific problems

The [FAQ](../faq.md) covers common platform problems, including:

- iOS: the simulator SDK can't be located, a `Python.xcframework` download
  returns HTTP 404, and an invalid character in the bundle identifier.
- macOS: Developer ID signing fails with `errSecInternalComponent`.
- Linux: `libfuse2` errors, headless builds, the glibc floor, and WSL2.
- Windows: SmartScreen warnings, long-path errors, and a black console window.

## What's next

- [Exit and diagnostic codes](../reference/codes.md)
- [Signing prerequisites](signing-prerequisites.md)
- [FAQ](../faq.md)

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
| `KF-BYTECOMPILE-NO-INTERP` | Byte-compiling needs a CPython of the minor your app ships on this machine, and there is none. A warning when the build shipped source instead; an error with `byte_compile = true`. | Run `kivyforge bytecompiler -p PLATFORM`, or install that CPython yourself. |
| `KF-HOST-PYTHON-FETCH` | `kivyforge bytecompiler` couldn't download its CPython: no network, a GitHub rate limit, or a download that failed its check. | Retry with network access. In CI, set `GITHUB_TOKEN`. |
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

## When Gradle fails

Gradle's own advice, "Run with --stacktrace" or "Run with --info", means
rerunning the same kivyforge command with `-v` or `-vv`:

```bash
kivyforge build -p android --debug -v
```

`-v` adds `--stacktrace` to every Gradle run and prints the folder and the exact
`gradlew` command before it starts. `-vv` also adds `--info`, which makes the
log thousands of lines longer. `KIVYFORGE_VERBOSE=1` or `2` does the same for
every command, which is useful in CI. See [Verbose output](../reference/cli.md#verbose-output).

For any other Gradle flag, run Gradle yourself. The generated project,
`<app>-android/` next to your `pyproject.toml`, is complete on its own, so the
command `-v` printed works from that folder, with whatever flags you add:

=== "PowerShell"
    ```powershell
    cd hello-android-android
    .\gradlew.bat --console=plain --stacktrace assembleDebug --debug
    ```

=== "bash"
    ```bash
    cd hello-android-android
    ./gradlew --console=plain --stacktrace assembleDebug --debug
    ```

For a release task (`package`, or `run --release`), first set the keystore
password variables that `-v` names. The next `kivyforge build` overwrites any
edit you make in that folder, so use it to diagnose a failure, not to fix it.

## Platform-specific problems

The [FAQ](../faq.md) covers common platform problems, including:

- Android: the harmless "SDK XML versions up to 3" warning.
- iOS: the simulator SDK can't be located, a `Python.xcframework` download
  returns HTTP 404, and an invalid character in the bundle identifier.
- macOS: Developer ID signing fails with `errSecInternalComponent`.
- Linux: `libfuse2` errors, headless builds, the glibc floor, and WSL2.
- Windows: SmartScreen warnings, long-path errors, and a black console window.

To find your app's own output in a noisy Android log, see [Filter the app's
log](../guides/android/run.md#filter-the-apps-log).

## Known issues on iOS

Both issues are in the Kivy iOS wheel, not in your project.

- **Rotation breaks on iOS 27.** After you rotate the device, or launch in
  landscape, `Window.size` snaps back to portrait while the screen stays in
  landscape, so most of the UI is drawn off screen. The app can also crash when
  you rotate back. iOS 26 and earlier are not affected. The cause is SDL 3.4.2,
  and the fix needs an SDL release that includes it and a new Kivy wheel. Follow
  [#195](https://github.com/ElliotGarbus/kivyforge/issues/195).
- **Text is blank, or KivyMD crashes with `FBO Initialization failed`.** Calling
  `dp()` or `sp()` before the window exists caches a density of 0, and KivyMD
  does this when imported. Until a wheel with
  [kivy/kivy#9443](https://github.com/kivy/kivy/pull/9443) is published, set the
  density at the top of `main.py`, before anything imports Kivy:

    ```python
    import os

    os.environ["KIVY_METRICS_DENSITY"] = "3"
    ```

## Report a problem

kivyforge is in beta, so a report helps even when you found a way around the
problem. Search the [open issues](https://github.com/ElliotGarbus/kivyforge/issues)
first, then [open a new one](https://github.com/ElliotGarbus/kivyforge/issues/new/choose)
with:

- The output of `kivyforge --version`.
- The output of `kivyforge doctor -p PLATFORM`, for the target you are building.
- The exact command you ran, and the build log from
  [Capture the build log](#capture-the-build-log). For Android, add `-v`.
- Your `pyproject.toml`, or a small project that reproduces the problem.
- For a failure on a device, the device model and its OS version.

Check that the log and `pyproject.toml` hold no passwords, tokens, or private
paths before you post them.

## What's next

- [Exit and diagnostic codes](../reference/codes.md)
- [Signing prerequisites](signing-prerequisites.md)
- [FAQ](../faq.md)

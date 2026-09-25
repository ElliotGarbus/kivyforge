---
title: Avoid Windows file-locking problems
sources:
  - docs/design/platforms/windows/windows-spec.md
  - FAQ.md
---

# Avoid Windows file-locking problems

Windows does not let a program replace files that another process holds open.
If your app is still running, or an Explorer window is open in the output
folder, a rebuild can fail with an "Access is denied" error (`WinError 5`).
This page shows how to avoid that and how to recover.

## Close the app before rebuilding

Each `build` or `package` first moves the previous bundle aside, then writes
the new one. A running copy of the app, or an Explorer or terminal window
sitting in `build\windows`, holds the folder open and blocks that move. Close
the app window, or stop `kivyforge run`, before you build again.

`kivyforge doctor -p windows` checks for this. Its "Build output not locked"
check warns when another process holds the built bundle open.

## Use a short project path

The bundled Python runtime nests deep under `build\windows\`, and Windows
limits paths to 260 characters unless long-path support is on. Keep your
project close to the drive root, or turn on long paths. In an administrator
PowerShell, run:

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
  -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force
```

Restart Windows afterward. `kivyforge doctor -p windows` warns when long-path
support is off. For the limit on your users' machines, see
[Keep paths short](build.md#keep-paths-short).

## Use a Dev Drive

Antivirus real-time scanning can hold newly written files open for a moment.
On Windows 11, a [Dev Drive](https://learn.microsoft.com/windows/dev-drive/)
is a ReFS volume where Microsoft Defender can scan asynchronously in
performance mode, which reduces this interference. If you rebuild often and
hit locking errors, put your project on a Dev Drive. `kivyforge doctor -p
windows` reports the build volume's file system in its "Build volume" check.

## If a file stays locked

- In Task Manager, confirm that no copy of your app's `.exe` or of the
  bundle's `python.exe` is still running.
- Close any Explorer or terminal window whose current folder is inside
  `build\windows` or `dist\windows`.
- As a last resort, run `kivyforge clean`. It takes no `-p` option: it removes
  the generated output for every platform in the project, including
  `build\windows` and `dist\windows`, so the next build starts fresh.

## What's next

- [Build a Windows onedir app](build.md).
- [Understand the Windows launcher](launcher.md).
- [Diagnose a failing build](../../troubleshooting/index.md).

---
title: Create a Windows installer
sources:
  - docs/design/platforms/windows/windows-spec.md
  - docs/design/platforms/windows/signing-windows.md
  - docs/design/common/06-packaging-scope.md
  - docs/design/dev/test-matrix.md
  - examples/desktop/dice-roller/pyproject.toml
---

# Create a Windows installer

kivyforge does not produce Windows installers. `kivyforge package -p windows`
produces a run-from-folder bundle, signs its launcher if you configured signing,
and stops. You can ship that folder as a `.zip`, or wrap it in an installer
with a tool of your choice, such as Inno Setup, NSIS, or WiX. This page shows
one way to do that with [Inno Setup](https://jrsoftware.org/isinfo.php).

!!! note
    Everything after step 1 happens outside kivyforge. kivyforge does not run,
    configure, or sign the installer, and it does not check the installer's
    output.

## Before you begin

- A packaged bundle from `kivyforge package -p windows`, ideally with a
  [signed launcher](signing.md).
- [Inno Setup](https://jrsoftware.org/isinfo.php) 6.3 or later.
- If you plan to sign the installer, `signtool.exe` and a code-signing
  certificate. See [Sign a Windows app with Authenticode](signing.md).

## Step 1: Package the bundle

```powershell
kivyforge package -p windows
```

This produces `dist\windows\DISPLAY_NAME-VERSION-amd64\`, which holds the
launcher `DISPLAY_NAME.exe` and the runtime. The rest of this page uses the
`dice-roller` example, which packages to
`dist\windows\Dice Roller-0.1.0-amd64\`.

If `package` reports a `KF-PATH-DEPTH` warning, the bundle only works from an
install folder shorter than the length the warning gives. Choose a short
default install folder in step 2. See
[Keep paths short](build.md#keep-paths-short).

## Step 2: Write an Inno Setup script

Create `DiceRoller.iss` in the project root, next to the `dist` folder:

```ini
[Setup]
AppName=Dice Roller
AppVersion=0.1.0
DefaultDirName={autopf}\Dice Roller
DefaultGroupName=Dice Roller
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=DiceRoller-0.1.0-Setup

[Files]
Source: "dist\windows\Dice Roller-0.1.0-amd64\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Dice Roller"; Filename: "{app}\Dice Roller.exe"
```

The `[Files]` entry copies the whole packaged folder into the install folder.
The `[Icons]` entry points the Start menu shortcut at the launcher, not at
`python.exe`.

## Step 3: Compile the installer

Open `DiceRoller.iss` in the Inno Setup Compiler and compile it, or run the
command-line compiler:

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" DiceRoller.iss
```

Inno Setup writes `Output\DiceRoller-0.1.0-Setup.exe` next to the script.

## Step 4: Sign the installer

kivyforge signs only the launcher inside the bundle. Sign the installer
yourself. Users see the installer's signature first, so it matters for
Microsoft Defender SmartScreen. These `signtool` options match the ones
kivyforge uses for the launcher:

```powershell
signtool sign /sha1 CERT_THUMBPRINT /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 Output\DiceRoller-0.1.0-Setup.exe
```

Replace `CERT_THUMBPRINT` with your certificate's thumbprint. Add `/sm` if the
certificate is in the machine store.

## Verify

1. Run the installer on a clean Windows machine.
2. Start the app from the Start menu. The window opens with no console window.
3. Right-click the installer, select **Properties**, and confirm the **Digital
   Signatures** tab lists your certificate.

## What's next

- [Sign a Windows app with Authenticode](signing.md).
- [Build versus package](../../concepts/build-vs-package.md), which covers where
  kivyforge's job ends.
- [Build a Windows onedir app](build.md).

---
title: Sign a Windows app with Authenticode
sources:
  - docs/design/platforms/windows/signing-prerequisites-windows.md
  - docs/design/platforms/windows/signing-windows.md
  - FAQ.md
---

# Sign a Windows app with Authenticode

Signing a Windows app is opt-in. With no configuration,
`kivyforge package -p windows` ships the launcher unsigned. This page shows how
to point kivyforge at a code-signing certificate so that `package` signs and
timestamps the launcher with Authenticode, Microsoft's code-signing format.

## Before you begin

- A Windows build host.
- A code-signing certificate with its private key, imported into a Windows
  certificate store. To distribute, you need a publicly trusted OV
  (Organization Validation) or EV (Extended Validation) certificate. To test,
  a self-signed certificate exercises the whole pipeline. See
  [Test with a self-signed certificate](#test-with-a-self-signed-certificate).
- `signtool.exe` on `PATH`. It ships with the Windows SDK and is on `PATH` in a
  Developer Command Prompt.

## Step 1: Find the certificate thumbprint

kivyforge identifies the certificate by its SHA-1 thumbprint in the certificate
store. It never takes a `.pfx` file or a password. List the code-signing
certificates in your user store:

```powershell
Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Select-Object Subject, Thumbprint
```

For a certificate in the machine store, use `Cert:\LocalMachine\My` instead.

## Step 2: Configure the signing table

Add a `[tool.kivy.windows.signing]` table to `pyproject.toml`:

```toml
[tool.kivy.windows.signing]
thumbprint = "CERT_THUMBPRINT"
```

Replace `CERT_THUMBPRINT` with the thumbprint from step 1. Spaces and letter
case in the thumbprint do not matter.

Two optional keys change where the certificate is found and which timestamp
server is used:

```toml
[tool.kivy.windows.signing]
thumbprint = "CERT_THUMBPRINT"
store_scope = "machine"
timestamp_url = "TIMESTAMP_URL"
```

- `store_scope` is `"current_user"` (the default, `Cert:\CurrentUser\My`) or
  `"machine"` (`Cert:\LocalMachine\My`).
- Replace `TIMESTAMP_URL` with your certificate authority's RFC 3161 timestamp
  server. The default is `http://timestamp.digicert.com`.

## Step 3: Check the setup

```powershell
kivyforge doctor -p windows
```

`doctor` checks that `signtool` is on `PATH`, that the thumbprint matches
exactly one code-signing certificate in the configured store, and that the
timestamp server is reachable.

## Step 4: Package

```powershell
kivyforge package -p windows
```

`package` runs `signtool` on the launcher in the `dist\windows` copy, with a
SHA-256 digest and an RFC 3161 timestamp. The timestamp keeps the signature
valid after the certificate expires. If signing fails, `package` fails and
restores the previous packaged folder, if there was one.

## Verify

Right-click the `.exe` in the `dist\windows` folder, select **Properties**, and
open the **Digital Signatures** tab. Your certificate is listed with a
timestamp.

## What gets signed

kivyforge signs only the launcher `.exe`, and only in the `dist\windows` copy.
The development bundle in `build\windows` stays unsigned. kivyforge does not
sign the runtime's DLLs or `.pyd` files, and it does not sign installers. If you
[build an installer](installer.md), sign it yourself.

## SmartScreen

Signing does not immediately silence Microsoft Defender SmartScreen. With an
OV certificate, the "Windows protected your PC" prompt stops only after your
app builds up download reputation. This is Microsoft's policy, not kivyforge
behavior.

## Test with a self-signed certificate

A self-signed certificate drives the whole pipeline, but it does not satisfy
SmartScreen. Create one in your user store:

```powershell
New-SelfSignedCertificate -Type CodeSigningCert `
  -Subject "CN=KivyForge Test Signer" -CertStoreLocation Cert:\CurrentUser\My `
  -KeyUsage DigitalSignature -KeyExportPolicy Exportable -HashAlgorithm SHA256
```

Set its thumbprint in the signing table, then package as in step 4.

## What's next

- [Create a Windows installer](installer.md) around the signed bundle.
- [Build a Windows onedir app](build.md).
- [Signing prerequisites](../../troubleshooting/signing-prerequisites.md) for
  all platforms.

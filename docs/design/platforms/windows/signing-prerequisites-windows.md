# Windows — Signing Prerequisites (how to sign your kivyforge output)

This is the user-facing checklist for producing an **Authenticode-signed**
Windows app with kivyforge. Signing is **opt-in**: with no configuration,
`kivyforge package -p windows` ships the artifact **unsigned** (the documented
v1 default). The *design* behind this — the `Signer` protocol, thumbprint
identity, and Inno composition — lives in
[signing-windows.md](signing-windows.md); this document only enumerates what a
user must set up **before** running `package`.

> **Status: implemented.** The signing hook ships
> (`kivyforge/platforms/windows/signing.py`); everything below is exercised in
> CI against a self-signed certificate.

## Prerequisites

Complete these on the Windows build host before signing.

1. **A code-signing certificate (with its private key).**
   - *For distribution:* a publicly-trusted code-signing certificate. Since 2023
     the CA/Browser Forum requires the private key in hardware/HSM, so in
     practice this is an EV/OV hardware token or a cloud-held key.
   - *For development / testing:* a self-signed certificate is enough to exercise
     the whole pipeline (it just won't satisfy SmartScreen) — see
     [Development & test with a self-signed cert](#development--test-with-a-self-signed-cert).

2. **Import the certificate into the Windows certificate store**, in the scope you
   will configure. kivyforge never takes a `.pfx` path or password — it
   references the certificate **in the store**:
   - `Cert:\CurrentUser\My` — the default (`store_scope = "current_user"`), or
   - `Cert:\LocalMachine\My` — when `store_scope = "machine"` (requires admin;
     adds signtool's `/sm`).

3. **Note the certificate's SHA-1 thumbprint** — this is the value you put in
   config:

   ```powershell
   Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Select-Object Subject, Thumbprint
   ```

4. **Make `signtool.exe` available on `PATH`.** It ships with the Windows SDK /
   Visual Studio Build Tools (or run from a "Developer Command Prompt").
   kivyforge shells out to it.

5. **Add the signing table to `pyproject.toml`:**

   ```toml
   [tool.kivy.windows.signing]
   thumbprint = "A1B2C3..."                          # required (SHA-1, from step 3)
   # store_scope = "current_user"                    # default; "machine" -> LocalMachine\My + /sm
   # timestamp_url = "http://timestamp.digicert.com" # default shown
   ```

6. **Ensure the RFC-3161 timestamp server is reachable.** Signing is *always*
   timestamped (so a signature outlives the certificate's expiry), so the
   timestamp host must be reachable at build time — the default
   `timestamp.digicert.com` over HTTP (port 80).

## Sign

```powershell
kivyforge doctor -p windows      # verify signtool, the cert in the configured store, timestamp reachability
kivyforge package -p windows     # signs the launcher in the dist\windows copy
```

Run `doctor` first — it pre-checks exactly the setup above and catches the common
mistakes (`signtool` not on `PATH`, the certificate imported into the wrong
store, an unreachable timestamp server) before a full package. The relevant
checks are **signtool available**, **Signing certificate** (the thumbprint
resolves to exactly one code-signing cert in the *configured* `store_scope`
store), and **Required hosts reachable** (which includes the timestamp host when
signing is configured). See the
[spec's doctor table](windows-spec.md#doctor-checks-windows).

## What gets signed (v1 scope)

- **Only the launcher `.exe`** — the file SmartScreen and users actually judge.
- **Only the `dist\windows\...` copy** — the `build\windows` dev tree stays
  unsigned and re-runnable.
- **Payload DLLs/`.pyd`s** (CPython, Kivy, SDL, declared native binaries) are
  **not** signed in v1; that is a v2 concern and only matters under Smart App
  Control / WDAC, not SmartScreen. onedir keeps them individually signable later.

## Development & test with a self-signed cert

A self-signed certificate drives the *entire* orchestration (config parsing,
thumbprint lookup, signing, timestamping, verification) at full fidelity — it
only cannot replicate SmartScreen reputation, so it is a dev/CI fixture, **not**
for distribution.

```powershell
# 1. Create a self-signed code-signing cert in CurrentUser\My
New-SelfSignedCertificate -Type CodeSigningCert `
  -Subject "CN=KivyForge Test Signer" -CertStoreLocation Cert:\CurrentUser\My `
  -KeyUsage DigitalSignature -KeyExportPolicy Exportable -HashAlgorithm SHA256

# 2. (Optional) so `signtool verify /pa` trusts the chain, import the public
#    cert into LocalMachine\Root (admin). Not needed for a real CA-issued cert.
Export-Certificate -Cert Cert:\CurrentUser\My\<thumbprint> -FilePath test-signer.cer
Import-Certificate -FilePath test-signer.cer -CertStoreLocation Cert:\LocalMachine\Root
```

Then set the thumbprint in `[tool.kivy.windows.signing]` and `package` as above.

## Related

- [signing-windows.md](signing-windows.md) — the signing design (policy, `Signer`
  protocol, PEP 440 → version resource, Inno composition).
- [windows-spec.md](windows-spec.md) — the Windows backend spec (verbs, `doctor`
  table, scope).

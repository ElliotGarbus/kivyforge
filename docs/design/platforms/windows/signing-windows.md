# Windows — Signing Design

Authenticode signing of the Windows artifact, per the
[common packaging-scope principle](../../common/06-packaging-scope.md):
signing operates on the bundled binaries, so it stays inside kivyforge; the
installer step is external. This document specifies the policy (ship v1
unsigned, hook first-class from day one), the architecture (a `Signer`
protocol + thumbprint identity), the composition with an external Inno Setup
step, and the self-signed dev/CI flow.

> **Status: implemented** (tracked with the [Windows spec](windows-spec.md)). The
> signing hook ships (`kivyforge/platforms/windows/signing.py`): a `Signer`
> protocol with `SigntoolSigner` + `NullSigner`, off by default, verified against
> a self-signed certificate in CI. v1 ships the default artifact unsigned.

## Policy

- **Skip signing kivyforge's own binaries for now** (the prebuilt bootloader
  asset, kivyforge's releases). The developer audience tolerates the
  SmartScreen wall; a certificate costs money and process; this matches the
  defer-pending-demand pattern used across the backends.
- **But build the signing hook as a first-class, optional pipeline step from
  day one.** For a *packaging tool*, signing the **output** is a feature
  users will need — their end users will not click through "Windows protected
  your PC."
- Ship v1 unsigned + **document the wall**: what SmartScreen shows for an
  unsigned/unknown binary, plus a short "how to sign your kivyforge output"
  guide (get a cert into the store → set the thumbprint → `package`) — the
  user-facing prerequisites checklist lives in
  [signing-prerequisites-windows.md](signing-prerequisites-windows.md).

## Architecture

### The `Signer` protocol

A swappable-backend seam, the same shape as the existing `Downloader` and
`RuntimeProvider` protocols. Note that no `Signer` abstraction exists in the
codebase today — macOS signing is free functions in
`platforms/macos/signing.py`, iOS signing rides Xcode build settings (the
[abstraction-leak retro](../../common/abstraction-leak-retro.md) records this
explicitly). **Windows introduces the protocol**; it lives in
`platforms/windows/signing.py` and is *not* retrofitted onto macOS/iOS —
Windows signing is genuinely pluggable (store cert, hardware token, cloud
signer) in a way Apple's keychain-bound flow is not, so the seam earns its
keep here without forcing a shared abstraction the other backends don't need.

```python
class Signer(Protocol):
    def sign(self, paths: Sequence[Path]) -> None: ...
```

Backends:

- **`SigntoolSigner`** — the default: shells out to `signtool sign` with the
  configured thumbprint (`/sha1 <thumbprint> /fd SHA256 /tr <timestamp_url>
  /td SHA256`), adding **`/sm`** when `store_scope = "machine"` so signtool
  reads the `LocalMachine\My` store (default reads `CurrentUser\My`). Covers
  store-imported pfx certs *and* hardware tokens *and* Azure-backed certs
  transparently, because all of them surface as cert-store entries (see
  "Identity" below).
- **`NullSigner`** — the unconfigured default; `package` produces the
  unsigned artifact.
- A future **`ArtifactSigningSigner`** (Azure Artifact Signing's dlib-based
  signtool invocation) slots in behind the same protocol to sign **user**
  output with an Azure-held cert — deferred pending demand.

The protocol keeps credential mess out of the pipeline core: `bundle.py` and
`cli.py` ask for "the configured signer" and call `sign`; which backend and
which credentials is resolved at the edge.

### Identity: thumbprint-from-cert-store, not pfx-path

Adopted from Briefcase. `[tool.kivy.windows.signing].thumbprint` is the SHA-1
thumbprint of a code-signing certificate **in the Windows certificate store**.
Which store is the `store_scope` setting: `current_user` (default →
`Cert:\CurrentUser\My`) or `machine` (→ `Cert:\LocalMachine\My`). **One setting
drives both sides:** signtool signs against that store (`/sm` for machine) and
the `doctor` certificate check enumerates the *same* store — so a cert found by
`doctor` is the cert signtool will use, closing the classic "found in one store,
signed against the other" mismatch.

- The *same* configuration works whether the credential behind the cert is an
  imported `.pfx`, a hardware token (EV certs), or a cloud-held key — the
  store abstracts the key location.
- **No passwords ever touch the pipeline** — no `.pfx` path in
  `pyproject.toml`, no password prompt/env var plumbing, nothing committed
  that shouldn't be. (Contrast PyInstaller's canonical recipe, which still
  documents the pfx-path + password flow.)
- The pfx-path model is dying anyway: since 2023 the CA/Browser Forum
  requires code-signing keys in hardware/HSM, so file-based `.pfx` certs are
  no longer issued for publicly-trusted code signing.

Briefcase cannot enumerate installed certificates for the user — a
`kivyforge doctor`-adjacent listing (surface matching code-signing certs +
thumbprints when the configured thumbprint doesn't match) is a possible
differentiator, but a nice-to-have, not table stakes.

### What gets signed, in what order

For `package -f folder` with signing configured, signing operates **only on the
`dist/windows/<safe-name>-<version>-amd64/` copy** the packaging step produces —
never on the `build/windows` dev tree, which stays unsigned and re-runnable (see
the [spec's build/package split](windows-spec.md#init--build--run--package--status)):

1. **Resource-patch the launcher first** (icon + version resource — a
   resource edit invalidates any signature, so it must precede signing; see
   the [bootloader doc](bootloader-windows.md#per-app-parameterization-resource-patching)).
2. **Sign the launcher `.exe`** — the file SmartScreen and users actually
   judge. Always timestamped (see below).
3. **Payload DLLs/`.pyd`s** (`python.exe`, `python3xx.dll`, `SDL3.dll`, wheel
   extensions, ...) — **deferred to v2**; this matters only under Smart App
   Control / WDAC, not SmartScreen. onedir is what keeps it possible later:
   every payload file is real on disk and individually signable, which
   onefile would have foreclosed.

Windows signing is *flat* — a PKCS#7 blob appended to each PE independently —
unlike macOS's *structural* bundle seal (nested seals, inside-out ordering).
There is no Windows analog of "sign the deepest Mach-O first"; the ordering
constraints here are only patch-before-sign and sign-before-installer.

### Version-resource metadata (PEP 440 → four-part numeric)

The resource patch (step 1) writes the launcher's version resource from
declared metadata. Two representations are needed because a Windows version
resource carries both a human string and fixed numeric fields:

- **String fields** (`ProductName`, `FileDescription`, `ProductVersion`,
  `LegalCopyright`) take the values verbatim — `ProductName` from
  `[tool.kivy].display_name`, `ProductVersion` the full **PEP 440** string of
  `[project].version` (e.g. `1.4.0rc2`), copyright from `[project]` metadata.
- **Numeric fields** `FILEVERSION` / `PRODUCTVERSION` are **four 16-bit
  integers**, so the PEP 440 version is mapped to a **deterministic four-part
  numeric**: `(major, minor, micro, N)` where `N` encodes any pre/post/dev
  segment by a fixed rule (release → a high sentinel so it sorts above its own
  pre-releases; `rcK`/`bK`/`aK` → an ordered lower band; `.postK`/`.devK`
  folded in by the documented offset). The mapping is total and monotonic
  (a newer PEP 440 version never produces a lower tuple) and each field is
  clamped to `0..65535`. This is metadata only — it never affects wheel/runtime
  resolution, which uses the PEP 440 string throughout.

## Orchestration: kivyforge + Inno are composed, not redundant

Installers are **permanently external** — a scope decision, not a deferral
(see the [spec's scope](windows-spec.md#scope)); kivyforge stops at the
signed onedir artifact. But users who wrap that artifact in an installer
still need the two signing domains to compose correctly, so this section
specifies the seam as **user-facing guidance** — the Windows analog of the
macOS spec's copy-paste `.dmg` notarization snippet, destined for the "how to
sign your kivyforge output" guide. It is not groundwork for a future
`package -f installer`. Inno Setup is used as the worked example; the same
sign-the-artifact-first sequencing applies to NSIS/WiX pipelines. Each side
can reach an artifact the other cannot:

| Artifact | Signed by | Why |
|---|---|---|
| Launcher `.exe` in the onedir tree | **kivyforge** | Inno's `[Files]` sign flag only fires for files passing through an Inno compile — the portable-folder deliverable never does |
| Payload DLLs (optional, v2) | **kivyforge** | Same reason; only matters for Smart App Control / WDAC |
| `setup.exe` | **Inno** (`SignTool` directive) | Doesn't exist until Inno compile time |
| Uninstaller (`unins000.exe`) | **Inno** (`SignedUninstaller`) | Generated on the *end user's* machine at install time — structurally unreachable from outside Inno |

**One credential path.** Inno's `SignTool` directive is just a command
template — point it at the same `signtool` invocation kivyforge's `Signer`
backend produces. kivyforge owns the *policy* (which backend, which
thumbprint); Inno is merely a second *execution site* for the identical
command.

**Order** (in the user's release pipeline): `kivyforge package` signs the
tree → the user's Inno compile packages the *already-signed* launcher
(**no `sign` flag on that `[Files]` entry** — don't double-sign) and signs
`setup.exe` + the uninstaller. Each file is signed exactly once.

## Development & CI

**Develop and test against a self-signed certificate.** `signtool`'s command
surface is byte-for-byte identical regardless of certificate origin, so a
self-signed cert exercises the *entire* orchestration layer — config parsing,
thumbprint lookup, signing, timestamping, verification plumbing — at full
fidelity:

```powershell
$cert = New-SelfSignedCertificate -Type CodeSigningCert `
  -Subject "CN=KivyForge Test Signer" -CertStoreLocation Cert:\CurrentUser\My `
  -KeyUsage DigitalSignature -KeyExportPolicy Exportable -HashAlgorithm SHA256
```

```
signtool sign /sha1 <thumbprint> /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 MyApp.exe
```

- **Always timestamp, and test the timestamp path.** Public timestamp servers
  are free and need no account; a timestamped signature survives the
  certificate's expiry, an untimestamped one dies with it. The timestamp
  round-trip is part of real signing, so it is part of the tested pipeline
  (and of the `doctor` reachability check).
- **`signtool verify /pa` fails on a self-signed cert** (untrusted chain)
  unless the public `.cer` is imported into `Cert:\LocalMachine\Root` on the
  test box. CI does that import; the verify step then validates the full
  sign→verify loop.
- **The self-signed flow is the CI default** — PRs exercise the whole signing
  pipeline with **no secrets** in the repository or the workflow.
- **What self-signed does *not* replicate:** SmartScreen behavior (which
  needs a real, publicly-trusted cert plus accrued reputation) and cloud
  credential mechanics. Briefcase's docs warn explicitly that self-signed is
  not for distribution — agreed; it is a dev/CI fixture only, and the docs
  say so.

## Deferred

- **Payload-DLL signing** — a Smart App Control concern (SAC enforces more
  strictly than SmartScreen and can object to unsigned payload DLLs). v2;
  kept possible by onedir.
- **PBS binary signatures** — RESOLVED: PBS's `python.exe`/`python3xx.dll` are
  **unsigned** (verified with `Get-AuthenticodeSignature` over a built bundle;
  see the [spec's open items](windows-spec.md#open-items) and
  [windows-dll-findings.md](../../dev/windows-dll-findings.md)). They therefore
  fold into the payload sweep above, alongside the unsigned Kivy/SDL payload;
  only PBS's incidental PSF Tcl/Tk and the Microsoft VC-runtime DLLs arrive
  pre-signed. Only affects SAC/WDAC machines.
- **MSIX / MSI signing** — **out of scope (not deferred).** MSIX/MSI are
  installer/package formats kivyforge does not produce; they are
  [permanently external](windows-spec.md#scope), so signing them belongs to
  that external build, never to kivyforge. Listed here only to disclaim it.

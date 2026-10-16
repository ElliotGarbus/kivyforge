# Agent prompt — `doctor -p android` emulator acceleration on Windows

> **Run this on a Windows host with the Android SDK and at least one AVD**, from
> the repo root, in PowerShell. Written 2026-10-16 on macOS, which cannot run
> the Windows branch for real. You need the commit that adds this file, or
> later.
>
> Point the agent at this file, or copy the "Prompt" section.

## Background — what changed, and what the Mac could not prove

`doctor -p android`'s "Emulator / virtualization" check used to *assume* that a
Windows host was accelerated: `has_hardware_acceleration` returned `True` there
without asking, so doctor printed "accelerated" on every Windows host and its
WHPX/AEHD hint could never appear. Now
`RealAndroidProbe.hardware_acceleration()` runs the SDK emulator's own check
there:

```
<sdk>\emulator\emulator.exe -accel-check     (stdin=DEVNULL, timeout 30 s)
```

and reads the frame it prints on stdout: `accel:`, a status number (0 is
usable), a description, `accel`. The status number decides; the description goes
into the detail of a WARN. With no frame (a crash, a timeout, a binary that
will not start), the probe reports *unknown*, and doctor then **passes** with
`N AVD(s); acceleration not verified (<reason>)` rather than warning: a WARN on
every host for a probe that cannot tell is the bug just fixed for macOS.

What has been verified, on macOS 26.6.2 with emulator 37.1.11.0:

- The frame format, exit status 0, nothing on stderr:
  `accel:\n0\nHypervisor.Framework OS X Version 26.6\naccel\n`.
- The Windows code path itself, driven on the Mac against that real emulator
  binary (only doctor's view of the platform changed): it returned *usable* with
  the emulator's description in 0.03 s.
- A negative case without touching the machine: `HVF = off` in an
  `advancedFeatures.ini` under a scratch `ANDROID_EMULATOR_HOME` (with
  `ANDROID_AVD_HOME` keeping the real AVDs visible). `-accel-check` logged the
  override on stderr, printed `accel:\n138\n\naccel` (no description) and
  exited 138, and the Windows branch of the check then warned with the WHPX/AEHD
  hint. So the exit status matches a non-zero printed status, on macOS.
- The hermetic tests: the verdict, the crash, timeout and will-not-start
  cases, and the parser, including both real outputs above.

**Not verified, and only a Windows host can say:**

1. `emulator.exe -accel-check` prints the same frame **on stdout** on Windows,
   with the status on its own line. If the frame goes elsewhere, the probe says
   *unknown* on every Windows host: no false WARN, but no answer either.
2. `WindowsHypervisorPlatform = off` switches WHPX off the way `HVF = off` does
   on a Mac, and the exit status again equals the printed status.
3. How long it takes, the **first** time too (Defender scans a newly spawned
   binary), against the 30 s timeout.
4. A redirected report (`doctor > report.txt`) does not crash on the emulator's
   description. The probe decodes it as ASCII with `backslashreplace`, so it
   should not.

The same checks, as a repeatable hardware-pass item, are
`android-doctor-accel-windows` in
[`hardware-checklist.toml`](hardware-checklist.toml).

---

## Prompt

You are verifying kivyforge's emulator-acceleration probe on a real Windows
host. **Record what you observe**, with exit codes and output verbatim. If a step
fails, capture it and continue with the independent steps.

### Step 0 — environment

```powershell
git log -1 --oneline
[System.Environment]::OSVersion.VersionString
.venv\Scripts\kivyforge --version
$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { "$env:LOCALAPPDATA\Android\Sdk" }
$emu = "$sdk\emulator\emulator.exe"
& $emu -version | Select-Object -First 1
& $emu -list-avds
sc.exe query aehd          # AEHD's service; "does not exist" is a fine answer
```

### Step 1 — the emulator's raw answer

```powershell
$t = Measure-Command { & $emu -accel-check > accel.out 2> accel.err; $code = $LASTEXITCODE }
"exit=$code seconds=$($t.TotalSeconds)"
Format-Hex accel.out
Get-Content accel.err
```

Run it twice and give both times; the first spawn after a fresh emulator install
may be the slow one. Check:

- stdout is `accel:`, a number, one or more description lines, `accel`, and
  stderr holds none of it.
- `exit=` equals the printed number.

### Step 2 — doctor

```powershell
$kf = (Resolve-Path .venv\Scripts\kivyforge.exe).Path
mkdir $env:TEMP\kf-empty -Force | Out-Null; pushd $env:TEMP\kf-empty
& $kf doctor -p android --offline; "exit=$LASTEXITCODE"
& $kf doctor -p android --offline --json > doctor.json; "exit=$LASTEXITCODE"
& $kf doctor -p android --offline > report.txt; "exit=$LASTEXITCODE"
Select-String "Emulator" report.txt
popd
```

From an empty folder, doctor runs only the environment checks. Expect, on a host
where Step 1 printed status `0`:

- `[PASS] Emulator / virtualization: N AVD(s), accelerated`.
- In `doctor.json`, the same check with `"status": "PASS"`.
- `report.txt` written, with no traceback on the console.

If Step 1 printed a non-zero status, expect instead
`[WARN] Emulator / virtualization: AVDs present (N) but no hardware acceleration: <the emulator's description>`
and a hint naming WHPX and AEHD. If the line says `acceleration not verified`,
the probe found no frame: record its reason and Step 1's raw output side by
side. That is the defect this prompt exists to catch.

### Step 3 — the emulator *without* acceleration, without touching the machine

Switch WHPX off for the emulator only, through a feature override in a scratch
emulator home. This works only where AEHD is not installed (`sc.exe query aehd`
in Step 0 says the service does not exist); with AEHD present the emulator
would fall back to it, so record that and skip this step.

```powershell
New-Item -ItemType Directory -Force "$env:TEMP\kf-emu-home" | Out-Null
Set-Content "$env:TEMP\kf-emu-home\advancedFeatures.ini" 'WindowsHypervisorPlatform = off'
$env:ANDROID_EMULATOR_HOME = "$env:TEMP\kf-emu-home"
$env:ANDROID_AVD_HOME = "$env:USERPROFILE\.android\avd"   # keep the real AVDs visible
& $emu -accel-check; "exit=$LASTEXITCODE"
pushd $env:TEMP\kf-empty; & $kf doctor -p android --offline; "exit=$LASTEXITCODE"; popd
Remove-Item Env:ANDROID_EMULATOR_HOME, Env:ANDROID_AVD_HOME
```

Expect stderr to say the feature `WindowsHypervisorPlatform` is overridden to
`disabled`, a non-zero status with `exit=` showing the same number, and
`[WARN] Emulator / virtualization: AVDs present (N) but no hardware acceleration`
with the WHPX/AEHD hint. If there is no override line, the feature name is wrong
for this emulator version: record what it printed.

**Do not turn off Hyper-V, WHPX or AEHD in Windows itself.** That needs an
administrator and a reboot, and it changes the user's machine: their call, not
this prompt's.

### Step 4 — report

Write findings to `docs/design/dev/doctor-android-acceleration-windows-findings.md`:
an environment table (Windows build, CPU vendor, emulator version, which of WHPX
or AEHD the emulator named), then each step's commands, exit codes and output
verbatim. Lead with any defect.

If you fix one, put the fix and a hermetic test in
`tests/platforms/android/test_doctor.py` in a separate commit from the findings.

Record the result into [`test-matrix.md`](test-matrix.md) §7 with
`python scripts/hardware_pass.py record android-doctor-accel-windows --result pass|fail --device "<Windows build, CPU>" --note "..."`,
saying in the note whether Step 3 ran, and update that item's "Last known
result" in §6.

### Rules of engagement

- Record what you **observed**. A skipped step is reported as skipped, with the
  reason.
- Do not commit `accel.out`, `doctor.json` or `report.txt`.
- Commit on the current feature branch. **Do not push without asking.**

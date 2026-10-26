# `doctor -p android` emulator acceleration on Windows — findings

Run per
[`doctor-android-acceleration-windows-prompt.md`](doctor-android-acceleration-windows-prompt.md)
on a real Windows host. Date: 2026-10-26.

**No defects.** Every pass criterion of checklist item
`android-doctor-accel-windows` held: the frame arrives on stdout, the exit
status equals the printed status, `WindowsHypervisorPlatform = off` switches
WHPX off the way `HVF = off` does on a Mac, and neither doctor run said
`acceleration not verified`. Nothing in `kivyforge/` changed. The two real
outputs are pinned as parser tests in `tests/platforms/android/test_doctor.py`.

One observation, not a defect, under Step 3: with WHPX off, the emulator's own
description says to *disable* Hyper-V, while doctor's hint says to turn WHPX
*on*. Both are routes to acceleration (AEHD needs Hyper-V off; WHPX needs it
on), so the WARN line carries two opposite instructions.

## Environment (Step 0)

| Item | Value |
|------|-------|
| Host | Windows 11 Home, 10.0.26200 |
| CPU | Intel Core i7-9700 @ 3.00 GHz |
| Emulator | 36.6.11.0 (build_id 15507667) |
| Accelerator the emulator named | WHPX (10.0.26200) |
| AEHD | not installed (`sc.exe query aehd`: service does not exist) |
| SDK | `C:\Android\Sdk` (`ANDROID_HOME`) |
| AVDs | `kivyforge_api24_x86_64`, `kivyforge_api30_x86_64`, `kivyforge_x86_64` |
| Python | 3.13.3, venv in the worktree |
| kivyforge | 3.0.0.dev1 (editable install) |
| Branch | `claude/brave-williamson-806025` @ `0fb29cae` |

## Step 1 — the emulator's raw answer

Captured through Python's `subprocess.run(..., stdin=DEVNULL,
capture_output=True)`, the way the probe spawns it. PowerShell's `>`
re-encodes output (it added a BOM), so its bytes are not what doctor sees.

```
exit 0, 0.071 s
stdout b'accel:\r\n0\r\nWHPX(10.0.26200) is installed and usable.\r\naccel\r\n'
stderr b''
```

Timings: 0.31 s for the first spawn this session, 0.07 s after. That is far
inside the 30 s timeout, but the emulator was not freshly installed, so this is
not a cold Defender scan.

- The frame is on stdout, one item per line, with **CRLF** line endings. Every
  earlier fixture was LF. The probe reads in text mode, which turns CRLF into LF,
  and the parser's `splitlines()` handles either way.
- `exit` equals the printed status, 0. stderr is empty.

## Step 2 — doctor

From an empty folder (`%TEMP%\kf-empty`), so doctor runs environment checks only.

```
[PASS] Emulator / virtualization: 3 AVD(s), accelerated
exit=0   (1.6 s for the whole doctor run)
```

- `--json`: exit 0, `ok: true`, the check
  `{"name": "Emulator / virtualization", "status": "PASS", "detail": "3 AVD(s), accelerated"}`.
- Redirected (`> report.txt`): exit 0, no traceback, and the same line in the file.

The only other non-PASS was `[WARN] adb: ... no device or emulator attached`,
which is expected with no emulator running.

## Step 3 — WHPX switched off for the emulator only

AEHD is not installed, so the step applies. `advancedFeatures.ini` holding
`WindowsHypervisorPlatform = off` was put in a scratch `ANDROID_EMULATOR_HOME`,
with `ANDROID_AVD_HOME` keeping the real AVDs visible. Both variables were
removed afterwards, and nothing on the machine changed.

```
exit 15, 0.063 s
stdout b"accel:\r\n15\r\nPlease disable Hyper-V before using the Android Emulator.  Start a command prompt as Administrator, run 'bcdedit /set hypervisorlaunchtype off', reboot.\r\naccel\r\n"
stderr b"WARNING: All log messages before absl::InitializeLog() is called are written to STDERR\r\nI0000 00:00:1793036598.729100   50524 FeatureControlImpl.cpp:381] Feature 'WindowsHypervisorPlatform' (14) is overridden to 'disabled'\r\n"
```

- stderr names the override, so the feature name is right for this emulator
  version.
- The printed status is 15 and `exit` is 15. Unlike the Mac's 138, it comes with
  a description.

doctor, same folder:

```
[WARN] Emulator / virtualization: AVDs present (3) but no hardware acceleration: Please disable Hyper-V before using the Android Emulator.  Start a command prompt as Administrator, run 'bcdedit /set hypervisorlaunchtype off', reboot.
       hint: turn on Windows Hypervisor Platform (WHPX) in Windows Features, or install the Android Emulator hypervisor driver (AEHD) from the SDK Manager; either needs virtualization turned on in the firmware.
exit=0
```

Redirected to `report-off.txt`: exit 0, with the same two lines and no
traceback. The description is plain ASCII, so `backslashreplace` had nothing
to do.

**Observation.** With WHPX off and Hyper-V on, the emulator falls back to
AEHD's advice: switch Hyper-V off. The hint right below it says to turn WHPX
on, which needs Hyper-V. A real host with Hyper-V on but the Windows Hypervisor
Platform feature off would probably print the same text, and there WHPX is the
one-checkbox fix. The behaviour matches the item's pass criteria and the
CHANGELOG ("carries the emulator's own reason"), so this is recorded, not fixed.

## Not run

- A host where acceleration is genuinely off in Windows. That would mean
  turning off Hyper-V or WHPX, which needs an administrator and a reboot. The
  prompt rules it out.
- A first spawn after a fresh emulator install, the cold Defender case.
- An AMD host, and a host with AEHD installed.

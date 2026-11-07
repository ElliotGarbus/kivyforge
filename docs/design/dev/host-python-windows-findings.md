# Findings — the lock-pinned host CPython on Windows

Run of [`host-python-windows-prompt.md`](host-python-windows-prompt.md) on a
Windows 11 host, 2026-11-06, from `main` at `758dc40e` (the merge of PR #214).
Everything the prompt asked about the Windows install path **passed**. Two
things did not go as the prompt predicted; neither is a defect in the host-CPython
code, and one is unexplained. They come first.

## Defects and surprises

### 1. Step 3's log has no `installing` or `[download]` line — unexplained, not reproduced

The first release build after a cold start (`package -p android ... --json`, no
Python on `PATH`) exited 0, compiled with
`...\host-python\ada613a2...\python\python.exe`, and produced a valid APK, but its
stderr (104 lines) contains neither
`host CPython 3.14.6 (x86_64-pc-windows-msvc): installing from the lock` nor any
`[download] cpython` line. The prompt expects both.

What the filesystem says: the `host-python\<Pin>` directory and its `.lock` file
were created at 17:19:41-17:19:57, but that build's log was last written at
17:31:52 (it ran 83 s). So the install was made **by a different process, about
ten minutes earlier**, and step 3 found it complete. I can't say which process
that was: `doctor` (checked afterwards, with the install and archive moved away)
creates nothing, and no other kivyforge command of mine ran at that time. It
may have been a call that the tool harness reported as rejected and ran anyway;
I can't show that.

The log lines are not lost to `--json`, to a cold archive cache or to a missing
`host-python` directory. Three later builds reproduced each of those conditions
and every one logged both lines:

| Build | Condition | `installing` line | `[download]` lines |
|---|---|---|---|
| 4c | install moved aside, archive cached, `--json` | yes | 0 (cached) |
| 4d | install and archive moved aside, no `--json` | yes | 11 |
| 4e | install and archive moved aside, `--json` | yes | 11 |
| 4f | whole `host-python` directory (and `.lock`) and archive moved aside, `--json` | yes | 11 |

**4f is the record of a first-ever install on this host** and passes. Step 3's
own log should be read only as "compiled with the locked interpreter".

### 2. After a network drop, `lock --check` fails with a misleading message and keeps failing

The first run of step 1 coincided with a connectivity outage (pip logged
`ConnectionResetError(10054...)`, `ReadTimeoutError` and
`Failed to resolve 'files.pythonhosted.org'`). `lock -p android --check --json`
then exited 1 with `KF-LOCK-PINS-CONFLICT` and text saying the dependency "has no
android_* wheel for that ABI". The plain `lock` that followed succeeded, but a
later `lock --check` kept failing **after DNS and HTTPS were healthy again**:

```
ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE. ...
    kivy==2.3.1 from https://github.com/ElliotGarbus/kivy-mobile-wheels/releases/download/kivy-android-2.3.1/Kivy-2.3.1-cp314-cp314-android_24_arm64_v8a.whl#sha256=078870f0...:
        Expected sha256 20da914a3abff114448106df16161184eb283283d5444a4c5caf02c147f65d0e
             Got        e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

`e3b0c442...` is the SHA-256 of zero bytes. The wheel itself downloads fine from
this machine (8,889,878 bytes, SHA-256 `078870f0...`, the lock's value). The same
`--check` passed at once with `PIP_NO_CACHE_DIR=1`, so pip's HTTP cache (here
under a Cursor sandbox temp directory) holds a bad entry from the outage. I did
not inspect the cache entry. This has nothing to do with the host CPython, but
the diagnostic names the wrong cause. I ran every later step with
`PIP_NO_CACHE_DIR=1`.

### 3. The prompt's APK check needs a Python 3.14 runner

Step 3 runs `tests/platforms/android/test_apk_artifact.py` with the repo venv's
Python, which was 3.13 here, and the test fails by design: "ships CPython 3.14,
but this test is running under 3.13 ... Pin the CI job's setup-python to 3.14."
I ran it from a throwaway 3.14 venv (`py -3.14 -m venv`, `pip install -e ".[dev]"`
from the repo, outside the repo tree) and it passed. The prompt should say so.

## Environment

| | |
|---|---|
| Windows | 11 25H2, build 26200 (`10.0.26200.0`) |
| PowerShell | **Windows PowerShell 5.1.26100.9711** (no `pwsh`; the prompt assumes 7) |
| kivyforge | 0.1.0, editable, repo venv on CPython 3.13.1 |
| Locale encoding | `cp1252`, `sys.flags.utf8_mode` 0 |
| `PYTHONUTF8` | empty |
| `PYTHONIOENCODING` | **was `utf-8:surrogateescape`**; unset for this run (it would hide step 6's cp1252 fallback) |
| `LongPathsEnabled` | **1** (long paths on; see step 3) |
| `%LOCALAPPDATA%` length | 28 (`C:\Users\ellio\AppData\Local`) |
| JDK | Temurin 17.0.19.10 |
| Android SDK | `C:\Android\Sdk` |
| Scratch root | `C:\kf\hostpy` |
| `$Pin` | `ada613a2af32c04cf7c54726243c56d76f0e59f5f61d2f28371d3b9d8efad566`, still the Windows entry in `hello-android/pylock.android.toml` |
| Start state | cold: no `host-python` directory, no cached archive for `$Pin` |

Deviations from the prompt, all because of this host:

- **Windows PowerShell 5.1.** `>` on a native command writes UTF-16 there, and
  `2>` wraps stderr in `ErrorRecord`s, so the `kf` helper redirects through
  `cmd /c "... > out 2> err"` instead. That gives the raw bytes, which is also
  closer to what step 6's cp1252 point is about. Step 5 uses `Start-Process`
  as written.
- **Variables don't persist between commands**, so setup lives in a dot-sourced
  script. Nothing here changes what ran.
- **`LongPathsEnabled` was already 1.** I did not turn it off (a machine setting).
  Step 3's path-length result is therefore a measurement, not a proof that it
  works with long paths off.

## Results by step

| Step | Expectation | Observed |
|---|---|---|
| 0 | environment | table above |
| 1 | pre-table `--check` exit 4 `KF-LOCK-INCOMPLETE`; `lock` exit 0; diff empty; `--check` exit 0 | **pass** (clean rerun; see defect 2 for the first attempt) |
| 2 | doctor PASS "downloaded on the first release build" | **pass** |
| 3 | package, no Python on `PATH`: exit 0, one APK, stripped APK passes T3 | **pass**, but the install lines are missing from this log (defect 1) |
| 4 | second build: no install; reinstall over an install with the marker removed | **pass**, no `WinError` |
| 5 | two concurrent builds, one install | **pass**: exactly one logged `installing` |
| 6 | `never` warm and cold; `byte_compile = true` fails; two misuses | **pass** |
| 7 | `upgrade` fetches; `never` build installs from the cached archive | **pass** |

### Step 1 — the lock is host-independent

```
check (pre-table lock)   exit=4   KF-LOCK-INCOMPLETE
  "pylock.android.toml is incomplete: it has no [[tool.kivyforge.host_python]] table (it predates it)."
lock                     exit=0
  stderr: [lock] host CPython 3.14.6 for byte-compiling: aarch64-apple-darwin, x86_64-pc-windows-msvc, x86_64-unknown-linux-gnu
  stdout: Updated pylock.android.toml (host CPython pinned; no package re-resolved).
git diff --no-index --stat <macOS-made lock> <this lock>    no output, exit 0
check                    exit=0   "pylock.android.toml is up to date."
```

The Windows re-lock is byte-identical to the one made on macOS (the expected
file is `HEAD`'s `examples/mobile/hello-android/pylock.android.toml`).

### Step 2

```
[PASS] Byte-compile interpreter: byte_compile = "release"; the locked host CPython 3.14.6 (x86_64-pc-windows-msvc) is downloaded on the first release build
```

### Step 3 — package, then the install

`PATH` was `C:\Windows\System32;C:\Windows;C:\Windows\System32\WindowsPowerShell\v1.0`.
`where.exe python python3 py` found nothing (`py.exe` isn't in `System32` here).
`package -p android --json`: exit 0 in 83.1 s, `ok: true`, `diagnostics: []`,
`artifacts: [{"path": "dist/android/hello-android-1.0.0.apk", "kind": "apk"}]`.

```
[stage] byte-compiling the Python payload with C:\Users\ellio\AppData\Local\kivyforge\Cache\artifacts\host-python\ada613a2...efad566\python\python.exe (.pyc only)
```

After the install:

- `host-python\<Pin>` holds `python` and `.kivyforge-complete`; the directory
  holds `<Pin>`, `<Pin>.lock` and no `.ada613a2af32-*` leftover.
- `python.exe -I`: `3.14.6 (main, Aug  4 2026, 18:29:47) [MSC v.1944 64 bit (AMD64)]`,
  magic `2b0e0d0a`.
- The cached archive is `<Pin>-cpython-3.14.6+20260804-x86_64-pc-windows-msvc-install_only_stripped.tar.gz`,
  22,517,559 bytes, SHA-256 `ADA613A2...EFAD566` (equal to `$Pin`).
- **Longest path: 237 characters**
  (`...\host-python\<Pin>\python\Lib\site-packages\pip\_internal\resolution\resolvelib\__pycache__\found_candidates.cpython-314.pyc`).
  The prefix up to `<Pin>` is 131 characters. That leaves 23 characters of
  margin under 260; a 20-character user name instead of `ellio` adds 15, giving
  252, so still under 260 but close. Staging extracts under
  `<root>\.ada613a2af32-<random>\new\`, a shorter prefix than `<Pin>\`, so the
  final path is the longest one. Not proven with `LongPathsEnabled` off (above).
- The APK check, from a 3.14 venv (defect 3), with
  `--android-abi arm64-v8a,x86_64 --android-stripped`: **passed**.
- stderr has no `UnicodeEncodeError` (output was redirected by `cmd`, so Python
  used the cp1252 locale encoding).

### Step 4 — a second build, and reinstalling over an install

- Second build: exit 0, no `installing` line, no `[download]`, the same
  `byte-compiling ... with` path.
- With `.kivyforge-complete` removed: exit 0, `installing from the lock`, **no**
  `[download]` (archive cached), the marker back, no `.ada613a2af32-*`
  directory left. No `WinError 5` or `WinError 32`; Defender did not hold the
  fresh `python.exe` on this run, so that remains luck of timing as much as
  proof.

### Step 5 — two builds installing the same pin at once

The install was moved away, the archive kept, and two `package` runs started
together from `ha` and `hb`:

```
a=0 b=0
a.err: [stage] byte-compiling the Python payload with C:\...\host-python\<Pin>\python\python.exe (.pyc only)
b.err: [stage] host CPython 3.14.6 (x86_64-pc-windows-msvc): installing from the lock
b.err: [stage] byte-compiling the Python payload with C:\...\host-python\<Pin>\python\python.exe (.pyc only)
```

Both exit 0, exactly one `installing` line, both compiled with the same
`python.exe`, one directory for `<Pin>`, no leftovers. `msvcrt.locking`
excludes on Windows. One run, so this shows the lock works and is not a
guarantee against every interleaving.

### Step 6 — downloads off, and `byte_compile = true`

With `KIVYFORGE_HOST_PYTHON_DOWNLOADS=never`:

| Case | Result |
|---|---|
| install present: `package` | exit 0, compiled |
| install present: `doctor` | `[PASS] ... the locked host CPython 3.14.6 (x86_64-pc-windows-msvc): C:\...\python.exe` |
| install and archive moved away: `doctor` | `[WARN] ... isn't in the cache and KIVYFORGE_HOST_PYTHON_DOWNLOADS=never; release builds will ship source` (exit 0) |
| same: `package --json` | exit 0, `ok: true`, `KF-BYTECOMPILE-NO-INTERP` as a **warning**, APK still produced; stderr `not byte-compiling: ... KIVYFORGE_HOST_PYTHON_DOWNLOADS=never.` |
| `byte_compile = true`: `doctor` | `[FAIL] ... the build will fail`, **exit 3** |
| same: `package --json` | **exit 3**, `ok: false`, `artifacts: []`, `KF-BYTECOMPILE-NO-INTERP` severity `error`, `context: {"tool": "python3.14"}` |
| `KIVYFORGE_HOST_PYTHON_DOWNLOADS=sometimes`: `package --json` | **exit 1**, `KF-ERROR`: "KIVYFORGE_HOST_PYTHON_DOWNLOADS='sometimes' is not valid. Fix: set it to `automatic` or `never`, or unset it." |
| `never`: `upgrade --name host-python --json` | **exit 1**, `KF-ERROR`: "KIVYFORGE_HOST_PYTHON_DOWNLOADS=never forbids downloading the host CPython. Fix: unset it while running `kivyforge upgrade`, then set it again." |

### Step 7 — `upgrade` fetches ahead of time

With the pin moved away and `byte_compile = true`:

- `doctor`: `[PASS] Byte-compile interpreter: byte_compile = true; the locked host CPython 3.14.6 (x86_64-pc-windows-msvc) is downloaded on the first release build`.
- `upgrade -p android --name host-python --json`: exit 0, `ok: true`,
  `data.refreshed == ["host-python"]`, `Refreshing the host CPython 3.14.6
  (x86_64-pc-windows-msvc) ...` and `[download]` lines on stderr; the archive was
  back in the cache (22,517,559 bytes) and **not** installed.
- Then, with `never`: `package` exit 0, `installing from the lock`, no
  `[download]`, compiled.

## What this does not cover

- Long paths **off** (the machine had them on).
- Antivirus holding a fresh `python.exe` during step 4's rename: it did not
  happen, so the failure path was not exercised.
- PowerShell 7; this ran under 5.1, with `cmd` doing the redirection.
- Defect 1's missing log lines: a 4-for-4 clean result later, no cause found.

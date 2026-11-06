# Agent prompt — the lock-pinned host CPython on Windows

> **Run this on a Windows 10/11 x64 host with the Android SDK and a JDK 17**,
> from the repo root, in **PowerShell 7** (`pwsh`). Written 2026-11-06 on
> macOS, which can't run the Windows install path. You need branch
> `host-python-lock` at `98b55305` or later (PR #214), or `main` once it merges.
>
> Point the agent at this file, or copy the "Prompt" section.

## Background — what is proven, and what only a Windows host can say

[`host-python-download-proposal.md`](host-python-download-proposal.md)
(implemented) moves byte-compiling for iOS, Android and Linux `aarch64` onto a
python-build-standalone CPython that `kivyforge lock` pins in
`[[tool.kivyforge.host_python]]` and the first release build downloads,
verifies, installs and compiles with. On Windows that is the
`x86_64-pc-windows-msvc` entry, installed to
`%LOCALAPPDATA%\kivyforge\Cache\artifacts\host-python\<sha256>\python\python.exe`.

**Already proven:**

- macOS, for iOS and Android, by hand: [`test-matrix.md`](test-matrix.md) §7,
  the two 2026-11-06 rows.
- **The Windows happy path, by CI.** PR #214's "Android T3 from a Windows host"
  job (run 42310933394) logged `host CPython 3.14.6 (x86_64-pc-windows-msvc):
  installing from the lock`, downloaded the 22.5 MB stripped archive, compiled
  with `...\host-python\ada613a2...\python\python.exe`, and its stripped APK
  passed T3. So the download, the hash check, `tarfile` extraction, the
  `python.exe` layout and the compile all work on a fresh runner.

**Not proven, and Windows-specific:**

1. **Path length.** The install sits under a 64-character hash directory, and
   `_install_archive` extracts into `<root>\.<sha[:12]>-<random>\new\` first,
   then renames. Nobody has measured the longest path in the install against
   `MAX_PATH` (260) on a machine with a real user name and long paths
   disabled.
2. **The install lock.** `_install_lock` uses `msvcrt.locking` on Windows
   (`fcntl.flock` elsewhere): one byte of an empty `<sha256>.lock` file. Two
   builds installing the same pin at once have never run on Windows.
3. **Reinstalling over an install.** With the `.kivyforge-complete` marker gone,
   the install renames the old directory away, renames the new one in, and lets
   `TemporaryDirectory` delete the old one. On Windows, a file held open
   (Defender scanning a fresh `python.exe`, say) refuses both.
4. **Every state but the happy one**: `doctor`'s six states,
   `KIVYFORGE_HOST_PYTHON_DOWNLOADS=never` warm and cold, `byte_compile = true`
   failing, an invalid value, and `upgrade --name host-python`.
5. **The lock is host-independent.** Re-locking from a lock without the table
   should give the same three entries on Windows as on macOS, byte for byte.
6. **Redirected output in cp1252.** Every step redirects stdout and stderr to
   files, which is where Python falls back to the locale encoding (AGENTS.md).
   A crash from inside a print is a defect.

---

## Prompt

You are verifying kivyforge's lock-pinned host CPython on a real Windows host,
for what CI doesn't cover. **Record what you observe**, with exit codes and
output verbatim. If a step fails, capture it and go on with the independent
steps.

**Work in a short path.** Gradle's output tree is deep, so use `C:\kf` (or
another short root), not `%TEMP%`.

Set up once, from the repo root:

```powershell
$Repo = (Get-Location).Path
$KF   = "$Repo\.venv\Scripts\kivyforge.exe"
$PY   = "$Repo\.venv\Scripts\python.exe"
$W    = "C:\kf\hostpy"
$Root = "$env:LOCALAPPDATA\kivyforge\Cache\artifacts"
$Pin  = "ada613a2af32c04cf7c54726243c56d76f0e59f5f61d2f28371d3b9d8efad566"
function kf { & $KF @args > "$W\kf.out" 2> "$W\kf.err"; "exit=$LASTEXITCODE" }
New-Item -ItemType Directory -Force $W | Out-Null
```

If your shell doesn't keep state between commands, re-run this block before
each one, along with `$Sign` and any environment variable a step has set.

`$Pin` is the SHA-256 of the Windows entry in the tracked
`examples/mobile/hello-android/pylock.android.toml`; check that it still is.

### Step 0 — environment

```powershell
git log --oneline -1                     # 98b55305 or later
[Environment]::OSVersion.VersionString
$PSVersionTable.PSVersion
& $KF --version; & $PY -V
& $PY -c "import locale, sys; print(locale.getpreferredencoding(), sys.flags.utf8_mode)"
$env:PYTHONUTF8; $env:PYTHONIOENCODING   # both should be empty
(Get-ItemProperty HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem).LongPathsEnabled
$env:LOCALAPPDATA.Length
$env:JAVA_HOME; $env:ANDROID_HOME
Get-ChildItem "$Root\host-python" -ErrorAction SilentlyContinue
```

Record all of it: the locale encoding and `LongPathsEnabled` matter to steps 3
and 6. If `host-python` already holds `$Pin`, move it and the cached archive
(`$Root\ad\$Pin-*`) to `$W\aside0` so this run starts cold, and put them back
at the end in place of this run's.

Make a scratch copy of `hello-android` and a throwaway keystore:

```powershell
git archive -o "$W\ha.zip" HEAD:examples/mobile/hello-android
Expand-Archive "$W\ha.zip" "$W\ha"
$env:KIVYFORGE_KEYSTORE_PASSWORD = [guid]::NewGuid().ToString("N")
& "$env:JAVA_HOME\bin\keytool.exe" -genkeypair -noprompt -keystore "$W\test.keystore" `
  -storetype PKCS12 -alias upload -keyalg RSA -keysize 2048 -validity 30 `
  -storepass $env:KIVYFORGE_KEYSTORE_PASSWORD -keypass $env:KIVYFORGE_KEYSTORE_PASSWORD `
  -dname "CN=kivyforge scratch test"
$Sign = @("--keystore", "$W\test.keystore", "--key-alias", "upload")
```

`--debug` doesn't byte-compile, so the release path needs a keystore. Don't
print the password.

### Step 1 — the lock, from a lock that predates the table

```powershell
cmd /c "git show 98b55305~1:examples/mobile/hello-android/pylock.android.toml > $W\ha\pylock.android.toml"
cmd /c "git show HEAD:examples/mobile/hello-android/pylock.android.toml > $W\expected.toml"
cd $W\ha
kf lock -p android --check --json; Get-Content $W\kf.out
kf lock -p android; Get-Content $W\kf.err
git diff --no-index --stat $W\expected.toml $W\ha\pylock.android.toml; "diff exit=$LASTEXITCODE"
kf lock -p android --check; Get-Content $W\kf.err
```

Expect:

- The first `--check`: exit `4`, one `KF-LOCK-INCOMPLETE` diagnostic saying the
  lock has no `[[tool.kivyforge.host_python]]` table.
- Plain `lock`: exit `0`, `host CPython 3.14.6 for byte-compiling:` and all
  three triples on stderr, then `Updated pylock.android.toml (host CPython
  pinned; no package re-resolved).` A GitHub rate limit here is exit `3`,
  `KF-HOST-PYTHON-FETCH`; set `$env:GH_TOKEN = (gh auth token)` and retry.
- The `git diff`: **no output, exit 0**. The Windows re-lock is byte-identical
  to the one made on macOS. Any difference is a defect; quote it.
- The second `--check`: exit `0`.

### Step 2 — `doctor` before anything is installed

```powershell
& $KF doctor -p android 2>&1 | Select-String "Byte-compile" -Context 0,1
```

Expect `[PASS] Byte-compile interpreter: byte_compile = "release"; the locked
host CPython 3.14.6 (x86_64-pc-windows-msvc) is downloaded on the first release
build`.

### Step 3 — package with no Python on `PATH`

```powershell
$SavedPath = $env:PATH
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
where.exe python python3 py 2>&1          # record; py.exe may still be in C:\Windows
$t = Measure-Command { kf package -p android @Sign --json }; "took $($t.TotalSeconds) s"
Get-Content $W\kf.err | Select-String "host CPython|byte-compil|\[download\] cpython"
& $PY -m json.tool $W\kf.out
```

`py.exe` being visible doesn't matter: kivyforge no longer searches for a
Python. The `byte-compiling ... with` line is the proof of what compiled.

Expect exit `0`, `ok: true`, no diagnostics, `data.artifacts` one `apk` under
`dist/android/`; on stderr, `installing from the lock`, the `[download]` lines,
and `byte-compiling the Python payload with
...\host-python\<Pin>\python\python.exe (.pyc only)`. Then:

```powershell
$Inst = "$Root\host-python\$Pin"
Get-ChildItem -Force $Inst                 # python, .kivyforge-complete
Get-ChildItem -Force "$Root\host-python"   # $Pin, $Pin.lock, and no .ada613a2af32-* left over
& "$Inst\python\python.exe" -I -c "import sys, importlib.util; print(sys.version); print(importlib.util.MAGIC_NUMBER.hex())"
(Get-FileHash "$Root\ad\$Pin-*").Hash      # equals $Pin, uppercased
$long = Get-ChildItem -Recurse -Force $Inst | Sort-Object { $_.FullName.Length } -Descending | Select-Object -First 1
"$($long.FullName.Length)  $($long.FullName)"
```

The interpreter should report 3.14.6 and magic `2b0e0d0a`. **Record the longest
path and its length**: under 260 with `LongPathsEnabled` off is the result we
want. If it's close (over 240), say so, and add the length of a longer
`%LOCALAPPDATA%` (a 20-character user name) to judge the margin.

Check the APK, with `PATH` restored:

```powershell
$env:PATH = $SavedPath
$apk = (& $PY -c "import json,sys; print(json.load(open(sys.argv[1]))['data']['artifacts'][0]['path'])" $W\kf.out)
cd $Repo
& $PY -m pytest -q --no-cov -p no:cacheprovider tests/platforms/android/test_apk_artifact.py `
  --android-apk "$W\ha\$apk" --android-abi arm64-v8a,x86_64 --android-stripped
```

Expect it to pass. Also confirm the `.err` file has no `UnicodeEncodeError`.

### Step 4 — a second build, and reinstalling over an install

```powershell
cd $W\ha
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
kf package -p android @Sign; Get-Content $W\kf.err | Select-String "host CPython|\[download\] cpython|byte-compil"
```

Expect exit `0`, no `installing` and no `[download]` line, the same
`byte-compiling ... with` path.

Then remove the marker, so the next build reinstalls over the existing
directory from the cached archive:

```powershell
Remove-Item -Force "$Root\host-python\$Pin\.kivyforge-complete"
kf package -p android @Sign; Get-Content $W\kf.err | Select-String "host CPython|\[download\] cpython|byte-compil|Error"
Get-ChildItem -Force "$Root\host-python"
```

Expect exit `0`, `installing from the lock` but **no `[download]`** (the archive
is cached), the marker back, and no `.ada613a2af32-*` directory left behind.
Windows refusing the rename or the cleanup (`WinError 5` or `WinError 32`) is
the defect this step exists to find. It should arrive as exit `1` with the
OS's reason in one message (`os_failure`), not a traceback; record which, the
message verbatim, and whether retrying succeeds.

### Step 5 — two builds installing the same pin at once

Make a second scratch copy, remove the install (keep the archive), and start
both packages together:

```powershell
Expand-Archive "$W\ha.zip" "$W\hb"
Copy-Item $W\ha\pylock.android.toml $W\hb\
Remove-Item -Recurse -Force "$Root\host-python\$Pin"
$a = Start-Process -PassThru -NoNewWindow -WorkingDirectory $W\ha -FilePath $KF `
  -ArgumentList (@("package", "-p", "android") + $Sign) `
  -RedirectStandardOutput $W\a.out -RedirectStandardError $W\a.err
$b = Start-Process -PassThru -NoNewWindow -WorkingDirectory $W\hb -FilePath $KF `
  -ArgumentList (@("package", "-p", "android") + $Sign) `
  -RedirectStandardOutput $W\b.out -RedirectStandardError $W\b.err
$a, $b | Wait-Process; "a=$($a.ExitCode) b=$($b.ExitCode)"
Select-String "host CPython|byte-compil|Error" $W\a.err, $W\b.err
Get-ChildItem -Force "$Root\host-python"
```

Expect both exit `0`. **Exactly one** of the two logs an `installing from the
lock` line; the other waits on the lock silently, then finds the install
finished and compiles with it. Both name the same `python.exe`. One directory
for `$Pin`, no leftovers. If both log `installing`, the lock isn't excluding on
Windows: that's a defect, even if both builds succeed.

### Step 6 — downloads off, and `byte_compile = true`

With the install present:

```powershell
$env:KIVYFORGE_HOST_PYTHON_DOWNLOADS = "never"
kf package -p android @Sign; Get-Content $W\kf.err | Select-String "byte-compil"   # exit 0, compiles
& $KF doctor -p android 2>&1 | Select-String "Byte-compile"                        # PASS, the cached path
```

Move this pin's install and archive aside, and try again:

```powershell
New-Item -ItemType Directory -Force $W\aside | Out-Null
Move-Item "$Root\host-python\$Pin" $W\aside\
Move-Item "$Root\ad\$Pin-*" $W\aside\
& $KF doctor -p android 2>&1 | Select-String "Byte-compile" -Context 0,1           # WARN
kf package -p android @Sign --json; & $PY -m json.tool $W\kf.out                   # exit 0
Get-Content $W\kf.err | Select-String "not byte-compiling" -Context 0,1
```

Expect `doctor` WARN naming `KIVYFORGE_HOST_PYTHON_DOWNLOADS=never`, and the
package exit `0`, `ok: true`, with a `KF-BYTECOMPILE-NO-INTERP` warning: a
release that ships source. Now make it required:

```powershell
Add-Content $W\ha\pyproject.toml "`n[tool.kivy.android.build_settings]`nbyte_compile = true"
& $KF doctor -p android 2>&1 | Select-String "Byte-compile" -Context 0,1; "doctor exit=$LASTEXITCODE"
kf package -p android @Sign --json; & $PY -m json.tool $W\kf.out
```

Expect `doctor` FAIL (exit `3`), and the package exit `3`, `ok: false`,
`data.artifacts == []`, `KF-BYTECOMPILE-NO-INTERP`. Then two misuses:

```powershell
$env:KIVYFORGE_HOST_PYTHON_DOWNLOADS = "sometimes"
kf package -p android @Sign --json; & $PY -m json.tool $W\kf.out    # exit 1, names the variable
$env:KIVYFORGE_HOST_PYTHON_DOWNLOADS = "never"
kf upgrade -p android --name host-python --json; & $PY -m json.tool $W\kf.out   # exit 1
Remove-Item Env:KIVYFORGE_HOST_PYTHON_DOWNLOADS
```

### Step 7 — `upgrade` fetches ahead of time

Still with the pin moved aside and `byte_compile = true`:

```powershell
& $KF doctor -p android 2>&1 | Select-String "Byte-compile"        # PASS, "downloaded on the first release build"
kf upgrade -p android --name host-python --json; & $PY -m json.tool $W\kf.out
Get-ChildItem "$Root\ad\$Pin-*"
$env:KIVYFORGE_HOST_PYTHON_DOWNLOADS = "never"
kf package -p android @Sign; Get-Content $W\kf.err | Select-String "host CPython|\[download\] cpython|byte-compil"
Remove-Item Env:KIVYFORGE_HOST_PYTHON_DOWNLOADS
```

Expect `upgrade` exit `0`, `data.refreshed == ["host-python"]`, `Refreshing the
host CPython 3.14.6 (x86_64-pc-windows-msvc) ...` on stderr, the archive back in
the cache (not yet installed: `upgrade` only fetches),
and then the `never` build exit `0`: it installs from the cached archive with
no `[download]` line, and compiles.

Restore `PATH`. If Step 0 moved anything to `$W\aside0`, put it back in place
of this run's copies.

### Step 8 — report

Write findings to `docs/design/dev/host-python-windows-findings.md`: an
environment table (Windows build, PowerShell, locale encoding,
`LongPathsEnabled`, `%LOCALAPPDATA%` length, JDK, SDK), then each step's
commands, exit codes and output verbatim. **Lead with any defect.** If you fix
one, commit the fix and a hermetic test separately from the findings.

Add a row to [`test-matrix.md`](test-matrix.md) §7: `local`, dated, Host
`Windows` with the build number.

### Rules of engagement

- Record what you **observed**. A skipped step is reported as skipped, with the
  reason.
- Work in scratch copies. Don't commit the scratch locks, the keystore, or
  anything under `dist/` or `build/`.
- Commit on the current branch. **Don't push without asking.**

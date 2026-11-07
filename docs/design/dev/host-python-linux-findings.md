# The lock-pinned host CPython on Linux — findings

Run per [`host-python-linux-prompt.md`](host-python-linux-prompt.md) on WSL2,
2026-11-06, against `main` at `758dc40e` (PR #214 merged), on branch
`host-python-linux`.

**One defect, fixed (`b5dc7502`).** `lock --check` failed with
`KF-LOCK-DRIFT`, exit `4`, and an **empty diff** straight after `lock` wrote
the file, for `archs = ["x86_64", "aarch64"]`, the shape the Linux host-python
pin exists for (Step 2). The cause is older than the pin and not in it:
`serialize.dumps` writes `[[tool.kivyforge.python_runtime.artifacts]]` sorted
by arch, a freshly resolved lock holds them in `archs` order, and the desktop
`semantic_equal` normalised packages, wheels, native binaries, include files
and Swift packages but not the runtime artifacts. Android's normaliser already
sorted its runtimes by ABI. It hits every desktop lock whose `archs` aren't in
alphabetical order (Linux `["x86_64", "aarch64"]`, Windows `["arm64",
"amd64"]`, macOS `["x86_64", "arm64"]`). Fixed by sorting them in
`_normalized`; `tests/platforms/linux/lock/test_serialize.py::TestRoundTrip::
test_reloaded_lock_equals_one_resolved_in_archs_order` fails without the fix
and passes with it, and the real `lock --check` then exits `0`. CHANGELOG
entry under `[Unreleased]`.

**A second, smaller defect, fixed after review (`8a6400d7`).** A release
build's `KF-HOST-PYTHON-FETCH` (Step 5, the warning and the `byte_compile =
true` error) had the URL only in its message, while `upgrade`'s carried
`context.url`. `compiler_for` turns the fetch error into an `Unavailable` and
kept its code and exit status but not its context. The warning path also
ignored the classification's own context, so the `KF-BYTECOMPILE-NO-INTERP`
warning (Step 7) lacked the `context.tool` its error had. `diagnostics.py`
documents both fields for the code, not for one severity. Three tests in
`tests/bundle/test_hostpython.py::TestFetchFailureContext` fail without the
fix; re-run on this host, both Step 5 builds then carry `context.url` and the
Step 7 warning `context.tool` (verbatim under those steps).

Every other step held as the prompt predicted. Of its six unproven items, all
six are now observed on this host: `aarch64` packaging with the pin (Step 3),
the mirror (4), a hash mismatch from a real server and a corrupted cache entry
(5), the install lock (6, with the caveat there), `never` mode and `--no-cache`
with it (7), and WSL2 (this host).

Two things that are not defects, recorded so nobody rediscovers them:

- `--no-cache` with `KIVYFORGE_HOST_PYTHON_DOWNLOADS=never` is `KF-ERROR`,
  exit `1` (Step 7). This is what the design decided
  (`host-python-download-proposal.md` 3.7, "a usage error, exit 1"); the code
  is the unspecific one, which AGENTS.md calls "never wrong", and nothing can
  recover from it automatically, so a dedicated code would buy nothing.
- `kivyforge --version` prints `0.1.0`: `main` released 0.1.0 as the first
  public beta (`4e2a44ef`) after the `3.0.0.dev1` series.

## Environment (Step 0)

| Item | Value |
|------|-------|
| Host | Ubuntu 26.04 LTS on **WSL2** (not native), kernel 6.18.33.2-microsoft-standard-WSL2, x86_64 |
| Repo filesystem | ext4, under `~`, not `/mnt/c` |
| Host Python (kivyforge venv) | 3.14.4 |
| kivyforge | 0.1.0, editable install, `main` @ `758dc40e` |
| Other Pythons on `PATH` | `~/.local/bin/python3.13`, the venv's `python3.14`, uv at `~/.local/bin/uv` (none of them used, as intended) |
| `host-python` cache before | absent (`ls` exit 2) |
| Example | scratch copy of `examples/desktop/dice-roller` (ships CPython 3.13.14) at `/tmp/kf-hostpy/dr` |

```
$ git log --oneline -1
758dc40e Merge pull request #214 from ElliotGarbus/host-python-lock
$ uname -a
Linux DESKTOP-KAH7BP5 6.18.33.2-microsoft-standard-WSL2 #1 SMP PREEMPT_DYNAMIC Thu Jun 18 21:54:43 UTC 2026 x86_64 GNU/Linux
$ grep -qi microsoft /proc/version && echo WSL2 || echo native
WSL2
$ "$KF" --version; "$PY" -V
kivyforge, version 0.1.0
Python 3.14.4
```

## Step 1 — a native x86_64 build pins nothing: PASS

```
$ kf lock -p linux; tail -2 "$W/kf.err"
exit=0
[lock] CPython 3.13.14: checking releases 9-16
[lock] x86_64: resolving wheels
$ grep -c 'tool.kivyforge.host_python' pylock.linux.toml
0
$ kf lock -p linux --check
exit=0
$ "$KF" doctor -p linux 2>&1 | grep 'Byte-compile'
[PASS] Byte-compile interpreter: byte_compile = "release"; the staged runtime compiles its own payload
$ kf package -p linux -f folder --json; grep 'byte-compil' "$W/kf.err"
exit=0
[stage] byte-compiling the Python payload with /tmp/kf-hostpy/dr/build/linux/.Dice Roller.AppDir.tmp-ju0g43sv/usr/python/bin/python3 (.pyc only)
[stage] byte-compiling the embedded stdlib
$ ls "$ROOT/host-python"
(exit 2: does not exist)
```

## Step 2 — an `aarch64` target pins the x86_64 host build: FAIL, fixed, then PASS

```
$ grep '^archs' pyproject.toml
archs = ["arm64"]
archs = ["x86_64", "aarch64"]
archs = ["amd64"]
$ kf lock -p linux
exit=0
$ sed -n '/tool.kivyforge.host_python/,$p' pylock.linux.toml
[[tool.kivyforge.host_python]]
triple = "x86_64-unknown-linux-gnu"
state = "pinned"
minor = "3.13"
version = "3.13.14"
variant = "install_only_stripped"
url = "https://github.com/astral-sh/python-build-standalone/releases/download/20260805/cpython-3.13.14%2B20260805-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
sha256 = "39e82d05926bdcd206732026bcd878d9f00e288cd227d91c1fabf379b6ea4fa5"
$ kf lock -p linux --check
exit=4
$ "$KF" doctor -p linux 2>&1 | grep 'Byte-compile'
[PASS] Byte-compile interpreter: byte_compile = "release"; the locked host CPython 3.13.14 (x86_64-unknown-linux-gnu) is downloaded on the first release build
```

One entry, the x86_64 triple, pinned at 3.13.14 (PBS release `20260805` has it),
no macOS or Windows entry, `doctor` PASS. No GitHub rate limit was hit.

**The defect.** `--check`'s stderr and envelope:

```
[lock] CPython 3.13.14: keeping the locked python-build-standalone build
[lock] x86_64: resolving wheels
[lock] aarch64: resolving wheels
pylock.linux.toml is out of date:
Error: lock is stale; run `kivyforge lock`.
```
```json
"data": {"lockfile": "pylock.linux.toml", "action": "checked", "in_sync": false, "diff": []},
"diagnostics": [{"code": "KF-LOCK-DRIFT", "severity": "error",
  "message": "lock is stale; run `kivyforge lock`.", "remediation": "kivyforge lock -p linux"}]
```

Spying on `semantic_equal` during the real `--check` and printing the
normalised fields that differ found exactly one, `python_runtime`: on disk
`artifacts=(aarch64, x86_64)`, in the candidate `(x86_64, aarch64)`, every URL
and hash identical. After the fix (`b5dc7502`), the same command:

```
$ kf lock -p linux --check
exit=0
[lock] CPython 3.13.14: keeping the locked python-build-standalone build
[lock] x86_64: resolving wheels
[lock] aarch64: resolving wheels
```

Regression test, stashing the fix:

```
--- without fix
FAILED tests/platforms/linux/lock/test_serialize.py::TestRoundTrip::test_reloaded_lock_equals_one_resolved_in_archs_order
--- with fix
.                                                                        [100%]
```

Full suite after the fix: coverage 94.39%, ruff, ruff format and pyright clean.

## Step 3 — package `aarch64`: PASS

```
$ kf package -p linux --arch aarch64 -f folder --json
exit=0
[stage] host CPython 3.13.14 (x86_64-unknown-linux-gnu): installing from the lock
[download] cpython-3.13.14+20260805-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz  0% of 34.8 MB
[download] cpython-3.13.14+20260805-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz  100% of 34.8 MB
[stage] byte-compiling the Python payload with /home/elliot/.cache/kivyforge/artifacts/host-python/39e82d05926bdcd206732026bcd878d9f00e288cd227d91c1fabf379b6ea4fa5/python/bin/python3.13 (.pyc only)
[stage] byte-compiling the embedded stdlib
```

Envelope: `ok: true`, `diagnostics: []`, one artifact
`{"path": "build/linux/Dice Roller.AppDir", "kind": "folder"}`.

```
$ ls -a "$ROOT/host-python/$PIN"
.  ..  .kivyforge-complete  python
$ "$ROOT/host-python/$PIN/python/bin/python3.13" -I -c '...sys.version; MAGIC_NUMBER.hex()'
3.13.14 (main, Aug  5 2026, 15:44:26) [Clang 22.1.3 ]
f30d0d0a
```

The AppDir:

```
usr/python/bin/python3.13: ELF 64-bit LSB pie executable, ARM aarch64, version 1 (SYSV), dynamically linked, interpreter /lib/ld-linux-aarch64.so.1, ...
.py in usr/app + usr/lib: 0
Counter({'f30d0d0a': 336})
PASSED tests/platforms/linux/test_appimage_artifact.py::test_the_appdir_is_internally_consistent
PASSED tests/platforms/linux/test_appimage_artifact.py::test_the_expected_magic_came_from_the_artifact
SKIPPED [1] tests/platforms/linux/test_appimage_artifact.py:220: --linux-appdir given; there is no .AppImage to inspect
```

The skip is the container test, which has nothing to inspect when given a
folder; the `.AppImage` run below covers it.

```
$ kf package -p linux --arch aarch64 --json
exit=0
[stage] byte-compiling the Python payload with /home/elliot/.cache/kivyforge/artifacts/host-python/39e82d05.../python/bin/python3.13 (.pyc only)
[stage] byte-compiling the embedded stdlib
```

`ok: true`, no diagnostics, one artifact
`{"path": "dist/linux/dice-roller-0.1.0-aarch64.AppImage", "kind": "appimage"}`,
and **no download** line: the cached install was reused. The file is
`ELF 64-bit LSB pie executable, ARM aarch64, ... static-pie linked`, and the T3
driver against it (`--linux-appimage ... --linux-arch aarch64 --linux-stripped`):

```
PASSED tests/platforms/linux/test_appimage_artifact.py::test_the_appdir_is_internally_consistent
PASSED tests/platforms/linux/test_appimage_artifact.py::test_the_appimage_container_is_well_formed
PASSED tests/platforms/linux/test_appimage_artifact.py::test_the_expected_magic_came_from_the_artifact
```

A native build alongside the pin still compiles with its own runtime:

```
$ kf package -p linux --arch x86_64 -f folder; grep 'byte-compil' "$W/kf.err"
exit=0
[stage] byte-compiling the Python payload with /tmp/kf-hostpy/dr/build/linux/.Dice Roller.AppDir.tmp-o1if3ml6/usr/python/bin/python3 (.pyc only)
[stage] byte-compiling the embedded stdlib
```

## Step 4 — the mirror: PASS

`http.server` on `127.0.0.1:8765`, serving `20260805/<archive>`;
`KIVYFORGE_HOST_PYTHON_MIRROR=http://127.0.0.1:8765`.

```
$ curl -sI "http://127.0.0.1:8765/$TAG/" | head -1
HTTP/1.0 200 OK
$ kf upgrade -p linux --name host-python --json
exit=0
Refreshing the host CPython 3.13.14 (x86_64-unknown-linux-gnu) ...
[download] cpython-3.13.14+20260805-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz  0% of 34.8 MB
[download] cpython-3.13.14+20260805-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz  100% of 34.8 MB
```

Envelope `ok: true`, `data: {"refreshed": ["host-python"], "skipped": 0}`. Server log:

```
"HEAD /20260805/ HTTP/1.1" 200 -
"GET /20260805/cpython-3.13.14%2B20260805-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz HTTP/1.1" 200 -
```

Cold build through the mirror, install and archive moved aside:

```
$ kf package -p linux --arch aarch64 -f folder
exit=0
[stage] host CPython 3.13.14 (x86_64-unknown-linux-gnu): installing from the lock
[download] cpython-3.13.14+20260805-...-install_only_stripped.tar.gz  0% of 34.8 MB
[download] cpython-3.13.14+20260805-...-install_only_stripped.tar.gz  100% of 34.8 MB
[stage] byte-compiling the Python payload with /home/elliot/.cache/kivyforge/artifacts/host-python/39e82d05.../python/bin/python3.13 (.pyc only)
[stage] byte-compiling the embedded stdlib
$ tail -1 "$W/http.log"
"GET /20260805/cpython-3.13.14%2B20260805-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz HTTP/1.1" 200 -
```

## Step 5 — a hash mismatch, and a corrupt cache entry: PASS

One byte appended to the mirror's copy.

```
$ kf upgrade -p linux --name host-python --json
exit=3
```
```json
"data": {"refreshed": [], "skipped": 0},
"diagnostics": [{"code": "KF-HOST-PYTHON-FETCH", "severity": "error",
  "message": "the host CPython archive doesn't match the lock's SHA-256 (http://127.0.0.1:8765/20260805/cpython-3.13.14%2B20260805-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz)\nFix: check that KIVYFORGE_HOST_PYTHON_MIRROR serves the pinned file unchanged; if the release was replaced, re-lock with `kivyforge lock --update`; otherwise report it.",
  "remediation": "check that KIVYFORGE_HOST_PYTHON_MIRROR serves the pinned file unchanged; ...",
  "context": {"url": "http://127.0.0.1:8765/20260805/cpython-3.13.14%2B20260805-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"}}]
```
```
$ sha256sum <cached archive>; echo "$PIN"
39e82d05926bdcd206732026bcd878d9f00e288cd227d91c1fabf379b6ea4fa5
39e82d05926bdcd206732026bcd878d9f00e288cd227d91c1fabf379b6ea4fa5
```

The cached good archive is untouched.

Cold build against the bad mirror, default `byte_compile = "release"`:

```
$ kf package -p linux --arch aarch64 -f folder --json
exit=0
[stage] not byte-compiling: the host CPython archive doesn't match the lock's SHA-256 (http://127.0.0.1:8765/20260805/...).
  Fix: check that KIVYFORGE_HOST_PYTHON_MIRROR serves the pinned file unchanged; if the release was replaced, re-lock with `kivyforge lock --update`; otherwise report it.
payload .py: 336, .pyc: 0
```

`ok: true`, one `folder` artifact, one diagnostic
`{"code": "KF-HOST-PYTHON-FETCH", "severity": "warning", "message": "not byte-compiling: ..."}`
(no `context`, the second defect). The bad bytes were not cached: afterwards the archive's `39/`
folder was empty and `host-python/` held only `<PIN>.lock`.

With `byte_compile = true` added under `[tool.kivy.linux.build_settings]`:

```
exit=3
```

`ok: false`, `artifacts: []`, one `KF-HOST-PYTHON-FETCH` error: "[tool.kivy.linux.build_settings].byte_compile = true, but the host CPython archive doesn't match the lock's SHA-256 (...)", with the same `Fix:` and `remediation` (no `context`). Setting removed afterwards.

**After `8a6400d7`**, the same two builds, the mirror restarted with
`"$PY" -m http.server 8765 --bind 127.0.0.1 --directory "$W/mirror" & echo $!`
(which records the server's own PID, so `kill` stops it):

```json
[{"code": "KF-HOST-PYTHON-FETCH", "severity": "warning",
  "message": "not byte-compiling: the host CPython archive doesn't match the lock's SHA-256 (http://127.0.0.1:8765/20260805/cpython-3.13.14%2B20260805-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz).",
  "context": {"url": "http://127.0.0.1:8765/20260805/cpython-3.13.14%2B20260805-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"}}]
```
```json
[{"code": "KF-HOST-PYTHON-FETCH", "severity": "error",
  "message": "[tool.kivy.linux.build_settings].byte_compile = true, but the host CPython archive doesn't match the lock's SHA-256 (...).\n  Fix: ...",
  "remediation": "check that KIVYFORGE_HOST_PYTHON_MIRROR serves the pinned file unchanged; ...",
  "context": {"url": "http://127.0.0.1:8765/20260805/cpython-3.13.14%2B20260805-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"}}]
```

Exit `0` and `3`, as before.

Mirror stopped and `KIVYFORGE_HOST_PYTHON_MIRROR` unset; the good archive put
back and truncated to 1 MB:

```
$ kf package -p linux --arch aarch64 -f folder
exit=0
[stage] host CPython 3.13.14 (x86_64-unknown-linux-gnu): installing from the lock
[download] cpython-3.13.14+20260805-...-install_only_stripped.tar.gz  0% of 34.8 MB
[download] cpython-3.13.14+20260805-...-install_only_stripped.tar.gz  100% of 34.8 MB
[stage] byte-compiling the Python payload with /home/elliot/.cache/kivyforge/artifacts/host-python/39e82d05.../python/bin/python3.13 (.pyc only)
[stage] byte-compiling the embedded stdlib
$ sha256sum <cached archive>
39e82d05926bdcd206732026bcd878d9f00e288cd227d91c1fabf379b6ea4fa5
```

The prompt's `kill "$(cat http.pid)"` did not stop the server here: `$!`
inside `( cd ... && setsid nohup ... & )` is the PID of the backgrounded
`cd && setsid` list, not of the Python server, so it was still listening
during this build. A test-script problem, not kivyforge's. The
server log shows no request after the up-check that found it, so the
re-download came from GitHub, as intended; the server was stopped afterwards
with `pkill -f 'http.server 8765'`.

## Step 6 — two builds installing the same pin at once: PASS

Install removed, archive kept, `dr` and a second copy `dr2` started together:

```
b=0
a=0
/tmp/kf-hostpy/a.err:[stage] host CPython 3.13.14 (x86_64-unknown-linux-gnu): installing from the lock
/tmp/kf-hostpy/a.err:[stage] byte-compiling the Python payload with /home/elliot/.cache/kivyforge/artifacts/host-python/39e82d05.../python/bin/python3.13 (.pyc only)
/tmp/kf-hostpy/a.err:[stage] byte-compiling the embedded stdlib
/tmp/kf-hostpy/b.err:[stage] byte-compiling the Python payload with /home/elliot/.cache/kivyforge/artifacts/host-python/39e82d05.../python/bin/python3.13 (.pyc only)
/tmp/kf-hostpy/b.err:[stage] byte-compiling the embedded stdlib
$ ls -a "$ROOT/host-python"
.  ..  39e82d05926bdcd206732026bcd878d9f00e288cd227d91c1fabf379b6ea4fa5  39e82d05926bdcd206732026bcd878d9f00e288cd227d91c1fabf379b6ea4fa5.lock
```

Both exit `0`, exactly one `installing from the lock`, both compile with the
same interpreter, one `$PIN` directory and no `.<first 12>-*` temporary left.
The `<PIN>.lock` file is the `flock` target. **Caveat:** nothing in the output
proves the two installs overlapped in time. `b` finished first without
installing, which fits it having waited on the lock while `a` installed, but a
`b` that simply started after `a` finished would log the same.

## Step 7 — downloads off: PASS

`package --help` lists `--no-cache` ("Force re-download of every artifact.").
`KIVYFORGE_HOST_PYTHON_DOWNLOADS=never`:

```
### cached
$ kf package -p linux --arch aarch64 -f folder
exit=0
[stage] byte-compiling the Python payload with /home/elliot/.cache/kivyforge/artifacts/host-python/39e82d05.../python/bin/python3.13 (.pyc only)
$ "$KF" doctor -p linux 2>&1 | grep 'Byte-compile'
[PASS] Byte-compile interpreter: byte_compile = "release"; the locked host CPython 3.13.14 (x86_64-unknown-linux-gnu): /home/elliot/.cache/kivyforge/artifacts/host-python/39e82d05.../python/bin/python3.13
### --no-cache
$ kf package -p linux --arch aarch64 -f folder --no-cache --json
exit=1
```
```json
"ok": false, "data": {"artifacts": [], ...},
"diagnostics": [{"code": "KF-ERROR", "severity": "error",
  "message": "--no-cache asks to download the host CPython again, and KIVYFORGE_HOST_PYTHON_DOWNLOADS=never forbids downloading it.\nFix: drop --no-cache, or unset the variable.",
  "remediation": "drop --no-cache, or unset the variable."}]
```
```
### install and archive moved aside
$ "$KF" doctor -p linux 2>&1 | grep -A1 'Byte-compile'
[WARN] Byte-compile interpreter: byte_compile = "release", but the locked host CPython 3.13.14 (x86_64-unknown-linux-gnu) isn't in the cache and KIVYFORGE_HOST_PYTHON_DOWNLOADS=never; release builds will ship source
       hint: run `kivyforge upgrade -p linux` with network access, or unset KIVYFORGE_HOST_PYTHON_DOWNLOADS.
$ kf package -p linux --arch aarch64 -f folder --json
exit=0
```

`ok: true`, one `folder` artifact, one warning
`{"code": "KF-BYTECOMPILE-NO-INTERP", "message": "not byte-compiling: the locked host CPython 3.13.14 (x86_64-unknown-linux-gnu) isn't in the cache, and KIVYFORGE_HOST_PYTHON_DOWNLOADS=never."}`,
with no `context`. After `8a6400d7` the same run's warning carries
`"context": {"tool": "python3.13"}`, exit `0`.
The install and archive were put back (`.kivyforge-complete` present, archive
hash `$PIN`).

## Not done

- No launch on a Raspberry Pi: the prompt needs none, and the `aarch64`
  `.AppImage` was checked by T3 only.
- No GitHub rate limit was met, so that `KF-HOST-PYTHON-FETCH` path was not
  exercised.

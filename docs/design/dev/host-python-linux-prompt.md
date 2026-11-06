# Agent prompt — the lock-pinned host CPython on Linux

> **Run this on Linux x86_64 or WSL2**, from the repo root, on the Linux
> filesystem (not `/mnt/c`). Written 2026-11-06 on macOS, which can't build a
> Linux `aarch64` target. You need branch `host-python-lock` at `98b55305` or
> later (PR #214), or `main` once it merges. Network access is required; no
> Android SDK and no Raspberry Pi are needed.
>
> Point the agent at this file, or copy the "Prompt" section.

## Background — what is proven, and what this host adds

[`host-python-download-proposal.md`](host-python-download-proposal.md)
(implemented) moves byte-compiling for iOS, Android and Linux `aarch64` onto a
python-build-standalone CPython that `kivyforge lock` pins in
`[[tool.kivyforge.host_python]]` and the first release build downloads,
verifies, installs and compiles with. On Linux that is the
`x86_64-unknown-linux-gnu` entry, installed to
`~/.cache/kivyforge/artifacts/host-python/<sha256>/python/bin/python3.X`.

**Already proven:**

- macOS, for iOS and Android, by hand: [`test-matrix.md`](test-matrix.md) §7,
  the two 2026-11-06 rows, including `never` mode and `byte_compile = true`.
- **Android on Linux, by CI.** PR #214's "Android build (Gradle, x86_64)" and
  "Android App Bundle" jobs (run 42310933394) logged `host CPython 3.14.6
  (x86_64-unknown-linux-gnu): installing from the lock`, downloaded the 35.8 MB
  stripped archive, compiled with `.../host-python/ba960817.../python/bin/python3.14`,
  and their stripped T3 passed.

**Not proven, and this host is where they can be:**

1. **Linux `aarch64`, the reason Linux needs a pin at all.** A Linux build
   compiles with its own staged runtime when that runtime runs on the build
   machine. An `aarch64` target built on x86_64 can't, so the lock pins the
   x86_64 host build whenever `archs` includes `aarch64`, and only then. No run
   has built an `aarch64` package since the switch.
2. **`KIVYFORGE_HOST_PYTHON_MIRROR`**, against a real HTTP server.
3. **A hash mismatch from a real server**, and a corrupted cache entry.
4. **The install lock** (`fcntl.flock`): two builds installing the same pin at
   once, on any host.
5. `never` mode on Linux, and `--no-cache` combined with it.
6. WSL2, if that is what this host is.

---

## Prompt

You are verifying kivyforge's lock-pinned host CPython on a real Linux host.
**Record what you observe**, with exit codes and output verbatim. If a step
fails, capture it and go on with the independent steps.

Set up once, from the repo root:

```bash
rm -rf /tmp/kf-hostpy; mkdir /tmp/kf-hostpy
cat >/tmp/kf-hostpy/env.sh <<EOF
REPO=$PWD; KF=$PWD/.venv/bin/kivyforge; PY=$PWD/.venv/bin/python
W=/tmp/kf-hostpy
ROOT=\${XDG_CACHE_HOME:-\$HOME/.cache}/kivyforge/artifacts
kf() { "\$KF" "\$@" >"\$W/kf.out" 2>"\$W/kf.err"; echo "exit=\$?"; }
EOF
. /tmp/kf-hostpy/env.sh
```

If your shell doesn't keep state between commands, start each one with
`. /tmp/kf-hostpy/env.sh`, re-run the `PIN`/`URL`/`NAME`/`TAG` lines once
they exist, and repeat any `export` a step has in force.

### Step 0 — environment

```bash
git log --oneline -1                       # 98b55305 or later
uname -a; head -2 /etc/os-release
grep -qi microsoft /proc/version && echo WSL2 || echo native
"$KF" --version; "$PY" -V
command -v python3.13 python3.14 uv        # record; none of them should matter
ls -a "$ROOT/host-python" 2>/dev/null
```

If `host-python` already holds installs, leave them. Every step below names
its own pin by hash.

Make a scratch copy of `dice-roller`, which ships CPython 3.13.14 for Linux:

```bash
git archive HEAD:examples/desktop/dice-roller | tar -x -C "$W" --one-top-level=dr
cd "$W/dr"
```

### Step 1 — a native x86_64 build pins nothing

`archs` defaults to `["x86_64"]` here.

```bash
kf lock -p linux; tail -2 "$W/kf.err"
grep -c 'tool.kivyforge.host_python' pylock.linux.toml      # 0
kf lock -p linux --check                                     # exit 0
"$KF" doctor -p linux 2>&1 | grep 'Byte-compile'
kf package -p linux -f folder --json; grep 'byte-compil' "$W/kf.err"
ls "$ROOT/host-python" 2>/dev/null
```

Expect no table, `--check` exit `0`, `doctor` saying the staged runtime
compiles its own payload, and the package byte-compiling with the AppDir's own
`usr/python/bin/python3`, **not** a `host-python` path, with nothing new under
`host-python`.

### Step 2 — an `aarch64` target pins the x86_64 host build

```bash
sed -i 's/^archs = \["x86_64"\]/archs = ["x86_64", "aarch64"]/' pyproject.toml
grep '^archs' pyproject.toml
kf lock -p linux; tail -3 "$W/kf.err"
sed -n '/tool.kivyforge.host_python/,$p' pylock.linux.toml
kf lock -p linux --check
"$KF" doctor -p linux 2>&1 | grep 'Byte-compile'
```

Changing `archs` re-resolves the lock; a GitHub rate limit here is exit `3`,
`KF-HOST-PYTHON-FETCH` (set `GH_TOKEN=$(gh auth token)` and retry). Expect one
entry, `triple = "x86_64-unknown-linux-gnu"`, `state = "pinned"`, `minor =
"3.13"`, `variant = "install_only_stripped"`, at **3.13.14** if PBS has it for
that triple, otherwise the newest 3.13 it has (say which, and check the PBS
release page). No macOS or Windows entry: only a Linux host builds Linux.
`--check` exit `0`; `doctor` PASS, "downloaded on the first release build".

Record the pin, which every later step uses:

```bash
PIN=$(sed -n '/host_python/,$ s/^sha256 = "\(.*\)"/\1/p' "$W/dr/pylock.linux.toml" | head -1)
URL=$(sed -n '/host_python/,$ s/^url = "\(.*\)"/\1/p' "$W/dr/pylock.linux.toml" | head -1)
echo "$PIN $URL"
```

### Step 3 — package `aarch64`

```bash
kf package -p linux --arch aarch64 -f folder --json
grep -E 'host CPython|byte-compil|\[download\] cpython' "$W/kf.err" | grep -vE ' [1-9]0% of'
"$PY" -m json.tool "$W/kf.out"
ls -a "$ROOT/host-python/$PIN"
"$ROOT/host-python/$PIN/python/bin/python3.13" -I -c 'import sys, importlib.util; print(sys.version); print(importlib.util.MAGIC_NUMBER.hex())'
```

Expect exit `0`, `ok: true`, no diagnostics, one `folder` artifact; on stderr
`installing from the lock`, the download (about 36 MB), and `byte-compiling ...
with .../host-python/<PIN>/python/bin/python3.13`. The install holds `python`
and `.kivyforge-complete`, and reports 3.13.x final with magic `f30d0d0a`.

Check the AppDir, from the repo root:

```bash
APPDIR="$W/dr/$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["data"]["artifacts"][0]["path"])' "$W/kf.out")"
file "$APPDIR/usr/python/bin/python3"*                      # ARM aarch64
find "$APPDIR/usr/app" "$APPDIR/usr/lib" -name '*.py' | wc -l   # 0
"$PY" -I -c 'import collections, pathlib, sys; print(collections.Counter(p.read_bytes()[:4].hex() for d in sys.argv[1:] for p in pathlib.Path(d).rglob("*.pyc")))' "$APPDIR/usr/app" "$APPDIR/usr/lib"
cd "$REPO"
"$PY" -m pytest -q --no-cov -p no:cacheprovider tests/platforms/linux/test_appimage_artifact.py \
  --linux-appdir "$APPDIR" --linux-arch aarch64 --linux-stripped
cd "$W/dr"
```

Expect an aarch64 interpreter, no `.py` in the payload, one magic in the
counter, `f30d0d0a` (the host CPython's, which is 3.13's), and the T3 driver
passing.

Then the `.AppImage`, and a native build alongside the pin:

```bash
kf package -p linux --arch aarch64 --json; "$PY" -m json.tool "$W/kf.out"   # an appimage artifact, no download
kf package -p linux --arch x86_64 -f folder; grep 'byte-compil' "$W/kf.err"  # the AppDir's own runtime
```

### Step 4 — the mirror

Serve the pinned archive from a local server laid out like the release
download path:

```bash
NAME=$("$PY" -c 'import sys, urllib.parse; print(urllib.parse.unquote(sys.argv[1].rsplit("/", 1)[1]))' "$URL")
TAG=$(echo "$URL" | awk -F/ '{print $(NF-1)}')
mkdir -p "$W/mirror/$TAG"
cp "$ROOT/${PIN:0:2}/$PIN-$NAME" "$W/mirror/$TAG/$NAME"
(cd "$W/mirror" && setsid nohup "$PY" -m http.server 8765 --bind 127.0.0.1 >"$W/http.log" 2>&1 & echo $! >"$W/http.pid")
sleep 1; curl -sI "http://127.0.0.1:8765/$TAG/" | head -1   # the server is up
export KIVYFORGE_HOST_PYTHON_MIRROR=http://127.0.0.1:8765
kf upgrade -p linux --name host-python --json; "$PY" -m json.tool "$W/kf.out"
cat "$W/http.log"
```

Expect `upgrade` exit `0`, `data.refreshed == ["host-python"]`, and one `GET
/<TAG>/cpython-...%2B...tar.gz` with `200` in the server log. `upgrade` always
re-fetches, so this proves the mirror URL is built correctly.

Now a cold build through the mirror:

```bash
mkdir -p "$W/aside"; mv "$ROOT/host-python/$PIN" "$ROOT/${PIN:0:2}/$PIN-$NAME" "$W/aside/"
kf package -p linux --arch aarch64 -f folder; grep -E 'host CPython|byte-compil|\[download\]' "$W/kf.err" | grep -vE ' [1-9]0% of'
tail -1 "$W/http.log"
```

Expect exit `0`, a second `GET` in the server log, and the compile using the
fresh install.

### Step 5 — a hash mismatch, and a corrupt cache entry

Serve different bytes under the same name:

```bash
printf 'x' >> "$W/mirror/$TAG/$NAME"
cp "$ROOT/${PIN:0:2}/$PIN-$NAME" "$W/good.tar.gz"
kf upgrade -p linux --name host-python --json; "$PY" -m json.tool "$W/kf.out"
sha256sum "$ROOT/${PIN:0:2}/$PIN-$NAME" | cut -c1-64; echo "$PIN"
```

Expect exit `3`, one `KF-HOST-PYTHON-FETCH` saying the archive doesn't match
the lock's SHA-256, with the mirror URL, `context.url`, and a `Fix:` that names
`KIVYFORGE_HOST_PYTHON_MIRROR` and `lock --update`. The cached good archive is
**untouched** (its hash still equals `$PIN`): the bad bytes were checked before
they reached the cache.

The same mismatch during a cold build:

```bash
rm -rf "$ROOT/host-python/$PIN" "$ROOT/${PIN:0:2}/$PIN-$NAME"
kf package -p linux --arch aarch64 -f folder --json; "$PY" -m json.tool "$W/kf.out"
grep -A2 'not byte-compiling' "$W/kf.err"
```

With the default `byte_compile = "release"`, expect exit `0`, `ok: true`, a
`KF-HOST-PYTHON-FETCH` warning, and a payload that ships source. Then add
`byte_compile = true` under `[tool.kivy.linux.build_settings]` and run it
again: exit `3`, `ok: false`, no artifacts, `KF-HOST-PYTHON-FETCH`. Remove the
setting afterwards.

Stop the mirror and corrupt the cache entry instead:

```bash
unset KIVYFORGE_HOST_PYTHON_MIRROR; kill "$(cat "$W/http.pid")"
cp "$W/good.tar.gz" "$ROOT/${PIN:0:2}/$PIN-$NAME"
truncate -s 1M "$ROOT/${PIN:0:2}/$PIN-$NAME"
kf package -p linux --arch aarch64 -f folder; grep -E 'host CPython|byte-compil|\[download\]|mismatch|corrupt' "$W/kf.err" | grep -vE ' [1-9]0% of'
sha256sum "$ROOT/${PIN:0:2}/$PIN-$NAME" | cut -c1-64
```

Expect exit `0`: the truncated entry is dropped, the archive is downloaded
again from GitHub, its hash is `$PIN` again, and the build compiles.

### Step 6 — two builds installing the same pin at once

```bash
git -C "$REPO" archive HEAD:examples/desktop/dice-roller | tar -x -C "$W" --one-top-level=dr2
cp pyproject.toml pylock.linux.toml "$W/dr2/"
rm -rf "$ROOT/host-python/$PIN"            # keep the archive
( "$KF" package -p linux --arch aarch64 -f folder >"$W/a.out" 2>"$W/a.err"; echo "a=$?" ) &
( cd "$W/dr2" && "$KF" package -p linux --arch aarch64 -f folder >"$W/b.out" 2>"$W/b.err"; echo "b=$?" ) &
wait
grep -H -E 'host CPython|byte-compil' "$W/a.err" "$W/b.err"
ls -a "$ROOT/host-python"
```

Expect both exit `0`, **exactly one** `installing from the lock` line between
them, both compiling with the same interpreter, one `$PIN` directory and no
`.<first 12 of PIN>-*` directory left behind. Both logging `installing` means
the lock isn't excluding, a defect even if both builds pass.

### Step 7 — downloads off

```bash
export KIVYFORGE_HOST_PYTHON_DOWNLOADS=never
kf package -p linux --arch aarch64 -f folder; grep 'byte-compil' "$W/kf.err"     # exit 0, compiles
"$KF" doctor -p linux 2>&1 | grep 'Byte-compile'                                   # PASS, the cached path
kf package -p linux --arch aarch64 -f folder --no-cache --json; "$PY" -m json.tool "$W/kf.out"   # exit 1
mv "$ROOT/host-python/$PIN" "$ROOT/${PIN:0:2}/$PIN-$NAME" "$W/aside/"
"$KF" doctor -p linux 2>&1 | grep -A1 'Byte-compile'                               # WARN
kf package -p linux --arch aarch64 -f folder --json; "$PY" -m json.tool "$W/kf.out"   # exit 0, KF-BYTECOMPILE-NO-INTERP
unset KIVYFORGE_HOST_PYTHON_DOWNLOADS
```

Check `package --help` lists `--no-cache` before relying on it; if it doesn't,
skip that line and say so. The `--no-cache` + `never` run should exit `1` with
a message naming both. Put the install and archive back from `$W/aside`
afterwards (they are the same pin, so either copy is fine).

### Step 8 — report

Write findings to `docs/design/dev/host-python-linux-findings.md`: an
environment table (distro, kernel, **WSL2 or native**, Python, kivyforge
commit), then each step's commands, exit codes and output verbatim. **Lead with
any defect.** If you fix one, commit the fix and a hermetic test separately from
the findings.

Add a row to [`test-matrix.md`](test-matrix.md) §7: `local`, dated, Host
`Linux` or `WSL2` (that section requires saying which).

### Rules of engagement

- Record what you **observed**. A skipped step is reported as skipped, with the
  reason.
- Work in the scratch copies under `$W`. `dice-roller` gitignores its lock;
  don't commit it, or anything under `dist/` or `build/`.
- Commit on the current branch. **Don't push without asking.**

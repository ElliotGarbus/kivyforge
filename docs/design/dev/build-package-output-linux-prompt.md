# Agent prompt — `build`/`package` output on Linux

> **Run this on Linux or WSL2**, from the repo root of `modernization-rfc`. Written
> 2026-09-16. Companion to
> [`build-package-output-mac-prompt.md`](build-package-output-mac-prompt.md), and
> deliberately much shorter: CI already covers most of the Linux side.
>
> Point the agent at this file, or copy the "Prompt" section.

## Background — what CI proved, and what it did not

[`build-package-output-proposal.md`](build-package-output-proposal.md) §6 records
the implementation (commits `1930abe2`…`89798096`). Every push of those commits
was green in the `kivyforge` workflow, and two of its jobs matter here:

- **Unit tests (Ubuntu)** ran the full hermetic suite on 3.13 and 3.14, so the
  new tests passed on a POSIX host.
- **Android build (Gradle, no emulator)** runs real Gradle on Ubuntu through
  `kivyforge build -p android --debug` and `kivyforge package -p android`. That
  exercised step 2's stderr redirection with a real child and a real descriptor,
  and it still builds and signs. (It does not pass `--json`, so the envelope
  itself was not checked there.)

What no CI job does is **build a Linux AppImage**. So these are unproven against
a real `appimagetool`:

- `package -p linux --json`: stdout holds only the envelope, with the
  `.AppImage` as an `appimage` artifact, and the staging progress on stderr.
- **A failing `appimagetool`**: both of its output streams go to stderr, and the
  error is one line with exit `5`, `KF-BUILD-TOOL-FAILED`,
  `context = {"tool": "appimagetool", "task": "package"}`. Before, the error
  embedded `stderr or stdout` and dropped the other stream.
- **An `appimagetool` that cannot be executed**: exit `3`,
  `KF-TOOLCHAIN-UNUSABLE`, `context.errno`.

---

## Prompt

You are verifying kivyforge's `build`/`package` output contract on a real Linux
host, for the AppImage path that CI does not build. **Record what you observe**,
with exit codes and output verbatim. If a step fails, capture it and continue
with the independent steps.

**Work on the Linux filesystem, not `/mnt/c`.** Under WSL2, permission bits on
Windows drives do not behave like Linux ones, and Step 2 depends on them. Record
in the report whether this is WSL2 or a real Linux host.

Capture the streams separately in every step:

```bash
kf() { ../../../.venv/bin/kivyforge "$@" >/tmp/kf.out 2>/tmp/kf.err; echo "exit=$?"; }
```

### Step 0 — environment

```bash
git pull                      # you need 8036c8c5 or later
uname -a; cat /etc/os-release | head -2
grep -qi microsoft /proc/version && echo WSL2 || echo native
.venv/bin/kivyforge --version; .venv/bin/python -V
.venv/bin/kivyforge doctor -p linux
```

### Step 1 — the success path

```bash
cd examples/desktop/dice-roller
kf build -p linux
cat /tmp/kf.out                                   # expect only: Built build/linux/<Name>.AppDir
kf package -p linux --json
python -m json.tool /tmp/kf.out
cat /tmp/kf.err
ls -l dist/linux/
```

Check:

- The human `build`: stdout is exactly the `Built` line; the staging lines are
  on stderr.
- The `--json` `package`: stdout parses as one document, `ok: true`,
  `platform: "linux"`, and `data.artifacts` is exactly
  `[{"path": "dist/linux/<slug>-<version>-x86_64.AppImage", "kind": "appimage"}]`
  — a relative, posix path that exists. The distribution advice must **not** be
  on stdout. `Packaging … with appimagetool …` must be on stderr.
- `diagnostics`: empty, or a `KF-BYTECOMPILE-NO-INTERP` warning if no final
  CPython of the target minor was found (say which). Exit `0` either way.
- Run the built AppImage once (`--appimage-extract-and-run` if there is no FUSE)
  to confirm the step-1–4 refactor did not change what gets packaged.

Also `kf package -p linux -f folder --json`: one artifact, `kind: "folder"`,
path `build/linux/<Name>.AppDir`.

### Step 2 — `appimagetool` fails

Make the output directory unwritable, so `appimagetool` runs and then fails:

```bash
chmod a-w dist/linux
kf package -p linux --json
chmod u+w dist/linux
python -m json.tool /tmp/kf.out
cat /tmp/kf.err
```

Expect exit `5`, `ok: false`, `data.artifacts == []`, one diagnostic with code
`KF-BUILD-TOOL-FAILED`, `context == {"tool": "appimagetool", "task": "package"}`,
and a one-line message ending `its output is above.` `appimagetool`'s own output
must be in `/tmp/kf.err`, and **not** inside the diagnostic message.

Also check that `artifacts` is `[]` even though Step 1's `.AppImage` is still
sitting in `dist/linux`: the proposal (§4.1b) forbids naming a previous run's
artifact on a failure, and this is the real-world version of that case.

If `appimagetool` somehow **succeeds** here (e.g. running as root, which ignores
the permission bits), say so and note the user. If the run fails *before*
`appimagetool` starts, record where; that failure is not this step's target.

### Step 3 — `appimagetool` cannot be executed

kivyforge copies `appimagetool` into `$XDG_CACHE_HOME/kivyforge/bin` and marks it
executable on every run, so point the cache at a `noexec` mount:

```bash
sudo mkdir -p /mnt/kf-noexec
sudo mount -t tmpfs -o noexec,size=512m tmpfs /mnt/kf-noexec
sudo chown "$USER" /mnt/kf-noexec
XDG_CACHE_HOME=/mnt/kf-noexec ../../../.venv/bin/kivyforge package -p linux --json \
  >/tmp/kf.out 2>/tmp/kf.err; echo "exit=$?"
python -m json.tool /tmp/kf.out
sudo umount /mnt/kf-noexec
```

This re-downloads the runtime, wheels and `appimagetool` into the empty cache,
so it needs the network. Expect exit `3`, `KF-TOOLCHAIN-UNUSABLE`,
`context.tool == "appimagetool"` and `context.errno == "EACCES"`.

**If it fails earlier**, record exactly what failed and with which code. The
staged CPython is extracted into `build/linux`, not the cache, so byte-compilation
should be unaffected; anything else that tries to execute from the cache would
be a surprise worth noting. A traceback with no envelope is a defect; a
different, correctly classified failure is a finding about the test, not the
code.

`KF-TOOLCHAIN-MISSING` cannot be reached for `appimagetool`, because kivyforge
always downloads it. Do not try to force it.

### Step 4 — report

Write findings to `docs/design/dev/build-package-output-linux-findings.md`: an
environment table (including WSL2 vs native), then each step's commands, exit
codes and relevant output verbatim. Lead with any defect.

If you fix one, put the fix and a hermetic test in a separate commit from the
findings, so it cannot regress on the Windows host.

Add a row to [`test-matrix.md`](test-matrix.md) §7 (`local`, dated, Host `Linux`
or `WSL2` — that section requires saying which).

### Rules of engagement

- Record what you **observed**. A skipped step is reported as skipped, with the
  reason.
- Do **not** commit generated example locks or anything under `dist/`/`build/`.
- Commit on `modernization-rfc`. **Do not push without asking.**

---

## Follow-up added 2026-09-17 — the compiled stdlib on Linux

Independent of the steps above; needs `7aab358f` or later. Roadmap item 9 now
byte-compiles the staged stdlib, and the Windows host measured it
(`import kivy`: 66 ms compiled against 276 ms source-only). **Linux is
unmeasured, and it is the host with the most to gain**: a `.AppImage` mounts
read-only, so it could never cache the stdlib at runtime and has paid full parse
cost on every launch since the beginning (§5.10).

```bash
cd examples/desktop/dice-roller
kivyforge package -p linux -f folder     # the AppDir: inspectable and measurable
APPDIR=$(ls -d build/linux/*.AppDir)
```

**1. The artifact ships compiled, with sources kept.**

```bash
find "$APPDIR/usr/python" -name '*.py'  -not -path '*site-packages*' | wc -l   # many
find "$APPDIR/usr/python" -name '*.pyc' -not -path '*site-packages*' | wc -l   # ~same
find "$APPDIR/usr/app" -name '*.py' | wc -l                                    # 0
```

The 2026-09-15 finding to re-check while you are here: a stripped AppDir used to
ship 41 stdlib `.pyc` in 6 `__pycache__` dirs that nothing asked for — the
compile subprocess's own imports. That subset should now be gone, replaced by
the deliberate, complete set.

**2. Measure, min of 5, with the AppDir's own interpreter:**

```bash
cd "$APPDIR"
for i in 1 2 3 4 5; do
  PYTHONHOME="$PWD/usr/python" PYTHONPATH="$PWD/usr/app:$PWD/usr/lib" \
  PYTHONDONTWRITEBYTECODE=1 \
  ./usr/python/bin/python3 -X importtime -c 'import kivy' 2>&1 | tail -1
done
```

Take the cumulative figure for `kivy`, then delete the stdlib `__pycache__`
(`find usr/python -name __pycache__ -not -path '*site-packages*' -exec rm -rf {} +`)
and repeat for the source-only number. Re-run `package` afterwards to restore
the tree.

**3. Confirm the `.AppImage` carries it too** — that is the shape that could
never cache at runtime:

```bash
kivyforge package -p linux
./dist/linux/*.AppImage --appimage-extract >/dev/null
find squashfs-root/usr/python -name '*.pyc' -not -path '*site-packages*' | wc -l
```

**4. Record** in [`test-matrix.md`](test-matrix.md) §7 (Host `Linux` or `WSL2` —
say which), and replace §5.10's "not re-measured on Linux" line with the number.

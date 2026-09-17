# `build`/`package` output on Linux — findings

Run against `modernization-rfc` per
[`build-package-output-linux-prompt.md`](build-package-output-linux-prompt.md),
in WSL2. Date: 2026-09-16.

**No defects.** Every assertion in Steps 1–3 held exactly as specified, against
a real `appimagetool` on the AppImage path no CI job builds. Nothing was
changed in `kivyforge/`, so there is no accompanying fix commit.

One step was run by a different mechanism than the prompt suggested (Step 3,
a `noexec` filesystem that already existed rather than a `sudo` mount); the
substitution and why it is a closer match are recorded there.

## Environment (Step 0)

| Item | Value |
|------|-------|
| Host | Ubuntu 26.04 LTS on **WSL2** (not native), kernel 6.18.33.2-microsoft-standard-WSL2 |
| Repo filesystem | `ext4` on `/dev/sdd` — **not** `/mnt/c`, so permission bits behave |
| Running as | uid 1000 (`elliot`), **not root** — load-bearing for Step 2 |
| Host Python | 3.14.4 |
| Bundled runtime | CPython 3.13.14 |
| `appimagetool` | 1.9.1 (continuous build, git `8c8c91f`, build 296) |
| kivyforge | 3.0.0.dev0 (editable install) |
| Branch | `modernization-rfc` @ `5eb28e07` |
| Example | `examples/desktop/dice-roller` |

`kivyforge doctor -p linux` from the example directory: **exit 0**, every check
`PASS` except two `SKIP`s for unconfigured features (`find_links`, native
binaries). Note it must be run from the example, not the repo root — the root
`pyproject.toml` has no `[tool.kivy]` table, so doctor there reports a `FAIL`
that is correct and unrelated.

Streams were captured separately throughout, per the prompt's `kf` helper.

## Step 1 — the success path

### `build -p linux` (human)

Exit `0`. stdout, in full:

```
Built build/linux/Dice Roller.AppDir
```

stderr, in full:

```
Staging CPython 3.13.14 runtime (x86_64) ...
Installing 2 locked packages ...
```

The product line is alone on stdout and the staging progress is on stderr, as
the contract requires.

### `package -p linux --json`

Exit `0`. stdout is **278 bytes, one JSON document, nothing else** — checked by
strict `json.loads` on the raw bytes rather than by eye:

```json
{
  "schema": 1, "kivyforge": "3.0.0.dev0", "command": "package",
  "platform": "linux", "ok": true,
  "data": {"artifacts": [
    {"path": "dist/linux/dice-roller-0.1.0-x86_64.AppImage", "kind": "appimage"}
  ]},
  "diagnostics": []
}
```

Exactly one artifact; the path is relative, posix-spelled, and exists on disk.
`diagnostics` is empty rather than carrying `KF-BYTECOMPILE-NO-INTERP`, which is
the expected branch here: this is a native x86_64 build, so the staged runtime
compiles its own payload and no host interpreter is needed.

stderr carried the progress, including `Packaging dice-roller-0.1.0-x86_64.AppImage
with appimagetool 1.9.1 ...`.

**Observation, not a defect.** Under `--json` the distribution advice ("chmod +x,
then run …", the glibc/libGL note) is **suppressed entirely** rather than
redirected to stderr — it appears on neither stream. The contract only forbids
it on stdout, so this is compliant, but "moved to stderr" is the other
reasonable reading of the requirement and the two are indistinguishable from
the prompt's wording. Recorded so the choice is on the record rather than
discovered later.

### `package -p linux -f folder`

Human mode, exit `0` — product line *and* its advice on stdout, staging on
stderr:

```
Packaged build/linux/Dice Roller.AppDir (AppDir folder).
  Run it with ./AppRun, or `kivyforge package -f appimage` for a single-file distributable.
```

`--json` mode, exit `0`, one artifact as specified:

```json
"artifacts": [{"path": "build/linux/Dice Roller.AppDir", "kind": "folder"}]
```

The path contains a space and is still emitted relative and posix-spelled.

### Launching the packaged `.AppImage`

Ran directly (this host has `/dev/fuse`, so no `--appimage-extract-and-run` was
needed), for 15 s under `timeout`: SDL2 window provider up, `OpenGL 4.5
(Compatibility Profile) Mesa 26.0.3` via llvmpipe, and `Start application main
loop` reached. The step-1–4 refactor did not change what gets packaged.

It also prints a traceback ending:

```
OSError: libmtdev.so.1: cannot open shared object file: No such file or directory
```

This is **non-fatal and not kivyforge's**: Kivy probes its optional `mtdev`
input provider, this host has no `libmtdev.so.1`, Kivy logs and continues —
`Provider: sdl2` follows on the next line. Longstanding Kivy behaviour on hosts
without that library, unrelated to this contract.

## Step 2 — `appimagetool` fails

`chmod a-w dist/linux`, then `package -p linux --json`. Confirmed uid 1000
first, so the permission bits were actually enforced; the prompt's "if it
succeeds because you are root" caveat did not apply. Write permission was
restored immediately after.

**Exit `5`.** Envelope:

```json
{
  "ok": false,
  "data": {"artifacts": []},
  "diagnostics": [{
    "code": "KF-BUILD-TOOL-FAILED",
    "severity": "error",
    "message": "appimagetool failed to build the AppImage (exit 1); its output is above.",
    "context": {"tool": "appimagetool", "task": "package"}
  }]
}
```

Every assertion holds: `ok: false`; `artifacts` empty; exactly one diagnostic;
`context` equal to `{"tool": "appimagetool", "task": "package"}`; the message a
single line (72 chars) ending `its output is above.`

**`artifacts == []` while a previous artifact existed.** `dist/linux` still held
Step 1's `.AppImage` (timestamped 19:40) throughout, and the failure did not
name it — the real-world form of proposal §4.1b, checked rather than assumed.

**Both of `appimagetool`'s streams reached stderr**, which is the specific thing
the old `stderr or stdout` handling dropped. Its *stdout* ("… should be packaged
as …", the AppStream warning, `Generating squashfs...`) and its *stderr*
(`Could not create destination file: Permission denied`, `mksquashfs (pid 11919)
exited with code 1`, `sfs_mksquashfs error`) are both present, followed by
kivyforge's own one-line `Error:` rendering. Programmatically confirmed that
none of the tool's output is embedded in the diagnostic `message`.

## Step 3 — `appimagetool` cannot be executed

**Deviation from the prompt, deliberate.** The prompt suggests
`sudo mount -t tmpfs -o noexec`. This host already has `/run/lock`: a `tmpfs`
mounted `rw,nosuid,nodev,noexec,noatime`, mode `1777`, with 3.9 GB free against
the ~336 MB an empty kivyforge cache needs. Pointing `XDG_CACHE_HOME` there
gives the identical condition with no privileged host change and nothing to
unmount — and it is arguably the better test, because the process keeps its real
uid instead of being mapped to root inside a namespace, which is the situation a
user on a hardened `/home` or `/tmp` would actually be in.

```bash
XDG_CACHE_HOME=/run/lock/kf-noexec kivyforge package -p linux --json
```

**Exit `3`.** Envelope:

```json
{
  "ok": false,
  "data": {"artifacts": []},
  "diagnostics": [{
    "code": "KF-TOOLCHAIN-UNUSABLE",
    "severity": "error",
    "message": "failed to run appimagetool: [Errno 13] Permission denied: '/run/lock/kf-noexec/kivyforge/bin/ed4ce84f...-appimagetool-1.9.1-x86_64.AppImage'",
    "context": {"tool": "appimagetool", "errno": "EACCES"}
  }]
}
```

`context.tool` and `context.errno` are both as specified.

The run did **not** fail earlier, which is the prediction the prompt wanted
checked: with an empty cache it re-downloaded the runtime, the wheels and
`appimagetool` over the network, staged CPython into `build/linux`, and
byte-compiled the payload successfully — all visible on stderr — before failing
at the one point that must execute from the cache. The staged interpreter lives
outside `XDG_CACHE_HOME`, exactly as the prompt reasoned.

## Other observations

- **No leaked temp state.** Neither failure left a `build/linux/.Dice
  Roller.AppDir.tmp-*` directory behind; both cleaned up on the way out.
- **WSL2 has `/dev/fuse` here**, so `.AppImage`s mount and run directly. Already
  corrected in `test-matrix.md` §7 (2026-09-15); restated because this run
  depended on it.
- The `noexec` cache directory created for Step 3 was left in place at
  `/run/lock/kf-noexec` (tmpfs, cleared on reboot).

## Conclusion

The `build`/`package` output contract holds on the one path CI cannot cover.
Both failure modes classify correctly, carry the specified codes, exit statuses
and context, keep the tool's own output on stderr and out of the message, and
refuse to report a stale artifact as this run's product. No code changes were
needed.

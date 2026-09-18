# Linux aarch64 as a Raspberry Pi target — findings

Run against `modernization-rfc` per
[`aarch64-pi-target-prompt.md`](aarch64-pi-target-prompt.md), in WSL2. Date:
2026-09-17.

**Steps 1–7 are done on a Raspberry Pi 5.** An aarch64 AppImage was produced
on this x86_64 host, T3 asserts every ELF is `ELFCLASS64`/`EM_AARCH64`, and
the same file launched on a Pi 5 (labwc/Wayland, Broadcom V3D, "Start
application main loop"). A Pi 4 was not present.

The example `pyproject.toml` was pointed at `archs = ["aarch64"]` only for this
run and restored to `["x86_64"]` afterwards. The generated `pylock.linux.toml`
was not committed.

## Defects first

1. **`--linux-appimage` could not inspect a cross-built image.** The T3 driver
   exec'd `./<file> --appimage-extract`. A type-2 AppImage *is* the target
   ELF, so on this host that is `OSError: [Errno 8] Exec format error` before
   any check runs. Observed against
   `dice-roller-0.1.0-aarch64.AppImage`. Fixed in the same session: if exec
   fails, find the appended `hsqs` magic (offset 936456 in this file) and
   `unsquashfs -o <offset>`. After that, the prompt's T3 command is 3 passed.
2. **`_expected_magic` had the same exec problem**, plus a second one: the
   staged `python3.13` is aarch64, so `subprocess.run` raises rather than
   returning non-zero, and this suite runs under 3.14.4 while the artifact
   ships 3.13. The driver's own comment already named this case. Fixed by
   catching `OSError` and using `find_interpreter` — the same host CPython 3.13
   the byte-compile ladder already used to write the `.pyc`s.
3. **`linux-spec.md` overlay table still said "only `x86_64` this phase"**
   after the Architectures section had already moved aarch64 in-scope. The
   toml example comment matched. Corrected.
4. **SSH was off on first contact.** `raspberrypi` / `10.168.168.202` pinged
   with TCP/22 refused. Enabling SSH in Raspberry Pi Configuration fixed it.
   The login user is `edgarbus`, not `pi`. Not a packaging issue.

Not defects, recorded so they are not rediscovered:

- A **host-arch `appimagetool` plus `--runtime-file` for the target type2
  runtime** is load-bearing. Fetching `appimagetool-aarch64.AppImage` to *run*
  on x86_64 would fail the same way the T3 extract did. The product uses
  host-arch tool + target runtime.
- **Wheel availability was not the surprise.** `Kivy-2.3.1` locked
  `manylinux_2_17_aarch64.manylinux2014_aarch64` from PyPI, not a bare
  `linux_aarch64` from `find_links`. `filetype` is `py2.py3-none-any`. Doctor
  Architecture coverage: `all deps cover aarch64`.
- **Byte-compile fell back off the staged interpreter**, as designed:
  `[stage] byte-compiling the Python payload with python3.13 (.pyc only)`.
  Doctor: `Byte-compile interpreter: byte_compile = "release"; CPython 3.13
  via python3.13`. That is the first Linux build in this repo to exercise
  `find_interpreter()`.

## Environment (Step 0)

| Item | Value |
|------|-------|
| Host | Ubuntu 26.04 LTS on **WSL2** (not native), kernel 6.18.33.2-microsoft-standard-WSL2, `x86_64` |
| Repo filesystem | `ext4` — not `/mnt/c` |
| Host Python | 3.14.4 (venv); final CPython **3.13.14** on PATH for the compile fallback |
| Bundled runtime | CPython 3.13.14, PBS `aarch64-unknown-linux-gnu`, tag `20260805` |
| `appimagetool` | 1.9.1 (host x86_64 binary) |
| type2 runtime | `20251108` / `runtime-aarch64` |
| kivyforge | 3.0.0.dev0 (editable install) |
| Branch | `modernization-rfc` @ `286fbcdc` (prompt commit) plus this work |
| Example | `examples/desktop/dice-roller` (archs temporarily `["aarch64"]`) |
| Pi | **Raspberry Pi 5 Model B Rev 1.1**, hostname `raspberrypi`, `10.168.168.202`, user `edgarbus` |
| Pi OS | Raspberry Pi reference 2026-06-18 (`pi-gen` stage5), Debian 13.7 (trixie), kernel `6.18.39+rpt-rpi-2712`, `aarch64`, glibc 2.41 |
| Pi display | labwc Wayland (`rpd-labwc`), `wayland-0`, `/dev/fuse` present, DRM `card0`/`card1`/`renderD128` |

`pyright` is not installed in `.venv`; ruff and the hermetic pytest run are
the local gates that actually executed after the code changes.

## Steps 1–4 — config, pins, native-vs-cross, doctor

`VALID_LINUX_ARCHS` / `VALID_WHEEL_ARCHS` / `LINUX_TRIPLES` gained `aarch64`.
`DEFAULT_LINUX_ARCHS` stays `("x86_64",)`. The loader hint no longer says
"planned". `host_runs_natively` in `kivyforge/host.py` is the one definition;
linux/macos/windows `bundle.py` and `builds_natively` route through it.

Pinned 2026-09-17 from the GitHub release assets (hashed here, not copied):

| Asset | SHA-256 |
|-------|---------|
| `appimagetool-aarch64.AppImage` (1.9.1) | `f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158` |
| `runtime-aarch64` (20251108) | `00cbdfcf917cc6c0ff6d3347d59e0ca1f7f45a6df1a428a0d6d8a78664d87444` |

`kivyforge doctor -p linux` from the example after lock, **exit 0**. The new
check is the only WARN:

```
[WARN] Native vs cross: cross-build: this host (x86_64) cannot run aarch64. package the AppImage and copy it to aarch64 hardware (Pi 4/5); `kivyforge run` for those archs will fail here.
```

Byte-compile is PASS via host `python3.13`, not FAIL-missing-arch. Before
lock, doctor FAIL `runtime missing arch(es): aarch64` was the expected
coverage check, not a product bug.

## Step 5 — cross-build and T3

`lock -p linux` exit 0; stdout one envelope, `packages: 2`, `action: wrote`.

PBS artifact in the lock:

```
arch = "aarch64"
url = ".../cpython-3.13.14%2B20260805-aarch64-unknown-linux-gnu-install_only.tar.gz"
sha256 = "4777d7df2edb47b96e53abad5e1b9df1b2a1a9b2f7bdba12b5c0122163b3fed9"
floor = "2.17"
```

Kivy wheel: `Kivy-2.3.1-cp313-cp313-manylinux_2_17_aarch64.manylinux2014_aarch64.whl`
(sha256 `bfe25296…fed7618c2c`). glibc floor 2.17 is older than Raspberry Pi OS
Bookworm's glibc; that is an expectation for Step 7, not proven by this host.

`package -p linux --json` exit 0. stdout:

```json
{
  "schema": 1,
  "kivyforge": "3.0.0.dev0",
  "command": "package",
  "platform": "linux",
  "ok": true,
  "data": {
    "artifacts": [
      {"path": "dist/linux/dice-roller-0.1.0-aarch64.AppImage", "kind": "appimage"}
    ]
  },
  "diagnostics": []
}
```

stderr:

```
Staging CPython 3.13.14 runtime (aarch64) ...
Installing 2 locked packages ...
[stage] byte-compiling the Python payload with python3.13 (.pyc only)
[stage] byte-compiling the embedded stdlib
Packaging dice-roller-0.1.0-aarch64.AppImage with appimagetool 1.9.1 ...
```

`file` on the artifact: `ELF 64-bit LSB pie executable, ARM aarch64`,
static-pie, stripped. `package -f folder` produced
`build/linux/Dice Roller.AppDir`; payload **0 `.py` / 336 `.pyc` / 0
`__pycache__`**. Staged `usr/python/bin/python3.13` is `ARM aarch64`,
interpreter `/lib/ld-linux-aarch64.so.1`. AppRun is `python3 -P -m main`.

T3, after the extract/magic fallbacks:

```
pytest tests/platforms/linux/test_appimage_artifact.py --no-cov -v \
  --linux-appimage examples/desktop/dice-roller/dist/linux/dice-roller-0.1.0-aarch64.AppImage \
  --linux-arch aarch64 --linux-stripped
```

3 passed (AppDir consistent, AppImage container well-formed, magic not the
3.14 runner's). `linux_appimage_file_problems` on the file itself: `[]`.

Deliberate leak: copied `/lib/x86_64-linux-gnu/libc.so.6` to
`usr/lib/_host_leak.so` in the AppDir.

```
usr/lib/_host_leak.so is x86_64 (ELF64) but aarch64 requires aarch64 (ELF64)
```

Removed afterwards; the check returned `[]` again. The copy was never in the
`.AppImage`.

## Step 6 — docs

`linux-spec.md` §Scope lists aarch64 as an in-scope *target*. New
Architectures section states: `x86_64` native, `aarch64` cross-only from
x86_64 Linux, "Pi is a target, never a host", Pi 4/5 + 64-bit Raspberry Pi OS
as the supported combination, 32-bit ARM and musl out of scope. Host
requirements: no extra toolchain or emulator. Overlay `archs` row no longer
claims x86_64-only.

## Step 7 — the Pi

**Raspberry Pi 5 Model B Rev 1.1 only.** No Pi 4 was on the LAN.

After SSH was enabled, `scp` of
`dice-roller-0.1.0-aarch64.AppImage` (94 MB) to `edgarbus@10.168.168.202:~/`
exit 0. `file` on the Pi: `ELF 64-bit LSB pie executable, ARM aarch64`.
`/dev/fuse` exists, so the image self-mounted (`/tmp/.mount_dice-*`);
`--appimage-extract-and-run` was not needed.

An SSH login has no display (`XDG_SESSION_TYPE=tty`). The console session is
Wayland (`loginctl` session 1, `Desktop=rpd-labwc`, `wayland-0` under
`/run/user/1000`). Launch:

```bash
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 XDG_SESSION_TYPE=wayland
timeout 25 ~/dice-roller-0.1.0-aarch64.AppImage
```

Exit 124 from `timeout` after 25 s — the app stayed in the main loop until
killed. Log (stderr), abbreviated:

```
[INFO   ] [Kivy        ] v2.3.1
[INFO   ] [Python      ] v3.13.14 ... Interpreter at "/tmp/.mount_dice-.../usr/python/bin/python3"
[INFO   ] [Window      ] Provider: sdl2
[INFO   ] [GL          ] OpenGL version <b'3.1 Mesa 26.2.2-1~bpo13+0~rpt1'>
[INFO   ] [GL          ] OpenGL vendor <b'Broadcom'>
[INFO   ] [GL          ] OpenGL renderer <b'V3D 7.1.10.2'>
Unable to connect to X server
[INFO   ] [Base        ] Start application main loop
```

That is the GPU/display path the roadmap said would fail first if anything
would: SDL2 on labwc, real Broadcom V3D (not llvmpipe), main loop reached.
`Unable to connect to X server` is noise from something probing X11 on a
Wayland session; the SDL2 window still came up. glibc 2.41 clears the lock's
2.17 floor.

No screenshot. Evidence is the Kivy log, same bar as the WSL2 x86_64 T4 row.

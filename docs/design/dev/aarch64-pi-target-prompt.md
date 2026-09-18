# Agent prompt — Linux aarch64 as a Raspberry Pi target (roadmap item 4)

> **Run this on a Linux host** (WSL2 or bare metal) for everything except the
> final hardware step, which needs a **Raspberry Pi 4 or 5 running 64-bit
> Raspberry Pi OS** — nothing else. Written 2026-09-17 from the Windows host,
> where the code work can be written but not host-gated or hardware-tested.
>
> Point the agent at this file, or copy the "Prompt" section.

## Background — what already exists, and what is genuinely new

[`roadmap.md`](roadmap.md) item 4 states the scope precisely: **the Pi is a
build *target*, never a build host.** Cross-build on Linux x86_64, run the
result on the Pi. kivyforge never executes on the Pi itself, which is why this
needs no native aarch64 toolchain, no emulation, and no Pi as a dev machine.

**Already in place, unverified but real** — this is additive work, not new
architecture:

- `kivyforge/platforms/linux/elftools.py:37-38` already maps
  `"aarch64": (ELFCLASS64, EM_AARCH64)`. ELF validation is arch-agnostic.
- `kivyforge/platforms/linux/appimage.py:34-48` — `_APPIMAGETOOL` /
  `_TYPE2_RUNTIME` are per-arch dicts with exactly one entry (`x86_64`).
  Adding `aarch64` is a new key, not a refactor.
- `kivyforge/platforms/linux/lock/runtime.py:48-50` — `LINUX_TRIPLES` is a
  one-entry dict (`x86_64` maps to `x86_64-unknown-linux-gnu`).
- `kivyforge/platforms/linux/lock/profile.py:24` — `VALID_WHEEL_ARCHS`,
  `manylinux_platform_tags()` (already arch-parameterized).
- `kivyforge/config/model.py:34-37` — `VALID_LINUX_ARCHS = frozenset({"x86_64"})`,
  with a comment: "list-shaped so aarch64 is purely additive later."
- `kivyforge/config/loader.py:883` — the rejection hint already says
  `"aarch64 is planned"`.
- `docs/design/platforms/linux/linux-spec.md` §Scope (~line 49) lists aarch64
  under **out of scope**, with the reason ("no ARM verification host this
  phase") that this work removes.
- `tests/conftest.py:112-116` — the T3 driver's `--linux-arch` option already
  defaults to `"x86_64"` and is not hardcoded to it.
  `tests/platforms/linux/test_appimage_artifact.py` and
  `tests/artifact_checks.py`'s `linux_appdir_problems` /
  `linux_appimage_file_problems` are already arch-agnostic.

**One distinction that changes the shape of the work**, worth stating before
you start: the Python runtime and the two AppImage build tools are pinned
**differently**, and only one of them needs you to go find a hash.

- **The PBS runtime is resolved dynamically, not pinned in source.**
  `LINUX_TRIPLES` only supplies the target triple;
  `kivyforge/lock/wheelruntime/runtime.py`'s `PbsProvider` (fed by
  `GithubPbsMetadataFetcher`, see `pbs_github.py`) queries
  python-build-standalone's GitHub releases at **lock time** and records
  whatever asset + SHA-256 it finds for that triple. Adding
  `"aarch64": "aarch64-unknown-linux-gnu"` to `LINUX_TRIPLES` is the entire
  runtime-acquisition change — do **not** hand-pin a PBS URL/hash anywhere.
- **`appimagetool` and the type2 runtime *are* hand-pinned**, in
  `appimage.py`, because they are build tools that never enter the app's lock
  file (see that file's own docstring). You have to go get the real
  `aarch64` release asset URL and SHA-256 for both, the same way the existing
  `x86_64` entries were pinned — from
  `https://github.com/AppImage/appimagetool/releases` and
  `https://github.com/AppImage/type2-runtime/releases`, same version tags
  already pinned (`APPIMAGETOOL_VERSION`, `TYPE2_RUNTIME_VERSION`). Verify the
  SHA-256 yourself (download + hash); do not trust a hash from anywhere but
  the artifact you fetched.

## Prompt

You are implementing kivyforge roadmap item 4: aarch64 as a Linux build
*target*, validated by cross-building on this Linux x86_64 host and — at the
end — running the result on real Raspberry Pi hardware (Pi 4 or 5, 64-bit
Raspberry Pi OS; **32-bit ARM stays out of scope**, and so does native aarch64
building — cross-build only). Read `roadmap.md` item 4 in full before starting;
this prompt is a checklist against it, not a replacement for it.

### Step 0 — environment

```bash
git pull                      # modernization-rfc, latest
uname -a
python3 -m pytest -q
ruff check kivyforge tests && ruff format --check kivyforge tests
pyright
```

All four must be green before you change anything — this is your baseline.

### Step 1 — config and lock: widen the arch sets

- `kivyforge/config/model.py`: add `"aarch64"` to `VALID_LINUX_ARCHS`. Leave
  `DEFAULT_LINUX_ARCHS` at `("x86_64",)` — aarch64 is opt-in via
  `[tool.kivy.linux].archs`, not a new default.
- `kivyforge/config/loader.py:883`: drop `"(aarch64 is planned)"` from the
  rejection hint now that it is accepted.
- `kivyforge/platforms/linux/lock/profile.py:24`: add `"aarch64"` to
  `VALID_WHEEL_ARCHS`.
- `kivyforge/platforms/linux/lock/runtime.py:48-50`: add
  `"aarch64": "aarch64-unknown-linux-gnu"` to `LINUX_TRIPLES`. That is the
  whole runtime change — see Background above.

### Step 2 — pin the two AppImage build tools for aarch64

In `kivyforge/platforms/linux/appimage.py`, add an `"aarch64"` entry to both
`_APPIMAGETOOL` and `_TYPE2_RUNTIME`, matching the existing `x86_64` shape
exactly (same `APPIMAGETOOL_VERSION` / `TYPE2_RUNTIME_VERSION`, just the
`aarch64`-suffixed asset name). Download each asset and compute its SHA-256
yourself:

```bash
curl -LO https://github.com/AppImage/appimagetool/releases/download/<APPIMAGETOOL_VERSION>/appimagetool-aarch64.AppImage
sha256sum appimagetool-aarch64.AppImage
curl -LO https://github.com/AppImage/type2-runtime/releases/download/<TYPE2_RUNTIME_VERSION>/runtime-aarch64
sha256sum runtime-aarch64
```

If either asset does not exist at the currently-pinned version tag, say so —
do not silently pin a different version than the `x86_64` entries without
recording why.

### Step 3 — formalize build-for vs build-on

This is the deferred refactor the roadmap calls out, and aarch64 is what makes
it real rather than theoretical. Today, "can this host run a target-arch
binary natively" is open-coded three times, identically:

```
kivyforge/platforms/linux/bundle.py:95    native = platform.machine().lower() == target_arch
kivyforge/platforms/macos/bundle.py:91    native = platform.machine().lower() == target_arch
kivyforge/platforms/windows/bundle.py:114 native = platform.machine().lower() == target_arch
```

and there is a second, doctor-side version answering the same question over a
whole `archs` tuple: `kivyforge/doctor/checks_common.py:91`,
`builds_natively(probe, archs)`, called from each backend's `doctor.py`
(`linux/doctor.py:406`, `macos/doctor.py:446`, `windows/doctor.py:525`).

Introduce **one** function — a natural home is
`kivyforge/doctor/checks_common.py` beside `builds_natively`, or a new small
module if you find a better seam — that both call sites route through, so
"native" has one definition instead of three copies that could quietly
disagree. This is refactor-only: behaviour for `x86_64`-on-`x86_64` must not
change, and the three `bundle.py` call sites' existing tests must still pass
unmodified in what they assert (only *how* `native` is computed moves).

### Step 4 — doctor: report native vs cross

Linux `doctor` should say plainly whether the configured build is native or
cross, using the formalized check from Step 3 — this is explicit "Work" in the
roadmap item, not implied. Extend it to warn where a cross-build genuinely
loses something (the byte-compile ladder already degrades correctly for a
foreign target — it falls back to the kivyforge-hosting interpreter on a
matching CPython minor rather than the staged one — so the warning is about
what does *not* degrade gracefully, if anything; check `checks_common.py`'s
`check_byte_compile` for what it already reports and do not duplicate it).

### Step 5 — cross-build and validate on x86_64 (no Pi needed yet)

Use `examples/desktop/dice-roller` (or `hello-native`, if you want the native-
binaries channel exercised too — check its `[tool.kivy.linux.native.binaries]`
config first).

```bash
cd examples/desktop/dice-roller
# add aarch64 to [tool.kivy.linux].archs in pyproject.toml, or pass --arch
kivyforge lock -p linux
kivyforge build -p linux --arch aarch64
kivyforge package -p linux --arch aarch64 --json
```

Expect: `doctor -p linux` reports the build as cross (Step 4); the lock records
a real PBS aarch64 asset (inspect `pylock.linux.toml`, don't just trust exit 0);
byte-compile falls back off the staged (aarch64) interpreter since this host
cannot run it natively, per the existing ladder — confirm this in the progress
output rather than assuming it.

**Run the T3 checks** — the driver is already arch-parameterized, this should
need zero test-code changes:

```bash
pytest tests/platforms/linux/test_appimage_artifact.py -q \
  --linux-appimage dist/linux/*.AppImage --linux-arch aarch64
```

This must assert (via the existing `linux_appimage_file_problems` /
`linux_appdir_problems`): every ELF in the artifact is `ELFCLASS64`/
`EM_AARCH64`, and — the check that actually matters for a cross-build — **no
x86_64 binary leaked in** (the host's own `appimagetool`/type2-runtime are
build tools that must not end up *inside* the AppImage; confirm the check
actually catches this by deliberately breaking it once, e.g. temporarily
copying a host-arch `.so` into the AppDir, seeing it fail, then reverting).

**Verify wheel availability while you're here** — the roadmap flags this as
the likely surprise, not the build: check that every dependency in the example
apps you use actually has a `manylinux_*_aarch64` wheel published, not a bare
`linux_aarch64` one from `find_links` (which triggers the existing
`plain_linux_wheel_warning`, not a hard failure). If a dependency has no
aarch64 manylinux wheel, that is a finding to record, not a blocker to work
around silently.

### Step 6 — docs

`docs/design/platforms/linux/linux-spec.md` §Scope: move the aarch64 bullet
from "out of scope" to the in-scope list, and add a short **Architectures**
section (there isn't one by that name yet) stating: supported archs
(`x86_64` native, `aarch64` cross-only from an x86_64 Linux host), the "Pi is a
target, never a host" rule verbatim, Pi 4/5 + 64-bit Raspberry Pi OS as the
validated combination, 32-bit ARM and musl explicitly out of scope with the
existing reasons preserved. Update §Host requirements if the cross-build path
adds anything (it should not require anything beyond a Linux host — no
emulation, no foreign toolchain).

### Step 7 — the Pi itself (needs real hardware)

Only reachable after Step 5 produces a real aarch64 `.AppImage`.

```bash
scp dist/linux/*.AppImage pi@<host>:~/
ssh pi@<host>
chmod +x *.AppImage
./dice-roller-*.AppImage        # or --appimage-extract-and-run if no /dev/fuse
```

Record: does it launch, does SDL find a display provider (expect the Pi's
KMS/DRM stack, or X11/Wayland if running a desktop session — note which),
does the app actually render, and the OS details (`cat /etc/os-release`,
`uname -m` should read `aarch64`). GPU/display is the likeliest first failure
per the roadmap's own note — if it fails here, that is a runtime finding, not
evidence the packaging is wrong; say which it looks like and why.

If you only have access to one of Pi 4 / Pi 5, say so plainly rather than
implying both were tested — the roadmap commits to both being supported, and
this run can only validate the one you have.

### Step 8 — report

Write findings to `docs/design/dev/aarch64-pi-target-findings.md`: environment
table (host, Pi model + OS image), then each step's commands and verbatim
output, defects first. Then update:

- [`roadmap.md`](roadmap.md) item 4 — mark done, link the findings, note which
  Pi model(s) were actually verified.
- [`test-matrix.md`](test-matrix.md) §7 — a row for the cross-build (T2+T3, no
  hardware) and, separately, a row for the hardware run (T4/T5, naming the Pi
  model), per this file's own rule that coverage claims name what produced
  them.
- §1's host×target table gains the aarch64 column/row it currently lacks.

### Rules of engagement

- Record what you **observed**. If the Pi step cannot run (no hardware
  available in this session), say so and stop there rather than guessing.
- Do not commit generated example locks or pyproject edits made to reproduce
  something.
- Keep Step 3's refactor behaviour-neutral for `x86_64`; if you are not
  confident it is, land Steps 1-2 and 5-8 first and treat Step 3 as a separate,
  smaller commit so a regression there is easy to isolate and revert.
- Commit on `modernization-rfc`. **Do not push without asking.**

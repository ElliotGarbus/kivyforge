# Hello Native

A minimal desktop example of the `[tool.kivy.<platform>.native.binaries]`
channel: shipping **non-wheel** native binaries (a helper executable and a
shared library) inside the bundle and using them at runtime — on **both macOS
and Linux** from one source tree.

Two artifacts are built from C by [`build_native.sh`](build_native.sh) and
declared per platform in [`pyproject.toml`](pyproject.toml):

| Artifact                        | Kind              | Consumed by the app as…                              |
| ------------------------------- | ----------------- | --------------------------------------------------- |
| `roll`                          | helper executable | `subprocess.run(["roll"])` — **by name**, via PATH  |
| `libgreet.dylib` / `libgreet.so`| shared library    | `ctypes.CDLL(...)` — see the per-platform note below|

Both prove a different half of the channel:

- `roll` resolves only because the launcher prepends the staged `bin` directory
  to `PATH` — identical on both platforms.
- The library shows the **deliberate platform asymmetry**:
  - **Linux** loads `libgreet.so` **by name** (`ctypes.CDLL("libgreet.so")`),
    resolved via the `LD_LIBRARY_PATH` append `AppRun` adds (Option B). This is
    also what lets a multi-`.so` SDK resolve its inter-lib `NEEDED` deps.
  - **macOS** loads `libgreet.dylib` **by absolute path**, since `DYLD_*` is
    stripped under SIP/Hardened Runtime, using the portable recipe
    `Path(sys.prefix).parent / "bin"`.

## Run it (macOS)

```bash
./build_native.sh              # compile roll + libgreet.dylib (universal2) into binaries/macos/
kivyforge lock -p macos        # SHA-256-pins the two binaries into pylock.macos.toml
kivyforge doctor -p macos      # verifies the sources exist (and, once built, arch coverage)
kivyforge run -p macos         # builds the .app (staging + signing bin/) and launches it
kivyforge package -p macos     # the finished .app; the signing sweep signs bin/ contents
```

## Run it (Linux)

```bash
./build_native.sh              # compile roll + libgreet.so (host arch) into binaries/linux/
kivyforge lock -p linux        # SHA-256-pins the two binaries into pylock.linux.toml
kivyforge doctor -p linux      # verifies the sources exist (and, once built, ELF arch match)
kivyforge run -p linux         # builds the AppDir (staging usr/bin) and launches it
kivyforge package -p linux     # produces dist/linux/<app>-<ver>-<arch>.AppImage
```

The native binaries are gitignored build output — a C compiler is already
required for the desktop backends, so `./build_native.sh` regenerates them on
any machine. It detects the host and writes `binaries/macos/` or
`binaries/linux/` accordingly.

> **glibc floor (Linux):** a prebuilt `.so`/executable bakes in the GLIBC
> version-needs of the **build host**. Rebuilding on a newer distro can silently
> raise the shipped artifact's host requirement above the runtime's glibc 2.17
> floor. Build on the oldest distro you intend to support. (A deferred `doctor`
> fast-follow will WARN when a staged binary needs a newer glibc than the floor.)

## What the build does

`kivyforge build`/`run`/`package`:

1. fetches each pinned binary (here: verifies the vendored file's SHA-256),
2. stages it into the bundle's `bin` directory (`Contents/Resources/bin` on
   macOS, `usr/bin` on Linux); single files get their exec bit set, and `.zip`
   (both) or `.tar.gz`/`.tgz` (Linux) sources are extracted with a traversal
   guard,
3. the launcher exposes that `bin/`: **PATH-prepend** for helpers on both
   platforms, plus a **`LD_LIBRARY_PATH`-append** on Linux so declared libraries
   load by soname without shadowing the host's or the wheels' own `.so`s, and
4. on macOS the ad-hoc/Developer ID signing sweep signs every Mach-O under the
   bundle — including `bin/` — so the app stays notarizable (Linux has no
   code-signing analog, so staged binaries just carry their exec bit).

# Hello Native

A minimal macOS example of the `[tool.kivy.macos.native.binaries]` channel:
shipping **non-wheel** native binaries (a helper executable and a dylib) inside
the `.app` and using them at runtime.

Two artifacts are built from C by [`build_native.sh`](build_native.sh) and
declared in [`pyproject.toml`](pyproject.toml):

| Artifact             | Kind             | Consumed by the app as…                              |
| -------------------- | ---------------- | --------------------------------------------------- |
| `roll`               | helper executable | `subprocess.run(["roll"])` — **by name**, via PATH  |
| `libgreet.dylib`     | dynamic library  | `ctypes.CDLL(...)` — **by absolute path**           |

Both prove a different half of the channel:

- `roll` resolves only because the launcher prepends `Contents/Resources/bin`
  to `PATH`.
- `libgreet.dylib` is loaded with the documented recipe
  `Path(sys.prefix).parent / "bin"` (in the bundled app, `sys.prefix` is
  `Contents/Resources/python`, so its parent's `bin/` is
  `Contents/Resources/bin`).

## Run it

```bash
./build_native.sh              # compile roll + libgreet.dylib (universal2) into binaries/macos/
kivyforge lock -p macos        # SHA-256-pins the two binaries into pylock.macos.toml
kivyforge doctor -p macos      # verifies the sources exist (and, once built, arch coverage)
kivyforge run -p macos         # builds the .app (staging + signing bin/) and launches it
kivyforge package -p macos     # the finished .app; the signing sweep signs bin/ contents
```

The native binaries are gitignored build output — `clang` is already required
for the macOS backend, so `./build_native.sh` regenerates them on any machine.

## What the build does

`kivyforge build`/`run`/`package`:

1. fetches each pinned binary (here: verifies the vendored file's SHA-256),
2. stages it into `<App>.app/Contents/Resources/bin/` (single files get their
   exec bit set; a `.zip` source would be extracted with a traversal guard),
3. the launcher prepends that `bin/` to the child process `PATH`, and
4. the ad-hoc/Developer ID signing sweep signs every Mach-O under the bundle —
   including `bin/` — so the app stays notarizable.

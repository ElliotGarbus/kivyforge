# FAQ for kivyforge

## Introduction

kivyforge is a declarative, PEP 621-aligned build toolchain for
[Kivy](https://kivy.org) (and other Python) apps — the successor to kivy-ios,
python-for-android, and buildozer. You describe your app once in `pyproject.toml`
and kivyforge packages it for the platform you target. The goal is to support
every platform Kivy runs on (Android, iOS, Linux, macOS, Windows); today the
implemented target is **iOS**, where the toolchain resolves dependencies into a
lockfile, downloads the official `Python.xcframework` plus prebuilt iOS wheels,
and generates an [Xcode](https://developer.apple.com/xcode/) `.xcodeproj`.

For the full workflow see the [README](README.md); for design and reference
details see the [design docs](docs/design/common/00-overview.md). When something looks
wrong, `kivyforge doctor` runs environment and project health checks and is a
good first stop.

## FAQ

### `kivyforge: command not found`

The `kivyforge` script (and its `kf` alias) is installed into your virtual
environment. Activate it (`. .venv/bin/activate`) and make sure kivyforge is
installed (`pip install -e ".[dev]"` from the repo).

### Error: SDK "iphonesimulator" cannot be located

The active Xcode path is not set correctly. Point `xcode-select` at your Xcode:

    sudo xcode-select --switch /Applications/Xcode.app

If the command line tools are missing, install them with `xcode-select --install`.

### `kivyforge build` says the lock is out of sync

Your `pyproject.toml` changed since `pylock.ios.toml` was generated. Re-resolve:

    kivyforge lock

In CI, `kivyforge lock --check` exits non-zero when the lock is stale (it writes
nothing). Use `--no-verify-lock` on `build` only if you intentionally want to
skip the drift check.

### Downloading `Python.xcframework` fails with HTTP 404

`[tool.kivy.ios.python].version` must match a build that python.org actually
publishes. iOS support is new, so during the preview period you may need a
prerelease such as `3.15.0b2` rather than a final `3.15.0`. Set the version to a
published release and re-run `kivyforge lock`.

### "invalid character in Bundle Identifier"

A bundle identifier is a UTI: only letters, digits, hyphen (`-`), and period
(`.`) are allowed — no underscores. Fix `[tool.kivy.ios].bundle_id`, e.g. use
`org.example.hello-world` instead of `org.example.hello_world`.

### I edited my Python source but the app didn't change

Editing Python source does **not** require `kivyforge build`: the generated
project links your source directory (`app/` is a symlink to `app_dir`), so just
relaunch — `kivyforge run --simulator`, or ⌘R in Xcode. Re-run `kivyforge build`
only when you change app config or need to regenerate the project, and
`kivyforge clean` to reset the generated `<app>-ios/` folder for a fresh build.

### Where are downloaded artifacts stored?

`Python.xcframework` and other xcframeworks are cached under
`~/Library/Caches/kivy-ios/artifacts/` and shared across projects. Flush the
cache with `kivyforge clean --cache`, or force a fresh download for one build
with `kivyforge build --no-cache`.

### Can I bundle a plain Python app without Kivy?

Yes. List no Kivy in `dependencies` and the toolchain bundles a pure-Python app
(this is what `examples/mobile/hello-world` does). It runs Python directly with no UI —
ideal as a smoke test of the toolchain or for validating pure-Python code
on-device. To ship an actual app you still need a UI layer: Kivy (via SDL), or a
native bridge such as `rubicon-objc`/`pyobjus` that your Python code drives.

### macOS Developer ID signing fails with `errSecInternalComponent`

If `kivyforge package -p macos` (with `[tool.kivy.macos.signing]` configured)
fails on every Mach-O with `errSecInternalComponent` — even after retrying,
even on files that ad-hoc sign fine — your login keychain's private key ACL is
likely corrupted rather than the error being transient. This has been observed
after using Keychain Access's "reset my default keychain" flow; the corruption
can persist across reboots and re-issuing the certificate.

Check for the smoking gun:

    security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k <password> login.keychain-db

If this aborts with `SecKeychainItemCopyAccess: The specified item is no
longer valid`, the fix is to stop fighting the corrupted keychain and isolate
signing into a fresh one:

    security create-keychain -p <new-password> signing.keychain-db
    security list-keychains -d user -s signing.keychain-db login.keychain-db
    security unlock-keychain -p <new-password> signing.keychain-db
    security set-keychain-settings signing.keychain-db
    security default-keychain -s signing.keychain-db
    # In Xcode: Settings → Accounts → Manage Certificates → + → Developer ID Application
    # (it's created in signing.keychain-db since that's now default)
    security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k <new-password> signing.keychain-db
    security default-keychain -s login.keychain-db   # restore normal default

If `codesign` then reports `ambiguous` (a same-named certificate matches in
both keychains), delete the broken copy from `login.keychain-db` (Keychain
Access → Certificates tab, right-click → Delete) so only the working one in
`signing.keychain-db` remains. Recreate your `xcrun notarytool
store-credentials` profile too if it was wiped by the same reset — pass
`--keychain ~/Library/Keychains/signing.keychain-db` to keep it alongside the
signing identity, immune to future login-keychain resets. See the
["Developer ID sign + notarize + staple"](docs/design/platforms/macos/macos-spec.md#developer-id-sign--notarize--staple)
section of the macOS spec for the full config reference.

This isolated-keychain approach isn't a workaround unique to kivyforge — it's
Apple's own recommendation. Apple DTS's
[The Care and Feeding of Developer ID](https://developer.apple.com/forums/thread/732320)
suggests keeping a Developer ID identity in its own keychain (separate
password/locking policy from the login keychain) precisely because these
identities are hard to replace, and also recommends exporting a `.p12` backup
so a corrupted or reset keychain never puts you in this position again. For
the general `errSecInternalComponent` failure mode (locked keychains, ACL
prompts, SSH/CI contexts) — as opposed to the specific corrupted-item case
above — see Apple DTS's
[Resolving errSecInternalComponent errors during code signing](https://developer.apple.com/forums/thread/712005).

`kivyforge doctor` checks for this proactively: the `Signing identity` check
WARNs if your configured identity is found in `login.keychain-db`, before you
ever hit a corrupted-ACL failure.

### Why does the Python `multiprocessing`/`subprocess` module not work?

The iOS application model does not support spawning subprocesses in a
cross-platform-compatible way. The platform focuses on minimizing processor
usage (and therefore power consumption) and promotes an
[alternative concurrency model](https://developer.apple.com/library/archive/documentation/General/Conceptual/ConcurrencyProgrammingGuide/Introduction/Introduction.html).
Use threads or async concurrency instead.

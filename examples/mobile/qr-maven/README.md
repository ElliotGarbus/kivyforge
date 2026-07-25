# qr-maven

Renders a QR code using a **Maven-resolved Java library** (Google's ZXing),
driven from Python through **pyjnius**.

Two kivyforge features in one app:

1. **The Gradle/Maven channel (channel 4).** `com.google.zxing:core:3.5.3` is
   declared as a Gradle coordinate in `pyproject.toml`. `kivyforge lock` runs
   Gradle once to resolve and SHA-256-pin the full transitive graph into
   `pylock.android.toml`; `kivyforge build` materializes the verification
   metadata and Gradle fetches the artifacts. Python then reaches
   `QRCodeWriter` via `autoclass`.
2. **The pyjnius `invoke0` matched pair.** A Python `Runnable` is handed to a
   Java `FutureTask` and invoked back into Python — the
   Python-implements-a-Java-interface path, in a shipped app (not just the
   contract smoke test).

```bash
# Locking the Maven coordinate runs Gradle, so a JDK must be on PATH:
kivyforge lock -p android
kivyforge run -p android --emulator
```

Markers in logcat: `INVOKE0_OK` (the round-trip fired) and `QR_OK` (the QR
texture was produced by ZXing). Enter text and tap **Generate QR** to re-render.

> **Requires a JDK at lock time** (only this example — the other two lock with
> pip + python.org metadata alone). The resolved Maven graph is then committed
> in the lock, so `build` needs no network re-resolution.

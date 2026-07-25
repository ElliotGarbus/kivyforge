# pyjnius-deviceinfo

Reads Android device information from Python via **pyjnius** — the Android
counterpart of the iOS `pyobjus-deviceinfo` example. No Java is written: the
app `autoclass`es `android.os.Build`, `BatteryManager`, and the display metrics
directly from Python.

```bash
kivyforge lock -p android
kivyforge run -p android --emulator
```

Watch logcat for the `DEVICEINFO_OK` marker with the resolved values. Featured
APIs: `Build.MANUFACTURER/MODEL/SUPPORTED_ABIS`, `Build.VERSION`, the sticky
`ACTION_BATTERY_CHANGED` broadcast, and `DisplayMetrics`.

---
title: Call Android APIs with pyjnius
sources:
  - docs/design/platforms/android/05-bootstrap-android.md
  - kivyforge/platforms/android/bootstrap/contract.py
  - examples/mobile/pyjnius-deviceinfo/src/main.py
  - examples/mobile/qr-maven/src/main.py
---

# Call Android APIs with pyjnius

[pyjnius](https://github.com/kivy/pyjnius) bridges Python and Java, so your app
can call the Android framework and any Java library you have added. The Android
build of pyjnius is a prebuilt wheel on the mobile wheel index, so you compile
nothing.

## Before you begin

- [Configure your Android app](configure.md), including the mobile wheel index
  in `extra_index_urls`.
- Add `pyjnius` to your dependencies:

    ```toml
    [project]
    dependencies = [
        "kivy==2.3.1",
        "pyjnius",
    ]
    ```

    kivyforge supports pyjnius 1.7.x. A locked pyjnius outside that range fails
    the build.

- Declare any permission the API you call requires, under
  `[tool.kivy.android.permissions]`.

## Call an Android framework class

`autoclass` returns a Java class that you use like a Python class. This code
reads the device model and Android version:

```python
from jnius import autoclass

Build = autoclass("android.os.Build")
VERSION = autoclass("android.os.Build$VERSION")

print(Build.MODEL, Build.MANUFACTURER)
print("Android", VERSION.RELEASE, "API", VERSION.SDK_INT)
```

The `pyjnius-deviceinfo` example does the same. To reach the running activity,
use `autoclass("org.kivy.android.PythonActivity").mActivity`.

## Call a Java library you added

After you [add a Java library](java-libraries.md), reach its classes the same
way. This code, from the `qr-maven` example, encodes a QR code with ZXing:

```python
from jnius import autoclass

QRCodeWriter = autoclass("com.google.zxing.qrcode.QRCodeWriter")
BarcodeFormat = autoclass("com.google.zxing.BarcodeFormat")

matrix = QRCodeWriter().encode("hello", BarcodeFormat.QR_CODE, 512, 512)
```

## Implement a Java interface in Python

pyjnius can make a Python object implement a Java interface, so Java code can
call back into Python. Subclass `PythonJavaClass` and mark methods with
`@java_method`:

```python
from jnius import PythonJavaClass, autoclass, java_method


class Task(PythonJavaClass):
    __javainterfaces__ = ["java/lang/Runnable"]
    __javacontext__ = "app"

    @java_method("()V")
    def run(self):
        print("called from Java")


FutureTask = autoclass("java.util.concurrent.FutureTask")
task = Task()
future = FutureTask(task, None)
future.run()  # Java calls Task.run()
```

Keep a Python reference to the object for as long as Java might call it.

## Verify

Run the app on a device or emulator and confirm that the values appear in the
log that `kivyforge run` prints. To check the pyjnius bridge itself, including a
Java-to-Python callback, run the smoke test:

```bash
kivyforge run -p android --smoke
```

## What's next

- [Add a background service](services.md).
- [Add Java libraries](java-libraries.md).
- [Run your app on a device or emulator](run.md).

"""The code both services run, each in its own process.

Every line it logs starts with ``android-services:`` so ``adb logcat -s
python.stdout`` shows what the service could reach: its argument, itself
through ``PythonService.mService``, and the vendored ``android.storage``
module, which finds its Context through ``mService`` when there is no
activity in the process.
"""

import os
import time
import traceback


def log(message):
    print(f"android-services: {message}")


log(f"argument {os.environ.get('PYTHON_SERVICE_ARGUMENT')!r}")
try:
    from jnius import autoclass

    import android
    from android.config import SERVICE_CLASS_NAME
    from android.storage import app_storage_path

    service = autoclass(SERVICE_CLASS_NAME).mService
    log(f"mService {service.getClass().getName()}")
    log(f"mActivity {android.mActivity}")
    log(f"app_storage_path {app_storage_path()}")
except Exception:
    traceback.print_exc()
    log("FAILED")

tick = 0
while True:
    log(f"tick {tick}")
    tick += 1
    time.sleep(5)

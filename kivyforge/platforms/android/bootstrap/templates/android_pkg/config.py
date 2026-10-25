"""Build constants, under the names python-for-android's ``android.config`` uses.

The bootstrap lines are set for each build from ``kivy_generation``; the class
names are fixed, because kivyforge's bootstrap defines those classes.

The two activity constants stay on the generated ``PythonActivity`` even when
``[tool.kivy.android].main_activity`` names an app subclass as the launcher.
``ACTIVITY_CLASS_NAMESPACE`` is the prefix of nested interface names
(``$NewIntentListener``, ``$ActivityResultListener``, ``$PermissionsCallback``,
``$DarkModeListener``) that exist only under the base class's binary name, so a
subclass value would break ``android.activity.bind``,
``android.permissions.request_permissions`` and
``android.darkmode.set_dark_mode_listener`` at their first proxy. Nothing is
lost: every use is ``autoclass(ACTIVITY_CLASS_NAME).mActivity``, which holds
the subclass instance.
"""

BOOTSTRAP = "sdl2"
IS_SDL2 = 1
IS_SDL3 = 0
PY2 = 0
ANDROID_LIBS_DIR = ""
JAVA_NAMESPACE = "org.kivy.android"
JNI_NAMESPACE = "org/kivy/android"
ACTIVITY_CLASS_NAME = "org.kivy.android.PythonActivity"
ACTIVITY_CLASS_NAMESPACE = "org/kivy/android/PythonActivity"
SERVICE_CLASS_NAME = "org.kivy.android.PythonService"

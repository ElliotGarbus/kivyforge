"""Build constants, under the names python-for-android's ``android.config`` uses.

The bootstrap lines are set for each build from ``kivy_generation``; the class
names are fixed, because kivyforge's bootstrap defines those classes.
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

"""The ``android`` package of an app built by kivyforge.

Code written for python-for-android's ``android`` package runs unchanged: its
pure-Python modules (``android.permissions``, ``android.activity``,
``android.runnable``, ``android.broadcast``, ``android.darkmode``,
``android.storage``) are bundled as python-for-android has them, and this
module provides, in plain Python over pyjnius, the names its compiled
``_android`` extension gave the package.

``autoclass``, ``cast``, ``PythonJavaClass`` and ``java_method`` are re-exported
because existing code imports them from here; new code should import them from
``jnius``.
"""

import webbrowser

from jnius import PythonJavaClass, autoclass, cast, java_method

from android.config import ACTIVITY_CLASS_NAME

__all__ = [
    "AndroidBrowser",
    "PythonJavaClass",
    "api_version",
    "autoclass",
    "cast",
    "java_method",
    "mActivity",
    "open_url",
    "python_act",
    "remove_presplash",
    "version_codes",
]

api_version = autoclass("android.os.Build$VERSION").SDK_INT
version_codes = autoclass("android.os.Build$VERSION_CODES")
python_act = autoclass(ACTIVITY_CLASS_NAME)


def _current_activity():
    from _kivy_bootstrap import get_activity

    return get_activity()


def __getattr__(name):
    # mActivity is looked up on every access rather than fixed at import, so
    # ``android.mActivity`` is never older than the activity it names. ``from
    # android import mActivity`` still binds the value once, as it always has.
    if name == "mActivity":
        return _current_activity()
    raise AttributeError(f"module 'android' has no attribute {name!r}")


def remove_presplash():
    """Nothing to remove: the app's splash is the system splash screen, which
    Android dismisses when the first frame draws."""


def open_url(url):
    Intent = autoclass("android.content.Intent")
    Uri = autoclass("android.net.Uri")
    browser_intent = Intent()
    browser_intent.setAction(Intent.ACTION_VIEW)
    browser_intent.setData(Uri.parse(url))
    activity = cast("android.app.Activity", _current_activity())
    activity.startActivity(browser_intent)
    return True


class AndroidBrowser:
    def open(self, url, new=0, autoraise=True):
        return open_url(url)

    def open_new(self, url):
        return open_url(url)

    def open_new_tab(self, url):
        return open_url(url)


webbrowser.register("android", AndroidBrowser)

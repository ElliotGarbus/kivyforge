"""kivyforge's implementation of Kivy's Android bootstrap contract.

Kivy 3 holds no Android bootstrap class name of its own: it imports this
module — the name is Kivy's, not kivyforge's — and asks it for the current
``android.app.Activity``.  That indirection is the whole point of the contract:
Kivy runs on a kivyforge-built app and a python-for-android-built one without
knowing, or caring, which produced it.  kivyforge's obligation is just this
file; the activity class name below is kivyforge's business alone.

Kivy pulls on first use rather than kivyforge registering at startup, so nothing
here imports Kivy.  That is deliberate: importing Kivy from the bootstrap would
fix Kivy's ``KIVY_*`` environment and configuration before the app's ``main.py``
had a chance to set it.

The Activity is read fresh on every call and never cached.  Android recreates it
on rotation, on configuration change and after process death, so a stored
instance both goes stale and pins a JNI reference to a dead Activity.

``get_activity()`` and the optional ``remove_presplash()`` are implemented;
``get_context()`` is deliberately absent, since it would only repeat what Kivy
already derives from the Activity.

kivyforge's splash is the platform's own: the system splash on API 31+, and the
starting window drawn from the theme's ``windowBackground`` below it.  Android
dismisses either as soon as the activity's window first draws, which is right
after ``onCreate`` and seconds before Kivy has drawn anything, so the activity
holds its window's draws until ``remove_presplash()`` releases them.  That is
the "keep-on-screen condition" Kivy's contract describes, rather than a View
that python-for-android overlays and must remove.  Only Kivy knows when its
first frame is ready, which is why the release is its call to make; the
activity also gives up on its own after a timeout, for an app that never gets
that far.
"""

from jnius import autoclass

# kivyforge's own activity, fixed at build time.  Kivy never sees this string.
# It stays the base class when [tool.kivy.android].main_activity names an app
# subclass as the launcher: mActivity is the base's static, and holds the
# subclass instance.
_ACTIVITY_CLASS = "org.kivy.android.PythonActivity"

_activity_class = None


def get_activity():
    """Return the current ``android.app.Activity``, or ``None`` if there is none.

    ``None`` is a legitimate answer, not a failure: code may run in a process
    with no Activity, and Kivy treats it as such.
    """
    global _activity_class
    if _activity_class is None:
        # Resolved on first call rather than at import, so that a reflection
        # failure surfaces from the call that needs the Activity instead of from
        # Kivy's discovery import, where it would look like a missing module.
        _activity_class = autoclass(_ACTIVITY_CLASS)
    return _activity_class.mActivity


def remove_presplash():
    """Let the activity draw, ending the splash; Kivy calls this at its first frame.

    Idempotent, as the contract asks: the activity ignores a second release.
    With no Activity there is no splash to end.
    """
    activity = get_activity()
    if activity is None:
        return
    activity.removePresplash()

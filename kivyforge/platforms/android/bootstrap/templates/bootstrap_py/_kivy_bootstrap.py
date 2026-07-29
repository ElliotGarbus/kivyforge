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

Only ``get_activity()`` is implemented; the contract's optional members are
deliberately absent.  ``get_context()`` would only repeat what Kivy already
derives from the Activity.  ``remove_presplash()`` has nothing to do: kivyforge's
splash is the platform's own — the system splash window on API 31+, and the
theme's ``windowBackground`` below it — so it is dismissed by the framework when
the first frame draws rather than being a View anyone can tear down, unlike
python-for-android, which overlays a View and must remove it.  Kivy treats an
absent hook as the no-op it is, so there is nothing to stub out.
"""

from jnius import autoclass

# kivyforge's own activity, fixed at build time (generate/manifest.py names the
# same class as the launcher activity).  Kivy never sees this string.
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

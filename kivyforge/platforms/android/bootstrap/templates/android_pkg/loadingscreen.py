"""``android.loadingscreen``, kept so code that calls it runs unchanged."""


def hide_loading_screen():
    """Nothing to hide: the app's splash is the system splash screen, which
    Android dismisses when the first frame draws."""

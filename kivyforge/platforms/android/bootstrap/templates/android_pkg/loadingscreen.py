"""``android.loadingscreen``, kept so code that calls it runs unchanged."""


def hide_loading_screen():
    """End the splash, as ``android.remove_presplash()`` does."""
    from _kivy_bootstrap import remove_presplash

    remove_presplash()

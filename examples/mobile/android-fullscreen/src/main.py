"""android-fullscreen — an Android app with the system bars hidden.

``[tool.kivy.android].fullscreen = true`` in pyproject.toml is the whole
feature: the generated activity exports ``P4A_IS_WINDOWED=False``, Kivy creates
a fullscreen SDL window, and SDL hides the status bar and the navigation bar.
Nothing in this file asks for it. The label shows the variable so a run that
did not go fullscreen says which half failed.
"""

import os

from kivy.app import App
from kivy.uix.label import Label


class FullscreenApp(App):
    def build(self):
        windowed = os.environ.get("P4A_IS_WINDOWED", "unset")
        return Label(
            text=(
                "The status bar and navigation bar should be hidden.\n"
                "Swipe in from an edge to show them for a moment.\n\n"
                f"P4A_IS_WINDOWED = {windowed}"
            ),
            halign="center",
            font_size="18sp",
        )


# Runs the same way with or without an `if __name__ == "__main__":` guard —
# kivyforge runs entry_point as __main__ on every platform.
FullscreenApp().run()

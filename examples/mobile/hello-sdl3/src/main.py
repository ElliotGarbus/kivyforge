"""The smallest kivyforge Android app on Kivy 3.0 / SDL3.

Deliberately the same shape as hello-android (Kivy 2.3.1 / SDL2) so the two
differ only in the SDL generation being exercised.
"""

from kivy.app import App
from kivy.uix.label import Label


class HelloSdl3App(App):
    def build(self):
        return Label(text="Hello from SDL3", font_size="28sp")


# Runs the same way with or without an `if __name__ == "__main__":` guard —
# kivyforge runs entry_point as __main__ on every platform.
HelloSdl3App().run()

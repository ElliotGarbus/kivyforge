"""The smallest kivyforge Android app on Kivy 3.0 / SDL3.

Deliberately the same shape as hello-android (Kivy 2.3.1 / SDL2) so the two
differ only in the SDL generation being exercised.
"""

from kivy.app import App
from kivy.uix.label import Label


class HelloSdl3App(App):
    def build(self):
        return Label(text="Hello from SDL3", font_size="28sp")


# kivyforge imports the entry point (not run as __main__), so start at import.
HelloSdl3App().run()

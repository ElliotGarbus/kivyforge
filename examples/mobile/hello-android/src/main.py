"""The smallest kivyforge Android app: a label on screen."""

from kivy.app import App
from kivy.uix.label import Label


class HelloApp(App):
    def build(self):
        return Label(text="Hello from kivyforge", font_size="28sp")


# Runs the same way with or without an `if __name__ == "__main__":` guard —
# kivyforge runs entry_point as __main__ on every platform — so the plain,
# unconditional form here is just the simpler of the two.
HelloApp().run()

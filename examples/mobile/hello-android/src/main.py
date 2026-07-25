"""The smallest kivyforge Android app: a label on screen."""

from kivy.app import App
from kivy.uix.label import Label


class HelloApp(App):
    def build(self):
        return Label(text="Hello from kivyforge", font_size="28sp")


# kivyforge imports the entry point (not run as __main__), so start at import.
HelloApp().run()

"""Minimal Kivy smoke app for kivyforge 3.0."""

import os

from kivy.app import App
from kivy.core.window import Window
from kivy.uix.label import Label

# Runtime window/Dock icon (bundled under the app dir). The installed app icon
# (Finder/Home Screen) is set separately via [tool.kivy.*.icons].
_ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")


class HelloKivyApp(App):
    icon = _ICON

    def build(self):
        if os.path.isfile(_ICON):
            Window.set_icon(_ICON)
        return Label(text="Hello Kivy", font_size="48sp")


HelloKivyApp().run()

"""Notes — a cross-platform Kivy app that persists text to the OS data dir.

Demonstrates a pure-Python dependency (``platformdirs``) resolved into the bundle
alongside Kivy: the note is saved under the platform's per-user data directory
(``~/Library/Application Support`` on macOS, the app container on iOS).
"""

import os
from pathlib import Path

from kivy.app import App
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from platformdirs import user_data_dir

_NOTE = Path(user_data_dir("notes", "org.example")) / "note.txt"
# Runtime window/Dock icon (bundled under the app dir); resolves in the .app and
# in dev runs. The installed app icon is set via [tool.kivy.*.icons].
_ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")


class Notes(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=16, spacing=12, **kwargs)
        self.status = Label(
            text=f"Saving to {_NOTE}", font_size="14sp", size_hint=(1, 0.1)
        )
        self.editor = TextInput(text=_load(), font_size="20sp")
        save = Button(text="Save", font_size="24sp", size_hint=(1, 0.15))
        save.bind(on_release=self.save)
        self.add_widget(self.status)
        self.add_widget(self.editor)
        self.add_widget(save)

    def save(self, *_):
        _NOTE.parent.mkdir(parents=True, exist_ok=True)
        _NOTE.write_text(self.editor.text, encoding="utf-8")
        self.status.text = "Saved."


def _load() -> str:
    try:
        return _NOTE.read_text(encoding="utf-8")
    except OSError:
        return "Type a note, then press Save."


class NotesApp(App):
    icon = _ICON

    def build(self):
        self.title = "Notes"
        if os.path.isfile(_ICON):
            Window.set_icon(_ICON)
        return Notes()


if __name__ == "__main__":
    NotesApp().run()

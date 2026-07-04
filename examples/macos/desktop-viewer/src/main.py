"""Desktop Viewer — a macOS-only Kivy app showcasing desktop UX.

Unlike the cross-platform examples this leans into things that only make sense on
a desktop:

* a **resizable** window with a sensible minimum size,
* **keyboard shortcuts** using the Command (⌘) modifier
  (⌘O open, ⌘+/⌘- font size, ⌘W/⌘Q quit),
* a **file-open dialog** to read any text file from the filesystem.

None of these translate to a touch phone, which is why it has no iOS overlay.
"""

from kivy.app import App
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput

_HELP = "\u2318O open   \u2318+/\u2318- font size   \u2318W/\u2318Q quit"


class Viewer(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.header = Label(text=_HELP, size_hint=(1, 0.08), font_size="14sp")
        self.body = TextInput(
            text="Press \u2318O to open a text file.",
            readonly=True,
            font_size="16sp",
        )
        self.add_widget(self.header)
        self.add_widget(self.body)

    def open_dialog(self):
        chooser = FileChooserListView(path=str(_home()))
        box = BoxLayout(orientation="vertical", spacing=8, padding=8)
        buttons = BoxLayout(size_hint=(1, 0.12), spacing=8)
        popup = Popup(title="Open a text file", content=box, size_hint=(0.9, 0.9))
        open_btn = Button(text="Open")
        cancel = Button(text="Cancel")
        open_btn.bind(on_release=lambda *_: self._open(chooser.selection, popup))
        cancel.bind(on_release=popup.dismiss)
        buttons.add_widget(cancel)
        buttons.add_widget(open_btn)
        box.add_widget(chooser)
        box.add_widget(buttons)
        popup.open()

    def _open(self, selection, popup):
        if selection:
            try:
                with open(selection[0], encoding="utf-8", errors="replace") as fh:
                    self.body.text = fh.read()
                self.header.text = selection[0]
            except OSError as exc:
                self.body.text = f"Could not open file:\n{exc}"
        popup.dismiss()

    def bump_font(self, delta: int):
        self.body.font_size = max(8, self.body.font_size + delta)


def _home():
    from pathlib import Path

    return Path.home()


class DesktopViewerApp(App):
    def build(self):
        self.title = "Desktop Viewer"
        Window.minimum_width, Window.minimum_height = 480, 360
        Window.size = (800, 600)
        self.viewer = Viewer()
        Window.bind(on_key_down=self._on_key_down)
        return self.viewer

    def _on_key_down(self, _window, key, _scancode, _codepoint, modifiers):
        # ⌘ is reported as "meta" on macOS.
        if "meta" not in modifiers:
            return False
        if key == ord("o"):
            self.viewer.open_dialog()
        elif key in (ord("q"), ord("w")):
            self.stop()
        elif key in (ord("="), ord("+")):
            self.viewer.bump_font(2)
        elif key == ord("-"):
            self.viewer.bump_font(-2)
        else:
            return False
        return True


if __name__ == "__main__":
    DesktopViewerApp().run()

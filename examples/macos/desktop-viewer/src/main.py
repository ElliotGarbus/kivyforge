"""Desktop Viewer — a macOS-only Kivy app showcasing desktop UX.

Unlike the cross-platform examples this leans into things that only make sense on
a desktop:

* a **resizable** window with a sensible minimum size,
* **keyboard shortcuts** using the Command key
  (Cmd+O open, Cmd+ / Cmd- font size, Cmd+W / Cmd+Q quit),
* the **native macOS open panel** (Finder's own file chooser, via ``osascript``)
  instead of Kivy's cross-platform ``FileChooser``.

None of these translate to a touch phone, which is why it has no iOS overlay.
"""

import subprocess

from kivy.app import App
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

_HELP = "Cmd+O open    Cmd+ / Cmd- font size    Cmd+W / Cmd+Q quit"

# Kivy keycodes for the numeric-keypad +/- keys (distinct from the main-row keys,
# so a numpad-equipped keyboard needs them handled explicitly).
_KP_ADD = 270
_KP_SUBTRACT = 269


def native_open_panel() -> str | None:
    """Show the native macOS open panel and return the chosen POSIX path.

    Uses AppleScript's ``choose file`` so the user gets Finder's real open
    dialog (sidebar, search, tags, iCloud) rather than an in-app widget.
    Returns ``None`` if the user cancels or the tool is unavailable.
    """
    script = (
        'POSIX path of (choose file with prompt "Open a text file" '
        'of type {"public.plain-text", "public.text", "public.data"})'
    )
    try:
        proc = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True
        )
    except OSError:
        return None
    if proc.returncode != 0:  # user pressed Cancel (or osascript missing)
        return None
    return proc.stdout.strip() or None


class Viewer(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.header = Label(text=_HELP, size_hint=(1, 0.08), font_size="14sp")
        self.body = TextInput(
            text="Press Cmd+O to open a text file with the native macOS panel.",
            readonly=True,
            font_size="16sp",
        )
        self.add_widget(self.header)
        self.add_widget(self.body)

    def open_file(self):
        path = native_open_panel()
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                self.body.text = fh.read()
            self.header.text = path
        except OSError as exc:
            self.body.text = f"Could not open file:\n{exc}"

    def bump_font(self, delta: int):
        self.body.font_size = max(8, self.body.font_size + delta)


class DesktopViewerApp(App):
    def build(self):
        self.title = "Desktop Viewer"
        Window.minimum_width, Window.minimum_height = 480, 360
        Window.size = (800, 600)
        self.viewer = Viewer()
        Window.bind(on_key_down=self._on_key_down)
        return self.viewer

    def _on_key_down(self, _window, key, _scancode, _codepoint, modifiers):
        # The Command key is reported as "meta" on macOS.
        if "meta" not in modifiers:
            return False
        if key == ord("o"):
            self.viewer.open_file()
        elif key in (ord("q"), ord("w")):
            self.stop()
        elif key in (ord("="), ord("+"), _KP_ADD):
            self.viewer.bump_font(2)
        elif key in (ord("-"), _KP_SUBTRACT):
            self.viewer.bump_font(-2)
        else:
            return False
        return True


if __name__ == "__main__":
    DesktopViewerApp().run()

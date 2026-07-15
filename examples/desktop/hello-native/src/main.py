"""Hello Native — exercise the [tool.kivy.<platform>.native.binaries] channel.

Two non-wheel native binaries (built by ../build_native.sh) are staged into the
bundle's ``bin`` directory (macOS: Contents/Resources/bin; Linux: usr/bin) and
consumed here two ways:

1. ``roll`` (a helper executable) is invoked *by name* with subprocess — which
   resolves only because the launcher prepends the staged bin dir to PATH. This
   is identical on both platforms.
2. The shared library is loaded with ctypes, and this is where the platforms
   differ deliberately:
   - **Linux** loads ``libgreet.so`` *by name* (``ctypes.CDLL("libgreet.so")``),
     resolved via the ``LD_LIBRARY_PATH`` append AppRun adds — the idiom that
     also lets a multi-``.so`` SDK resolve its inter-lib NEEDED deps.
   - **macOS** loads ``libgreet.dylib`` *by absolute path*, since DYLD_* is
     stripped under SIP/Hardened Runtime, using the portable recipe
     ``Path(sys.prefix).parent / "bin"`` (there sys.prefix is
     Contents/Resources/python, so its parent's bin/ is Contents/Resources/bin).
"""

import ctypes
import subprocess
import sys
from pathlib import Path

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label


def native_bin_dir() -> Path:
    """Where the staged native binaries live inside the bundle (both platforms).

    macOS: Contents/Resources/bin (sys.prefix is Contents/Resources/python).
    Linux: usr/bin (sys.prefix is usr/python). One cross-platform recipe.
    """
    return Path(sys.prefix).parent / "bin"


def roll_die() -> int:
    # Called by name (no path): proves the launcher put the staged bin on PATH.
    out = subprocess.run(["roll"], capture_output=True, text=True, check=True)
    return int(out.stdout.strip())


def greet() -> str:
    if sys.platform == "darwin":
        # macOS: load by absolute path (DYLD_* is stripped, so by-name is out).
        lib = ctypes.CDLL(str(native_bin_dir() / "libgreet.dylib"))
    elif sys.platform == "win32":
        # Windows: load by name. The generated bootstrap registered the staged
        # bin\ with os.add_dll_directory + prepended it to PATH, so greet.dll
        # resolves without a path (ctypes.WinDLL is the Windows loader idiom).
        lib = ctypes.WinDLL("greet.dll")
    else:
        # Linux: load by soname via the LD_LIBRARY_PATH append (Option B). The
        # portable by-path form also works: ctypes.CDLL(native_bin_dir()/"libgreet.so").
        lib = ctypes.CDLL("libgreet.so")
    lib.greet.restype = ctypes.c_char_p
    return lib.greet().decode()


class HelloNative(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=24, spacing=16, **kwargs)
        self._status = Label(text=greet(), font_size="18sp", halign="center")
        self._result = Label(text="Tap to roll", font_size="48sp")
        button = Button(text="Roll the die", font_size="24sp", size_hint_y=0.3)
        button.bind(on_release=self._on_roll)
        self.add_widget(self._status)
        self.add_widget(self._result)
        self.add_widget(button)

    def _on_roll(self, *_):
        try:
            self._result.text = str(roll_die())
        except Exception as exc:  # surface any staging/PATH problem in the UI
            self._result.text = "error"
            self._status.text = f"roll failed: {exc}"


class HelloNativeApp(App):
    def build(self):
        return HelloNative()


if __name__ == "__main__":
    HelloNativeApp().run()

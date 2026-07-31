"""QR-code demo — a Maven-resolved Java library (ZXing) driven from Python.

Featured:
- **Channel 4 (Maven/Gradle):** ``com.google.zxing:core`` is declared as a
  Gradle coordinate; kivyforge pins its resolved graph in the lock and Gradle
  fetches it. Python reaches it through pyjnius ``autoclass``.
- **pyjnius invoke0 matched pair:** a ``PythonJavaClass`` ``Runnable`` is handed
  to Java and invoked back into Python (``@java_method`` → ``invoke0``),
  demonstrating the Python-implements-Java-interface path in a shipped app.

``QRCodeWriter.encode()`` produces a ZXing ``BitMatrix``; we convert it to a
Kivy texture and display it for user-entered text.
"""

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics.texture import Texture
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.utils import platform

BASE_PADDING = 16  # dp; matches the KV padding, which is the desktop baseline


def safe_area_insets():
    """Device safe-area insets as Kivy pixels: ``[left, top, right, bottom]``.

    Geometry comes from Kivy core's ``kivy.mobile``, which is mobile-only and
    raises ``ImportError`` on desktop — hence the platform guard and the zero
    fallback, so this example is unchanged when run on a desktop for a quick
    smoke-test. ``get_safe_area()`` reports **layout points** on both iOS and
    Android; ``get_scale()`` converts those to Kivy window pixels.

    On Android this keeps the entry field and button clear of the status bar
    and the gesture-navigation pill.
    """
    if platform not in ("ios", "android"):
        return [0, 0, 0, 0]
    try:
        from kivy.mobile import get_safe_area, get_scale
    except ImportError:
        return [0, 0, 0, 0]
    insets = get_safe_area()  # layout points
    scale = get_scale()  # -> Kivy window pixels
    return [
        insets["left"] * scale,
        insets["top"] * scale,
        insets["right"] * scale,
        insets["bottom"] * scale,
    ]


KV = """
BoxLayout:
    orientation: 'vertical'
    padding: '16dp'
    spacing: '12dp'
    TextInput:
        id: entry
        text: 'https://kivy.org'
        multiline: False
        size_hint_y: None
        height: '48dp'
        on_text_validate: app.render(self.text)
    Button:
        text: 'Generate QR'
        size_hint_y: None
        height: '48dp'
        on_release: app.render(entry.text)
    Image:
        id: qr
        allow_stretch: True
    Label:
        id: status
        text: app.status_text
        size_hint_y: None
        height: '32dp'
"""


def _encode_qr(text: str, size: int = 512) -> Texture | None:
    """ZXing (Maven-resolved) → BitMatrix → Kivy texture."""
    if platform != "android":
        return None

    from jnius import autoclass

    QRCodeWriter = autoclass("com.google.zxing.qrcode.QRCodeWriter")
    BarcodeFormat = autoclass("com.google.zxing.BarcodeFormat")
    writer = QRCodeWriter()
    matrix = writer.encode(text, BarcodeFormat.QR_CODE, size, size)

    # BitMatrix -> RGBA buffer (black modules on white).
    width, height = matrix.getWidth(), matrix.getHeight()
    buf = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            v = 0 if matrix.get(x, y) else 255
            i = (y * width + x) * 4
            buf[i : i + 4] = bytes((v, v, v, 255))
    texture = Texture.create(size=(width, height), colorfmt="rgba")
    texture.blit_buffer(bytes(buf), colorfmt="rgba", bufferfmt="ubyte")
    texture.flip_vertical()
    return texture


def _prove_invoke0() -> str:
    """Hand a Python Runnable to Java and let Java call it (invoke0)."""
    if platform != "android":
        return "invoke0: n/a (desktop)"
    from jnius import PythonJavaClass, autoclass, java_method

    fired = {"n": 0}

    class Task(PythonJavaClass):
        __javainterfaces__ = ["java/lang/Runnable"]
        __javacontext__ = "app"

        @java_method("()V")
        def run(self):
            fired["n"] += 1

    FutureTask = autoclass("java.util.concurrent.FutureTask")
    ft = FutureTask(Task(), None)
    ft.run()  # Java invokes our Python run() through invoke0
    print(f"INVOKE0_OK fired={fired['n']}", flush=True)
    return f"invoke0 round-trip: fired {fired['n']}×"


class QrApp(App):
    def build(self):
        self.status_text = ""
        root = Builder.load_string(KV)
        self._root = root
        return root

    def on_start(self):
        self.status_text = _prove_invoke0()
        self._root.ids.status.text = self.status_text
        self.render(self._root.ids.entry.text)
        # The root is an anonymous KV widget, so the padding is driven from the
        # App rather than a root-widget class. The safe area is not settled at
        # on_start and changes with orientation, so refresh on the next frame
        # and on every resize.
        Clock.schedule_once(self._refresh_safe_area, 0)
        Window.bind(on_resize=self._on_resize)

    def _on_resize(self, *_):
        Clock.schedule_once(self._refresh_safe_area, 0)

    def _refresh_safe_area(self, *_):
        base = dp(BASE_PADDING)
        left, top, right, bottom = safe_area_insets()
        self._root.padding = [base + left, base + top, base + right, base + bottom]

    def render(self, text: str):
        texture = _encode_qr(text)
        if texture is not None:
            self._root.ids.qr.texture = texture
            print(f"QR_OK text={text!r} size={texture.size}", flush=True)
        else:
            self._root.ids.status.text = "QR needs Android (ZXing via pyjnius)"


# kivyforge imports the entry point (not run as __main__), so start at import.
QrApp().run()

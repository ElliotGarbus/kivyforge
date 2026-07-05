"""Dice Roller — a tiny cross-platform Kivy app.

Tap the button to roll two dice. Deliberately uses only stdlib + core Kivy
widgets so the same source runs on macOS (Kivy 2.3.1 from PyPI) and iOS (the
vendored 3.0 wheels).

The dice faces are drawn with Kivy's canvas (a rounded square plus pips) rather
than Unicode die glyphs (U+2680..U+2685): those glyphs are missing from Kivy's
default Roboto font (and vary across platform fonts), so they render as empty
boxes. Drawing the pips keeps the app self-contained and pixel-crisp everywhere.
"""

import os
import random

from kivy.app import App
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line, RoundedRectangle
from kivy.properties import NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.widget import Widget

# Runtime window/Dock icon (desktop). Bundled under the app dir, so a path
# relative to this file resolves in the .app and during dev runs. The installed
# app icon (Finder/Home Screen) is set separately via [tool.kivy.*.icons].
_ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")

# Pip layout per face value, as (x, y) fractions of the die face
# (Kivy's origin is bottom-left). Columns/rows at 1/4, 1/2, 3/4.
_L, _M, _H = 0.25, 0.5, 0.75
_PIPS = {
    1: [(_M, _M)],
    2: [(_L, _H), (_H, _L)],
    3: [(_L, _H), (_M, _M), (_H, _L)],
    4: [(_L, _L), (_L, _H), (_H, _L), (_H, _H)],
    5: [(_L, _L), (_L, _H), (_M, _M), (_H, _L), (_H, _H)],
    6: [(_L, _L), (_L, _M), (_L, _H), (_H, _L), (_H, _M), (_H, _H)],
}


class Die(Widget):
    """A single die face that draws `value` (1..6) as pips on a rounded square."""

    value = NumericProperty(1)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self._redraw, size=self._redraw, value=self._redraw)
        self._redraw()

    def _redraw(self, *_):
        self.canvas.clear()
        # Centered square face with a little breathing room.
        side = min(self.width, self.height) * 0.9
        if side <= 0:
            return
        x = self.x + (self.width - side) / 2
        y = self.y + (self.height - side) / 2
        radius = side * 0.18
        pip_r = side * 0.09
        with self.canvas:
            Color(0.97, 0.97, 0.98, 1)  # ivory face
            RoundedRectangle(pos=(x, y), size=(side, side), radius=[radius])
            Color(0.75, 0.77, 0.82, 1)  # subtle border
            Line(
                rounded_rectangle=(x, y, side, side, radius),
                width=max(1.0, side * 0.01),
            )
            Color(0.13, 0.14, 0.17, 1)  # dark pips
            for fx, fy in _PIPS[int(self.value)]:
                cx = x + fx * side
                cy = y + fy * side
                Ellipse(pos=(cx - pip_r, cy - pip_r), size=(pip_r * 2, pip_r * 2))


class DiceRoller(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=24, spacing=16, **kwargs)
        dice_row = BoxLayout(spacing=24, size_hint=(1, 0.6))
        self.die_a = Die()
        self.die_b = Die()
        dice_row.add_widget(self.die_a)
        dice_row.add_widget(self.die_b)
        self.total = Label(text="Tap to roll", font_size="28sp", size_hint=(1, 0.15))
        roll = Button(text="Roll", font_size="32sp", size_hint=(1, 0.25))
        roll.bind(on_release=self.roll)
        self.add_widget(dice_row)
        self.add_widget(self.total)
        self.add_widget(roll)

    def roll(self, *_):
        a, b = random.randint(1, 6), random.randint(1, 6)
        self.die_a.value = a
        self.die_b.value = b
        self.total.text = f"You rolled {a + b}"


class DiceRollerApp(App):
    icon = _ICON

    def build(self):
        self.title = "Dice Roller"
        self.icon = _ICON
        return DiceRoller()


if __name__ == "__main__":
    DiceRollerApp().run()

"""Dice Roller — a tiny cross-platform Kivy app.

Tap the button to roll two dice. Deliberately uses only stdlib + core Kivy
widgets so the same source runs on macOS (Kivy 2.3.1 from PyPI) and iOS (the
vendored 3.0 wheels).
"""

import random

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label

_FACES = ["\u2680", "\u2681", "\u2682", "\u2683", "\u2684", "\u2685"]


class DiceRoller(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=24, spacing=16, **kwargs)
        self.dice = Label(text="\u2680 \u2680", font_size="120sp")
        self.total = Label(text="Tap to roll", font_size="28sp")
        roll = Button(text="Roll", font_size="32sp", size_hint=(1, 0.3))
        roll.bind(on_release=self.roll)
        self.add_widget(self.dice)
        self.add_widget(self.total)
        self.add_widget(roll)

    def roll(self, *_):
        a, b = random.randint(1, 6), random.randint(1, 6)
        self.dice.text = f"{_FACES[a - 1]} {_FACES[b - 1]}"
        self.total.text = f"You rolled {a + b}"


class DiceRollerApp(App):
    def build(self):
        self.title = "Dice Roller"
        return DiceRoller()


if __name__ == "__main__":
    DiceRollerApp().run()

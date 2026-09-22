"""The smallest Kivy app that still proves the macOS build path works.

Deliberately trivial. This is a build fixture, not a demonstration — every
line here is one the CI job has to stage, byte-compile, ad-hoc sign, and
strip, so there is no reason for it to be longer than it is.

Written in the portable, guard-free ``App().run()`` style that every in-repo
example uses. The ``if __name__ == "__main__":`` idiom also works on every
platform as of the 2026-09-21 entry_point unification, but a fixture should
exercise the *ordinary* shape rather than the interesting one; the interesting
one has its own regression tests.
"""

from kivy.app import App
from kivy.uix.label import Label


class MacosGateApp(App):
    def build(self):
        return Label(text="macos-gate")


MacosGateApp().run()

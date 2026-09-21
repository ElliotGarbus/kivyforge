"""iOS managed build settings — the KIVYFORGE_REQUIRES_SDL wiring.

Hermetic: constructs a bare ``StagingLayout`` over a ``tmp_path`` and creates
(or not) an empty ``Frameworks/SDL3.xcframework`` directory, rather than
running the full symlink-based project generation
(``tests/platforms/ios/test_generator.py``, ``requires_symlinks``) — the
signal this checks is a single directory's existence, not anything staging
actually produces.
"""

from __future__ import annotations

from kivyforge.platforms.ios.buildsettings import managed_settings
from kivyforge.platforms.ios.staging import StagingLayout


def _layout(tmp_path, *, sdl3: bool) -> StagingLayout:
    layout = StagingLayout(root=tmp_path / "touchtracer-ios")
    if sdl3:
        (layout.frameworks / "SDL3.xcframework").mkdir(parents=True)
    else:
        layout.frameworks.mkdir(parents=True)
    return layout


class TestRequiresSdlFlag:
    """KIVYFORGE_REQUIRES_SDL=1 gates a compile-time #error in
    kivyforge_bootstrap.m when a Kivy app's SDL3 headers go missing, instead
    of silently building the headless (windowless) fallback path. Credit:
    PR #1 (kengoon)."""

    def test_set_when_sdl3_is_staged(self, config, tmp_path):
        layout = _layout(tmp_path, sdl3=True)
        settings = managed_settings(config, configuration="Debug", layout=layout)
        assert (
            settings["GCC_PREPROCESSOR_DEFINITIONS"]
            == "$(inherited) KIVYFORGE_REQUIRES_SDL=1"
        )

    def test_absent_when_sdl3_is_not_staged(self, config, tmp_path):
        """A pure-Python (no-Kivy) app must not get a macro demanding SDL3 —
        its own bootstrap's headless path is the correct one, not a bug to
        fail the build over."""
        layout = _layout(tmp_path, sdl3=False)
        settings = managed_settings(config, configuration="Debug", layout=layout)
        assert "GCC_PREPROCESSOR_DEFINITIONS" not in settings

    def test_absent_when_no_layout_given(self, config):
        """`layout=None` is a valid call shape (e.g. a settings-only refresh
        with no staging tree to inspect yet) and must not guess either way."""
        settings = managed_settings(config, configuration="Debug", layout=None)
        assert "GCC_PREPROCESSOR_DEFINITIONS" not in settings

    def test_agrees_with_header_search_paths_on_the_same_signal(self, config, tmp_path):
        """Both settings derive from the same _sdl3_staged() check, so a Kivy
        build can never end up with SDL3 headers wired in but the fail-fast
        guard silently not compiled in, or vice versa."""
        layout = _layout(tmp_path, sdl3=True)
        settings = managed_settings(config, configuration="Debug", layout=layout)
        assert "SDL3.xcframework" in settings["HEADER_SEARCH_PATHS"]
        assert "KIVYFORGE_REQUIRES_SDL=1" in settings["GCC_PREPROCESSOR_DEFINITIONS"]

"""iOS managed build settings — KIVYFORGE_REQUIRES_SDL and merging user flags.

Hermetic: constructs a bare ``StagingLayout`` over a ``tmp_path`` and creates
(or not) an empty ``Frameworks/SDL3.xcframework`` directory, rather than
running the full symlink-based project generation
(``tests/platforms/ios/test_generator.py``, ``requires_symlinks``) — the
signal this checks is a single directory's existence, not anything staging
actually produces.
"""

from __future__ import annotations

from kivyforge.platforms.ios.buildsettings import (
    managed_settings,
    merge_build_settings,
)
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
    of silently building the no-SDL smoke-test path, which can never open a
    window. Credit: PR #1 (kengoon)."""

    def test_set_when_sdl3_is_staged(self, config, tmp_path):
        layout = _layout(tmp_path, sdl3=True)
        settings = managed_settings(config, configuration="Debug", layout=layout)
        assert (
            settings["GCC_PREPROCESSOR_DEFINITIONS"]
            == "$(inherited) KIVYFORGE_REQUIRES_SDL=1"
        )

    def test_absent_when_sdl3_is_not_staged(self, config, tmp_path):
        """A project with no SDL3.xcframework must not get a macro demanding
        SDL3. The no-SDL branch is the smoke-test scaffold, and failing the
        build over its lack of SDL would reject that project."""
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


class TestMergeBuildSettings:
    """A user's flags for a list-valued managed setting are added to the
    toolchain's, not dropped under them. Issue #197: Firebase requires
    ``OTHER_LDFLAGS = "$(inherited) -ObjC"``, and the managed
    ``-framework UIKit`` silently replaced it."""

    def test_user_ldflags_are_appended_to_the_managed_ones(self):
        merged = merge_build_settings(
            {"OTHER_LDFLAGS": "$(inherited) -ObjC"},
            {"OTHER_LDFLAGS": "-framework UIKit"},
        )
        assert merged["OTHER_LDFLAGS"] == "$(inherited) -framework UIKit -ObjC"

    def test_inherited_appears_once_when_both_sides_ask_for_it(self):
        merged = merge_build_settings(
            {"GCC_PREPROCESSOR_DEFINITIONS": "$(inherited) FOO=1"},
            {"GCC_PREPROCESSOR_DEFINITIONS": "$(inherited) KIVYFORGE_REQUIRES_SDL=1"},
        )
        assert merged["GCC_PREPROCESSOR_DEFINITIONS"] == (
            "$(inherited) KIVYFORGE_REQUIRES_SDL=1 FOO=1"
        )

    def test_no_inherited_is_added_when_neither_side_asks(self):
        merged = merge_build_settings(
            {"OTHER_LDFLAGS": "-ObjC"}, {"OTHER_LDFLAGS": "-framework UIKit"}
        )
        assert merged["OTHER_LDFLAGS"] == "-framework UIKit -ObjC"

    def test_a_key_only_the_user_sets_passes_through(self):
        merged = merge_build_settings(
            {"GCC_PREPROCESSOR_DEFINITIONS": "$(inherited) FOO=1"},
            {"OTHER_LDFLAGS": "-framework UIKit"},
        )
        assert merged == {
            "GCC_PREPROCESSOR_DEFINITIONS": "$(inherited) FOO=1",
            "OTHER_LDFLAGS": "-framework UIKit",
        }

    def test_other_managed_keys_still_win(self):
        merged = merge_build_settings(
            {"COPY_PHASE_STRIP": "YES", "SWIFT_VERSION": "5.0"},
            {"COPY_PHASE_STRIP": "NO"},
        )
        assert merged == {"COPY_PHASE_STRIP": "NO", "SWIFT_VERSION": "5.0"}

    def test_managed_ldflags_reach_the_settings_merge(self, config):
        """The key the issue is about is one managed_settings() emits, so the
        merge is what decides whether the user's -ObjC survives."""
        managed = managed_settings(config, configuration="Release")
        merged = merge_build_settings({"OTHER_LDFLAGS": "-ObjC"}, managed)
        assert merged["OTHER_LDFLAGS"].split() == ["-framework", "UIKit", "-ObjC"]

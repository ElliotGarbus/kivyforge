"""Per-process link checking for declared native binaries (proposal §3.5).

The cases are the spikes' (macos-native-binaries-placement-proposal §2): A to D
are helpers in their own processes, A1 to A8 are libraries Python loads with
ctypes. Each expectation here is what dyld did on a real Mac.
"""

from __future__ import annotations

from pathlib import Path

from kivyforge.platforms.macos import machotools
from kivyforge.platforms.macos.native_links import (
    Image,
    Interpreter,
    check_links,
    describe,
)
from tests.platforms.macos import macho_fixtures as mf

C = Path("/b/App.app/Contents")
HELPERS = C / "Helpers"
FRAMEWORKS = C / "Frameworks"
PYTHON = Interpreter(
    C / "Resources" / "python" / "bin" / "python3.13", ("@executable_path/../lib",)
)


def _slice(data: bytes) -> machotools.MachoSlice:
    return machotools.parse_macho(data).slices[0]


def helper(name: str, *deps, rpaths=()) -> Image:
    return Image(HELPERS / name, _slice(mf.helper(deps=deps, rpaths=rpaths)), True)


def lib(name: str, *deps, rpaths=(), install_name=None) -> Image:
    data = mf.dylib(
        name, deps=deps, rpaths=rpaths, install_name=install_name or f"@rpath/{name}"
    )
    return Image(FRAMEWORKS / name, _slice(data), False)


def problems(*images: Image):
    return {
        (p.binary.path.name, p.dependency.name, p.process, p.warning)
        for p in check_links(list(images), PYTHON)
    }


class TestHelpers:
    """Section 2.1: which helper link forms survive the move."""

    def test_executable_path_sibling_fails(self):
        found = problems(helper("A", "@executable_path/libx.dylib"), lib("libx.dylib"))
        assert found == {
            ("A", "@executable_path/libx.dylib", "the helper A", ""),
        }

    def test_rpath_executable_path_fails(self):
        found = problems(
            helper("B", "@rpath/libx.dylib", rpaths=("@executable_path",)),
            lib("libx.dylib"),
        )
        assert found == {("B", "@rpath/libx.dylib", "the helper B", "")}

    def test_apples_form_resolves(self):
        found = problems(
            helper(
                "C", "@rpath/libx.dylib", rpaths=("@executable_path/../Frameworks",)
            ),
            lib("libx.dylib"),
        )
        assert found == set()

    def test_loader_path_sibling_fails(self):
        found = problems(helper("D", "@loader_path/libx.dylib"), lib("libx.dylib"))
        assert found == {("D", "@loader_path/libx.dylib", "the helper D", "")}

    def test_executable_path_to_frameworks_resolves(self):
        found = problems(
            helper("E", "@executable_path/../Frameworks/libx.dylib"),
            lib("libx.dylib"),
        )
        assert found == set()

    def test_absolute_and_bare_links_fail(self):
        found = problems(
            helper("F", "/usr/local/lib/libx.dylib", "liby.dylib"),
            lib("libx.dylib"),
            lib("liby.dylib"),
        )
        assert found == {
            ("F", "/usr/local/lib/libx.dylib", "the helper F", ""),
            ("F", "liby.dylib", "the helper F", ""),
        }

    def test_weak_link_warns(self):
        found = problems(
            helper("G", ("@loader_path/libx.dylib", "weak")), lib("libx.dylib")
        )
        assert found == {("G", "@loader_path/libx.dylib", "the helper G", "weak")}

    def test_lazy_link_is_strong(self):
        found = problems(
            helper("H", ("@loader_path/libx.dylib", "lazy")), lib("libx.dylib")
        )
        assert found == {("H", "@loader_path/libx.dylib", "the helper H", "")}

    def test_install_name_is_no_excuse_in_a_helper(self):
        # A helper cannot load the library first, so preloading does not apply.
        found = problems(helper("I", "@rpath/libx.dylib"), lib("libx.dylib"))
        assert found == {("I", "@rpath/libx.dylib", "the helper I", "")}


class TestPython:
    """Section 2.2: libraries the app loads with ctypes."""

    def test_executable_path_means_the_interpreter(self):
        # A1: Apple's helper form, used in a library, looks beside python3.13.
        problem = check_links(
            [
                lib("libA1.dylib", "@executable_path/../Frameworks/libB.dylib"),
                lib("libB.dylib", install_name="@rpath/libB.dylib"),
            ],
            PYTHON,
        )
        (p,) = problem
        assert (p.binary.path.name, p.process, p.warning) == (
            "libA1.dylib",
            "Python (ctypes)",
            "",
        )
        assert p.tried == (C / "Resources/python/Frameworks/libB.dylib",)

    def test_own_loader_path_rpath_resolves(self):
        # A2
        found = problems(
            lib("libA2.dylib", "@rpath/libB.dylib", rpaths=("@loader_path",)),
            lib("libB.dylib"),
        )
        assert found == set()

    def test_rpath_without_own_rpath_warns_preload(self):
        # A3: tried the interpreter's lib/; works if libB is loaded first.
        (p,) = check_links(
            [lib("libA3.dylib", "@rpath/libB.dylib"), lib("libB.dylib")], PYTHON
        )
        assert p.warning == "preload"
        assert p.tried == (C / "Resources/python/lib/libB.dylib",)

    def test_absolute_install_name_warns_preload(self):
        # A4
        found = problems(
            lib("libA4.dylib", "/usr/local/lib/libB.dylib"),
            lib("libB.dylib", install_name="/usr/local/lib/libB.dylib"),
        )
        assert found == {
            ("libA4.dylib", "/usr/local/lib/libB.dylib", "Python (ctypes)", "preload")
        }

    def test_bare_link_not_matching_install_name_fails(self):
        # A5
        found = problems(lib("libA5.dylib", "libB.dylib"), lib("libB.dylib"))
        assert found == {("libA5.dylib", "libB.dylib", "Python (ctypes)", "")}

    def test_absolute_link_not_matching_install_name_fails(self):
        # A6
        found = problems(
            lib("libA6.dylib", "/usr/local/lib/libB.dylib"), lib("libB.dylib")
        )
        assert found == {
            ("libA6.dylib", "/usr/local/lib/libB.dylib", "Python (ctypes)", "")
        }

    def test_bare_install_name_warns_preload(self):
        # A7
        found = problems(
            lib("libA7.dylib", "libB.dylib"),
            lib("libB.dylib", install_name="libB.dylib"),
        )
        assert found == {
            ("libA7.dylib", "libB.dylib", "Python (ctypes)", "preload"),
        }

    def test_weak_link_warns(self):
        # A8
        found = problems(
            lib("libA8.dylib", ("@rpath/libB.dylib", "weak")), lib("libB.dylib")
        )
        assert found == {
            ("libA8.dylib", "@rpath/libB.dylib", "Python (ctypes)", "weak"),
        }


class TestChains:
    def test_library_resolves_through_its_helpers_rpath(self):
        # libVarnish has no run path of its own; the tool's covers it.
        found = problems(
            helper(
                "tool",
                "@rpath/libVarnish.dylib",
                rpaths=("@executable_path/../Frameworks",),
            ),
            lib("libVarnish.dylib", "@rpath/libWaffle.dylib"),
            lib("libWaffle.dylib"),
        )
        assert found == set()

    def test_rpaths_are_not_pooled_across_helpers(self):
        # Through `good` libVarnish finds libWaffle; through `bare` it cannot,
        # and `bare`'s own link to libVarnish fails first.
        found = problems(
            helper(
                "good",
                "@rpath/libVarnish.dylib",
                rpaths=("@executable_path/../Frameworks",),
            ),
            helper("bare", "@executable_path/../Frameworks/libVarnish.dylib"),
            lib("libVarnish.dylib", "@rpath/libWaffle.dylib"),
            lib("libWaffle.dylib"),
        )
        assert found == {
            ("libVarnish.dylib", "@rpath/libWaffle.dylib", "the helper bare", ""),
        }

    def test_helper_linked_library_is_not_judged_from_python(self):
        # Apple's form in a library a helper uses: right there, A1 in Python.
        found = problems(
            helper("tool", "@executable_path/../Frameworks/libA.dylib"),
            lib("libA.dylib", "@executable_path/../Frameworks/libB.dylib"),
            lib("libB.dylib"),
        )
        assert found == set()

    def test_library_linked_only_by_libraries_is_judged_through_them(self):
        found = problems(
            lib("libA.dylib", "@loader_path/libB.dylib"),
            lib("libB.dylib", "@rpath/libC.dylib"),
            lib("libC.dylib"),
        )
        # libB has no run path; through libA (also none) it falls to the
        # interpreter's lib/, so it warns rather than resolving.
        assert found == {
            ("libB.dylib", "@rpath/libC.dylib", "Python (ctypes)", "preload"),
        }

    def test_cycle_is_walked_once(self):
        found = problems(
            lib("libA.dylib", "@loader_path/libB.dylib"),
            lib("libB.dylib", "@loader_path/libA.dylib", "@loader_path/libC.dylib"),
            lib("libC.dylib"),
        )
        assert found == set()

    def test_cycle_only_libraries_still_checked(self):
        found = problems(
            lib("libA.dylib", "@loader_path/libB.dylib", "/opt/libC.dylib"),
            lib("libB.dylib", "@loader_path/libA.dylib"),
            lib("libC.dylib"),
        )
        assert ("libA.dylib", "/opt/libC.dylib", "Python (ctypes)", "") in found


class TestWhichLinksCount:
    def test_system_paths_are_exempt(self):
        found = problems(
            helper("tool", "/usr/lib/libz.1.dylib", "/System/Library/X.framework/X"),
            lib("libz.1.dylib"),
            lib("X"),
        )
        assert found == set()

    def test_undeclared_libraries_are_ignored(self):
        found = problems(helper("tool", "@rpath/libpython3.13.dylib", "libother.dylib"))
        assert found == set()

    def test_leaf_name_matches_case_insensitively(self):
        found = problems(helper("tool", "@loader_path/LibX.dylib"), lib("libx.dylib"))
        assert found == {("tool", "@loader_path/LibX.dylib", "the helper tool", "")}

    def test_install_name_match_beats_leaf_name(self):
        found = problems(
            helper("tool", "/opt/sdk/core", rpaths=()),
            lib("libcore.dylib", install_name="/opt/sdk/core"),
        )
        assert found == {("tool", "/opt/sdk/core", "the helper tool", "")}

    def test_absolute_rpath_and_relative_rpath(self):
        found = problems(
            helper(
                "tool",
                "@rpath/libx.dylib",
                rpaths=("relative/dir", str(FRAMEWORKS)),
            ),
            lib("libx.dylib"),
        )
        assert found == set()


class TestDescribe:
    def _one(self, *images: Image):
        (p,) = check_links(list(images), PYTHON)
        return describe(p, C)

    def test_helper_fix_adds_frameworks_rpath(self):
        text = self._one(helper("A", "@executable_path/libx.dylib"), lib("libx.dylib"))
        assert "Contents/Helpers/A links libx.dylib" in text
        assert "dyld tries Contents/Helpers/libx.dylib" in text
        assert "install_name_tool -change '@executable_path/libx.dylib'" in text
        assert "install_name_tool -add_rpath @executable_path/../Frameworks A" in text
        assert "Fix:" in text

    def test_library_fix_adds_loader_path_rpath(self):
        text = self._one(lib("libA5.dylib", "libB.dylib"), lib("libB.dylib"))
        assert "-add_rpath @loader_path libA5.dylib" in text
        assert "nowhere in the bundle" in text

    def test_preload_explains_the_condition(self):
        text = self._one(lib("libA3.dylib", "@rpath/libB.dylib"), lib("libB.dylib"))
        assert "loads only if the app loads libB.dylib first" in text
        assert "-change" not in text

    def test_weak_says_it_still_loads(self):
        text = self._one(
            helper("G", ("@loader_path/libx.dylib", "weak")), lib("libx.dylib")
        )
        assert "weak link, so G loads without libx.dylib" in text

    def test_paths_outside_the_bundle_are_absolute(self):
        text = self._one(helper("F", "/usr/local/lib/libx.dylib"), lib("libx.dylib"))
        assert "dyld tries /usr/local/lib/libx.dylib" in text

    def test_context(self):
        (p,) = check_links(
            [helper("A", "@executable_path/libx.dylib"), lib("libx.dylib")], PYTHON
        )
        assert p.context() == {
            "binary": "A",
            "library": "libx.dylib",
            "process": "the helper A",
            "dependency": "@executable_path/libx.dylib",
        }

"""Bootstrap template rendering + the invoke0 contract gate (android/05)."""

from __future__ import annotations

import pytest

from kivyforge.platforms.android.bootstrap.contract import (
    COMPATIBLE_PYJNIUS,
    INVOKE0_CONTRACT_VERSION,
    ContractError,
    check_pyjnius_contract,
    check_sdl_glue_contract,
    sdl_version_from_glue,
    sdl_version_from_library,
)
from kivyforge.platforms.android.bootstrap.render import (
    TEMPLATES_DIR,
    RenderError,
    androidtest_files,
    finder_source,
    kivy_bootstrap_source,
    python_stem,
    render_bootstrap,
    selftest_source,
)


def _by_path(files):
    return {f.relpath: f.content for f in files}


class TestRender:
    def test_diff_clean_against_templates(self):
        """Rendering with the sdl=2 / py3.14 parameters reproduces the template
        sources byte-for-byte (substitution with those values is a no-op) — the
        templates are the source of truth, extracted from the proven prototype
        plus the Kivy-compat shims Phase 5 proved on-device."""
        files = _by_path(render_bootstrap(sdl=2, python_version="3.14.6"))
        for relpath, template in [
            (
                "java/org/kivy/android/PythonActivity.java",
                TEMPLATES_DIR / "java/org/kivy/android/PythonActivity.java",
            ),
            (
                "java/org/renpy/android/Hardware.java",
                TEMPLATES_DIR / "java/org/renpy/android/Hardware.java",
            ),
            (
                "java/org/jnius/NativeInvocationHandler.java",
                TEMPLATES_DIR / "java/org/jnius/NativeInvocationHandler.java",
            ),
            ("cpp/main.c", TEMPLATES_DIR / "cpp/main.c"),
            ("cpp/CMakeLists.txt", TEMPLATES_DIR / "cpp/CMakeLists.txt"),
        ]:
            assert files[relpath] == template.read_text(encoding="utf-8"), relpath

    def test_kivy_compat_shim_included(self):
        files = _by_path(render_bootstrap(sdl=2, python_version="3.14.6"))
        # Kivy's metrics.py autoclasses org.renpy.android.Hardware at startup.
        assert "java/org/renpy/android/Hardware.java" in files
        assert "getDPI" in files["java/org/renpy/android/Hardware.java"]
        # PythonActivity exposes the mActivity static Kivy reaches through.
        assert (
            "public static PythonActivity mActivity"
            in files["java/org/kivy/android/PythonActivity.java"]
        )

    def test_full_sdl2_glue_included(self):
        files = _by_path(render_bootstrap(sdl=2, python_version="3.14.6"))
        assert "java/org/libsdl/app/SDLActivity.java" in files
        assert "java/org/libsdl/app/SDL.java" in files
        # The stock (unpatched) glue: onCreate must load libraries itself —
        # the p4a-patched variant that omits this never starts SDL_main
        # (loadmodel findings #1).
        assert "loadLibraries" in files["java/org/libsdl/app/SDLActivity.java"]

    def test_python_stem_substitution(self):
        files = _by_path(render_bootstrap(sdl=2, python_version="3.15.0"))
        activity = files["java/org/kivy/android/PythonActivity.java"]
        assert '"python3.15",' in activity
        assert '"python3.14",' not in activity

    def test_sdl3_is_a_clear_error_until_validated(self):
        with pytest.raises(RenderError, match="SDL3"):
            render_bootstrap(sdl=3, python_version="3.14.6")

    def test_python_stem(self):
        assert python_stem("3.14.6") == "python3.14"
        assert python_stem("3.15.0") == "python3.15"
        with pytest.raises(RenderError):
            python_stem("not-a-version")

    def test_finder_source_is_the_proven_module(self):
        source = finder_source()
        assert "KivyforgeExtensionFinder" in source
        assert "def install(manifest_path, native_dir):" in source
        assert "sys.meta_path.insert(0, finder)" in source

    def test_kivy_bootstrap_source_satisfies_the_contract(self):
        source = kivy_bootstrap_source()
        # Kivy discovers the module by name and calls exactly this.
        assert "def get_activity():" in source
        assert "org.kivy.android.PythonActivity" in source
        # Kivy must never be imported from the bootstrap: doing so would fix
        # Kivy's KIVY_* config before the app's main.py could set it.
        assert "import kivy" not in source
        # The Activity is recreated on rotation and after process death, so it
        # has to be read per call rather than stashed at import.
        assert "return _activity_class.mActivity" in source
        compile(source, "_kivy_bootstrap.py", "exec")

    def test_selftest_asserts_the_kivy_contract_on_device(self):
        # A unit test of the staging code cannot catch a bundle that starts and
        # then fails when Kivy first asks for the Activity; the on-device
        # self-test is what does.
        source = selftest_source()
        assert "import _kivy_bootstrap" in source
        assert "KIVY_CONTRACT_OK" in source
        java = "\n".join(f.content for f in androidtest_files())
        assert "KIVY_CONTRACT_OK" in java, "the marker must be asserted on-device"

    def test_selftest_source_is_inert_and_complete(self):
        source = selftest_source()
        # Exercises both load-bearing mechanisms + writes the result markers
        # the instrumented test polls.
        assert "import _ssl" in source and "import jnius" in source
        assert "PythonJavaClass" in source
        assert "SELFTEST_ALL_OK" in source and "SELFTEST_DONE" in source
        # Compiles cleanly (no syntax errors in the shipped module).
        compile(source, "_kivyforge_selftest.py", "exec")

    def test_androidtest_generated(self):
        files = {f.relpath: f.content for f in androidtest_files()}
        ((path, content),) = files.items()
        assert path == (
            "androidTest/java/org/kivyforge/test/KivyforgeContractTest.java"
        )
        assert "kivyforge_selftest" in content
        assert "EXT_OK" in content and "PROXY_OK" in content

    def test_sdl_license_travels_with_the_glue(self):
        assert (TEMPLATES_DIR / "sdl2" / "LICENSE-SDL.txt").is_file()
        revision = (TEMPLATES_DIR / "sdl2" / "SDL_REVISION.txt").read_text()
        assert "SDL_MAJOR_VERSION" in revision


class TestContract:
    def test_contract_version(self):
        assert INVOKE0_CONTRACT_VERSION == 1
        assert "1.7" in str(COMPATIBLE_PYJNIUS)

    @pytest.mark.parametrize("version", ["1.7.0", "1.7.1", "1.7.99"])
    def test_in_range(self, version):
        check_pyjnius_contract(version)  # must not raise

    @pytest.mark.parametrize("version", ["1.6.1", "1.8.0", "2.0.0"])
    def test_out_of_range(self, version):
        with pytest.raises(ContractError, match="invoke0"):
            check_pyjnius_contract(version)

    def test_garbage_version(self):
        with pytest.raises(ContractError, match="not a valid version"):
            check_pyjnius_contract("not-a-version")


class TestSdlGlueContract:
    """SDLActivity aborts onCreate silently when its compiled-in version does
    not match libSDL2.so — a black screen with nothing in logcat. The build
    must catch that instead (regression: the templates carried 2.30.11 glue
    while the first-party wheel shipped a 2.32.10 libSDL2.so)."""

    def _so(self, tmp_path, revision: bytes):
        so = tmp_path / "libSDL2.so"
        so.write_bytes(b"\x7fELF" + b"\x00" * 32 + revision + b"\x00padding")
        return so

    def test_shipped_glue_matches_its_recorded_revision(self):
        """The vendored glue and SDL_REVISION.txt must not drift apart."""
        glue = sdl_version_from_glue(
            (TEMPLATES_DIR / "sdl2/org/libsdl/app/SDLActivity.java").read_text(
                encoding="utf-8"
            )
        )
        revision = (TEMPLATES_DIR / "sdl2" / "SDL_REVISION.txt").read_text(
            encoding="utf-8"
        )
        major, minor, patch = (
            line.split()[-1] for line in revision.strip().splitlines()
        )
        assert glue == f"{major}.{minor}.{patch}"

    def test_matching_versions_pass(self, tmp_path):
        java = (
            "int SDL_MAJOR_VERSION = 2;\n"
            "int SDL_MINOR_VERSION = 32;\n"
            "int SDL_MICRO_VERSION = 10;\n"
        )
        so = self._so(tmp_path, b"release-2.32.10-0-g5d2495703")
        check_sdl_glue_contract(java_source=java, so_path=so)  # must not raise

    def test_mismatch_names_both_versions(self, tmp_path):
        java = (
            "int SDL_MAJOR_VERSION = 2;\n"
            "int SDL_MINOR_VERSION = 30;\n"
            "int SDL_MICRO_VERSION = 11;\n"
        )
        so = self._so(tmp_path, b"release-2.32.10-0-g5d2495703")
        with pytest.raises(ContractError) as excinfo:
            check_sdl_glue_contract(java_source=java, so_path=so)
        message = str(excinfo.value)
        assert "2.30.11" in message and "2.32.10" in message
        # The message has to name the symptom, or the next person debugs a
        # black screen from scratch.
        assert "black screen" in message

    def test_unstamped_library_is_not_a_build_failure(self, tmp_path):
        java = "int SDL_MAJOR_VERSION = 2;\nint SDL_MINOR_VERSION = 32;\nint SDL_MICRO_VERSION = 10;\n"
        so = self._so(tmp_path, b"no version here")
        assert sdl_version_from_library(so) is None
        check_sdl_glue_contract(java_source=java, so_path=so)  # must not raise

    def test_missing_library_is_not_a_build_failure(self, tmp_path):
        assert sdl_version_from_library(tmp_path / "absent.so") is None

    def test_non_stock_glue_is_rejected(self):
        with pytest.raises(ContractError, match="no SDL_MAJOR"):
            sdl_version_from_glue("class SDLActivity {}")

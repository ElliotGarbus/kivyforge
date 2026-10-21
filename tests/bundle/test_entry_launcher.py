"""A ``module:function`` entry point, as each platform starts it (issue #68).

Each platform test goes through that platform's own copy step and its own
start mechanism -- the Windows bootstrap, the ``-m`` module ``AppRun`` and the
macOS launcher exec, the module the Android activity names, the launcher iOS
compiles in -- and then runs what it produced with this interpreter. The app is
a src-layout package whose function is declared only in
``[project.gui-scripts]`` and whose module imports a sibling relatively, which
is what breaks when the module itself runs as ``__main__``. Every desktop and
Android run is byte-compiled with ``strip_source`` first, as a release build
is, so the launcher has to be found as a sourceless ``.pyc``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from kivyforge.bundle import app_metadata, entry_launcher
from kivyforge.bundle.pycompile import byte_compile
from kivyforge.config import load_config_from_text
from kivyforge.config.model import Config, KivyMeta
from kivyforge.platforms.android.bootstrap.render import render_bootstrap
from kivyforge.platforms.android.stage import bundle as android_bundle
from kivyforge.platforms.ios.sources import c_string_body, render_main_config_h
from kivyforge.platforms.linux import bundle as linux_bundle
from kivyforge.platforms.linux.launcher import render_apprun
from kivyforge.platforms.macos import bundle as macos_bundle
from kivyforge.platforms.macos.launcher import render_launcher_source
from kivyforge.platforms.windows import bundle as windows_bundle
from kivyforge.platforms.windows.launcher import BOOTSTRAP_NAME, write_bootstrap

PYPROJECT = """\
[project]
name = "demoapp"
version = "1.0"

[project.scripts]
demoapp-cli = "demoapp.cli:main"

[project.gui-scripts]
demoapp = "demoapp.app:main"

[tool.kivy]
app_dir = "src"
{entry_point}
"""

#: What the probe writes: the module's own name, proving it was imported as
#: part of its package, and a value it imported relatively.
EXPECTED_PROBE = "demoapp.app|relative import ok"
#: main() returns this, so the exit status proves sys.exit(main()).
EXIT_STATUS = 3


def load(pyproject: Path) -> Config:
    return load_config_from_text(pyproject.read_text("utf-8"), require_ios=False)


def make_project(root: Path, entry_point: str = "") -> Config:
    """A src-layout package app; ``entry_point`` is a whole ``[tool.kivy]`` line."""
    (root / "pyproject.toml").write_text(
        PYPROJECT.format(entry_point=entry_point), encoding="utf-8"
    )
    package = root / "src" / "demoapp"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "helper.py").write_text(
        'GREETING = "relative import ok"\n', encoding="utf-8"
    )
    (package / "app.py").write_text(
        textwrap.dedent(
            f"""\
            import os

            from .helper import GREETING


            def main():
                with open(os.environ["KF_ENTRY_PROBE"], "w") as probe:
                    probe.write(f"{{__name__}}|{{GREETING}}")
                return {EXIT_STATUS}
            """
        ),
        encoding="utf-8",
    )
    return load(root / "pyproject.toml")


def release_compile(tree: Path) -> None:
    """Byte-compile *tree* and strip its sources, as a release build does."""
    byte_compile([tree], compiler=(), strip_source=True, stripdir=tree.parent)
    assert not list(tree.rglob("*.py")), "strip_source left a .py behind"


def run_python(args: list[str], tmp_path: Path, *, pythonpath: Path) -> str:
    """Run this interpreter; return the probe after checking the exit status."""
    probe = tmp_path / "probe.txt"
    env = {
        **os.environ,
        "KF_ENTRY_PROBE": str(probe),
        "PYTHONPATH": str(pythonpath),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    # Somewhere neither the app nor the project is, so nothing is found by
    # accident through the current directory.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(exist_ok=True)
    proc = subprocess.run(
        [sys.executable, *args],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
    )
    assert proc.returncode == EXIT_STATUS, proc.stderr
    return probe.read_text(encoding="utf-8")


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return root, make_project(root)


# --------------------------------------------------------------------------- #
# The launcher itself
# --------------------------------------------------------------------------- #


class TestRender:
    def test_pip_shaped(self):
        source = entry_launcher.render_launcher("pkg.app", "main")
        assert "from pkg.app import main\n" in source
        assert 'if __name__ == "__main__":\n    _status = main()\n' in source

    def test_attribute_path(self):
        """``module:object.attr`` imports the object and calls the attribute."""
        source = entry_launcher.render_launcher("pkg.app", "App.launch")
        assert "from pkg.app import App\n" in source
        assert "_status = App.launch()" in source

    @pytest.mark.parametrize(
        ("returns", "status", "raises"),
        [("None", 0, False), ("0", 0, False), ("4", 4, True), ("'bad'", 1, True)],
    )
    def test_exit_status_as_pip_gives_it(self, tmp_path, returns, status, raises):
        """The status is pip's: None and 0 are 0, an int is itself, a string is
        printed and is 1. Only a status that is not success raises SystemExit,
        because an uncaught one aborts an Android app on its way out."""
        (tmp_path / "probe_mod.py").write_text(
            f"def main():\n    return {returns}\n", encoding="utf-8"
        )
        source = entry_launcher.render_launcher("probe_mod", "main")
        (tmp_path / "launcher.py").write_text(source, encoding="utf-8")

        def python(code: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, "-c", code],
                cwd=tmp_path,
                env={**os.environ, "PYTHONPATH": str(tmp_path)},
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=60,
            )

        proc = python(source)
        assert proc.returncode == status, proc.stderr
        seen = python(
            "import runpy\n"
            "try:\n"
            "    runpy.run_path('launcher.py', run_name='__main__')\n"
            "except SystemExit:\n"
            "    print('raised')\n"
        )
        assert ("raised" in seen.stdout) is raises, seen.stderr

    def test_bare_form_has_no_launcher(self):
        kivy = KivyMeta(app_dir="src", entry_point="main")
        assert entry_launcher.launcher_source(kivy) is None
        assert entry_launcher.main_module(kivy) == "main"
        assert entry_launcher.write_launcher(Path("unused"), kivy) is None

    def test_function_form_runs_the_launcher(self):
        kivy = KivyMeta(app_dir="src", entry_point="pkg.app", entry_function="main")
        assert entry_launcher.main_module(kivy) == entry_launcher.LAUNCHER_MODULE

    def test_function_form_accepts_a_package_module(self, tmp_path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        function = KivyMeta(app_dir="src", entry_point="pkg", entry_function="main")
        bare = KivyMeta(app_dir="src", entry_point="pkg")
        assert entry_launcher.missing_entry_module(tmp_path, function) is None
        # Unchanged: the bare form runs a module file, so a package is missing.
        assert entry_launcher.missing_entry_module(tmp_path, bare) == "pkg.py"

    def test_import_guard(self, tmp_path):
        """Imported rather than run (multiprocessing's spawn re-imports the main
        module), the launcher does not start the app again."""
        root = tmp_path / "project"
        root.mkdir()
        config = make_project(root)
        entry_launcher.write_launcher(root / "src", config.kivy)
        probe = tmp_path / "probe.txt"
        proc = subprocess.run(
            [sys.executable, "-c", "import _kivyforge_main"],
            cwd=tmp_path,
            env={
                **os.environ,
                "PYTHONPATH": str(root / "src"),
                "KF_ENTRY_PROBE": str(probe),
            },
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert not probe.exists()

    def test_not_in_top_level(self, project, tmp_path):
        """top_level.txt lists the app's modules, not kivyforge's launcher."""
        root, config = project
        dest = tmp_path / "app"
        windows_bundle._copy_app_sources(config, root, dest)
        assert (dest / "_kivyforge_main.py").is_file()
        dist_info = dest / "demoapp-1.0.dist-info"
        assert (dist_info / "top_level.txt").read_text("utf-8").split() == ["demoapp"]
        metadata = app_metadata.for_build(config)
        assert metadata is not None and metadata.main_module == "demoapp.app"


# --------------------------------------------------------------------------- #
# Per platform
# --------------------------------------------------------------------------- #


class TestWindows:
    def test_bootstrap_calls_the_function(self, project, tmp_path):
        root, config = project
        bundle = tmp_path / "bundle"
        windows_bundle._copy_app_sources(config, root, bundle / "app")
        write_bootstrap(
            bundle,
            entry_point=entry_launcher.main_module(config.kivy),
            app_id="Example.DemoApp",
        )
        release_compile(bundle / "app")
        # The native launcher runs the bootstrap under the bundled python.exe;
        # the bootstrap puts app\ on sys.path and runs the module as __main__.
        probe = run_python(
            [str(bundle / BOOTSTRAP_NAME)], tmp_path, pythonpath=bundle / "app"
        )
        assert probe == EXPECTED_PROBE


class TestLinux:
    def test_apprun_module_calls_the_function(self, project, tmp_path):
        root, config = project
        usr_app = tmp_path / "AppDir" / "usr" / "app"
        linux_bundle._copy_app_sources(config, root, usr_app)
        apprun = render_apprun(
            entry_point=entry_launcher.main_module(config.kivy),
            app_id="org.example.demoapp",
        )
        release_compile(usr_app)
        found = re.search(r'python3" (-P -m \S+) "\$@"', apprun)
        assert found is not None
        probe = run_python(found.group(1).split(), tmp_path, pythonpath=usr_app)
        assert probe == EXPECTED_PROBE


class TestMacos:
    def test_launcher_module_calls_the_function(self, project, tmp_path):
        root, config = project
        app = tmp_path / "Demo.app" / "Contents" / "Resources" / "app"
        macos_bundle._copy_app_sources(config, root, app)
        source = render_launcher_source(entry_launcher.main_module(config.kivy))
        release_compile(app)
        found = re.search(r'static const char \*ENTRY = "([^"]+)";', source)
        assert found is not None
        # The launcher execs python3 -P -m ENTRY with app on PYTHONPATH.
        probe = run_python(["-P", "-m", found.group(1)], tmp_path, pythonpath=app)
        assert probe == EXPECTED_PROBE


#: How the Android launcher (bootstrap/templates/cpp/main.c) runs the module
#: PythonActivity names.
ANDROID_RUN = (
    "import runpy, sys\n"
    "runpy.run_module(sys.argv[1], run_name='__main__', alter_sys=True)\n"
)


class TestAndroid:
    def test_activity_module_calls_the_function(self, project, tmp_path):
        root, config = project
        app = tmp_path / "bundle" / "app"
        android_bundle._copy_app(
            root / config.kivy.app_dir,
            app,
            entry_point=config.kivy.entry_point,
            launcher_source=entry_launcher.launcher_source(config.kivy),
            service_entry_points={},
            app_metadata=app_metadata.for_build(config),
        )
        rendered = render_bootstrap(
            sdl=2,
            python_version="3.13.14",
            entry_point=entry_launcher.main_module(config.kivy),
        )
        activity = next(
            r.content for r in rendered if r.relpath.endswith("PythonActivity.java")
        )
        release_compile(app)
        found = re.search(r'String ENTRY_POINT = "([^"]+)";', activity)
        assert found is not None
        probe = run_python(
            ["-c", ANDROID_RUN, found.group(1)], tmp_path, pythonpath=app
        )
        assert probe == EXPECTED_PROBE

    def test_missing_module_is_named(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        config = make_project(root, 'entry_point = "demoapp.nope:main"')
        with pytest.raises(android_bundle.BundleError, match=r"demoapp/nope\.py"):
            android_bundle._copy_app(
                root / "src",
                tmp_path / "app",
                entry_point=config.kivy.entry_point,
                launcher_source=entry_launcher.launcher_source(config.kivy),
                service_entry_points={},
            )


def c_string(header: str, name: str) -> str:
    """The value of ``#define <name> "..."`` in *header*, unescaped as C would."""
    found = re.search(rf'#define {name}\s+"((?:[^"\\]|\\.)*)"', header)
    assert found is not None, name
    raw = re.sub(
        r"\\([0-7]{3}|.)",
        lambda m: chr(int(m.group(1), 8)) if len(m.group(1)) == 3 else m.group(1),
        found.group(1),
    )
    return raw.encode("latin-1").decode("utf-8")


class TestIos:
    def test_embedded_launcher_calls_the_function(self, project, tmp_path):
        """The bootstrap runs ENTRY_LAUNCHER with PyRun_SimpleString, i.e. as
        __main__ with no file; ``-c`` is the same. The app is the user's
        source, as a debug build's app/ is."""
        root, config = project
        header = render_main_config_h(config, python_version="3.13.14")
        assert '#define ENTRY_POINT        "demoapp.app"' in header
        launcher = c_string(header, "ENTRY_LAUNCHER")
        assert launcher == entry_launcher.launcher_source(config.kivy)
        probe = run_python(["-c", launcher], tmp_path, pythonpath=root / "src")
        assert probe == EXPECTED_PROBE

    def test_embedded_launcher_with_a_stripped_release_copy(self, project, tmp_path):
        root, config = project
        app = tmp_path / "myapp-ios" / "app"
        app.parent.mkdir()
        shutil.copytree(root / "src", app)
        release_compile(app)
        header = render_main_config_h(config, python_version="3.13.14")
        launcher = c_string(header, "ENTRY_LAUNCHER")
        probe = run_python(["-c", launcher], tmp_path, pythonpath=app)
        assert probe == EXPECTED_PROBE

    def test_bare_form_embeds_nothing(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        config = make_project(root, 'entry_point = "main"')
        header = render_main_config_h(config, python_version="3.13.14")
        assert '#define ENTRY_POINT        "main"' in header
        assert '#define ENTRY_LAUNCHER     ""' in header

    def test_non_ascii_survives_the_c_literal(self):
        text = 'from café import main\n"\\'
        header = f'#define X "{c_string_body(text)}"\n'
        assert c_string_body(text).isascii()
        assert c_string(header, "X") == text


# --------------------------------------------------------------------------- #
# The bare form is unchanged
# --------------------------------------------------------------------------- #


class TestBareFormUnchanged:
    @pytest.fixture
    def bare(self, tmp_path):
        root = tmp_path / "project"
        (root / "src" / "pkg").mkdir(parents=True)
        (root / "pyproject.toml").write_text(
            '[project]\nname = "bare"\nversion = "1.0"\n\n'
            '[tool.kivy]\napp_dir = "src"\nentry_point = "pkg.start"\n',
            encoding="utf-8",
        )
        (root / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (root / "src" / "pkg" / "start.py").write_text(
            "import os, sys\n"
            'if __name__ == "__main__":\n'
            '    open(os.environ["KF_ENTRY_PROBE"], "w").write(__name__)\n'
            f"    sys.exit({EXIT_STATUS})\n",
            encoding="utf-8",
        )
        config = load(root / "pyproject.toml")
        return root, config

    def test_module_runs_as_main_with_no_launcher(self, bare, tmp_path):
        root, config = bare
        assert config.kivy.entry_function is None
        bundle = tmp_path / "bundle"
        windows_bundle._copy_app_sources(config, root, bundle / "app")
        assert not (bundle / "app" / "_kivyforge_main.py").exists()
        write_bootstrap(
            bundle,
            entry_point=entry_launcher.main_module(config.kivy),
            app_id="Example.Bare",
        )
        assert "_ENTRY = 'pkg.start'" in (bundle / BOOTSTRAP_NAME).read_text("utf-8")
        probe = run_python(
            [str(bundle / BOOTSTRAP_NAME)], tmp_path, pythonpath=bundle / "app"
        )
        assert probe == "__main__"

    def test_every_platform_names_the_module(self, bare):
        _, config = bare
        assert entry_launcher.main_module(config.kivy) == "pkg.start"
        assert "-P -m pkg.start " in render_apprun(
            entry_point=entry_launcher.main_module(config.kivy), app_id="org.x.bare"
        )
        activity = next(
            r.content
            for r in render_bootstrap(
                sdl=2,
                python_version="3.13.14",
                entry_point=entry_launcher.main_module(config.kivy),
            )
            if r.relpath.endswith("PythonActivity.java")
        )
        assert 'String ENTRY_POINT = "pkg.start";' in activity

    def test_missing_message_unchanged(self, tmp_path):
        root = tmp_path / "project"
        (root / "src").mkdir(parents=True)
        (root / "pyproject.toml").write_text(
            '[project]\nname = "bare"\nversion = "1.0"\n\n'
            '[tool.kivy]\napp_dir = "src"\n',
            encoding="utf-8",
        )
        config = load(root / "pyproject.toml")
        with pytest.raises(
            linux_bundle.AppDirError,
            match=re.escape(
                "entry point main.py not found in src/ (set [tool.kivy].entry_point)."
            ),
        ):
            linux_bundle._copy_app_sources(config, root, tmp_path / "out")

    def test_function_form_missing_message_names_its_origin(self, tmp_path):
        root = tmp_path / "project"
        (root / "src").mkdir(parents=True)
        (root / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "1.0"\n\n'
            '[project.gui-scripts]\nx = "pkg.app:main"\n\n'
            '[tool.kivy]\napp_dir = "src"\n',
            encoding="utf-8",
        )
        config = load(root / "pyproject.toml")
        with pytest.raises(
            macos_bundle.AppBundleError,
            match=re.escape(
                "entry point pkg/app.py not found in src/ (pkg.app:main, from "
                "[project.gui-scripts] x; set [tool.kivy].entry_point)."
            ),
        ):
            macos_bundle._copy_app_sources(config, root, tmp_path / "out")

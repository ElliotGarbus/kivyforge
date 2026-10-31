"""Info.plist + launcher generation."""

from __future__ import annotations

import dataclasses
import os
import platform
import plistlib
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.config.model import ResolvedVersion
from kivyforge.config.version import with_version
from kivyforge.platforms.macos import AppBundleError
from kivyforge.platforms.macos import launcher as launcher_mod
from kivyforge.platforms.macos.launcher import (
    RPATHS,
    build_launcher,
    find_libpython,
    render_launcher_source,
)
from kivyforge.platforms.macos.machotools import is_macho, macho_arches
from kivyforge.platforms.macos.plist import (
    DEFAULT_MINIMUM_SYSTEM_VERSION,
    build_info_plist,
)
from tests.conftest import skip_missing_toolchain

_BASE = (
    "[project]\nname='myapp'\nversion='2.5.0'\nrequires-python='>=3.14'\n"
    "dependencies=[]\n"
    "[tool.kivy]\ndisplay_name='My App'\napp_dir='src'\nentry_point='main'\n"
    "[tool.kivy.macos]\nschema_version=1\nbundle_id='org.example.myapp'\nbuild=7\n"
    "{extra}"
    "[tool.kivy.macos.python]\nversion='3.14.5'\n"
)


def _config(extra: str = ""):
    return load_config_from_text(
        _BASE.format(extra=extra), require_ios=False, require_macos=True
    )


class TestInfoPlist:
    def test_core_keys(self):
        plist = build_info_plist(_config(), executable="myapp", icon_file=None)
        assert plist["CFBundleIdentifier"] == "org.example.myapp"
        assert plist["CFBundleName"] == "My App"
        assert plist["CFBundleExecutable"] == "myapp"
        assert plist["CFBundleShortVersionString"] == "2.5.0"
        assert plist["CFBundleVersion"] == "7"
        assert plist["CFBundlePackageType"] == "APPL"
        assert "CFBundleIconFile" not in plist

    def test_short_version_is_the_resolved_one_as_given(self):
        # Never rewritten: an App Store export is checked in the verb instead.
        config = with_version(_config(), ResolvedVersion("2.6.0.dev3+gabc", "backend"))
        plist = build_info_plist(config, executable="x", icon_file=None)
        assert plist["CFBundleShortVersionString"] == "2.6.0.dev3+gabc"
        assert plist["CFBundleVersion"] == "7"

    def test_default_minimum_system_version(self):
        plist = build_info_plist(_config(), executable="x", icon_file=None)
        assert plist["LSMinimumSystemVersion"] == DEFAULT_MINIMUM_SYSTEM_VERSION

    def test_explicit_minimum_and_icon(self):
        plist = build_info_plist(
            _config('minimum_system_version="13.0"\n'),
            executable="x",
            icon_file="x.icns",
        )
        assert plist["LSMinimumSystemVersion"] == "13.0"
        assert plist["CFBundleIconFile"] == "x.icns"

    def test_user_keys_merge_over_the_managed_ones(self):
        """#201: ``[tool.kivy.macos.info_plist]`` reaches the bundle."""
        config = _config(
            "[tool.kivy.macos.info_plist]\nNSCameraUsageDescription='QR'\n"
            "FirebaseAppDelegateProxyEnabled=false\n"
        )
        plist = build_info_plist(config, executable="x", icon_file=None)
        assert plist["NSCameraUsageDescription"] == "QR"
        assert plist["FirebaseAppDelegateProxyEnabled"] is False
        assert plist["CFBundleIdentifier"] == "org.example.myapp"

    def test_a_managed_key_is_refused_even_past_the_loader(self):
        config = _config()
        macos = dataclasses.replace(
            config.macos_required, info_plist={"CFBundleExecutable": "evil"}
        )
        config = dataclasses.replace(config, macos=macos)
        with pytest.raises(ValueError, match="managed"):
            build_info_plist(config, executable="x", icon_file=None)


LIB = "libpython3.14.dylib"


class TestLauncherSource:
    def test_embeds_entry_and_layout(self):
        src = render_launcher_source("main", LIB)
        assert 'static const char *ENTRY = "main";' in src
        assert f'static const char *LIBPYTHON = "{LIB}";' in src
        assert "Resources/python" in src
        assert "Resources/app" in src
        assert "Resources/lib" in src

    def test_runs_python_in_process_not_by_exec(self):
        """#201: after an ``execv`` the main bundle was ``Resources/python/bin``.

        Apple's main bundle is the one holding the process's executable, so
        only a launcher that stays the process keeps the ``.app`` as it --
        and with it the Info.plist, the bundle id and ``Contents/Resources``.
        """
        src = render_launcher_source("main", LIB)
        assert "execv" not in src
        assert "dlopen(libpython, RTLD_NOW | RTLD_GLOBAL)" in src
        assert 'dlsym(python, "Py_BytesMain")' in src

    def test_sys_executable_stays_the_interpreter(self):
        src = render_launcher_source("main", LIB)
        assert 'setenv("PYTHONEXECUTABLE", py, 1)' in src

    def test_prepends_helpers_to_path(self):
        src = render_launcher_source("main", LIB)
        assert '"%s/Helpers", contents' in src
        assert "Resources/bin" not in src
        assert 'getenv("PATH")' in src
        assert 'setenv("PATH", newpath, 1)' in src

    def test_never_writes_bytecode_into_the_signed_bundle(self):
        """A running app must never write into its own signed bundle.

        The regression this guards: the app's first-ever real launch (once the
        ``-m`` fix above made a launch possible at all) wrote ``__pycache__``
        into the unstripped embedded stdlib and invalidated the bundle's code
        signature (``codesign --verify`` then reports "a sealed resource is
        missing or invalid").
        """
        src = render_launcher_source("main", LIB)
        assert 'setenv("PYTHONDONTWRITEBYTECODE", "1", 1)' in src

    def test_rejects_non_identifier_entry(self):
        with pytest.raises(AppBundleError, match="not a valid module name"):
            render_launcher_source("main.py", LIB)

    @pytest.mark.parametrize("name", ["lib/libpython3.14.dylib", 'a"b.dylib'])
    def test_rejects_a_libpython_that_is_not_a_file_name(self, name):
        with pytest.raises(AppBundleError, match="not a library file name"):
            render_launcher_source("main", name)

    def test_the_launcher_never_names_a_source_file(self):
        """A path-based exec cannot survive strip_source; -m does.

        The regression this guards shipped: the launcher execv'd
        ``Resources/app/main.py`` while ``package`` had just byte-compiled and
        deleted it, so every default ``.app`` exited 2 before Python started.
        Mirrors ``platforms/linux/test_launcher.py``'s identical guard.
        """
        src = render_launcher_source("main", LIB)
        assert '"main.py"' not in src
        assert '"-P"' in src
        assert '"-m"' in src
        assert "(char *)ENTRY" in src

    def test_the_cwd_is_kept_off_sys_path(self):
        """``-m`` alone would put the launch directory on sys.path; ``-P`` must not.

        Weaker-stakes here than on Linux (this launcher already ``chdir``s into
        ``app`` first), but kept for symmetry — see the module docstring.
        """
        src = render_launcher_source("main", LIB)
        assert 'child[1] = "-P";' in src
        assert 'child[2] = "-m";' in src


class TestFindLibpython:
    def test_names_the_one_libpython(self, tmp_path):
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / LIB).write_text("")
        (tmp_path / "lib" / "libtcl9.0.dylib").write_text("")
        assert find_libpython(tmp_path) == LIB

    def test_none_is_an_error(self, tmp_path):
        (tmp_path / "lib").mkdir()
        with pytest.raises(AppBundleError, match="no libpython3"):
            find_libpython(tmp_path)

    def test_two_is_an_error(self, tmp_path):
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / LIB).write_text("")
        (tmp_path / "lib" / "libpython3.14t.dylib").write_text("")
        with pytest.raises(AppBundleError, match="exactly one"):
            find_libpython(tmp_path)


class TestLauncherCompileHermetic:
    """build_launcher's compile wiring + error handling, without a real clang.

    The real Mach-O compile is macOS+clang-only (covered by the skipif'd class
    below on the macOS CI job); these mock ``subprocess.run`` so the argv
    assembly, chmod, and both failure branches get coverage on every host.
    """

    def _build(self, tmp_path):
        build_launcher(
            tmp_path / "MacOS" / "myapp",
            entry_point="main",
            libpython=LIB,
            arch="arm64",
        )

    def test_missing_clang_is_actionable(self, tmp_path, monkeypatch):
        def no_clang(*a, **k):
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(launcher_mod.subprocess, "run", no_clang)
        with pytest.raises(AppBundleError, match="clang not found"):
            self._build(tmp_path)

    def test_compile_failure_reports_stderr(self, tmp_path, monkeypatch):
        def fail(cmd, **k):
            return subprocess.CompletedProcess(cmd, 1, "", "ld: symbol not found")

        monkeypatch.setattr(launcher_mod.subprocess, "run", fail)
        with pytest.raises(AppBundleError, match="failed to compile"):
            self._build(tmp_path)

    def test_success_passes_arch_and_rpath_and_marks_executable(
        self, tmp_path, monkeypatch
    ):
        recorded = {}

        def ok(cmd, **k):
            recorded["cmd"] = cmd
            dest = Path(cmd[cmd.index("-o") + 1])
            dest.write_bytes(b"\xcf\xfa\xed\xfe")  # Mach-O magic placeholder
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(launcher_mod.subprocess, "run", ok)
        self._build(tmp_path)
        # build_launcher chmods 0o755 (a no-op on Windows CI hosts, hence no
        # executable-bit assertion here) and writes the compiled output.
        assert (tmp_path / "MacOS" / "myapp").exists()
        # The arch is forwarded to clang as a single `-arch <a>` pair.
        assert recorded["cmd"].count("-arch") == 1
        assert "arm64" in recorded["cmd"]
        # python3's own run path, restated from Contents/MacOS, so a ctypes
        # load by @rpath resolves where it did before the launcher ran Python.
        assert RPATHS == ("@executable_path/../Resources/python/lib",)
        assert f"-Wl,-rpath,{RPATHS[0]}" in recorded["cmd"]


# A stand-in libpython: Py_BytesMain reports what the launcher handed it, and
# what the process's main bundle is, instead of running Python.
_FAKE_LIBPYTHON = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <CoreFoundation/CoreFoundation.h>

int Py_BytesMain(int argc, char **argv) {
    const char *show = getenv("KF_FAKE_SHOW");
    if (strcmp(show, "argv") == 0) {
        for (int i = 1; i < argc; i++) printf("%s\n", argv[i]);
    } else if (strcmp(show, "argv0") == 0) {
        printf("%s\n", argv[0]);
    } else if (strcmp(show, "bundle") == 0) {
        CFStringRef id = CFBundleGetIdentifier(CFBundleGetMainBundle());
        char buf[256] = "";
        if (id != NULL) CFStringGetCString(id, buf, sizeof(buf), kCFStringEncodingUTF8);
        printf("%s", buf);
    } else {
        const char *value = getenv(show);
        printf("%s", value ? value : "");
    }
    return 0;
}
"""


# The launcher is a Mach-O stub built with `clang -arch ...`; that is a macOS-only
# operation (Linux clang rejects `-arch`/can't emit Mach-O), matching the fact
# that the whole `.app` build only runs on macOS hosts. The macOS integration CI
# job exercises these; skip them elsewhere.
#
# Wrong host and missing clang are deliberately two separate gates: off macOS
# there is nothing to test, but *on* macOS an absent clang means the one job that
# covers this silently covered nothing, so KIVYFORGE_REQUIRE_TOOLCHAIN turns it
# into a failure.
@pytest.mark.requires_toolchain
@pytest.mark.skipif(
    sys.platform != "darwin", reason="Mach-O launcher build is macOS-only"
)
class TestLauncherCompile:
    @pytest.fixture(autouse=True)
    def _needs_clang(self):
        if shutil.which("clang") is None:
            skip_missing_toolchain("clang", "install the Xcode command line tools")

    @staticmethod
    def _host() -> str:
        return "arm64" if platform.machine() == "arm64" else "x86_64"

    def _app(self, tmp_path: Path) -> Path:
        """A ``.app`` with a real launcher and a stand-in libpython."""
        contents = tmp_path / "My.app" / "Contents"
        build_launcher(
            contents / "MacOS" / "myapp",
            entry_point="main",
            libpython=LIB,
            arch=self._host(),
        )
        lib = contents / "Resources" / "python" / "lib"
        lib.mkdir(parents=True)
        src = tmp_path / "libpython.c"
        src.write_text(_FAKE_LIBPYTHON)
        subprocess.run(
            ["clang", "-dynamiclib", "-arch", self._host(), "-framework"]
            + ["CoreFoundation", "-o", str(lib / LIB), str(src)],
            check=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
        )
        (contents / "Resources" / "app").mkdir(parents=True)
        (contents / "Helpers").mkdir(parents=True)
        with (contents / "Info.plist").open("wb") as f:
            plistlib.dump(
                {
                    "CFBundleExecutable": "myapp",
                    "CFBundleIdentifier": "org.example.launcher201",
                    "CFBundlePackageType": "APPL",
                },
                f,
            )
        return contents / "MacOS" / "myapp"

    @staticmethod
    def _run(launcher: Path, show: str, *args: str) -> str:
        return subprocess.run(
            [str(launcher), *args],
            capture_output=True,
            text=True,
            check=True,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "KF_FAKE_SHOW": show},
        ).stdout

    def test_builds_thin_macho(self, tmp_path):
        path = tmp_path / "MacOS" / "myapp"
        build_launcher(path, entry_point="main", libpython=LIB, arch=self._host())
        assert is_macho(path)
        assert macho_arches(path) == (self._host(),)
        assert os.stat(path).st_mode & stat.S_IXUSR

    def test_the_main_bundle_is_the_app(self, tmp_path):
        """#201 end to end: Python's process sees the ``.app``'s Info.plist."""
        launcher = self._app(tmp_path)
        assert self._run(launcher, "bundle") == "org.example.launcher201"

    def test_sys_executable_is_the_interpreter(self, tmp_path):
        launcher = self._app(tmp_path)
        python = launcher.parents[1] / "Resources" / "python" / "bin" / "python3"
        assert self._run(launcher, "PYTHONEXECUTABLE") == str(python)
        assert self._run(launcher, "argv0").strip() == str(python)

    def test_child_sees_helpers_first_on_path(self, tmp_path):
        out = self._run(self._app(tmp_path), "PATH")
        first = out.split(":", 1)[0]
        assert first.endswith("/Contents/Helpers")

    def test_child_is_invoked_with_dash_m_not_a_source_path(self, tmp_path):
        """End-to-end proof the launcher runs ``-P -m main``, not a ``.py`` path.

        The closest thing to a real regression test for the exit-2-before-
        Python-starts defect: a real compiled launcher, a stand-in libpython
        that echoes its argv, and no ``main.py`` on disk at all — only the
        argv-based ``-m`` invocation can possibly work here.
        """
        out = self._run(self._app(tmp_path), "argv", "--extra")
        assert out.splitlines() == ["-P", "-m", "main", "--extra"]

    def test_child_never_writes_bytecode(self, tmp_path):
        """End-to-end proof Python receives ``PYTHONDONTWRITEBYTECODE=1``."""
        assert self._run(self._app(tmp_path), "PYTHONDONTWRITEBYTECODE") == "1"

    def test_a_missing_libpython_fails_loudly(self, tmp_path):
        launcher = self._app(tmp_path)
        (launcher.parents[1] / "Resources" / "python" / "lib" / LIB).unlink()
        proc = subprocess.run(
            [str(launcher)], capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
        assert proc.returncode == 71
        assert proc.stderr.startswith("kivyforge launcher: ")
        assert LIB in proc.stderr

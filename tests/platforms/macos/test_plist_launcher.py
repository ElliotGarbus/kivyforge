"""Info.plist + launcher generation."""

from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.platforms.macos import AppBundleError
from kivyforge.platforms.macos import launcher as launcher_mod
from kivyforge.platforms.macos.launcher import build_launcher, render_launcher_source
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


class TestLauncherSource:
    def test_embeds_entry_and_layout(self):
        src = render_launcher_source("main")
        assert 'static const char *ENTRY = "main";' in src
        assert "Resources/python" in src
        assert "Resources/app" in src
        assert "Resources/lib" in src
        assert "execv(py, child)" in src

    def test_prepends_bin_to_path(self):
        src = render_launcher_source("main")
        assert "Resources/bin" in src
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
        src = render_launcher_source("main")
        assert 'setenv("PYTHONDONTWRITEBYTECODE", "1", 1)' in src

    def test_rejects_non_identifier_entry(self):
        with pytest.raises(AppBundleError, match="not a valid module name"):
            render_launcher_source("main.py")

    def test_the_launcher_never_names_a_source_file(self):
        """A path-based exec cannot survive strip_source; -m does.

        The regression this guards shipped: the launcher execv'd
        ``Resources/app/main.py`` while ``package`` had just byte-compiled and
        deleted it, so every default ``.app`` exited 2 before Python started.
        Mirrors ``platforms/linux/test_launcher.py``'s identical guard.
        """
        src = render_launcher_source("main")
        assert '"main.py"' not in src
        assert '"-P"' in src
        assert '"-m"' in src
        assert "(char *)ENTRY" in src

    def test_the_cwd_is_kept_off_sys_path(self):
        """``-m`` alone would put the launch directory on sys.path; ``-P`` must not.

        Weaker-stakes here than on Linux (this launcher already ``chdir``s into
        ``app`` first), but kept for symmetry — see the module docstring.
        """
        src = render_launcher_source("main")
        assert 'child[1] = "-P";' in src
        assert 'child[2] = "-m";' in src


class TestLauncherCompileHermetic:
    """build_launcher's compile wiring + error handling, without a real clang.

    The real Mach-O compile is macOS+clang-only (covered by the skipif'd class
    below on the macOS CI job); these mock ``subprocess.run`` so the argv
    assembly, chmod, and both failure branches get coverage on every host.
    """

    def test_missing_clang_is_actionable(self, tmp_path, monkeypatch):
        def no_clang(*a, **k):
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(launcher_mod.subprocess, "run", no_clang)
        with pytest.raises(AppBundleError, match="clang not found"):
            build_launcher(
                tmp_path / "MacOS" / "myapp", entry_point="main", arch="arm64"
            )

    def test_compile_failure_reports_stderr(self, tmp_path, monkeypatch):
        def fail(cmd, **k):
            return subprocess.CompletedProcess(cmd, 1, "", "ld: symbol not found")

        monkeypatch.setattr(launcher_mod.subprocess, "run", fail)
        with pytest.raises(AppBundleError, match="failed to compile"):
            build_launcher(
                tmp_path / "MacOS" / "myapp", entry_point="main", arch="arm64"
            )

    def test_success_passes_arch_and_marks_executable(self, tmp_path, monkeypatch):
        recorded = {}

        def ok(cmd, **k):
            recorded["cmd"] = cmd
            dest = Path(cmd[cmd.index("-o") + 1])
            dest.write_bytes(b"\xcf\xfa\xed\xfe")  # Mach-O magic placeholder
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(launcher_mod.subprocess, "run", ok)
        dest = tmp_path / "MacOS" / "myapp"
        build_launcher(dest, entry_point="main", arch="arm64")
        # build_launcher chmods 0o755 (a no-op on Windows CI hosts, hence no
        # executable-bit assertion here) and writes the compiled output.
        assert dest.exists()
        # The arch is forwarded to clang as a single `-arch <a>` pair.
        assert recorded["cmd"].count("-arch") == 1
        assert "arm64" in recorded["cmd"]


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

    def test_builds_thin_macho(self, tmp_path):
        host = "arm64" if platform.machine() == "arm64" else "x86_64"
        path = tmp_path / "MacOS" / "myapp"
        build_launcher(path, entry_point="main", arch=host)
        assert is_macho(path)
        assert macho_arches(path) == (host,)
        assert os.stat(path).st_mode & stat.S_IXUSR

    def test_child_sees_bin_first_on_path(self, tmp_path):
        import subprocess

        host = "arm64" if platform.machine() == "arm64" else "x86_64"
        contents = tmp_path / "My.app" / "Contents"
        launcher = contents / "MacOS" / "myapp"
        build_launcher(launcher, entry_point="main", arch=host)

        # A fake "python3" that ignores its script arg and prints PATH, standing
        # in for the interpreter the launcher execs.
        py = contents / "Resources" / "python" / "bin" / "python3"
        py.parent.mkdir(parents=True)
        py.write_text('#!/bin/sh\nprintf "%s" "$PATH"\n')
        py.chmod(0o755)
        (contents / "Resources" / "app").mkdir(parents=True)
        (contents / "Resources" / "app" / "main.py").write_text("")
        (contents / "Resources" / "bin").mkdir(parents=True)

        out = subprocess.run(
            [str(launcher)], capture_output=True, text=True, check=True
        ).stdout
        first = out.split(":", 1)[0]
        assert first.endswith("/Resources/bin")

    def test_child_is_invoked_with_dash_m_not_a_source_path(self, tmp_path):
        """End-to-end proof the launcher execs ``-P -m main``, not a ``.py`` path.

        The closest thing to a real regression test for the exit-2-before-
        Python-starts defect: a real compiled launcher, a fake interpreter that
        echoes its own argv, and no ``main.py`` on disk at all — only the
        argv-based ``-m`` invocation can possibly work here.
        """
        host = "arm64" if platform.machine() == "arm64" else "x86_64"
        contents = tmp_path / "My.app" / "Contents"
        launcher = contents / "MacOS" / "myapp"
        build_launcher(launcher, entry_point="main", arch=host)

        # A fake "python3" that prints its own argv, standing in for the
        # interpreter the launcher execs.
        py = contents / "Resources" / "python" / "bin" / "python3"
        py.parent.mkdir(parents=True)
        py.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        py.chmod(0o755)
        (contents / "Resources" / "app").mkdir(parents=True)
        # Deliberately no main.py/main.pyc here: only an argv-based `-m`
        # invocation could ever find the entry point in a stripped bundle, so
        # this is checking the launcher's own argv, not whether main resolves.
        (contents / "Resources" / "bin").mkdir(parents=True)

        out = subprocess.run(
            [str(launcher), "--extra"], capture_output=True, text=True, check=True
        ).stdout
        argv = out.splitlines()
        assert argv == ["-P", "-m", "main", "--extra"]

    def test_child_never_writes_bytecode(self, tmp_path):
        """End-to-end proof the child actually receives ``PYTHONDONTWRITEBYTECODE=1``."""
        host = "arm64" if platform.machine() == "arm64" else "x86_64"
        contents = tmp_path / "My.app" / "Contents"
        launcher = contents / "MacOS" / "myapp"
        build_launcher(launcher, entry_point="main", arch=host)

        py = contents / "Resources" / "python" / "bin" / "python3"
        py.parent.mkdir(parents=True)
        py.write_text('#!/bin/sh\nprintf "%s" "$PYTHONDONTWRITEBYTECODE"\n')
        py.chmod(0o755)
        (contents / "Resources" / "app").mkdir(parents=True)
        (contents / "Resources" / "bin").mkdir(parents=True)

        out = subprocess.run(
            [str(launcher)], capture_output=True, text=True, check=True
        ).stdout
        assert out == "1"

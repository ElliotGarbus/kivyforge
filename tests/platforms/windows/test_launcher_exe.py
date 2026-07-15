"""End-to-end launcher .exe behavior on a real Windows host (needs MSVC).

Builds a tiny console stub that stands in for ``python.exe`` (it records the
argv + Python env it was handed, then exits with a requested code), lays out a
minimal bundle around the vendored launcher, and runs it. This proves the
spawn-and-wait model, the CommandLineToArgvW-inverse argv quoting, exit-code
propagation, and the PYTHONHOME/PYTHONPATH/PYTHONNOUSERSITE environment — the
parts of the bootloader test matrix that are automatable. (The remaining matrix
items — deep >260-char paths, shortcut launches, Ctrl-C, no-console-flash — stay
a manual/interactive gate per bootloader-windows.md.)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_windows

# A console-subsystem stand-in for python.exe. It writes the Python isolation
# env vars and every forwarded argv entry (UTF-8, one per line) to the file in
# %KIVY_STUB_OUT%, then exits with %KIVY_STUB_EXIT% (default 0).
_STUB_C = r"""
#include <windows.h>
#include <stdlib.h>

static void write_utf8(HANDLE h, const wchar_t *s) {
    int n = WideCharToMultiByte(CP_UTF8, 0, s, -1, NULL, 0, NULL, NULL);
    if (n <= 0) return;
    char *buf = (char *)HeapAlloc(GetProcessHeap(), 0, n);
    if (buf == NULL) return;
    WideCharToMultiByte(CP_UTF8, 0, s, -1, buf, n, NULL, NULL);
    DWORD written;
    WriteFile(h, buf, (DWORD)(n - 1), &written, NULL); /* drop the NUL */
    HeapFree(GetProcessHeap(), 0, buf);
}

int wmain(int argc, wchar_t **argv) {
    static wchar_t buf[32768];
    DWORD len = GetEnvironmentVariableW(L"KIVY_STUB_OUT", buf, 32768);
    if (len == 0) return 90;
    HANDLE h = CreateFileW(buf, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
                           FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return 91;
    const wchar_t *keys[] = {L"PYTHONHOME", L"PYTHONPATH", L"PYTHONNOUSERSITE"};
    for (int k = 0; k < 3; k++) {
        static wchar_t val[32768];
        DWORD n = GetEnvironmentVariableW(keys[k], val, 32768);
        write_utf8(h, keys[k]);
        write_utf8(h, L"=");
        if (n) write_utf8(h, val);
        write_utf8(h, L"\n");
    }
    for (int i = 1; i < argc; i++) {
        write_utf8(h, L"ARG=");
        write_utf8(h, argv[i]);
        write_utf8(h, L"\n");
    }
    CloseHandle(h);
    static wchar_t code[16];
    DWORD cn = GetEnvironmentVariableW(L"KIVY_STUB_EXIT", code, 16);
    return cn ? _wtoi(code) : 0;
}
"""


@pytest.fixture(scope="module")
def launcher_bundle(tmp_path_factory):
    """A bundle: vendored launcher as MyApp.exe + a stub python.exe + bootstrap."""
    from kivyforge.platforms.windows.assets import vendored_launcher
    from kivyforge.platforms.windows.launcher.build_launcher import (
        LauncherBuildError,
        compile_c_source,
    )

    root = tmp_path_factory.mktemp("bundle")
    stub_src = root / "stub.c"
    stub_src.write_text(_STUB_C, encoding="utf-8")
    (root / "python").mkdir()
    try:
        compile_c_source(stub_src, root / "python" / "python.exe", subsystem="CONSOLE")
    except LauncherBuildError as exc:
        pytest.skip(f"MSVC not available to build the launcher test stub: {exc}")

    import shutil

    shutil.copy2(vendored_launcher(), root / "MyApp.exe")
    (root / "_kivyforge_bootstrap.py").write_text("# stub\n", encoding="utf-8")
    return root


def _run_launcher(bundle: Path, args, out: Path, *, exit_code: int = 0, env=None):
    import os

    full_env = dict(os.environ)
    full_env["KIVY_STUB_OUT"] = str(out)
    full_env["KIVY_STUB_EXIT"] = str(exit_code)
    if env:
        full_env.update(env)
    proc = subprocess.run(
        [str(bundle / "MyApp.exe"), *args],
        env=full_env,
        capture_output=True,
        timeout=30,
    )
    return proc


def _read_lines(out: Path) -> list[str]:
    return out.read_text(encoding="utf-8").splitlines()


class TestLauncherExe:
    def test_exit_code_zero(self, launcher_bundle, tmp_path):
        out = tmp_path / "out.txt"
        proc = _run_launcher(launcher_bundle, [], out, exit_code=0)
        assert proc.returncode == 0
        assert out.is_file()

    def test_exit_code_propagates(self, launcher_bundle, tmp_path):
        out = tmp_path / "out.txt"
        proc = _run_launcher(launcher_bundle, [], out, exit_code=42)
        assert proc.returncode == 42

    def test_bootstrap_is_first_arg(self, launcher_bundle, tmp_path):
        out = tmp_path / "out.txt"
        _run_launcher(launcher_bundle, [], out)
        args = [ln[4:] for ln in _read_lines(out) if ln.startswith("ARG=")]
        assert args[0].replace("\\", "/").endswith("_kivyforge_bootstrap.py")

    def test_env_is_set(self, launcher_bundle, tmp_path):
        out = tmp_path / "out.txt"
        _run_launcher(launcher_bundle, [], out)
        text = out.read_text(encoding="utf-8")
        assert "PYTHONHOME=" in text
        assert str(launcher_bundle / "python") in text
        assert (launcher_bundle / "app").name in text  # PYTHONPATH -> <bundle>\app
        assert "PYTHONNOUSERSITE=1" in text

    @pytest.mark.parametrize(
        "forwarded",
        [
            ["plain"],
            ["with space"],
            ['embedded"quote'],
            ["trailing\\", "back\\\\slashes"],
            ["Ünïcödé-Café"],
            ["a b", 'c"d', "e\\", "--flag=value with space"],
        ],
    )
    def test_argv_round_trips(self, launcher_bundle, tmp_path, forwarded):
        out = tmp_path / "out.txt"
        _run_launcher(launcher_bundle, forwarded, out)
        args = [ln[4:] for ln in _read_lines(out) if ln.startswith("ARG=")]
        # args[0] is the bootstrap path; the rest are the forwarded argv verbatim.
        assert args[1:] == forwarded

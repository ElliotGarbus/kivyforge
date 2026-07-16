"""End-to-end launcher .exe behavior on a real Windows host (needs MSVC).

Builds a tiny console stub that stands in for ``python.exe`` (it records its PID,
the argv + Python env it was handed, optionally sleeps, then exits with a
requested code), lays out a minimal bundle around the vendored launcher, and runs
it. This proves the spawn-and-wait model, the CommandLineToArgvW-inverse argv
quoting, exit-code propagation, the PYTHONHOME/PYTHONPATH/PYTHONNOUSERSITE
environment, launching from **space- and non-ASCII-containing install paths**,
and **process-tree teardown** (killing the launcher reaps the child via the Job
object). The remaining matrix items stay a manual/interactive gate per
bootloader-windows.md: **deep >260-char paths** (the launcher declares no
``longPathAware`` manifest, so this needs more than a registry opt-in),
**shortcut launches**, **Ctrl-C**, and **no-console-flash**.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_windows

# A console-subsystem stand-in for python.exe. It writes its own PID, the Python
# isolation env vars, and every forwarded argv entry (UTF-8, one per line) to the
# file in %KIVY_STUB_OUT%. If %KIVY_STUB_SLEEP% (ms) is set it stays alive that
# long (so process-tree teardown can be observed), then exits with
# %KIVY_STUB_EXIT% (default 0).
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
    static wchar_t pidbuf[32];
    _ultow(GetCurrentProcessId(), pidbuf, 10);
    write_utf8(h, L"PID=");
    write_utf8(h, pidbuf);
    write_utf8(h, L"\n");
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
    CloseHandle(h);  /* flush before any sleep so the test can read PID/args */
    static wchar_t sleepbuf[16];
    DWORD sn = GetEnvironmentVariableW(L"KIVY_STUB_SLEEP", sleepbuf, 16);
    if (sn) Sleep((DWORD)_wtoi(sleepbuf));
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


def _clone_bundle(src: Path, dest: Path) -> Path:
    """Copy an assembled launcher bundle to *dest* (e.g. a space/Unicode path)."""
    import shutil

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    return dest


def _pid_alive(pid: int) -> bool:
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


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

    @pytest.mark.parametrize(
        "subdir",
        [
            "Program Files X/My App",  # spaces in the install path
            "Ünïcödé Café/Приложение",  # non-ASCII (and spaces) in the install path
        ],
    )
    def test_runs_from_awkward_install_path(self, launcher_bundle, tmp_path, subdir):
        bundle = _clone_bundle(launcher_bundle, tmp_path / Path(subdir))
        out = tmp_path / "out.txt"
        proc = _run_launcher(bundle, ["an arg"], out)
        assert proc.returncode == 0
        text = out.read_text(encoding="utf-8")
        # The launcher self-locates from its own (awkward) path and points
        # PYTHONHOME back into that same bundle.
        assert f"PYTHONHOME={bundle / 'python'}" in text
        args = [ln[4:] for ln in _read_lines(out) if ln.startswith("ARG=")]
        assert args[0].replace("\\", "/").endswith("_kivyforge_bootstrap.py")
        assert args[1:] == ["an arg"]

    def test_process_tree_teardown(self, launcher_bundle, tmp_path):
        # Killing the launcher must reap the child python via the kill-on-close
        # Job object — no orphaned python.exe.
        import os
        import time

        out = tmp_path / "out.txt"
        env = dict(os.environ)
        env["KIVY_STUB_OUT"] = str(out)
        env["KIVY_STUB_SLEEP"] = "30000"  # keep the child alive so we can kill it
        proc = subprocess.Popen([str(launcher_bundle / "MyApp.exe")], env=env)
        child_pid = None
        try:
            deadline = time.time() + 15
            while time.time() < deadline and child_pid is None:
                if out.is_file():
                    for ln in _read_lines(out):
                        if ln.startswith("PID="):
                            child_pid = int(ln[4:])
                            break
                if child_pid is None:
                    time.sleep(0.1)
            assert child_pid is not None, "stub child never reported its PID"
            assert _pid_alive(child_pid)

            proc.kill()  # terminate the launcher; its job handle closes -> child dies
            proc.wait(timeout=15)

            deadline = time.time() + 15
            while time.time() < deadline and _pid_alive(child_pid):
                time.sleep(0.1)
            assert not _pid_alive(child_pid), (
                "child python survived the launcher being killed (orphaned)"
            )
        finally:
            if child_pid is not None and _pid_alive(child_pid):
                subprocess.run(["taskkill", "/F", "/PID", str(child_pid)], check=False)
            if proc.poll() is None:
                proc.kill()

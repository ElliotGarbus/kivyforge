"""kivyforge.bundle.hostpython — the host CPython ``kivyforge bytecompiler`` installs.

Hermetic: the fetcher, the downloader and the interpreter probe are faked, so
nothing here touches the network or runs a downloaded binary. The real install
is a dated run in test-matrix.md section 7.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.bundle import hostpython
from kivyforge.lock.wheelruntime.runtime import ReleaseAsset, RuntimeProviderError
from kivyforge.report import diagnostics, exit_codes
from kivyforge.status import LockState, LockStatus

_PYCOMPILE = "kivyforge.bundle.pycompile"
_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    "20261101/cpython-3.15.2%2B20261101-aarch64-apple-darwin-install_only.tar.gz"
)


def _archive(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


_GOOD = _archive({"python/bin/python3.15": b"#!/bin/sh\n", "python/lib/x": b""})


class _Fetcher:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[tuple[str, str, str | None]] = []

    def find_install_only(self, minor, target_triple, *, prefer=None):
        self.calls.append((minor, target_triple, prefer))
        if self.error is not None:
            raise self.error
        return self.result


class _Downloader:
    def __init__(self, data: bytes):
        self.data = data

    def fetch_to(self, url, dest):
        Path(dest).write_bytes(self.data)


@pytest.fixture
def mac(monkeypatch):
    """Pretend to be the Apple Silicon host whatever runs the tests."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("kivyforge.host.host_machine", lambda: "arm64")


@pytest.fixture
def runs_as(monkeypatch):
    """Make the installed interpreter's probe answer a chosen version."""

    def answer(version: tuple[int, int, int, str, int] | None):
        monkeypatch.setattr(f"{_PYCOMPILE}._probe_version", lambda argv: version)

    return answer


def _install(tmp_path, data=_GOOD, sha=None, fetcher=None, **kw):
    cache = ArtifactCache(tmp_path / "cache")
    asset = ReleaseAsset(url=_URL, sha256=sha or hashlib.sha256(data).hexdigest())
    fetcher = fetcher or _Fetcher(result=("3.15.2", asset))
    installed = hostpython.install(
        "3.15",
        prefer="3.15.2",
        fetcher=fetcher,
        cache=cache,
        downloader=_Downloader(data),
        **kw,
    )
    return installed, cache, fetcher


class TestHostTriple:
    @pytest.mark.parametrize(
        ("system", "machine", "triple"),
        [
            ("Darwin", "arm64", "aarch64-apple-darwin"),
            ("Linux", "x86_64", "x86_64-unknown-linux-gnu"),
            ("Windows", "amd64", "x86_64-pc-windows-msvc"),
        ],
    )
    def test_the_three_build_hosts(self, system, machine, triple):
        assert hostpython.host_triple(system=system, machine=machine) == triple

    @pytest.mark.parametrize(
        ("system", "machine"),
        [("Darwin", "x86_64"), ("Linux", "aarch64"), ("Windows", "arm64")],
    )
    def test_hosts_kivyforge_does_not_build_on(self, system, machine):
        """An Intel Mac and aarch64 Linux are not build hosts."""
        assert hostpython.host_triple(system=system, machine=machine) is None


class TestInstalledInterpreter:
    def test_none_until_installed(self, tmp_path):
        assert hostpython.installed_interpreter("3.15", root=tmp_path) is None

    def test_posix_layout(self, tmp_path, monkeypatch):
        monkeypatch.setattr("platform.system", lambda: "Darwin")
        exe = tmp_path / "3.15" / "python" / "bin" / "python3.15"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        assert hostpython.installed_interpreter("3.15", root=tmp_path) == exe

    def test_windows_layout(self, tmp_path, monkeypatch):
        monkeypatch.setattr("platform.system", lambda: "Windows")
        exe = tmp_path / "3.15" / "python" / "python.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        assert hostpython.installed_interpreter("3.15", root=tmp_path) == exe

    def test_lives_in_the_artifact_cache(self, tmp_path):
        """So `clean --cache` removes it with the archive it came from."""
        cache = ArtifactCache(tmp_path / "cache")
        assert hostpython.install_root(cache) == cache.root / "host-python"


class TestInstall:
    def test_installs_the_preferred_build(self, tmp_path, mac, runs_as):
        runs_as((3, 15, 2, "final", 0))
        installed, cache, fetcher = _install(tmp_path)
        assert fetcher.calls == [("3.15", "aarch64-apple-darwin", "3.15.2")]
        assert installed.version == "3.15.2"
        assert installed.interpreter == (
            cache.root / "host-python" / "3.15" / "python" / "bin" / "python3.15"
        )
        assert installed.interpreter.is_file()
        assert (
            hostpython.installed_interpreter("3.15", root=cache.root / "host-python")
            == installed.interpreter
        )

    def test_replaces_an_existing_install(self, tmp_path, mac, runs_as):
        runs_as((3, 15, 2, "final", 0))
        root = tmp_path / "cache" / "host-python" / "3.15"
        (root / "python").mkdir(parents=True)
        (root / "python" / "stale").write_text("old")
        installed, _, _ = _install(tmp_path)
        assert not (root / "python" / "stale").exists()
        assert installed.interpreter.is_file()

    def test_a_failed_probe_keeps_the_old_install(self, tmp_path, mac, runs_as):
        """The swap happens only after the new interpreter answered."""
        runs_as((3, 14, 7, "final", 0))
        old = tmp_path / "cache" / "host-python" / "3.15" / "python" / "bin"
        old.mkdir(parents=True)
        (old / "python3.15").write_text("old")
        with pytest.raises(hostpython.HostPythonError, match="did not run as a final"):
            _install(tmp_path)
        assert (old / "python3.15").read_text() == "old"

    def test_a_prerelease_interpreter_is_refused(self, tmp_path, mac, runs_as):
        runs_as((3, 15, 0, "candidate", 1))
        with pytest.raises(hostpython.HostPythonError, match="did not run as a final"):
            _install(tmp_path)

    def test_no_build_for_the_minor(self, tmp_path, mac):
        with pytest.raises(hostpython.HostPythonError) as exc:
            _install(tmp_path, fetcher=_Fetcher(result=None))
        assert exc.value.code == diagnostics.BYTECOMPILE_NO_INTERP
        assert exc.value.exit_code == exit_codes.ENVIRONMENT_ERROR

    def test_no_network_is_a_fetch_failure(self, tmp_path, mac):
        fetcher = _Fetcher(error=RuntimeProviderError("connection refused"))
        with pytest.raises(hostpython.HostPythonError) as exc:
            _install(tmp_path, fetcher=fetcher)
        assert exc.value.code == diagnostics.HOST_PYTHON_FETCH
        assert exc.value.exit_code == exit_codes.ENVIRONMENT_ERROR
        assert "retry with network access" in str(exc.value)

    def test_a_hash_mismatch_is_a_fetch_failure(self, tmp_path, mac):
        with pytest.raises(hostpython.HostPythonError) as exc:
            _install(tmp_path, sha="0" * 64)
        assert exc.value.code == diagnostics.HOST_PYTHON_FETCH
        assert exc.value.context == {"url": _URL}

    def test_a_host_with_no_build(self, tmp_path, monkeypatch):
        monkeypatch.setattr("platform.system", lambda: "Darwin")
        monkeypatch.setattr("kivyforge.host.host_machine", lambda: "x86_64")
        with pytest.raises(hostpython.HostPythonError) as exc:
            _install(tmp_path)
        assert exc.value.code == diagnostics.HOST_INCAPABLE
        assert exc.value.exit_code == exit_codes.ENVIRONMENT_ERROR

    def test_an_archive_escaping_its_directory_is_refused(self, tmp_path, mac):
        evil = _archive({"../escape": b"x"})
        with pytest.raises(hostpython.HostPythonError, match="unsafe path"):
            _install(tmp_path, data=evil)
        assert not (tmp_path / "cache" / "host-python" / "escape").exists()

    def test_reports_the_download(self, tmp_path, mac, runs_as):
        runs_as((3, 15, 2, "final", 0))
        lines: list[str] = []
        _install(tmp_path, on_progress=lines.append)
        assert lines == [
            "[bytecompiler] installing CPython 3.15.2 (aarch64-apple-darwin)"
        ]

    def test_messages_encode_for_a_redirected_stream(self, tmp_path, mac):
        fetcher = _Fetcher(error=RuntimeProviderError("x"))
        with pytest.raises(hostpython.HostPythonError) as exc:
            _install(tmp_path, fetcher=fetcher)
        str(exc.value).encode("cp1252")


class TestByteCompileNeed:
    def test_an_in_sync_lock_gives_its_version(self):
        need = hostpython.byte_compile_need(
            "ios",
            byte_compile=True,
            host_compiler=True,
            lock=LockStatus(LockState.IN_SYNC, "kivyforge lock"),
            lock_version=lambda: "3.15.2",
        )
        assert need.python_version == "3.15.2"
        assert need.lock_problem is None

    @pytest.mark.parametrize(
        ("state", "code"),
        [
            (LockState.MISSING, diagnostics.LOCK_MISSING),
            (LockState.OUT_OF_DATE, diagnostics.LOCK_DRIFT),
            (LockState.UNREADABLE, diagnostics.LOCK_UNREADABLE),
        ],
    )
    def test_a_bad_lock_is_reported_not_read(self, state, code):
        def unread() -> str:
            raise AssertionError("a stale lock's version must not be used")

        need = hostpython.byte_compile_need(
            "android",
            byte_compile="release",
            host_compiler=True,
            lock=LockStatus(state, "kivyforge lock -p android"),
            lock_version=unread,
        )
        assert need.python_version is None
        assert need.lock_problem is not None
        assert need.lock_problem.code == code
        assert need.lock_problem.exit_code == exit_codes.LOCK_DRIFT
        assert "kivyforge lock -p android" in str(need.lock_problem)

"""doctor's check for the pinned host CPython: the six states (proposal 3.9).

doctor never downloads or extracts: it reports what the first release build
will do with this host's entry in the lock.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.bundle import hostpython
from kivyforge.doctor.checks_common import BYTE_COMPILE_NAME, check_host_python
from kivyforge.doctor.result import Status
from kivyforge.lock import host_python as hp
from kivyforge.report import diagnostics

TABLE = "tool.kivy.ios.python.build_settings"
SHA = hashlib.sha256(b"archive").hexdigest()
PINNED = hp.HostPython(
    hp.MACOS_ARM64,
    hp.PINNED,
    "3.15",
    version="3.15.2",
    variant="install_only_stripped",
    url=f"{hostpython.PBS_DOWNLOAD_BASE}/20261101/cpython-3.15.2-x.tar.gz",
    sha256=SHA,
)


@pytest.fixture(autouse=True)
def mac(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("kivyforge.host.host_machine", lambda: "arm64")


@pytest.fixture
def cache(tmp_path):
    return ArtifactCache(tmp_path / "cache")


def _check(entries, cache, byte_compile: bool | str = True, lock=True):
    return check_host_python(
        platform="ios",
        byte_compile=byte_compile,
        lock=SimpleNamespace(host_python=entries) if lock else None,
        table=TABLE,
        cache=cache,
    )


def test_installed_passes_and_names_it(cache):
    exe = hostpython.interpreter_in(hostpython.install_dir(PINNED, cache), "3.15")
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    (hostpython.install_dir(PINNED, cache) / hostpython.MARKER).write_text("")
    result = _check((PINNED,), cache)
    assert result.status is Status.PASS
    assert str(exe) in result.detail


def test_a_cached_archive_is_extracted_on_the_first_build(cache):
    cache.put_bytes(b"archive", SHA, hostpython.archive_filename(PINNED))
    result = _check((PINNED,), cache)
    assert result.status is Status.PASS
    assert "extracted on the first release build" in result.detail


def test_not_cached_with_downloads_on_is_downloaded_on_the_first_build(cache):
    result = _check((PINNED,), cache)
    assert result.status is Status.PASS
    assert "downloaded on the first release build" in result.detail


@pytest.mark.parametrize(
    ("setting", "status"), [(True, Status.FAIL), ("release", Status.WARN)]
)
def test_not_cached_with_downloads_off(cache, monkeypatch, setting, status):
    monkeypatch.setenv(hostpython.DOWNLOADS_VAR, "never")
    result = _check((PINNED,), cache, byte_compile=setting)
    assert result.status is status
    assert result.code == diagnostics.BYTECOMPILE_NO_INTERP
    assert "kivyforge upgrade -p ios" in result.hint


def test_no_build(cache):
    result = _check((hp.HostPython(hp.MACOS_ARM64, hp.NO_BUILD, "3.15"),), cache)
    assert result.status is Status.FAIL
    assert "no final" in result.detail


@pytest.mark.parametrize(
    "entries",
    [None, (hp.HostPython(hp.MACOS_ARM64, hp.UNRESOLVED_OFFLINE, "3.15"),)],
)
def test_no_table_or_unresolved_says_re_lock(cache, entries):
    result = _check(entries, cache, byte_compile="release")
    assert result.status is Status.WARN
    assert result.code == diagnostics.LOCK_INCOMPLETE
    assert "kivyforge lock -p ios" in result.hint


def test_byte_compile_off_skips(cache):
    assert _check(None, cache, byte_compile=False).status is Status.SKIP


def test_no_lock_yet_skips(cache):
    result = _check(None, cache, lock=False)
    assert result.status is Status.SKIP
    assert result.name == BYTE_COMPILE_NAME

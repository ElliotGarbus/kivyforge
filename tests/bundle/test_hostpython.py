"""kivyforge.bundle.hostpython — the pinned host CPython, installed from the lock.

Hermetic: the downloader and the interpreter probe are faked, so nothing here
touches the network or runs a downloaded binary. The real install is a dated
run in test-matrix.md section 7.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.bundle import hostpython
from kivyforge.lock import host_python as hp
from kivyforge.report import diagnostics, exit_codes

_PYCOMPILE = "kivyforge.bundle.pycompile"
_BASE = hostpython.PBS_DOWNLOAD_BASE


def _archive(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


GOOD = _archive({"python/bin/python3.15": b"#!/bin/sh\n", "python/lib/x": b""})


def _entry(data=GOOD, *, sha=None, triple=hp.MACOS_ARM64, state=hp.PINNED):
    name = f"cpython-3.15.2+20261101-{triple}-install_only_stripped.tar.gz"
    return hp.HostPython(
        triple,
        state,
        "3.15",
        version="3.15.2",
        variant="install_only_stripped",
        url=f"{_BASE}/20261101/{name.replace('+', '%2B')}",
        sha256=sha or hashlib.sha256(data).hexdigest(),
    )


class _Downloader:
    def __init__(self, data: bytes = GOOD):
        self.data = data
        self.urls: list[str] = []

    def fetch_to(self, url, dest):
        self.urls.append(url)
        Path(dest).write_bytes(self.data)


@pytest.fixture(autouse=True)
def mac(monkeypatch):
    """Pretend to be the Apple Silicon host whatever runs the tests."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("kivyforge.host.host_machine", lambda: "arm64")


@pytest.fixture
def runs_as(monkeypatch):
    """Make every probe of an interpreter answer a chosen version."""

    def answer(version=(3, 15, 2, "final", 0)):
        monkeypatch.setattr(f"{_PYCOMPILE}._probe_version", lambda argv: version)

    answer()
    return answer


@pytest.fixture
def cache(tmp_path):
    return ArtifactCache(tmp_path / "cache")


def _compile(entries, cache, downloader=None, **kw):
    return hostpython.compiler_for(
        entries,
        platform="ios",
        python_version="3.15.2",
        cache=cache,
        downloader=downloader or _Downloader(),
        **kw,
    )


class TestHostTriple:
    @pytest.mark.parametrize(
        ("system", "machine", "triple"),
        [
            ("Darwin", "arm64", hp.MACOS_ARM64),
            ("Linux", "x86_64", hp.LINUX_X86_64),
            ("Windows", "amd64", hp.WINDOWS_AMD64),
        ],
    )
    def test_the_three_build_hosts(self, system, machine, triple):
        assert hostpython.host_triple(system=system, machine=machine) == triple

    @pytest.mark.parametrize(
        ("system", "machine"), [("Darwin", "x86_64"), ("Linux", "aarch64")]
    )
    def test_hosts_kivyforge_does_not_build_on(self, system, machine):
        assert hostpython.host_triple(system=system, machine=machine) is None


class TestNoUsablePin:
    def test_a_lock_without_the_table_is_incomplete(self, cache):
        result = _compile(None, cache)
        assert isinstance(result, hostpython.Unavailable)
        assert result.code == diagnostics.LOCK_INCOMPLETE
        assert result.classification.get("exit_code") == exit_codes.LOCK_DRIFT
        assert "kivyforge lock -p ios" in result.detail()

    def test_no_entry_for_this_host(self, cache):
        result = _compile((_entry(triple=hp.LINUX_X86_64),), cache)
        assert isinstance(result, hostpython.Unavailable)
        assert result.code == diagnostics.LOCK_INCOMPLETE

    def test_unresolved_offline(self, cache):
        entry = hp.HostPython(hp.MACOS_ARM64, hp.UNRESOLVED_OFFLINE, "3.15")
        result = _compile((entry,), cache)
        assert isinstance(result, hostpython.Unavailable)
        assert "locked offline" in result.headline

    def test_no_build(self, cache):
        entry = hp.HostPython(hp.MACOS_ARM64, hp.NO_BUILD, "3.15")
        result = _compile((entry,), cache)
        assert isinstance(result, hostpython.Unavailable)
        assert result.code == diagnostics.BYTECOMPILE_NO_INTERP
        assert result.classification.get("exit_code") == exit_codes.ENVIRONMENT_ERROR


class TestInstall:
    def test_downloads_extracts_marks_and_uses_it(self, cache, runs_as):
        downloader = _Downloader()
        argv = _compile((_entry(),), cache, downloader)
        exe = hostpython.install_dir(_entry(), cache) / "python" / "bin" / "python3.15"
        assert argv == (str(exe),)
        assert (hostpython.install_dir(_entry(), cache) / hostpython.MARKER).is_file()
        assert len(downloader.urls) == 1

    def test_the_install_is_keyed_by_the_full_hash(self, cache):
        assert hostpython.install_dir(_entry(), cache).name == _entry().sha256

    def test_a_second_build_uses_the_install(self, cache, runs_as):
        _compile((_entry(),), cache)
        downloader = _Downloader()
        _compile((_entry(),), cache, downloader)
        assert downloader.urls == []

    def test_an_install_without_its_marker_is_rebuilt(self, cache, runs_as):
        _compile((_entry(),), cache)
        (hostpython.install_dir(_entry(), cache) / hostpython.MARKER).unlink()
        argv = _compile((_entry(),), cache)
        assert isinstance(argv, tuple)
        assert (hostpython.install_dir(_entry(), cache) / hostpython.MARKER).is_file()

    def test_an_interpreter_that_no_longer_runs_is_rebuilt(self, cache, runs_as):
        _compile((_entry(),), cache)
        runs_as(None)
        result = _compile((_entry(),), cache)
        # Rebuilt from the archive, then refused: it still won't run.
        assert isinstance(result, hostpython.Unavailable)
        assert "did not run as a final CPython 3.15" in result.headline

    def test_a_prerelease_interpreter_is_refused(self, cache, runs_as):
        runs_as((3, 15, 0, "candidate", 1))
        result = _compile((_entry(),), cache)
        assert isinstance(result, hostpython.Unavailable)
        assert result.code == diagnostics.BYTECOMPILE_NO_INTERP

    def test_a_hash_mismatch_says_what_to_check(self, cache, runs_as):
        result = _compile((_entry(sha="0" * 64),), cache)
        assert isinstance(result, hostpython.Unavailable)
        assert result.code == diagnostics.HOST_PYTHON_FETCH
        assert "doesn't match the lock's SHA-256" in result.headline
        assert "re-lock" in result.detail()

    def test_a_failed_download_is_a_fetch_failure(self, cache, runs_as):
        class _Down:
            def fetch_to(self, url, dest):
                from kivyforge.artifacts.download import DownloadError

                raise DownloadError("connection refused")

        result = _compile((_entry(),), cache, _Down())
        assert isinstance(result, hostpython.Unavailable)
        assert result.code == diagnostics.HOST_PYTHON_FETCH
        assert "retry with network access" in result.detail()

    def test_an_archive_escaping_its_directory_is_refused(self, cache, runs_as):
        evil = _archive({"../escape": b"x"})
        result = _compile((_entry(evil),), cache, _Downloader(evil))
        assert isinstance(result, hostpython.Unavailable)
        assert "unsafe path" in result.headline

    def test_messages_encode_for_a_redirected_stream(self, cache, runs_as):
        result = _compile((_entry(sha="0" * 64),), cache)
        assert isinstance(result, hostpython.Unavailable)
        result.required("tool.kivy.ios.python.build_settings").encode("cp1252")


class TestDownloadSettings:
    def test_never_extracts_a_cached_archive(self, cache, runs_as, monkeypatch):
        entry = _entry()
        cache.put_bytes(GOOD, entry.sha256 or "", hostpython.archive_filename(entry))
        monkeypatch.setenv(hostpython.DOWNLOADS_VAR, "never")
        downloader = _Downloader()
        assert isinstance(_compile((entry,), cache, downloader), tuple)
        assert downloader.urls == []

    def test_never_without_a_cached_archive_ships_source(self, cache, monkeypatch):
        monkeypatch.setenv(hostpython.DOWNLOADS_VAR, "never")
        result = _compile((_entry(),), cache)
        assert isinstance(result, hostpython.Unavailable)
        assert result.code == diagnostics.BYTECOMPILE_NO_INTERP
        assert "kivyforge upgrade -p ios" in result.detail()

    def test_no_cache_with_never_is_a_usage_error(self, cache, monkeypatch):
        monkeypatch.setenv(hostpython.DOWNLOADS_VAR, "never")
        with pytest.raises(hostpython.HostPythonError) as exc:
            _compile((_entry(),), cache, no_cache=True)
        assert exc.value.exit_code == exit_codes.CONFIG_ERROR

    def test_an_unknown_value_is_refused(self, cache, monkeypatch):
        monkeypatch.setenv(hostpython.DOWNLOADS_VAR, "sometimes")
        with pytest.raises(hostpython.HostPythonError) as exc:
            _compile((_entry(),), cache)
        assert exc.value.exit_code == exit_codes.CONFIG_ERROR

    def test_the_mirror_replaces_the_base_and_the_hash_still_verifies(
        self, cache, runs_as, monkeypatch
    ):
        monkeypatch.setenv(hostpython.MIRROR_VAR, "https://mirror.example/pbs/")
        downloader = _Downloader()
        assert isinstance(_compile((_entry(),), cache, downloader), tuple)
        assert downloader.urls[0].startswith("https://mirror.example/pbs/20261101/")

    def test_a_mirror_serving_other_bytes_fails_the_hash(
        self, cache, runs_as, monkeypatch
    ):
        monkeypatch.setenv(hostpython.MIRROR_VAR, "https://mirror.example/pbs")
        result = _compile((_entry(),), cache, _Downloader(b"not the archive"))
        assert isinstance(result, hostpython.Unavailable)
        assert hostpython.MIRROR_VAR in result.detail()


class TestPolicy:
    """pinned_compiler: the setting decides what a missing compiler means."""

    def _call(self, byte_compile, note_calls, echoed):
        from kivyforge.report.failures import ClassifiedError

        class _Err(ClassifiedError):
            pass

        return _Err, hostpython.pinned_compiler(
            None,
            platform="ios",
            python_version="3.15.2",
            byte_compile=byte_compile,
            table="tool.kivy.ios.python.build_settings",
            what=" pip-deps",
            error=_Err,
            echo=echoed.append,
            note=lambda *a: note_calls.append(a),
            context={"payload": "pip-deps"},
        )

    def test_release_ships_source_with_a_note(self):
        notes, echoed = [], []
        _err, result = self._call("release", notes, echoed)
        assert result is None
        assert notes[0][0] == diagnostics.LOCK_INCOMPLETE
        assert notes[0][2] == {"payload": "pip-deps"}
        assert echoed[0].startswith("[stage] not byte-compiling pip-deps:")

    def test_true_fails_with_the_reason_s_classification(self):
        from kivyforge.report.failures import ClassifiedError

        with pytest.raises(ClassifiedError) as exc:
            self._call(True, [], [])
        assert exc.value.code == diagnostics.LOCK_INCOMPLETE
        assert exc.value.exit_code == exit_codes.LOCK_DRIFT


class TestFetchFailureContext:
    """A build's fetch failure names the URL in ``context``, as ``upgrade``'s does."""

    def _mismatch(self, byte_compile, cache, notes, context=None):
        from kivyforge.report.failures import ClassifiedError

        return hostpython.pinned_compiler(
            (_entry(sha="0" * 64),),
            platform="ios",
            python_version="3.15.2",
            byte_compile=byte_compile,
            table="tool.kivy.ios.python.build_settings",
            what=" pip-deps",
            error=ClassifiedError,
            echo=lambda line: None,
            note=lambda *a: notes.append(a),
            context=context,
            cache=cache,
            downloader=_Downloader(),
        )

    def test_the_warning_carries_the_url_beside_the_caller_s_context(self, cache):
        notes = []
        assert self._mismatch("release", cache, notes, {"payload": "pip-deps"}) is None
        ((code, _message, context),) = notes
        assert code == diagnostics.HOST_PYTHON_FETCH
        assert context == {"url": _entry().url, "payload": "pip-deps"}

    def test_the_warning_carries_the_url_without_a_caller_context(self, cache):
        notes = []
        self._mismatch("release", cache, notes)
        assert notes[0][2] == {"url": _entry().url}

    def test_true_fails_with_the_url(self, cache):
        from kivyforge.report.failures import ClassifiedError

        with pytest.raises(ClassifiedError) as exc:
            self._mismatch(True, cache, [])
        assert exc.value.code == diagnostics.HOST_PYTHON_FETCH
        assert exc.value.context == {"url": _entry().url}


class TestInstallLock:
    @pytest.mark.requires_posix
    def test_a_held_lock_times_out_instead_of_racing(self, cache, runs_as, monkeypatch):
        """POSIX only: flock locks are per open file, so this process can hold
        one and still be refused a second; msvcrt locks are per process."""
        import fcntl

        entry = _entry()
        root = hostpython.install_root(cache)
        root.mkdir(parents=True)
        monkeypatch.setattr(hostpython, "LOCK_TIMEOUT_S", 0.0)
        with open(root / f"{entry.sha256}.lock", "a+b") as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX)
            result = _compile((entry,), cache)
        assert isinstance(result, hostpython.Unavailable)
        assert result.code == diagnostics.HOST_PYTHON_FETCH
        assert "another build" in result.headline

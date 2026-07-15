"""Windows doctor checks (hermetic, over a fake Probe)."""

from __future__ import annotations

import dataclasses
import struct
import textwrap

from kivyforge.config import load_config_from_text
from kivyforge.config.icons import _PNG_SIG
from kivyforge.doctor.result import Status
from kivyforge.lock.model import LockedPackage, LockedWheel
from kivyforge.lock.wheelruntime.model import (
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)
from kivyforge.platforms.windows import doctor as W
from kivyforge.platforms.windows.doctor import run_windows_checks
from tests.doctor.probe_fakes import FakeProbe


def _config(extra: str = "", app_id='"Acme.MyApp"', archs='["amd64"]', signing=""):
    return load_config_from_text(
        textwrap.dedent(
            f"""
            [project]
            name = "myapp"
            version = "1.2.3"

            [tool.kivy]
            app_dir = "src"
            display_name = "My App"

            [tool.kivy.windows]
            schema_version = 1
            app_id = {app_id}
            archs = {archs}
            {extra}

            [tool.kivy.windows.python]
            version = "3.13"
            {signing}
            """
        ).strip(),
        require_ios=False,
        require_windows=True,
    )


def _lock(*, packages=(), archs=("amd64",), native=()):
    return WheelRuntimeLock(
        platform="windows",
        requires_python=">=3.13",
        packages=tuple(packages),
        python_runtime=PythonRuntime(
            provider="python-build-standalone",
            version="3.13.0",
            artifacts=tuple(
                RuntimeArtifact(arch=a, url=f"https://files/{a}", sha256="x")
                for a in archs
            ),
        ),
        archs=archs,
        kivyforge_version="3.0.0",
        generated_at="t",
        pyproject_sha256="0" * 64,
        tool_kivyforge_schema_version=1,
        native_binaries=tuple(native),
    )


def _nb_config(entries: str):
    return _config(extra=f"[tool.kivy.windows.native.binaries]\n{entries}")


def _wheel(name):
    return LockedWheel(name=name, url=f"https://files/{name}", sha256="a" * 64)


def _valid_png(path):
    path.write_bytes(
        _PNG_SIG + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 1024, 1024)
    )


class TestHost:
    def test_pass_on_windows(self):
        assert W.check_windows_host(FakeProbe(host="Windows")).status is Status.PASS

    def test_fail_off_windows(self):
        r = W.check_windows_host(FakeProbe(host="Linux"))
        assert r.status is Status.FAIL


class TestLongPath:
    def test_pass_when_enabled(self):
        r = W.check_long_path_support(FakeProbe(long_paths=True))
        assert r.status is Status.PASS

    def test_warn_when_disabled(self):
        r = W.check_long_path_support(FakeProbe(long_paths=False))
        assert r.status is Status.WARN

    def test_skip_when_unknown(self):
        r = W.check_long_path_support(FakeProbe(long_paths=None))
        assert r.status is Status.SKIP


class TestAppId:
    def test_pass_pascal_period(self):
        assert W.check_windows_app_id(_config()).status is Status.PASS

    def test_warn_on_style(self):
        r = W.check_windows_app_id(_config(app_id='"myapp"'))
        assert r.status is Status.WARN

    def test_fail_on_hard_constraint(self):
        # The loader enforces the hard constraints, so force an invalid id onto a
        # loaded config to exercise the doctor's defensive FAIL branch.
        cfg = _config()
        bad_windows = dataclasses.replace(cfg.windows, app_id="Has Spaces")
        cfg = dataclasses.replace(cfg, windows=bad_windows)
        assert W.check_windows_app_id(cfg).status is Status.FAIL


class TestArchCoverage:
    def test_skip_without_lock(self):
        assert W.check_windows_arch_coverage(_config(), None).status is Status.SKIP

    def test_pass_pure_python(self):
        pkg = LockedPackage(
            name="click", version="8", wheels=(_wheel("click-8-py3-none-any.whl"),)
        )
        r = W.check_windows_arch_coverage(_config(), _lock(packages=(pkg,)))
        assert r.status is Status.PASS

    def test_pass_win_amd64(self):
        pkg = LockedPackage(
            name="kivy",
            version="2",
            wheels=(_wheel("kivy-2-cp313-cp313-win_amd64.whl"),),
        )
        r = W.check_windows_arch_coverage(_config(), _lock(packages=(pkg,)))
        assert r.status is Status.PASS

    def test_fail_missing_win_amd64(self):
        pkg = LockedPackage(
            name="numpy",
            version="2",
            wheels=(_wheel("numpy-2-cp313-cp313-manylinux_x86_64.whl"),),
        )
        r = W.check_windows_arch_coverage(_config(), _lock(packages=(pkg,)))
        assert r.status is Status.FAIL

    def test_fail_runtime_missing_arch(self):
        # Config wants amd64 but the lock's runtime shipped a different arch.
        bad = dataclasses.replace(
            _lock(),
            python_runtime=PythonRuntime(
                provider="python-build-standalone",
                version="3.13.0",
                artifacts=(RuntimeArtifact(arch="x86", url="https://f/x", sha256="x"),),
            ),
        )
        r = W.check_windows_arch_coverage(_config(), bad)
        assert r.status is Status.FAIL


class TestIcon:
    def test_skip_unconfigured(self, tmp_path):
        assert W.check_windows_app_icon(_config(), tmp_path).status is Status.SKIP

    def test_pass_valid(self, tmp_path):
        _valid_png(tmp_path / "icon.png")
        r = W.check_windows_app_icon(
            _config(extra='icons.source = "icon.png"'), tmp_path
        )
        assert r.status is Status.PASS

    def test_fail_missing(self, tmp_path):
        r = W.check_windows_app_icon(
            _config(extra='icons.source = "nope.png"'), tmp_path
        )
        assert r.status is Status.FAIL


class TestNativeSources:
    def test_skip_unconfigured(self, tmp_path):
        r = W.check_windows_native_sources(_config(), tmp_path)
        assert r.status is Status.SKIP

    def test_pass_vendored_present(self, tmp_path):
        (tmp_path / "sdk.dll").write_bytes(b"MZ")
        cfg = _nb_config('sdk = { version = "1", source = "sdk.dll" }')
        r = W.check_windows_native_sources(cfg, tmp_path)
        assert r.status is Status.PASS

    def test_fail_vendored_missing(self, tmp_path):
        cfg = _nb_config('sdk = { version = "1", source = "missing.dll" }')
        r = W.check_windows_native_sources(cfg, tmp_path)
        assert r.status is Status.FAIL


class TestNativeCollision:
    def test_skip_unconfigured(self):
        assert W.check_windows_native_collision(_config()).status is Status.SKIP

    def test_fail_casefold(self):
        cfg = _nb_config(
            'a = { version = "1", source = "https://e/SDK.dll" }\n'
            'b = { version = "1", source = "https://e/sdk.dll" }'
        )
        assert W.check_windows_native_collision(cfg).status is Status.FAIL

    def test_fail_reserved_name(self):
        cfg = _nb_config('a = { version = "1", source = "https://e/NUL.dll" }')
        assert W.check_windows_native_collision(cfg).status is Status.FAIL

    def test_pass_distinct(self):
        cfg = _nb_config(
            'a = { version = "1", source = "https://e/a.dll" }\n'
            'b = { version = "1", source = "https://e/b.dll" }'
        )
        assert W.check_windows_native_collision(cfg).status is Status.PASS


class TestNativeArch:
    def _cfg(self):
        return _nb_config('sdk = { version = "1", source = "https://e/sdk.dll" }')

    def _pe(self, machine):
        buf = bytearray(0x88)
        buf[0:2] = b"MZ"
        struct.pack_into("<I", buf, 0x3C, 0x80)
        buf[0x80:0x84] = b"PE\x00\x00"
        struct.pack_into("<H", buf, 0x84, machine)
        return bytes(buf)

    def test_skip_unconfigured(self, tmp_path):
        assert W.check_windows_native_arch(_config(), tmp_path).status is Status.SKIP

    def test_skip_unbuilt(self, tmp_path):
        assert W.check_windows_native_arch(self._cfg(), tmp_path).status is Status.SKIP

    def test_pass_matching(self, tmp_path):
        from kivyforge.platforms.windows.petools import IMAGE_FILE_MACHINE_AMD64

        bin_dir = tmp_path / "build" / "windows" / "My App" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "sdk.dll").write_bytes(self._pe(IMAGE_FILE_MACHINE_AMD64))
        r = W.check_windows_native_arch(self._cfg(), tmp_path)
        assert r.status is Status.PASS

    def test_fail_wrong_arch(self, tmp_path):
        from kivyforge.platforms.windows.petools import IMAGE_FILE_MACHINE_I386

        bin_dir = tmp_path / "build" / "windows" / "My App" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "x86.dll").write_bytes(self._pe(IMAGE_FILE_MACHINE_I386))
        r = W.check_windows_native_arch(self._cfg(), tmp_path)
        assert r.status is Status.FAIL


_SIGNING = textwrap.dedent(
    """
    [tool.kivy.windows.signing]
    thumbprint = "AABBCCDD"
    store_scope = "current_user"
    """
).strip()


class TestSigntool:
    def test_skip_unconfigured(self):
        r = W.check_windows_signtool(FakeProbe(), _config())
        assert r.status is Status.SKIP

    def test_pass_present(self):
        r = W.check_windows_signtool(
            FakeProbe(signtool=True), _config(signing=_SIGNING)
        )
        assert r.status is Status.PASS

    def test_fail_missing(self):
        r = W.check_windows_signtool(
            FakeProbe(signtool=False), _config(signing=_SIGNING)
        )
        assert r.status is Status.FAIL


class TestSigningCert:
    def test_skip_unconfigured(self):
        r = W.check_windows_signing_cert(FakeProbe(), _config())
        assert r.status is Status.SKIP

    def test_pass_exactly_one(self):
        probe = FakeProbe(thumbprints={"current_user": ["AABBCCDD"]})
        r = W.check_windows_signing_cert(probe, _config(signing=_SIGNING))
        assert r.status is Status.PASS

    def test_fail_none(self):
        probe = FakeProbe(thumbprints={"current_user": ["OTHER"]})
        r = W.check_windows_signing_cert(probe, _config(signing=_SIGNING))
        assert r.status is Status.FAIL

    def test_fail_duplicate(self):
        probe = FakeProbe(thumbprints={"current_user": ["AABBCCDD", "AABBCCDD"]})
        r = W.check_windows_signing_cert(probe, _config(signing=_SIGNING))
        assert r.status is Status.FAIL

    def test_targets_configured_store(self):
        # Cert lives only in machine store; current_user config must not find it.
        probe = FakeProbe(thumbprints={"machine": ["AABBCCDD"], "current_user": []})
        r = W.check_windows_signing_cert(probe, _config(signing=_SIGNING))
        assert r.status is Status.FAIL


class TestFindLinks:
    def test_skip_unconfigured(self, tmp_path):
        assert W.check_windows_find_links(_config(), tmp_path).status is Status.SKIP

    def test_pass_with_wheels(self, tmp_path):
        (tmp_path / "wheels").mkdir()
        (tmp_path / "wheels" / "x-1-py3-none-any.whl").write_bytes(b"x")
        r = W.check_windows_find_links(
            _config(extra='find_links = ["wheels"]'), tmp_path
        )
        assert r.status is Status.PASS

    def test_warn_empty_dir(self, tmp_path):
        (tmp_path / "wheels").mkdir()
        r = W.check_windows_find_links(
            _config(extra='find_links = ["wheels"]'), tmp_path
        )
        assert r.status is Status.WARN

    def test_fail_missing_dir(self, tmp_path):
        r = W.check_windows_find_links(_config(extra='find_links = ["nope"]'), tmp_path)
        assert r.status is Status.FAIL


class TestHostsReachable:
    def test_skip_offline(self):
        r = W.check_windows_hosts_reachable(
            FakeProbe(), _config(), _lock(), offline=True
        )
        assert r.status is Status.SKIP

    def test_pass_all_vendored(self):
        # Runtime artifacts have urls in _lock; make them reachable.
        r = W.check_windows_hosts_reachable(
            FakeProbe(reachable=True), _config(), _lock()
        )
        assert r.status is Status.PASS

    def test_fail_unreachable(self):
        r = W.check_windows_hosts_reachable(
            FakeProbe(reachable=False), _config(), _lock()
        )
        assert r.status is Status.FAIL

    def test_includes_timestamp_when_signing(self):
        seen = {}

        class _P(FakeProbe):
            def tcp_reachable(self, host, port):
                seen[host] = True
                return True

        W.check_windows_hosts_reachable(_P(), _config(signing=_SIGNING), None)
        assert "timestamp.digicert.com" in seen

    def test_probes_scheme_port(self):
        # HTTPS artifact hosts on 443, the HTTP RFC-3161 timestamp host on 80
        # (regression: the timestamp server was probed on 443 and false-failed).
        seen: dict[str, int] = {}

        class _P(FakeProbe):
            def tcp_reachable(self, host, port):
                seen[host] = port
                return True

        # _lock()'s runtime artifacts use https://files/... (host "files", 443).
        W.check_windows_hosts_reachable(_P(), _config(signing=_SIGNING), _lock())
        assert seen["files"] == 443
        assert seen["timestamp.digicert.com"] == 80


_VALID_PYPROJECT = textwrap.dedent(
    """
    [project]
    name = "myapp"
    version = "1.2.3"

    [tool.kivy]
    app_dir = "src"
    display_name = "My App"

    [tool.kivy.windows]
    schema_version = 1
    app_id = "Acme.MyApp"

    [tool.kivy.windows.python]
    version = "3.13"
    """
).strip()


class TestWindowsDoctorEntry:
    def test_environment_mode_no_pyproject(self, tmp_path):
        results = W.windows_doctor(tmp_path, kivyforge_version="1.0.0", offline=True)
        names = {r.name for r in results}
        assert "Host is Windows" in names
        # No project -> every project check SKIPs with the "no pyproject" note.
        assert all(
            r.status is Status.SKIP for r in results if r.name in W._PROJECT_CHECK_NAMES
        )

    def test_project_mode(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(_VALID_PYPROJECT, encoding="utf-8")
        (tmp_path / "src").mkdir()
        results = W.windows_doctor(tmp_path, kivyforge_version="1.0.0", offline=True)
        by_name = {r.name: r for r in results}
        assert by_name["App source directory"].status is Status.PASS
        assert by_name["AppUserModelID"].status is Status.PASS

    def test_malformed_pyproject_reports_fail(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            "[tool.kivy.windows]\nschema_version = 1\n", encoding="utf-8"
        )
        results = W.windows_doctor(tmp_path, kivyforge_version="1.0.0", offline=True)
        assert any(
            r.name == "pyproject.toml" and r.status is Status.FAIL for r in results
        )

    def test_unreadable_lock_reports_fail(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(_VALID_PYPROJECT, encoding="utf-8")
        (tmp_path / "src").mkdir()
        (tmp_path / "pylock.windows.toml").write_text("not = [valid", encoding="utf-8")
        results = W.windows_doctor(tmp_path, kivyforge_version="1.0.0", offline=True)
        assert any(
            r.name == "pylock.windows.toml" and r.status is Status.FAIL for r in results
        )


class TestRunAll:
    def test_environment_mode_skips_project_checks(self):
        results = run_windows_checks(
            FakeProbe(host="Windows"), kivyforge_version="1.0.0"
        )
        names = {r.name for r in results}
        assert "Host is Windows" in names
        for name in W._PROJECT_CHECK_NAMES:
            assert name in names

    def test_project_mode_runs_all(self, tmp_path):
        (tmp_path / "src").mkdir()
        results = run_windows_checks(
            FakeProbe(host="Windows"),
            kivyforge_version="1.0.0",
            config=_config(),
            project_root=tmp_path,
            lock=_lock(),
        )
        statuses = {r.name: r.status for r in results}
        assert statuses["App source directory"] is Status.PASS
        assert statuses["AppUserModelID"] is Status.PASS

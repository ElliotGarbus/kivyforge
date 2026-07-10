"""Linux doctor checks (hermetic, over a fake Probe)."""

from __future__ import annotations

import textwrap

from kivyforge.config import load_config_from_text
from kivyforge.doctor.result import Status
from kivyforge.lock.model import LockedPackage, LockedWheel
from kivyforge.lock.wheelruntime.model import (
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)
from kivyforge.platforms.linux import doctor as L
from kivyforge.platforms.linux.doctor import run_linux_checks
from tests.doctor.probe_fakes import FakeProbe


def _linux_config(extra: str = "", archs="['x86_64']"):
    return load_config_from_text(
        textwrap.dedent(
            f"""
            [project]
            name = "myapp"
            version = "1.0.0"

            [tool.kivy]
            app_dir = "src"

            [tool.kivy.linux]
            schema_version = 1
            app_id = "org.example.myapp"
            archs = {archs}
            {extra}

            [tool.kivy.linux.python]
            version = "3.14.5"
            """
        ).strip(),
        require_ios=False,
        require_linux=True,
    )


def _lock(*, packages=(), archs=("x86_64",), floor="2.17"):
    return WheelRuntimeLock(
        platform="linux",
        requires_python=">=3.14",
        packages=tuple(packages),
        python_runtime=PythonRuntime(
            provider="python-build-standalone",
            version="3.14.5",
            artifacts=tuple(
                RuntimeArtifact(arch=a, url=f"https://files/{a}", sha256="x")
                for a in archs
            ),
            floor=floor,
        ),
        archs=archs,
        kivyforge_version="3.0.0",
        generated_at="t",
        pyproject_sha256="0" * 64,
        tool_kivyforge_schema_version=1,
    )


def _wheel(name):
    return LockedWheel(name=name, url=f"https://files/{name}", sha256="a" * 64)


def _vendored_wheel(name):
    return LockedWheel(name=name, path=f"wheels/{name}", sha256="a" * 64)


class TestHost:
    def test_pass_on_glibc(self):
        r = L.check_linux_host(FakeProbe(host="Linux", libc="glibc"))
        assert r.status is Status.PASS

    def test_warn_on_musl(self):
        r = L.check_linux_host(FakeProbe(host="Linux", libc="musl"))
        assert r.status is Status.WARN
        assert "musl" in r.detail

    def test_fail_off_linux(self):
        r = L.check_linux_host(FakeProbe(host="Darwin"))
        assert r.status is Status.FAIL


class TestGlLibraries:
    def test_pass_when_present(self):
        r = L.check_gl_libraries(FakeProbe())
        assert r.status is Status.PASS

    def test_warn_when_missing(self):
        r = L.check_gl_libraries(FakeProbe(libraries={"libc.so.6"}))
        assert r.status is Status.WARN
        assert "libGL.so.1" in r.detail


class TestDisplaySession:
    def test_pass_with_session(self):
        assert L.check_display_session(FakeProbe()).status is Status.PASS

    def test_warn_when_headless(self):
        r = L.check_display_session(FakeProbe(sessions=set()))
        assert r.status is Status.WARN
        assert "xvfb-run" in r.hint


class TestGlibcFloor:
    def test_reports_effective_floor(self):
        pkg = LockedPackage(
            name="foo",
            version="1",
            wheels=(_wheel("foo-1-cp314-cp314-manylinux_2_28_x86_64.whl"),),
        )
        r = L.check_linux_glibc_floor(_linux_config(), _lock(packages=[pkg]))
        assert r.status is Status.PASS
        assert "2.28" in r.detail

    def test_below_runtime_floor_fails(self):
        cfg = _linux_config('glibc_floor = "2.5"')
        r = L.check_linux_glibc_floor(cfg, _lock(floor="2.17"))
        assert r.status is Status.FAIL

    def test_skip_without_lock(self):
        r = L.check_linux_glibc_floor(_linux_config(), None)
        assert r.status is Status.SKIP

    def test_below_floor_fails_without_lock(self):
        cfg = _linux_config('glibc_floor = "2.5"')
        r = L.check_linux_glibc_floor(cfg, None)
        assert r.status is Status.FAIL


class TestArchCoverage:
    def test_pure_python_ok(self):
        pkg = LockedPackage(
            name="certifi", version="1", wheels=(_wheel("certifi-1-py3-none-any.whl"),)
        )
        r = L.check_linux_arch_coverage(_linux_config(), _lock(packages=[pkg]))
        assert r.status is Status.PASS

    def test_manylinux_ok(self):
        pkg = LockedPackage(
            name="foo",
            version="1",
            wheels=(_wheel("foo-1-cp314-cp314-manylinux_2_17_x86_64.whl"),),
        )
        r = L.check_linux_arch_coverage(_linux_config(), _lock(packages=[pkg]))
        assert r.status is Status.PASS

    def test_musllinux_only_fails(self):
        pkg = LockedPackage(
            name="foo",
            version="1",
            wheels=(_wheel("foo-1-cp314-cp314-musllinux_1_2_x86_64.whl"),),
        )
        r = L.check_linux_arch_coverage(_linux_config(), _lock(packages=[pkg]))
        assert r.status is Status.FAIL
        assert "foo" in r.detail

    def test_runtime_missing_arch_fails(self):
        r = L.check_linux_arch_coverage(_linux_config(), _lock(archs=()))
        assert r.status is Status.FAIL

    def test_plain_linux_from_index_fails(self):
        # A plain linux_x86_64 wheel not sourced from find_links makes no glibc
        # promise and must not count toward coverage.
        pkg = LockedPackage(
            name="foo",
            version="1",
            wheels=(_wheel("foo-1-cp314-cp314-linux_x86_64.whl"),),
        )
        r = L.check_linux_arch_coverage(_linux_config(), _lock(packages=[pkg]))
        assert r.status is Status.FAIL
        assert "foo" in r.detail

    def test_plain_linux_vendored_warns(self):
        pkg = LockedPackage(
            name="foo",
            version="1",
            wheels=(_vendored_wheel("foo-1-cp314-cp314-linux_x86_64.whl"),),
        )
        r = L.check_linux_arch_coverage(_linux_config(), _lock(packages=[pkg]))
        assert r.status is Status.WARN
        assert "no glibc promise" in r.hint

    def test_skip_without_lock(self):
        assert L.check_linux_arch_coverage(_linux_config(), None).status is Status.SKIP


class TestDesktopEntry:
    def test_skip_when_tool_absent(self):
        r = L.check_linux_desktop_entry(
            FakeProbe(desktop_validate=False), _linux_config()
        )
        assert r.status is Status.SKIP

    def test_pass_when_valid(self):
        r = L.check_linux_desktop_entry(FakeProbe(), _linux_config())
        assert r.status is Status.PASS
        assert "org.example.myapp.desktop" in r.detail

    def test_fail_on_validation_error(self):
        probe = FakeProbe(desktop_errors="error: value not defined")
        r = L.check_linux_desktop_entry(probe, _linux_config())
        assert r.status is Status.FAIL
        assert "not defined" in r.hint


class TestAppIcon:
    def test_skip_when_unset(self, tmp_path):
        assert L.check_linux_app_icon(_linux_config(), tmp_path).status is Status.SKIP


class TestFindLinks:
    def test_missing_dir_fails(self, tmp_path):
        cfg = _linux_config("find_links = ['wheels/linux']")
        r = L.check_linux_find_links(cfg, tmp_path)
        assert r.status is Status.FAIL

    def test_with_wheels_passes(self, tmp_path):
        d = tmp_path / "wheels" / "linux"
        d.mkdir(parents=True)
        (d / "foo-1-py3-none-any.whl").write_text("x")
        cfg = _linux_config("find_links = ['wheels/linux']")
        r = L.check_linux_find_links(cfg, tmp_path)
        assert r.status is Status.PASS


class TestHostsReachable:
    def test_includes_appimagetool_hosts(self):
        r = L.check_linux_hosts_reachable(FakeProbe(), _linux_config(), None)
        assert r.status is Status.PASS
        assert "github.com" in r.detail

    def test_unreachable_fails(self):
        probe = FakeProbe(reachable=False)
        r = L.check_linux_hosts_reachable(probe, _linux_config(), _lock())
        assert r.status is Status.FAIL


class TestRunner:
    def test_environment_mode_skips_project_checks(self):
        results = run_linux_checks(
            FakeProbe(host="Linux"), kivyforge_version="3.0.0", config=None
        )
        names = {r.name for r in results}
        assert "Host is Linux" in names
        assert any(
            r.name == "Architecture coverage" and r.status is Status.SKIP
            for r in results
        )
        assert any(
            r.name == "Desktop entry valid" and r.status is Status.SKIP for r in results
        )

    def test_project_mode_runs_all(self, tmp_path):
        (tmp_path / "src").mkdir()
        results = run_linux_checks(
            FakeProbe(host="Linux"),
            kivyforge_version="3.0.0",
            config=_linux_config(),
            project_root=tmp_path,
            lock=_lock(),
        )
        names = {r.name for r in results}
        assert {
            "Host is Linux",
            "GL libraries",
            "Display session",
            "glibc floor",
            "Architecture coverage",
            "Desktop entry valid",
            "Required hosts reachable",
        } <= names

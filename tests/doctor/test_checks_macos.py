"""macOS doctor checks (hermetic, over a fake Probe)."""

from __future__ import annotations

import textwrap

from kivyforge.config import load_config_from_text
from kivyforge.doctor import checks_macos as M
from kivyforge.doctor.result import Status
from kivyforge.doctor.runner import run_macos_checks
from kivyforge.lock.model import LockedPackage, LockedWheel
from kivyforge.lock.wheelruntime.model import (
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)

from .conftest import FakeProbe


def _macos_config(extra: str = "", archs="['arm64','x86_64']"):
    return load_config_from_text(
        textwrap.dedent(
            f"""
            [project]
            name = "myapp"
            version = "1.0.0"

            [tool.kivy]
            app_dir = "src"

            [tool.kivy.macos]
            schema_version = 1
            bundle_id = "org.example.myapp"
            archs = {archs}
            {extra}

            [tool.kivy.macos.python]
            version = "3.14.5"
            """
        ).strip(),
        require_ios=False,
        require_macos=True,
    )


def _lock(*, packages=(), archs=("arm64", "x86_64"), floor=None):
    return WheelRuntimeLock(
        platform="macos",
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


class TestEnvironment:
    def test_host_pass_and_fail(self):
        assert M.check_macos_host(FakeProbe()).status is Status.PASS
        assert M.check_macos_host(FakeProbe(host="Linux")).status is Status.FAIL

    def test_codesign(self):
        assert M.check_codesign(FakeProbe()).status is Status.PASS
        assert M.check_codesign(FakeProbe(codesign=False)).status is Status.FAIL


class TestArchCoverage:
    def test_pure_python_ok(self):
        pkg = LockedPackage(
            name="certifi", version="1", wheels=(_wheel("certifi-1-py3-none-any.whl"),)
        )
        r = M.check_macos_arch_coverage(_macos_config(), _lock(packages=[pkg]))
        assert r.status is Status.PASS

    def test_universal2_ok(self):
        pkg = LockedPackage(
            name="foo",
            version="1",
            wheels=(_wheel("foo-1-cp314-cp314-macosx_11_0_universal2.whl"),),
        )
        r = M.check_macos_arch_coverage(_macos_config(), _lock(packages=[pkg]))
        assert r.status is Status.PASS

    def test_per_arch_missing_fails(self):
        pkg = LockedPackage(
            name="foo",
            version="1",
            wheels=(_wheel("foo-1-cp314-cp314-macosx_11_0_arm64.whl"),),
        )
        r = M.check_macos_arch_coverage(_macos_config(), _lock(packages=[pkg]))
        assert r.status is Status.FAIL
        assert "x86_64" in r.detail

    def test_runtime_missing_arch_fails(self):
        r = M.check_macos_arch_coverage(_macos_config(), _lock(archs=("arm64",)))
        assert r.status is Status.FAIL

    def test_skip_without_lock(self):
        assert M.check_macos_arch_coverage(_macos_config(), None).status is Status.SKIP


class TestRuntimeFloor:
    def test_ok(self):
        cfg = _macos_config('minimum_system_version = "13.0"')
        r = M.check_macos_runtime_floor(cfg, _lock(floor="12.0"))
        assert r.status is Status.PASS

    def test_below_floor_fails(self):
        cfg = _macos_config('minimum_system_version = "11.0"')
        r = M.check_macos_runtime_floor(cfg, _lock(floor="12.0"))
        assert r.status is Status.FAIL

    def test_skip_when_unset(self):
        r = M.check_macos_runtime_floor(_macos_config(), _lock(floor=None))
        assert r.status is Status.SKIP


class TestHostsReachable:
    def test_pass(self):
        pkg = LockedPackage(
            name="certifi", version="1", wheels=(_wheel("certifi-1-py3-none-any.whl"),)
        )
        r = M.check_macos_hosts_reachable(FakeProbe(), _lock(packages=[pkg]))
        assert r.status is Status.PASS
        assert "files" in r.detail

    def test_unreachable_fails(self):
        pkg = LockedPackage(
            name="certifi", version="1", wheels=(_wheel("certifi-1-py3-none-any.whl"),)
        )
        probe = FakeProbe(reachable=False)
        r = M.check_macos_hosts_reachable(probe, _lock(packages=[pkg]))
        assert r.status is Status.FAIL

    def test_skip_without_lock(self):
        assert M.check_macos_hosts_reachable(FakeProbe(), None).status is Status.SKIP


class TestRunner:
    def test_environment_mode_skips_project_checks(self):
        results = run_macos_checks(FakeProbe(), kivyforge_version="3.0.0", config=None)
        names = {r.name for r in results}
        assert "Host is macOS" in names
        assert any(
            r.name == "Architecture coverage" and r.status is Status.SKIP
            for r in results
        )

    def test_project_mode_runs_all(self, tmp_path):
        (tmp_path / "src").mkdir()
        results = run_macos_checks(
            FakeProbe(),
            kivyforge_version="3.0.0",
            config=_macos_config(),
            project_root=tmp_path,
            lock=_lock(),
        )
        names = {r.name for r in results}
        assert {"Architecture coverage", "Runtime floor", "App icon"} <= names


class TestFindLinks:
    def test_missing_dir_fails(self, tmp_path):
        cfg = _macos_config("find_links = ['wheels/macos']")
        r = M.check_macos_find_links(cfg, tmp_path)
        assert r.status is Status.FAIL

    def test_empty_dir_warns(self, tmp_path):
        (tmp_path / "wheels" / "macos").mkdir(parents=True)
        cfg = _macos_config("find_links = ['wheels/macos']")
        r = M.check_macos_find_links(cfg, tmp_path)
        assert r.status is Status.WARN

    def test_with_wheels_passes(self, tmp_path):
        d = tmp_path / "wheels" / "macos"
        d.mkdir(parents=True)
        (d / "foo-1-py3-none-any.whl").write_text("x")
        cfg = _macos_config("find_links = ['wheels/macos']")
        r = M.check_macos_find_links(cfg, tmp_path)
        assert r.status is Status.PASS


class TestAppIcon:
    def test_skip_when_unset(self, tmp_path):
        assert M.check_macos_app_icon(_macos_config(), tmp_path).status is Status.SKIP

    def test_invalid_fails(self, tmp_path):
        (tmp_path / "icon.png").write_bytes(b"not a png")
        cfg = _macos_config("[tool.kivy.macos.icons]\nsource = 'icon.png'")
        # icons subtable placed after python subtable is fine for parsing order;
        # reconstruct via a dedicated config below to avoid ordering pitfalls.
        cfg = load_config_from_text(
            textwrap.dedent(
                """
                [project]
                name='myapp'
                version='1'
                [tool.kivy]
                app_dir='src'
                [tool.kivy.macos]
                schema_version=1
                bundle_id='o.x.a'
                [tool.kivy.macos.icons]
                source='icon.png'
                [tool.kivy.macos.python]
                version='3.14.5'
                """
            ).strip(),
            require_ios=False,
            require_macos=True,
        )
        r = M.check_macos_app_icon(cfg, tmp_path)
        assert r.status is Status.FAIL

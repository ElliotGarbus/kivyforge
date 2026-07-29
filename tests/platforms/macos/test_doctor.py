"""macOS doctor checks (hermetic, over a fake Probe)."""

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
from kivyforge.platforms.macos import doctor as M
from kivyforge.platforms.macos.doctor import run_macos_checks
from tests.doctor.probe_fakes import FakeProbe


def _macos_config(extra: str = "", archs="['arm64']"):
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


def _lock(*, packages=(), archs=("arm64",), floor=None):
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

    def test_thin_arm64_ok(self):
        pkg = LockedPackage(
            name="foo",
            version="1",
            wheels=(_wheel("foo-1-cp314-cp314-macosx_11_0_arm64.whl"),),
        )
        r = M.check_macos_arch_coverage(_macos_config(), _lock(packages=[pkg]))
        assert r.status is Status.PASS

    def test_wrong_arch_wheel_fails(self):
        # An Intel-only wheel covers nothing on an arm64-only build.
        pkg = LockedPackage(
            name="foo",
            version="1",
            wheels=(_wheel("foo-1-cp314-cp314-macosx_11_0_x86_64.whl"),),
        )
        r = M.check_macos_arch_coverage(_macos_config(), _lock(packages=[pkg]))
        assert r.status is Status.FAIL
        assert "arm64" in r.detail

    def test_runtime_missing_arch_fails(self):
        # A stale lock whose runtime predates the arm64-only switch.
        r = M.check_macos_arch_coverage(_macos_config(), _lock(archs=("x86_64",)))
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


_NB = (
    "[tool.kivy.macos.native.binaries]\n"
    'roll = { version = "1.0", source = "binaries/macos/roll" }\n'
)


class TestNativeBinaries:
    def test_skip_when_unconfigured(self, tmp_path):
        r = M.check_macos_native_binaries(_macos_config(), tmp_path)
        assert r.status is Status.SKIP

    def test_fail_when_vendored_source_missing(self, tmp_path):
        cfg = _macos_config(_NB)
        r = M.check_macos_native_binaries(cfg, tmp_path)
        assert r.status is Status.FAIL
        assert "binaries/macos/roll" in r.detail

    def test_pass_sources_present_no_build(self, tmp_path):
        src = tmp_path / "binaries" / "macos" / "roll"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"helper")
        r = M.check_macos_native_binaries(_macos_config(_NB), tmp_path)
        assert r.status is Status.PASS
        assert "sources present" in r.detail

    def test_url_source_skips_local_check(self, tmp_path):
        cfg = _macos_config(
            "[tool.kivy.macos.native.binaries]\n"
            'sdk = { version = "1.0", source = "https://vendor.example/sdk.zip" }\n'
        )
        r = M.check_macos_native_binaries(cfg, tmp_path)
        assert r.status is Status.PASS

    def _built_bin(self, tmp_path):
        bin_dir = (
            tmp_path
            / "build"
            / "macos"
            / "myapp.app"
            / "Contents"
            / "Resources"
            / "bin"
        )
        bin_dir.mkdir(parents=True)
        (tmp_path / "binaries" / "macos").mkdir(parents=True)
        (tmp_path / "binaries" / "macos" / "roll").write_bytes(b"helper")
        (bin_dir / "roll").write_bytes(b"macho")
        return bin_dir

    def test_pass_when_built_covers_archs(self, tmp_path, monkeypatch):
        self._built_bin(tmp_path)
        monkeypatch.setattr(M, "is_macho", lambda p: p.name == "roll")
        monkeypatch.setattr(M, "macho_arches", lambda p: ("arm64",))
        r = M.check_macos_native_binaries(_macos_config(_NB), tmp_path)
        assert r.status is Status.PASS
        assert "cover" in r.detail

    def test_fail_when_built_missing_arch(self, tmp_path, monkeypatch):
        # An Intel-only helper cannot load in an arm64 app.
        self._built_bin(tmp_path)
        monkeypatch.setattr(M, "is_macho", lambda p: p.name == "roll")
        monkeypatch.setattr(M, "macho_arches", lambda p: ("x86_64",))
        r = M.check_macos_native_binaries(_macos_config(_NB), tmp_path)
        assert r.status is Status.FAIL
        assert "roll missing arm64" in r.detail

    def test_fail_on_single_file_basename_collision(self, tmp_path):
        for rel in ("binaries/a/tool", "binaries/b/tool"):
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")
        cfg = _macos_config(
            "[tool.kivy.macos.native.binaries]\n"
            'A = { version = "1.0", source = "binaries/a/tool" }\n'
            'B = { version = "1.0", source = "binaries/b/tool" }\n'
        )
        r = M.check_macos_native_binaries(cfg, tmp_path)
        assert r.status is Status.FAIL
        assert "bin/tool" in r.detail

    def test_zip_sources_do_not_false_positive(self, tmp_path):
        for rel in ("binaries/a.zip", "binaries/b.zip"):
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_bytes(b"zip")
        cfg = _macos_config(
            "[tool.kivy.macos.native.binaries]\n"
            'A = { version = "1.0", source = "binaries/a.zip" }\n'
            'B = { version = "1.0", source = "binaries/b.zip" }\n'
        )
        r = M.check_macos_native_binaries(cfg, tmp_path)
        assert r.status is Status.PASS


class TestNativeBinaryHosts:
    def test_native_binary_url_host_included(self):
        from kivyforge.lock.wheelruntime.model import LockedNativeBinary

        lock = _lock()
        lock = WheelRuntimeLock(
            platform=lock.platform,
            requires_python=lock.requires_python,
            packages=lock.packages,
            python_runtime=lock.python_runtime,
            archs=lock.archs,
            kivyforge_version=lock.kivyforge_version,
            generated_at=lock.generated_at,
            pyproject_sha256=lock.pyproject_sha256,
            tool_kivyforge_schema_version=lock.tool_kivyforge_schema_version,
            native_binaries=(
                LockedNativeBinary(
                    "sdk", "1.0", "a" * 64, url="https://vendor.example/sdk.zip"
                ),
            ),
        )
        r = M.check_macos_hosts_reachable(FakeProbe(), lock)
        assert r.status is Status.PASS
        assert "vendor.example" in r.detail


class TestRunner:
    def test_environment_mode_skips_project_checks(self):
        results = run_macos_checks(FakeProbe(), kivyforge_version="3.0.0", config=None)
        names = {r.name for r in results}
        assert "Host is macOS" in names
        assert any(
            r.name == "Architecture coverage" and r.status is Status.SKIP
            for r in results
        )
        assert any(
            r.name == "Signing identity type" and r.status is Status.SKIP
            for r in results
        )
        assert "Not running as root" in names

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
        assert {
            "Architecture coverage",
            "Runtime floor",
            "App icon",
            "Signing identity type",
            "Not running as root",
        } <= names


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


_SIGNING = (
    "[tool.kivy.macos.signing]\n"
    "identity = 'Developer ID Application: Jane Doe (ABC1234)'\n"
)


class TestSigningIdentity:
    def test_skip_when_unconfigured(self):
        r = M.check_macos_signing_identity(FakeProbe(), _macos_config())
        assert r.status is Status.SKIP
        assert "ad-hoc" in r.detail

    def test_pass_when_in_keychain(self):
        probe = FakeProbe(
            identities=['1) ABCD "Developer ID Application: Jane Doe (ABC1234)"']
        )
        r = M.check_macos_signing_identity(probe, _macos_config(_SIGNING))
        assert r.status is Status.PASS

    def test_fail_when_missing(self):
        probe = FakeProbe(identities=['1) EF12 "Apple Development: Someone Else"'])
        r = M.check_macos_signing_identity(probe, _macos_config(_SIGNING))
        assert r.status is Status.FAIL
        assert "not in keychain" in r.detail

    def test_warn_when_in_login_keychain(self):
        line = '1) ABCD "Developer ID Application: Jane Doe (ABC1234)"'
        probe = FakeProbe(identities=[line], login_identities=[line])
        r = M.check_macos_signing_identity(probe, _macos_config(_SIGNING))
        assert r.status is Status.WARN
        assert "login keychain" in r.detail
        assert "dedicated keychain" in r.hint

    def test_pass_when_in_keychain_but_not_login(self):
        probe = FakeProbe(
            identities=['1) ABCD "Developer ID Application: Jane Doe (ABC1234)"'],
            login_identities=[],
        )
        r = M.check_macos_signing_identity(probe, _macos_config(_SIGNING))
        assert r.status is Status.PASS

    def test_fail_when_ambiguous_across_keychains(self):
        probe = FakeProbe(
            identities=[
                '1) ABCD "Developer ID Application: Jane Doe (ABC1234)"',
                '2) EF01 "Developer ID Application: Jane Doe (ABC1234)"',
            ]
        )
        r = M.check_macos_signing_identity(probe, _macos_config(_SIGNING))
        assert r.status is Status.FAIL
        assert "2 certificates match" in r.detail
        assert "ambiguous" in r.hint


class TestSigningIdentityType:
    def test_skip_when_unconfigured(self):
        r = M.check_macos_signing_identity_type(_macos_config())
        assert r.status is Status.SKIP

    def test_pass_for_developer_id_application(self):
        r = M.check_macos_signing_identity_type(_macos_config(_SIGNING))
        assert r.status is Status.PASS

    def test_pass_for_developer_id_installer(self):
        cfg = _macos_config(
            "[tool.kivy.macos.signing]\n"
            "identity = 'Developer ID Installer: Jane Doe (ABC1234)'\n"
        )
        r = M.check_macos_signing_identity_type(cfg)
        assert r.status is Status.PASS

    def test_warn_for_non_developer_id_identity(self):
        cfg = _macos_config(
            "[tool.kivy.macos.signing]\nidentity = 'Apple Development: Jane Doe (ABC1234)'\n"
        )
        r = M.check_macos_signing_identity_type(cfg)
        assert r.status is Status.WARN
        assert "Developer ID" in r.hint


class TestNotRoot:
    def test_pass_when_not_root(self):
        r = M.check_macos_not_root(FakeProbe(root=False))
        assert r.status is Status.PASS

    def test_warn_when_root(self):
        r = M.check_macos_not_root(FakeProbe(root=True))
        assert r.status is Status.WARN
        assert "root" in r.detail


class TestNotarySetup:
    def test_skip_without_profile(self):
        r = M.check_macos_notary_setup(FakeProbe(), _macos_config())
        assert r.status is Status.SKIP

    def test_pass_with_profile_and_tool(self):
        cfg = _macos_config(_SIGNING + "notary_profile = 'kf-notary'\n")
        r = M.check_macos_notary_setup(FakeProbe(), cfg)
        assert r.status is Status.PASS
        assert "kf-notary" in r.detail

    def test_fail_without_notarytool(self):
        cfg = _macos_config(_SIGNING + "notary_profile = 'kf-notary'\n")
        r = M.check_macos_notary_setup(FakeProbe(notarytool=False), cfg)
        assert r.status is Status.FAIL


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

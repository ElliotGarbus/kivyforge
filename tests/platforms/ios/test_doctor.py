"""Phase 7 — doctor check logic (hermetic, fake probe)."""

from __future__ import annotations

import struct

import pytest

from kivyforge.config import load_config_from_text
from kivyforge.doctor import checks_common as CC
from kivyforge.doctor.probe import CertificateSubject
from kivyforge.doctor.result import Status, worst_status
from kivyforge.platforms.ios import doctor as C
from kivyforge.platforms.ios.doctor import run_ios_checks as run_checks
from kivyforge.platforms.ios.lock import LockedSwiftPackage, Lockfile, PythonXcframework
from tests.doctor.probe_fakes import FakeProbe
from tests.platforms.ios.test_entitlements import write_profile

_DOCTOR_CONFIG = """
[project]
name = "myapp"
version = "1.0.0"

[tool.kivy]
app_dir = "src"

[tool.kivy.ios]
schema_version = 1
bundle_id = "org.example.myapp"
deployment_target = "16.0"

[tool.kivy.ios.python]
version = "3.15.0"
""".strip()


@pytest.fixture
def fake_probe():
    return FakeProbe()


@pytest.fixture
def config():
    return load_config_from_text(_DOCTOR_CONFIG)


def _config_with_swift_package():
    return load_config_from_text(
        "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
        "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
        "[tool.kivy.ios.python]\nversion='3.15.0'\n"
        "[tool.kivy.ios.native.swift_packages]\n"
        'Sentry = { url = "https://github.com/getsentry/sentry-cocoa", '
        'requirement = { from = "8.49.0" }, products = ["Sentry"] }'
    )


class TestEnvironmentChecks:
    def test_xcode_missing(self):
        r = C.check_xcode_version(FakeProbe(xcode=None))
        assert r.status is Status.FAIL

    def test_xcode_too_old(self):
        r = C.check_xcode_version(FakeProbe(xcode="14.2"))
        assert r.status is Status.FAIL

    def test_xcode_ok(self):
        r = C.check_xcode_version(FakeProbe(xcode="16.1"))
        assert r.status is Status.PASS

    def test_pip_ok(self):
        r = CC.check_pip_version(FakeProbe(pip="24.3.1"))
        assert r.status is Status.PASS

    def test_pip_too_old_fails(self):
        r = CC.check_pip_version(FakeProbe(pip="24.2"))
        assert r.status is Status.FAIL
        assert "need >= 24.3" in r.detail

    def test_pip_unknown_warns(self):
        r = CC.check_pip_version(FakeProbe(pip=None))
        assert r.status is Status.WARN

    def test_clt_missing_path(self):
        r = C.check_command_line_tools(FakeProbe(select=None))
        assert r.status is Status.FAIL

    def test_clt_no_clang(self):
        r = C.check_command_line_tools(FakeProbe(clang=False))
        assert r.status is Status.FAIL

    def test_no_runtimes_warns(self, config):
        r = C.check_simulator_runtimes(FakeProbe(runtimes=[]), config)
        assert r.status is Status.WARN

    def test_runtime_below_floor_warns(self, config):
        r = C.check_simulator_runtimes(FakeProbe(runtimes=["12.0"]), config)
        assert r.status is Status.WARN

    def test_runtime_meets_floor(self, config):
        r = C.check_simulator_runtimes(FakeProbe(runtimes=["13.0", "18.0"]), config)
        assert r.status is Status.PASS

    def test_deployment_target_inside_the_sdk_range(self, config):
        r = C.check_deployment_target(FakeProbe(sdk_range=("15.0", "27.0.99")), config)
        assert r.status is Status.PASS
        assert r.detail == "16.0 (Xcode supports 15.0 to 27.0.x)"

    def test_deployment_target_below_the_sdk_floor_fails(self):
        """Xcode 27 refuses 13.0, the old default (found 2026-10-14)."""
        cfg = load_config_from_text(_DOCTOR_CONFIG.replace('"16.0"', '"13.0"'))
        r = C.check_deployment_target(FakeProbe(sdk_range=("15.0", "27.0.99")), cfg)
        assert r.status is Status.FAIL
        assert "13.0 is below the 15.0 to 27.0.x" in r.detail
        # Xcode's floor is 15.0, but Kivy's wheels need 16.0: suggest that.
        assert r.hint is not None and '"16.0"' in r.hint

    def test_deployment_target_hint_follows_a_floor_above_the_default(self):
        cfg = load_config_from_text(_DOCTOR_CONFIG.replace('"16.0"', '"13.0"'))
        r = C.check_deployment_target(FakeProbe(sdk_range=("17.0", "28.0.99")), cfg)
        assert r.status is Status.FAIL
        assert r.hint is not None and '"17.0"' in r.hint

    def test_deployment_target_above_the_sdk_maximum_fails(self):
        cfg = load_config_from_text(_DOCTOR_CONFIG.replace('"16.0"', '"28.0"'))
        r = C.check_deployment_target(FakeProbe(sdk_range=("15.0", "27.0.99")), cfg)
        assert r.status is Status.FAIL
        assert "above" in r.detail

    @pytest.mark.parametrize("target", ["15", "15.0", "27.0", "27.0.1"])
    def test_deployment_target_bounds_are_inclusive(self, target):
        cfg = load_config_from_text(_DOCTOR_CONFIG.replace('"16.0"', f'"{target}"'))
        r = C.check_deployment_target(FakeProbe(sdk_range=("15.0", "27.0.99")), cfg)
        assert r.status is Status.PASS

    def test_deployment_target_environment_mode_reports_the_range(self):
        r = C.check_deployment_target(FakeProbe(sdk_range=("15.0", "27.0.99")), None)
        assert r.status is Status.PASS
        assert r.detail == "Xcode supports iOS 15.0 to 27.0.x"

    def test_deployment_target_unreadable_sdk_skips(self, config):
        r = C.check_deployment_target(FakeProbe(sdk_range=None), config)
        assert r.status is Status.SKIP

    def test_kivyforge_version_offline_pass(self):
        r = CC.check_kivyforge_version(FakeProbe(), "3.0.0", offline=True)
        assert r.status is Status.PASS

    def test_kivyforge_version_newer_warns(self):
        r = CC.check_kivyforge_version(
            FakeProbe(latest="9.0.0"), "3.0.0", offline=False
        )
        assert r.status is Status.WARN


class TestProjectChecks:
    def test_app_dir_missing_fails(self, config, tmp_path):
        # tmp_path has no src/ directory
        assert CC.check_app_dir(config, tmp_path).status is Status.FAIL

    def test_app_dir_present_passes(self, config, tmp_path):
        (tmp_path / "src").mkdir()
        assert CC.check_app_dir(config, tmp_path).status is Status.PASS

    def test_signing_auto_pass(self, config, fake_probe):
        assert C.check_signing_identity(fake_probe, config).status is Status.PASS

    def test_signing_manual_missing_fail(self):
        from kivyforge.config import load_config_from_text

        cfg = load_config_from_text(
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            "[tool.kivy.ios.python]\nversion='3.15.0'\n"
            "[tool.kivy.ios.signing]\nauto_signing=false\nidentity='Acme Inc'"
        )
        probe = FakeProbe(identities=['1) ABC "Apple Development: x"'])
        assert C.check_signing_identity(probe, cfg).status is Status.FAIL

    def test_provisioning_unset_pass(self, config, tmp_path):
        assert C.check_provisioning_profile(config, tmp_path).status is Status.PASS

    def test_app_icon_skip_when_unconfigured(self, config, tmp_path):
        assert C.check_app_icon(config, tmp_path).status is Status.SKIP

    def test_app_icon_fail_wrong_size(self, tmp_path):
        from kivyforge.config import load_config_from_text
        from tests.test_icon import _write_minimal_png

        (tmp_path / "assets").mkdir()
        _write_minimal_png(tmp_path / "assets" / "icon.png", 100, 100)
        cfg = load_config_from_text(
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            "[tool.kivy.ios.python]\nversion='3.15.0'\n"
            '[tool.kivy.ios.icons]\nsource = "assets/icon.png"'
        )
        result = C.check_app_icon(cfg, tmp_path)
        assert result.status is Status.FAIL
        assert "100x100" in (result.hint or "")

    def test_app_icon_pass(self, tmp_path):
        from kivyforge.config import load_config_from_text
        from tests.test_icon import _write_minimal_png

        (tmp_path / "assets").mkdir()
        _write_minimal_png(tmp_path / "assets" / "icon.png", 1024, 1024)
        cfg = load_config_from_text(
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            "[tool.kivy.ios.python]\nversion='3.15.0'\n"
            '[tool.kivy.ios.icons]\nsource = "assets/icon.png"'
        )
        assert C.check_app_icon(cfg, tmp_path).status is Status.PASS

    def test_hosts_reachable_pass(self, fake_probe):
        lock = _lock_with_python_url("https://www.python.org/x.tar.gz")
        assert C.check_hosts_reachable(fake_probe, lock).status is Status.PASS

    def test_hosts_unreachable_fail(self):
        lock = _lock_with_python_url("https://www.python.org/x.tar.gz")
        probe = FakeProbe(reachable={"www.python.org": False})
        r = C.check_hosts_reachable(probe, lock)
        assert r.status is Status.FAIL
        assert "www.python.org" in r.detail

    def test_swift_toolchain_skipped_without_packages(self, config, fake_probe):
        r = C.check_swift_toolchain(fake_probe, config)
        assert r.status is Status.SKIP

    def test_swift_toolchain_fail_when_missing(self):
        cfg = _config_with_swift_package()
        probe = FakeProbe(swift=False)
        r = C.check_swift_toolchain(probe, cfg)
        assert r.status is Status.FAIL
        assert "swift not found" in r.detail

    def test_swift_toolchain_pass(self):
        cfg = _config_with_swift_package()
        r = C.check_swift_toolchain(FakeProbe(swift=True), cfg)
        assert r.status is Status.PASS
        assert "1 swift package" in r.detail

    def test_hosts_include_swift_package_git_host(self, fake_probe):
        lock = _lock_with_swift_url("https://github.com/getsentry/sentry-cocoa")
        r = C.check_hosts_reachable(fake_probe, lock)
        assert r.status is Status.PASS
        assert "github.com" in r.detail

    def test_hosts_swift_scp_url_host(self, fake_probe):
        lock = _lock_with_swift_url("git@github.com:getsentry/sentry-cocoa.git")
        r = C.check_hosts_reachable(fake_probe, lock)
        assert "github.com" in r.detail

    def test_native_binary_macos_fails(self, config, tmp_path, fake_probe_factory):
        (tmp_path / "src").mkdir()
        so = tmp_path / "src" / "ext.so"
        so.write_bytes(b"\x00")
        probe = fake_probe_factory(platforms={"ext.so": {"macos"}})
        r = C.check_app_native_binaries(probe, config, tmp_path)
        assert r.status is Status.FAIL

    def test_native_binary_ios_passes(self, config, tmp_path, fake_probe_factory):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "ext.so").write_bytes(b"\x00")
        probe = fake_probe_factory(platforms={"ext.so": {"ios"}})
        assert (
            C.check_app_native_binaries(probe, config, tmp_path).status is Status.PASS
        )

    def test_native_binary_unrecognized_warns(
        self, config, tmp_path, fake_probe_factory
    ):
        # A truncated/unrecognized .so yields an empty platform set; it must not
        # silently pass as iOS-safe.
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "ext.so").write_bytes(b"\x00")
        probe = fake_probe_factory(platforms={})  # empty -> unknown
        r = C.check_app_native_binaries(probe, config, tmp_path)
        assert r.status is Status.WARN
        assert "ext.so" in r.detail

    def test_privacy_manifest_absent_warns(self, config, tmp_path):
        assert C.check_app_privacy_manifest(config, tmp_path).status is Status.WARN

    def test_privacy_manifest_present_pass(self, config, tmp_path):
        staging = tmp_path / "myapp-ios"
        staging.mkdir()
        (staging / "PrivacyInfo.xcprivacy").write_text("<plist/>")
        assert C.check_app_privacy_manifest(config, tmp_path).status is Status.PASS

    def test_xcframework_privacy_missing_warns(self, config, tmp_path):
        fw = tmp_path / "myapp-ios" / "Frameworks" / "SDL3.xcframework" / "ios-arm64"
        fw.mkdir(parents=True)
        r = C.check_xcframework_privacy_manifests(config, tmp_path)
        assert r.status is Status.WARN
        assert "SDL3" in r.detail


# Two certificates of one paid team, as read from a real keychain on 2026-10-14:
# on Apple Development the ID in the name is not the Team ID (the OU); on
# Developer ID it is.
APPLE_DEVELOPMENT = CertificateSubject(
    "Apple Development: Jo Doe (X83FAZ586W)", "R5PKSQLUZY", "Jo Doe"
)
DEVELOPER_ID = CertificateSubject(
    "Developer ID Application: Jo Doe (R5PKSQLUZY)", "R5PKSQLUZY", "Jo Doe"
)
PERSONAL_TEAM = CertificateSubject(
    "Apple Development: jo@example.com (K1L2M3N4P5)", "A1B2C3D4E5", "Jo Doe"
)


def _team_config(team_id="", *, profile="", auto_signing=True):
    text = (
        "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
        "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
        "[tool.kivy.ios.python]\nversion='3.15.0'\n"
        f"[tool.kivy.ios.signing]\nteam_id='{team_id}'\n"
        f"auto_signing={str(auto_signing).lower()}\n"
    )
    if profile:
        text += f"provisioning_profile = '{profile}'\n"
    return load_config_from_text(text)


def _team_check(team_id="", *, certificates=(), env=None, tmp_path=None, **config):
    from pathlib import Path

    return C.check_team_id(
        FakeProbe(certificates=list(certificates)),
        _team_config(team_id, **config),
        tmp_path or Path("."),
        env={} if env is None else env,
        search_dirs=(),
    )


class TestTeamIdCheck:
    def test_unset_skips_and_lists_the_keychain_teams(self):
        """A simulator-only user must not be warned (issue #108)."""
        r = _team_check(certificates=[APPLE_DEVELOPMENT, DEVELOPER_ID, PERSONAL_TEAM])
        assert r.status is Status.SKIP
        assert r.detail == (
            "not set (needed for --device and --release); "
            "in keychain: A1B2C3D4E5 (Jo Doe), R5PKSQLUZY (Jo Doe)"
        )
        assert "KIVYFORGE_TEAM_ID" in r.hint

    def test_unset_with_an_empty_keychain(self):
        r = _team_check()
        assert r.status is Status.SKIP
        assert r.detail == "not set (needed for --device and --release)"

    def test_a_certificate_without_a_team_is_not_listed(self):
        local = CertificateSubject("My Local Signer", "Engineering", "Acme")
        r = _team_check(certificates=[local])
        assert "in keychain" not in r.detail

    @pytest.mark.parametrize(
        "value", ["ABCDE1234", "ABCDE123456", "abcde12345", "ABCDE-1234", "ABCDE 1234"]
    )
    def test_malformed_fails(self, value):
        r = _team_check(value, certificates=[APPLE_DEVELOPMENT])
        assert r.status is Status.FAIL
        assert f"{value!r} from [tool.kivy.ios.signing].team_id" in r.detail
        assert "R5PKSQLUZY (Jo Doe)" in r.hint

    def test_malformed_with_an_empty_keychain_points_at_the_guide(self):
        r = _team_check("nope")
        assert r.status is Status.FAIL
        assert "Find your Team ID" in r.hint

    def test_the_id_in_a_certificate_name_is_named_as_the_mistake(self):
        """The commonest wrong paste: it is the certificate's ID, not the team's."""
        r = _team_check("X83FAZ586W", certificates=[APPLE_DEVELOPMENT])
        assert r.status is Status.FAIL
        assert r.detail == (
            "X83FAZ586W is the ID in the name of the certificate "
            '"Apple Development: Jo Doe (X83FAZ586W)", not the Team ID'
        )
        assert r.hint.startswith(
            "set [tool.kivy.ios.signing].team_id to R5PKSQLUZY (Jo Doe)."
        )

    def test_the_certificate_mistake_without_a_readable_team(self):
        odd = CertificateSubject("Apple Development: Jo (X83FAZ586W)", "", "")
        r = _team_check("X83FAZ586W", certificates=[odd])
        assert r.status is Status.FAIL
        assert "Organizational Unit" in r.hint

    def test_the_id_in_a_developer_id_name_is_the_team_id(self):
        r = _team_check("R5PKSQLUZY", certificates=[DEVELOPER_ID])
        assert r.status is Status.PASS
        assert r.detail == "R5PKSQLUZY (Jo Doe)"

    def test_a_personal_team_passes(self):
        r = _team_check("A1B2C3D4E5", certificates=[APPLE_DEVELOPMENT, PERSONAL_TEAM])
        assert r.status is Status.PASS
        assert r.detail == "A1B2C3D4E5 (Jo Doe)"

    def test_a_team_with_no_certificate_warns(self):
        r = _team_check("ZZZZZ99999", certificates=[APPLE_DEVELOPMENT])
        assert r.status is Status.WARN
        assert r.detail == (
            "ZZZZZ99999: no signing certificate in the keychain is for this team; "
            "in keychain: R5PKSQLUZY (Jo Doe)"
        )
        assert "automatic signing can create one" in r.hint

    def test_a_team_with_no_certificate_under_manual_signing(self):
        r = _team_check("ZZZZZ99999", auto_signing=False)
        assert r.status is Status.WARN
        assert r.detail.endswith("is for this team")
        assert "manual signing needs" in r.hint

    def test_the_environment_wins_and_is_named(self):
        env = {"KIVYFORGE_TEAM_ID": "R5PKSQLUZY"}
        r = _team_check("bad", certificates=[DEVELOPER_ID], env=env)
        assert r.status is Status.PASS
        assert r.detail == "R5PKSQLUZY (Jo Doe) from KIVYFORGE_TEAM_ID"

    def test_a_malformed_environment_value_names_the_variable(self):
        r = _team_check("R5PKSQLUZY", env={"KIVYFORGE_TEAM_ID": "r5pksqluzy"})
        assert r.status is Status.FAIL
        assert "'r5pksqluzy' from KIVYFORGE_TEAM_ID" in r.detail

    def test_an_empty_environment_value_falls_back_to_pyproject(self):
        r = _team_check(
            "R5PKSQLUZY", certificates=[DEVELOPER_ID], env={"KIVYFORGE_TEAM_ID": ""}
        )
        assert r.status is Status.PASS
        assert r.detail == "R5PKSQLUZY (Jo Doe)"

    def test_a_pinned_profile_of_another_team_fails(self, tmp_path):
        write_profile(tmp_path / "p.mobileprovision", {}, teams=["OTHER12345"])
        r = _team_check(
            "R5PKSQLUZY",
            certificates=[DEVELOPER_ID],
            tmp_path=tmp_path,
            profile="p.mobileprovision",
            auto_signing=False,
        )
        assert r.status is Status.FAIL
        assert r.detail == (
            "R5PKSQLUZY is not the team of the pinned profile Acme Development "
            "(OTHER12345)"
        )

    def test_a_pinned_profile_of_this_team_passes(self, tmp_path):
        write_profile(tmp_path / "p.mobileprovision", {}, teams=["R5PKSQLUZY"])
        r = _team_check(
            "R5PKSQLUZY",
            certificates=[DEVELOPER_ID],
            tmp_path=tmp_path,
            profile="p.mobileprovision",
            auto_signing=False,
        )
        assert r.status is Status.PASS

    def test_a_profile_mismatch_outranks_a_missing_certificate(self, tmp_path):
        write_profile(tmp_path / "p.mobileprovision", {}, teams=["OTHER12345"])
        r = _team_check(
            "ZZZZZ99999",
            tmp_path=tmp_path,
            profile="p.mobileprovision",
            auto_signing=False,
        )
        assert r.status is Status.FAIL

    @pytest.mark.parametrize("contents", [None, b"not a profile", "no teams"])
    def test_an_unusable_profile_is_left_to_the_profile_check(self, tmp_path, contents):
        path = tmp_path / "p.mobileprovision"
        if contents == "no teams":
            write_profile(path, {})
        elif contents is not None:
            path.write_bytes(contents)
        r = _team_check(
            "R5PKSQLUZY",
            certificates=[DEVELOPER_ID],
            tmp_path=tmp_path,
            profile="p.mobileprovision",
            auto_signing=False,
        )
        assert r.status is Status.PASS

    def test_an_unknown_profile_name_is_left_to_the_profile_check(self):
        r = _team_check(
            "R5PKSQLUZY",
            certificates=[DEVELOPER_ID],
            profile="No Such Profile",
            auto_signing=False,
        )
        assert r.status is Status.PASS

    def test_messages_encode_in_cp1252(self):
        """Every outcome's text survives a redirected Windows stream."""
        results = [
            _team_check(),
            _team_check(certificates=[APPLE_DEVELOPMENT]),
            _team_check("nope"),
            _team_check("X83FAZ586W", certificates=[APPLE_DEVELOPMENT]),
            _team_check("ZZZZZ99999", certificates=[APPLE_DEVELOPMENT]),
        ]
        for r in results:
            r.render().encode("cp1252")
            r.hint.encode("cp1252")


class TestRunModes:
    def test_environment_mode_skips_project(self, fake_probe):
        results = run_checks(fake_probe, kivyforge_version="3.0.0", config=None)
        skipped = [r for r in results if r.status is Status.SKIP]
        assert len(skipped) == 13
        # Every project check must be represented, not silently dropped.
        names = {r.name for r in skipped}
        assert "Entitlements vs. profile" in names
        assert "Team ID" in names
        assert CC.BYTE_COMPILE_NAME in names

    def test_project_mode_runs_all(self, fake_probe, config, tmp_path):
        results = run_checks(
            fake_probe,
            kivyforge_version="3.0.0",
            config=config,
            project_root=tmp_path,
        )
        names = {r.name for r in results}
        assert "Deployment target" in names
        assert "App source directory" in names
        assert "Signing identity" in names
        assert "Team ID" in names
        assert "find_links directories" in names
        assert "App icon" in names
        assert "App-level privacy manifest" in names

    def test_find_links_missing_fail(self, tmp_path):
        from kivyforge.config import load_config_from_text

        cfg = load_config_from_text(
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            'find_links = ["wheels"]\n'
            "[tool.kivy.ios.python]\nversion='3.15.0'"
        )
        result = C.check_find_links(cfg, tmp_path)
        assert result.status is Status.FAIL
        assert "missing" in result.detail

    def test_find_links_empty_warns(self, tmp_path):
        from kivyforge.config import load_config_from_text

        (tmp_path / "wheels").mkdir()
        cfg = load_config_from_text(
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            'find_links = ["wheels"]\n'
            "[tool.kivy.ios.python]\nversion='3.15.0'"
        )
        result = C.check_find_links(cfg, tmp_path)
        assert result.status is Status.WARN
        assert "no .whl files" in result.detail

    def test_find_links_with_wheels_passes(self, tmp_path):
        from kivyforge.config import load_config_from_text

        wheels = tmp_path / "wheels"
        wheels.mkdir()
        (wheels / "kivy-1.whl").write_bytes(b"whl")
        cfg = load_config_from_text(
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            'find_links = ["wheels"]\n'
            "[tool.kivy.ios.python]\nversion='3.15.0'"
        )
        assert C.check_find_links(cfg, tmp_path).status is Status.PASS

    def test_worst_status(self):
        from kivyforge.doctor.result import CheckResult

        results = [
            CheckResult("a", Status.PASS),
            CheckResult("b", Status.WARN),
            CheckResult("c", Status.FAIL),
        ]
        assert worst_status(results) is Status.FAIL


class TestMachOParser:
    def test_parses_ios_platform(self):
        from kivyforge.doctor.probe import _macho_platforms

        assert "ios" in _macho_platforms(_thin_macho(platform=2))

    def test_parses_macos_platform(self):
        from kivyforge.doctor.probe import _macho_platforms

        assert "macos" in _macho_platforms(_thin_macho(platform=1))

    def test_non_macho_returns_empty(self):
        from kivyforge.doctor.probe import _macho_platforms

        assert _macho_platforms(b"not a macho") == set()


@pytest.fixture
def fake_probe_factory():
    return lambda **kw: FakeProbe(**kw)


def _lock_with_python_url(url: str) -> Lockfile:
    return Lockfile(
        requires_python=">=3.15",
        packages=(),
        python_xcframework=PythonXcframework(
            version="3.15.0", url=url, sha256="c" * 64
        ),
        kivyforge_version="3.0.0",
        generated_at="t",
        pyproject_sha256="d" * 64,
        tool_kivyforge_schema_version=1,
    )


def _lock_with_swift_url(url: str) -> Lockfile:
    return Lockfile(
        requires_python=">=3.15",
        packages=(),
        python_xcframework=PythonXcframework(version="3.15.0", url="", sha256="c" * 64),
        kivyforge_version="3.0.0",
        generated_at="t",
        pyproject_sha256="d" * 64,
        tool_kivyforge_schema_version=1,
        swift_packages=(
            LockedSwiftPackage(
                name="Sentry",
                products=("Sentry",),
                url=url,
                requirement={"from": "8.49.0"},
                revision="a" * 40,
                version="8.49.0",
            ),
        ),
    )


def _thin_macho(*, platform: int) -> bytes:
    # 64-bit Mach-O, big-endian, one LC_BUILD_VERSION command.
    # mach_header_64: magic, cputype, cpusubtype, filetype, ncmds,
    #                 sizeofcmds, flags, reserved  (8 x uint32 = 32 bytes)
    header = struct.pack(">IiiIIIII", 0xFEEDFACF, 0x0100000C, 0, 2, 1, 24, 0, 0)
    # LC_BUILD_VERSION: cmd, cmdsize, platform, minos, sdk, ntools
    lc = struct.pack(">IIIIII", 0x32, 24, platform, 0, 0, 0)
    return header + lc

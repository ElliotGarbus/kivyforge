"""Entitlements vs. provisioning-profile comparison (build pre-flight + doctor).

``codesign`` requires the app's entitlements to be a subset of the profile's, so
``build`` and ``doctor`` compare them up front. Severity follows the signing
mode: FAIL under manual signing (the pinned profile is the one that will sign),
WARN under automatic signing (``-allowProvisioningUpdates`` may register the
capability mid-build).
"""

from __future__ import annotations

import plistlib

import pytest

from kivyforge.config import load_config_from_text
from kivyforge.doctor.result import Status
from kivyforge.platforms.ios import doctor as C
from kivyforge.platforms.ios.entitlements import (
    ProfileError,
    missing_entitlements,
    preflight_entitlements,
    read_profile,
    resolve_profile_path,
)
from kivyforge.platforms.ios.xcode.commands import SigningError

APP_ID = "ABCDE12345.org.example.myapp"


def write_profile(path, granted, *, name="Acme Development"):
    """A .mobileprovision is a CMS envelope wrapping a verbatim XML plist."""
    payload = {
        "Name": name,
        "Entitlements": {"application-identifier": APP_ID, **granted},
    }
    path.write_bytes(b"\x30\x82\xde\xad" + plistlib.dumps(payload) + b"\x00\x01\x02")
    return path


def make_config(*, entitlements="", profile="", auto_signing=True):
    text = (
        "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
        "[tool.kivy.ios]\nschema_version=1\nbundle_id='org.example.myapp'\n"
        "[tool.kivy.ios.python]\nversion='3.15.0'\n"
        f"[tool.kivy.ios.signing]\nauto_signing={str(auto_signing).lower()}\n"
    )
    if profile:
        text += f'provisioning_profile = "{profile}"\n'
    if entitlements:
        text += f"[tool.kivy.ios.entitlements]\n{entitlements}\n"
    return load_config_from_text(text)


HEALTHKIT = '"com.apple.developer.healthkit" = true'


class TestReadProfile:
    def test_extracts_name_app_id_and_entitlements(self, tmp_path):
        path = write_profile(
            tmp_path / "dev.mobileprovision",
            {"com.apple.developer.healthkit": True},
        )
        profile = read_profile(path)
        assert profile.name == "Acme Development"
        assert profile.app_id == APP_ID
        assert profile.entitlements["com.apple.developer.healthkit"] is True

    def test_falls_back_to_filename_when_unnamed(self, tmp_path):
        path = tmp_path / "unnamed.mobileprovision"
        path.write_bytes(b"\x30\x82" + plistlib.dumps({"Entitlements": {}}))
        assert read_profile(path).name == "unnamed.mobileprovision"

    def test_no_embedded_plist_raises(self, tmp_path):
        path = tmp_path / "junk.mobileprovision"
        path.write_bytes(b"\x00\x01\x02 not a profile")
        with pytest.raises(ProfileError, match="no embedded plist"):
            read_profile(path)

    def test_malformed_plist_raises(self, tmp_path):
        path = tmp_path / "bad.mobileprovision"
        path.write_bytes(b"\x30\x82<?xml version='1.0'?><plist><oops</plist>")
        with pytest.raises(ProfileError, match="unreadable plist"):
            read_profile(path)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ProfileError, match="cannot read"):
            read_profile(tmp_path / "absent.mobileprovision")

    def test_profile_without_entitlements_dict(self, tmp_path):
        path = tmp_path / "p.mobileprovision"
        path.write_bytes(b"\x30" + plistlib.dumps({"Name": "P"}))
        profile = read_profile(path)
        assert profile.entitlements == {}
        assert profile.app_id == ""


class TestMissingEntitlements:
    def test_returns_sorted_ungranted_keys(self):
        assert missing_entitlements(["c", "a", "b"], ["b"]) == ["a", "c"]

    def test_empty_when_all_granted(self):
        assert missing_entitlements(["a"], ["a", "b"]) == []

    def test_empty_when_nothing_declared(self):
        assert missing_entitlements([], ["a"]) == []


class TestResolveProfilePath:
    def test_none_when_unset(self, tmp_path):
        assert resolve_profile_path(make_config(), tmp_path) is None

    def test_relative_resolves_against_project_root(self, tmp_path):
        cfg = make_config(profile="signing/dev.mobileprovision")
        assert resolve_profile_path(cfg, tmp_path) == (
            tmp_path / "signing/dev.mobileprovision"
        )

    def test_absolute_kept_as_is(self, tmp_path):
        absolute = tmp_path / "abs.mobileprovision"
        cfg = make_config(profile=str(absolute))
        assert resolve_profile_path(cfg, tmp_path) == absolute


class TestPreflight:
    def test_simulator_never_checks(self, tmp_path):
        write_profile(tmp_path / "p.mobileprovision", {})
        cfg = make_config(
            entitlements=HEALTHKIT, profile="p.mobileprovision", auto_signing=False
        )
        assert preflight_entitlements(cfg, tmp_path, "simulator") == []

    def test_no_entitlements_declared(self, tmp_path):
        write_profile(tmp_path / "p.mobileprovision", {})
        cfg = make_config(profile="p.mobileprovision", auto_signing=False)
        assert preflight_entitlements(cfg, tmp_path, "device") == []

    def test_no_profile_pinned(self, tmp_path):
        cfg = make_config(entitlements=HEALTHKIT, auto_signing=False)
        assert preflight_entitlements(cfg, tmp_path, "device") == []

    def test_absent_profile_file_does_not_block(self, tmp_path):
        cfg = make_config(
            entitlements=HEALTHKIT, profile="gone.mobileprovision", auto_signing=False
        )
        assert preflight_entitlements(cfg, tmp_path, "device") == []

    def test_unparseable_profile_does_not_block(self, tmp_path):
        (tmp_path / "p.mobileprovision").write_bytes(b"garbage")
        cfg = make_config(
            entitlements=HEALTHKIT, profile="p.mobileprovision", auto_signing=False
        )
        assert preflight_entitlements(cfg, tmp_path, "device") == []

    def test_all_granted_is_quiet(self, tmp_path):
        write_profile(
            tmp_path / "p.mobileprovision", {"com.apple.developer.healthkit": True}
        )
        cfg = make_config(
            entitlements=HEALTHKIT, profile="p.mobileprovision", auto_signing=False
        )
        assert preflight_entitlements(cfg, tmp_path, "device") == []

    def test_manual_signing_raises_with_actionable_message(self, tmp_path):
        write_profile(tmp_path / "p.mobileprovision", {})
        cfg = make_config(
            entitlements=HEALTHKIT, profile="p.mobileprovision", auto_signing=False
        )
        with pytest.raises(SigningError) as exc:
            preflight_entitlements(cfg, tmp_path, "device")
        message = str(exc.value)
        assert "com.apple.developer.healthkit" in message
        assert "Acme Development" in message
        assert APP_ID in message
        assert "developer.apple.com" in message

    def test_auto_signing_returns_keys_instead_of_raising(self, tmp_path):
        write_profile(tmp_path / "p.mobileprovision", {})
        cfg = make_config(
            entitlements=HEALTHKIT, profile="p.mobileprovision", auto_signing=True
        )
        assert preflight_entitlements(cfg, tmp_path, "device") == [
            "com.apple.developer.healthkit"
        ]

    def test_release_target_is_checked(self, tmp_path):
        write_profile(tmp_path / "p.mobileprovision", {})
        cfg = make_config(
            entitlements=HEALTHKIT, profile="p.mobileprovision", auto_signing=False
        )
        with pytest.raises(SigningError):
            preflight_entitlements(cfg, tmp_path, "release")


class TestDoctorCheck:
    def test_skip_without_entitlements(self, tmp_path):
        result = C.check_entitlements_vs_profile(make_config(), tmp_path)
        assert result.status is Status.SKIP

    def test_skip_without_pinned_profile(self, tmp_path):
        cfg = make_config(entitlements=HEALTHKIT)
        result = C.check_entitlements_vs_profile(cfg, tmp_path)
        assert result.status is Status.SKIP
        assert "provisioning_profile" in result.detail

    def test_skip_when_profile_file_absent(self, tmp_path):
        cfg = make_config(entitlements=HEALTHKIT, profile="gone.mobileprovision")
        assert C.check_entitlements_vs_profile(cfg, tmp_path).status is Status.SKIP

    def test_pass_when_granted(self, tmp_path):
        write_profile(
            tmp_path / "p.mobileprovision", {"com.apple.developer.healthkit": True}
        )
        cfg = make_config(entitlements=HEALTHKIT, profile="p.mobileprovision")
        result = C.check_entitlements_vs_profile(cfg, tmp_path)
        assert result.status is Status.PASS
        assert "Acme Development" in result.detail

    def test_fail_under_manual_signing(self, tmp_path):
        write_profile(tmp_path / "p.mobileprovision", {})
        cfg = make_config(
            entitlements=HEALTHKIT, profile="p.mobileprovision", auto_signing=False
        )
        result = C.check_entitlements_vs_profile(cfg, tmp_path)
        assert result.status is Status.FAIL
        assert "com.apple.developer.healthkit" in result.detail
        assert APP_ID in result.hint

    def test_warn_under_auto_signing(self, tmp_path):
        write_profile(tmp_path / "p.mobileprovision", {})
        cfg = make_config(
            entitlements=HEALTHKIT, profile="p.mobileprovision", auto_signing=True
        )
        result = C.check_entitlements_vs_profile(cfg, tmp_path)
        assert result.status is Status.WARN
        assert "auto_signing" in result.hint

    def test_warn_when_profile_unreadable(self, tmp_path):
        (tmp_path / "p.mobileprovision").write_bytes(b"garbage")
        cfg = make_config(
            entitlements=HEALTHKIT, profile="p.mobileprovision", auto_signing=False
        )
        result = C.check_entitlements_vs_profile(cfg, tmp_path)
        assert result.status is Status.WARN

    def test_reports_only_ungranted_keys(self, tmp_path):
        write_profile(
            tmp_path / "p.mobileprovision", {"com.apple.developer.healthkit": True}
        )
        cfg = make_config(
            entitlements=(
                f"{HEALTHKIT}\n"
                '"com.apple.security.application-groups" = ["group.org.example"]'
            ),
            profile="p.mobileprovision",
            auto_signing=False,
        )
        result = C.check_entitlements_vs_profile(cfg, tmp_path)
        assert result.status is Status.FAIL
        assert "application-groups" in result.detail
        assert "healthkit" not in result.detail

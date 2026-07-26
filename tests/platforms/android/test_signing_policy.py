"""Signing preflight + release manifest policy (android/06, 07)."""

from __future__ import annotations

import pytest

from kivyforge.config.model import AndroidSigningConfig
from kivyforge.platforms.android.policy import (
    ManifestPolicyError,
    check_release_manifest,
    enforce_release_manifest,
)
from kivyforge.platforms.android.signing import (
    SigningError,
    resolve_signing,
    signing_config_gradle,
)


class TestSigningPreflight:
    def _keystore(self, tmp_path):
        ks = tmp_path / "release.keystore"
        ks.write_bytes(b"not-a-real-keystore")
        return ks

    def test_no_keystore_actionable(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: None)  # skip keytool
        with pytest.raises(SigningError, match="code signing required"):
            resolve_signing(AndroidSigningConfig(), project_root=tmp_path)

    def test_missing_keystore_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: None)
        monkeypatch.setenv("KIVYFORGE_KEYSTORE_PASSWORD", "pw")
        cfg = AndroidSigningConfig(keystore="ghost.keystore", key_alias="upload")
        with pytest.raises(SigningError, match="keystore not found"):
            resolve_signing(cfg, project_root=tmp_path)

    def test_missing_password_env(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: None)
        monkeypatch.delenv("KIVYFORGE_KEYSTORE_PASSWORD", raising=False)
        cfg = AndroidSigningConfig(
            keystore=str(self._keystore(tmp_path)), key_alias="upload"
        )
        with pytest.raises(SigningError, match="password env var"):
            resolve_signing(cfg, project_root=tmp_path)

    def test_resolves_with_cli_override(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: None)  # skip alias verify
        monkeypatch.setenv("KIVYFORGE_KEYSTORE_PASSWORD", "pw")
        ks = self._keystore(tmp_path)
        resolved = resolve_signing(
            AndroidSigningConfig(),
            project_root=tmp_path,
            keystore_override=str(ks),
            key_alias_override="upload",
        )
        assert resolved.key_alias == "upload"
        assert resolved.v1_signing is False and resolved.v2_signing is True

    def test_gradle_block_reads_env(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: None)
        monkeypatch.setenv("KIVYFORGE_KEYSTORE_PASSWORD", "pw")
        resolved = resolve_signing(
            AndroidSigningConfig(
                keystore=str(self._keystore(tmp_path)), key_alias="upload"
            ),
            project_root=tmp_path,
        )
        block = signing_config_gradle(resolved)
        assert "System.getenv('KIVYFORGE_KEYSTORE_PASSWORD')" in block
        assert "keyAlias 'upload'" in block
        assert "enableV2Signing true" in block
        assert "enableV1Signing false" in block


def _manifest(*, package="org.real.app", body="", app_attrs="", perms=""):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    {perms}
    <application android:label="x"{app_attrs}>
        <activity android:name="org.kivy.android.PythonActivity"
                  android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
        {body}
    </application>
</manifest>"""


class TestManifestPolicy:
    def test_clean_manifest_passes(self):
        infos = enforce_release_manifest(_manifest(), package="org.real.app")
        assert infos == []

    def test_placeholder_package_fails(self):
        with pytest.raises(ManifestPolicyError, match="placeholder"):
            enforce_release_manifest(
                _manifest(package="org.example.app"), package="org.example.app"
            )

    def test_debuggable_forced_fails(self):
        xml = _manifest(app_attrs=' android:debuggable="true"')
        with pytest.raises(ManifestPolicyError, match="debuggable"):
            enforce_release_manifest(xml, package="org.real.app")

    def test_extra_exported_component_fails(self):
        body = '<service android:name="org.example.Leak" android:exported="true"/>'
        with pytest.raises(ManifestPolicyError, match="exported"):
            enforce_release_manifest(_manifest(body=body), package="org.real.app")

    def test_intent_filter_without_exported_fails(self):
        body = (
            '<activity android:name="org.example.Second">'
            "<intent-filter>"
            '<action android:name="android.intent.action.VIEW"/>'
            "</intent-filter></activity>"
        )
        with pytest.raises(ManifestPolicyError, match="explicit android:exported"):
            enforce_release_manifest(_manifest(body=body), package="org.real.app")

    def test_two_launchers_fails(self):
        body = (
            '<activity android:name="org.example.Second" '
            'android:exported="false">'
            "<intent-filter>"
            '<action android:name="android.intent.action.MAIN"/>'
            '<category android:name="android.intent.category.LAUNCHER"/>'
            "</intent-filter></activity>"
        )
        with pytest.raises(ManifestPolicyError, match="LAUNCHER"):
            enforce_release_manifest(_manifest(body=body), package="org.real.app")

    def test_cleartext_is_info_not_fail(self):
        xml = _manifest(app_attrs=' android:usesCleartextTraffic="true"')
        infos = enforce_release_manifest(xml, package="org.real.app")
        assert any("cleartext" in i.message for i in infos)

    def test_dangerous_permission_is_info(self):
        perms = '<uses-permission android:name="android.permission.CAMERA"/>'
        infos = enforce_release_manifest(_manifest(perms=perms), package="org.real.app")
        assert any("dangerous runtime permission" in i.message for i in infos)

    def test_findings_include_all_severities(self):
        xml = _manifest(
            package="org.example.app",
            app_attrs=' android:usesCleartextTraffic="true"',
        )
        findings = check_release_manifest(xml, package="org.example.app")
        sev = {f.severity for f in findings}
        assert "FAIL" in sev and "INFO" in sev

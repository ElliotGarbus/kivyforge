"""Authenticode signing hook: version mapping, signer selection, signtool argv."""

from __future__ import annotations

from pathlib import Path

import pytest

from kivyforge.config.model import WindowsSigningConfig
from kivyforge.platforms.windows import WindowsBundleError
from kivyforge.platforms.windows import signing as S


class TestPep440ToFileVersion:
    def test_final(self):
        assert S.pep440_to_file_version("1.2.3") == "1.2.3.40000"

    def test_short_release_pads(self):
        assert S.pep440_to_file_version("1.2") == "1.2.0.40000"
        assert S.pep440_to_file_version("5") == "5.0.0.40000"

    def test_alpha_beta_rc(self):
        assert S.pep440_to_file_version("1.0.0a1") == "1.0.0.10001"
        assert S.pep440_to_file_version("1.0.0b2") == "1.0.0.20002"
        assert S.pep440_to_file_version("1.0.0rc1") == "1.0.0.30001"

    def test_dev_and_post(self):
        assert S.pep440_to_file_version("1.0.0.dev5") == "1.0.0.5"
        assert S.pep440_to_file_version("1.2.3.post1") == "1.2.3.50001"

    def test_ordering_is_monotonic(self):
        def d(v):
            return int(S.pep440_to_file_version(v).split(".")[-1])

        assert (
            d("1.0.0.dev1")
            < d("1.0.0a1")
            < d("1.0.0b1")
            < d("1.0.0rc1")
            < d("1.0.0")
            < d("1.0.0.post1")
        )

    def test_invalid_degrades(self):
        assert S.pep440_to_file_version("not-a-version") == "0.0.0.0"

    def test_clamps_to_u16(self):
        parts = S.pep440_to_file_version("70000.70000.70000").split(".")
        assert all(int(p) <= 0xFFFF for p in parts)


class TestSelectSigner:
    def test_unconfigured_null(self):
        signer = S.select_signer(WindowsSigningConfig())
        assert isinstance(signer, S.NullSigner)
        assert signer.configured is False

    def test_configured_signtool(self):
        cfg = WindowsSigningConfig(thumbprint="aa bb cc", store_scope="current_user")
        signer = S.select_signer(cfg)
        assert isinstance(signer, S.SigntoolSigner)
        assert signer.thumbprint == "AABBCC"  # spaces stripped, upper-cased
        assert signer.configured is True

    def test_both_satisfy_protocol(self):
        assert isinstance(S.NullSigner(), S.Signer)
        assert isinstance(S.SigntoolSigner("AA", "http://ts", "current_user"), S.Signer)


class TestSigntoolCommand:
    def test_current_user_no_sm(self):
        signer = S.SigntoolSigner("AABBCC", "http://ts.example", "current_user")
        argv = signer.command([Path("app.exe")])
        assert argv == [
            "signtool",
            "sign",
            "/sha1",
            "AABBCC",
            "/fd",
            "SHA256",
            "/tr",
            "http://ts.example",
            "/td",
            "SHA256",
            "app.exe",
        ]

    def test_machine_adds_sm(self):
        signer = S.SigntoolSigner("AABBCC", "http://ts.example", "machine")
        argv = signer.command([Path("app.exe")])
        assert "/sm" in argv
        # /sm precedes the file arguments.
        assert argv.index("/sm") < argv.index("app.exe")

    def test_multiple_files(self):
        signer = S.SigntoolSigner("AA", "http://ts", "current_user")
        argv = signer.command([Path("a.exe"), Path("b.dll")])
        assert argv[-2:] == ["a.exe", "b.dll"]


class TestSign:
    def test_null_is_noop(self):
        S.NullSigner().sign([Path("whatever.exe")])  # no raise, no subprocess

    def test_signtool_runs(self, monkeypatch):
        captured = {}

        class _Proc:
            returncode = 0
            stdout = "Done"
            stderr = ""

        def _run(argv, *a, **k):
            captured["argv"] = argv
            return _Proc()

        monkeypatch.setattr(S.subprocess, "run", _run)
        monkeypatch.setattr(S.shutil, "which", lambda name: None)
        signer = S.SigntoolSigner("AA", "http://ts", "current_user")
        signer.sign([Path("app.exe")])
        assert captured["argv"][1] == "sign"
        assert captured["argv"][-1] == "app.exe"

    def test_empty_paths_noop(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("should not run signtool for no files")

        monkeypatch.setattr(S.subprocess, "run", _boom)
        S.SigntoolSigner("AA", "http://ts", "current_user").sign([])

    def test_failure_raises(self, monkeypatch):
        class _Proc:
            returncode = 1
            stdout = ""
            stderr = "SignTool Error: no certificate found"

        monkeypatch.setattr(S.subprocess, "run", lambda *a, **k: _Proc())
        monkeypatch.setattr(S.shutil, "which", lambda name: r"C:\sdk\signtool.exe")
        signer = S.SigntoolSigner("AA", "http://ts", "current_user")
        with pytest.raises(WindowsBundleError, match="signtool failed"):
            signer.sign([Path("app.exe")])

    def test_missing_signtool_raises(self, monkeypatch):
        def _oserror(*a, **k):
            raise FileNotFoundError("signtool")

        monkeypatch.setattr(S.subprocess, "run", _oserror)
        monkeypatch.setattr(S.shutil, "which", lambda name: None)
        signer = S.SigntoolSigner("AA", "http://ts", "current_user")
        with pytest.raises(WindowsBundleError, match="failed to run signtool"):
            signer.sign([Path("app.exe")])

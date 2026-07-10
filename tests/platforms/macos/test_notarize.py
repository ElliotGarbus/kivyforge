"""Notarize + staple flow over a faked subprocess (hermetic)."""

from __future__ import annotations

import json
import subprocess

import pytest

from kivyforge.platforms.macos import AppBundleError, notarize


class FakeRuns:
    """Canned subprocess.run responses keyed by the tool being invoked."""

    def __init__(self, responses):
        # responses: {tool_key: (returncode, stdout, stderr)}
        self.responses = responses
        self.calls: list[list[str]] = []

    def __call__(self, cmd, capture_output=True, text=True):
        self.calls.append(cmd)
        key = self._key(cmd)
        rc, out, err = self.responses.get(key, (0, "", ""))
        return subprocess.CompletedProcess(cmd, rc, out, err)

    @staticmethod
    def _key(cmd):
        if cmd[0] == "xcrun":
            return cmd[1] if cmd[1] != "notarytool" else f"notarytool-{cmd[2]}"
        return cmd[0]


def _app(tmp_path):
    app = tmp_path / "My.app"
    (app / "Contents").mkdir(parents=True)
    return app


def _submit_json(status, sub_id="abc-123"):
    return json.dumps({"id": sub_id, "status": status})


class TestNotarizeAndStaple:
    def test_accepted_zips_submits_staples(self, tmp_path, monkeypatch):
        fake = FakeRuns({"notarytool-submit": (0, _submit_json("Accepted"), "")})
        monkeypatch.setattr(notarize.subprocess, "run", fake)

        notarize.notarize_and_staple(
            _app(tmp_path), profile="prof", echo=lambda m: None
        )

        tools = [FakeRuns._key(c) for c in fake.calls]
        assert tools == ["ditto", "notarytool-submit", "stapler"]
        submit = fake.calls[1]
        assert "--keychain-profile" in submit
        assert submit[submit.index("--keychain-profile") + 1] == "prof"
        assert "--wait" in submit

    def test_invalid_status_surfaces_log_issues(self, tmp_path, monkeypatch):
        log = json.dumps(
            {
                "issues": [
                    {
                        "severity": "error",
                        "path": "My.app/Contents/MacOS/my",
                        "message": "The binary is not signed with a valid "
                        "Developer ID certificate.",
                    }
                ]
            }
        )
        fake = FakeRuns(
            {
                "notarytool-submit": (0, _submit_json("Invalid"), ""),
                "notarytool-log": (0, log, ""),
            }
        )
        monkeypatch.setattr(notarize.subprocess, "run", fake)

        with pytest.raises(AppBundleError) as exc:
            notarize.notarize_and_staple(
                _app(tmp_path), profile="prof", echo=lambda m: None
            )

        msg = str(exc.value)
        assert "Invalid" in msg
        assert "Developer ID certificate" in msg
        # Never stapled on rejection.
        assert all(FakeRuns._key(c) != "stapler" for c in fake.calls)

    def test_submit_failure_without_status_mentions_profile(
        self, tmp_path, monkeypatch
    ):
        fake = FakeRuns({"notarytool-submit": (1, "", "Error: no keychain item found")})
        monkeypatch.setattr(notarize.subprocess, "run", fake)

        with pytest.raises(AppBundleError, match="no keychain item"):
            notarize.notarize_and_staple(
                _app(tmp_path), profile="prof", echo=lambda m: None
            )

    def test_missing_tool_actionable(self, tmp_path, monkeypatch):
        def raise_missing(cmd, **kwargs):
            raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(notarize.subprocess, "run", raise_missing)

        with pytest.raises(AppBundleError, match="xcode-select --install"):
            notarize.notarize_and_staple(
                _app(tmp_path), profile="prof", echo=lambda m: None
            )

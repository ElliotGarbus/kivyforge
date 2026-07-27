"""Cross-target pip invocation shim (kivyforge.lock._pip_shim)."""

from __future__ import annotations

import json
import sys

from kivyforge.lock import _pip_shim


class TestMissingEnvVar:
    def test_returns_2_and_warns(self, monkeypatch, capsys):
        monkeypatch.delenv(_pip_shim.MARKER_ENV_VAR, raising=False)
        rc = _pip_shim.main(["install", "foo"])
        assert rc == 2
        assert "refusing to resolve" in capsys.readouterr().err

    def test_empty_string_treated_as_unset(self, monkeypatch, capsys):
        monkeypatch.setenv(_pip_shim.MARKER_ENV_VAR, "")
        rc = _pip_shim.main(["install", "foo"])
        assert rc == 2


class TestImportErrorPaths:
    def test_missing_vendored_markers_module(self, monkeypatch, capsys):
        monkeypatch.setenv(_pip_shim.MARKER_ENV_VAR, json.dumps({"os_name": "posix"}))
        monkeypatch.setitem(sys.modules, "pip._vendor.packaging.markers", None)
        rc = _pip_shim.main(["install", "foo"])
        assert rc == 3
        assert "does not vendor packaging.markers" in capsys.readouterr().err

    def test_missing_default_environment_attr(self, monkeypatch, capsys):
        from pip._vendor.packaging import markers as real_markers

        monkeypatch.setenv(_pip_shim.MARKER_ENV_VAR, json.dumps({"os_name": "posix"}))
        monkeypatch.delattr(real_markers, "default_environment", raising=False)
        rc = _pip_shim.main(["install", "foo"])
        assert rc == 3
        assert "cannot retarget marker evaluation" in capsys.readouterr().err


class TestSuccessPath:
    def test_replaces_default_environment_and_delegates_to_pip(self, monkeypatch):
        environment = {"os_name": "posix", "platform_system": "Android"}
        monkeypatch.setenv(_pip_shim.MARKER_ENV_VAR, json.dumps(environment))

        from pip._internal.cli import main as pip_main_mod

        captured = {}

        def fake_pip_main(argv):
            from pip._vendor.packaging import markers

            captured["argv"] = argv
            captured["environment"] = markers.default_environment()
            return 0

        monkeypatch.setattr(pip_main_mod, "main", fake_pip_main)

        rc = _pip_shim.main(["install", "kivy"])

        assert rc == 0
        assert captured["argv"] == ["install", "kivy"]
        assert captured["environment"] == environment

    def test_propagates_pip_exit_code(self, monkeypatch):
        monkeypatch.setenv(_pip_shim.MARKER_ENV_VAR, json.dumps({"os_name": "posix"}))
        from pip._internal.cli import main as pip_main_mod

        monkeypatch.setattr(pip_main_mod, "main", lambda argv: 1)
        assert _pip_shim.main(["install", "does-not-exist"]) == 1

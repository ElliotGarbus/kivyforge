"""``kivyforge build`` / ``package`` — the Android option surface (android/06).

The documented Android verbs (``build --debug [-f apk|aab] [--abi]`` and
``package --keystore/--key-alias/--abi``) are reachable only if the shared verbs
declare those options and hand them to the backend; these tests pin that wiring
with the backend resolution mocked.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from kivyforge.cli.build import build as build_cmd
from kivyforge.cli.package import package as package_cmd


class _FakeBackend:
    name = "android"
    package_formats = ("apk", "aab")
    default_package_format = "apk"

    def __init__(self, name: str = "android"):
        self.name = name
        self.build_calls: list[dict] = []
        self.package_calls: list[dict] = []

    def build(self, project_root, **kwargs):
        self.build_calls.append({"project_root": project_root, **kwargs})

    def package(self, project_root, **kwargs):
        self.package_calls.append({"project_root": project_root, **kwargs})


@pytest.fixture
def runner():
    return CliRunner()


def _patch(monkeypatch, module, backend, project_root):
    monkeypatch.setattr(
        module, "resolve_target", lambda cli_platform, verb: (backend, project_root)
    )


class TestAndroidBuildOptions:
    def test_debug_format_and_abi_reach_the_backend(
        self, runner, tmp_path, monkeypatch
    ):
        import kivyforge.cli.build as build_mod

        backend = _FakeBackend()
        _patch(monkeypatch, build_mod, backend, tmp_path)
        result = runner.invoke(
            build_cmd, ["-p", "android", "--debug", "-f", "aab", "--abi", "x86_64"]
        )
        assert result.exit_code == 0, result.output
        (call,) = backend.build_calls
        assert call["debug"] is True
        assert call["fmt"] == "aab"
        assert call["abi"] == "x86_64"

    def test_bare_build_stays_generate_only(self, runner, tmp_path, monkeypatch):
        import kivyforge.cli.build as build_mod

        backend = _FakeBackend()
        _patch(monkeypatch, build_mod, backend, tmp_path)
        result = runner.invoke(build_cmd, ["-p", "android"])
        assert result.exit_code == 0, result.output
        (call,) = backend.build_calls
        assert call["debug"] is False
        assert call["fmt"] is None

    @pytest.mark.parametrize("flag", [["--debug"], ["-f", "aab"], ["--abi", "x86_64"]])
    def test_android_only_options_rejected_elsewhere(
        self, runner, tmp_path, monkeypatch, flag
    ):
        import kivyforge.cli.build as build_mod

        backend = _FakeBackend("macos")
        _patch(monkeypatch, build_mod, backend, tmp_path)
        result = runner.invoke(build_cmd, flag)
        assert result.exit_code != 0
        assert "Android-only" in result.output
        assert not backend.build_calls

    def test_unknown_abi_rejected_by_click(self, runner, tmp_path, monkeypatch):
        import kivyforge.cli.build as build_mod

        backend = _FakeBackend()
        _patch(monkeypatch, build_mod, backend, tmp_path)
        result = runner.invoke(build_cmd, ["-p", "android", "--abi", "armeabi_v7a"])
        assert result.exit_code != 0
        assert "armeabi_v7a" in result.output


class TestAndroidPackageOptions:
    def test_signing_overrides_reach_the_backend(self, runner, tmp_path, monkeypatch):
        import kivyforge.cli.package as package_mod

        backend = _FakeBackend()
        _patch(monkeypatch, package_mod, backend, tmp_path)
        result = runner.invoke(
            package_cmd,
            [
                "-p",
                "android",
                "--keystore",
                "release.keystore",
                "--key-alias",
                "upload",
                "--abi",
                "arm64_v8a",
            ],
        )
        assert result.exit_code == 0, result.output
        (call,) = backend.package_calls
        assert call["keystore"] == "release.keystore"
        assert call["key_alias"] == "upload"
        assert call["abi"] == "arm64_v8a"

    @pytest.mark.parametrize(
        "flag",
        [["--keystore", "k.jks"], ["--key-alias", "upload"], ["--abi", "x86_64"]],
    )
    def test_android_only_options_rejected_elsewhere(
        self, runner, tmp_path, monkeypatch, flag
    ):
        import kivyforge.cli.package as package_mod

        backend = _FakeBackend("macos")
        _patch(monkeypatch, package_mod, backend, tmp_path)
        result = runner.invoke(package_cmd, flag)
        assert result.exit_code != 0
        assert "Android-only" in result.output
        assert not backend.package_calls

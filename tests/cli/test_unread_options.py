"""Signing/export options are refused on platforms that would ignore them.

Before this, ``package -p windows --signing-identity X`` succeeded and signed
nothing with X: the flag the user believed took effect was dropped silently.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

import kivyforge.cli.build as build_mod
import kivyforge.cli.package as package_mod
from kivyforge.build_outcome import BuildOutcome


class _FakeBackend:
    package_formats = ("folder",)
    default_package_format = "folder"

    def __init__(self, name: str):
        self.name = name
        self.calls: list[dict] = []

    def build(self, project_root, **kwargs):
        self.calls.append(kwargs)
        return BuildOutcome(())

    def package(self, project_root, **kwargs):
        self.calls.append(kwargs)
        return BuildOutcome(())


def _invoke(monkeypatch, tmp_path, module, platform: str, args: list[str]):
    backend = _FakeBackend(platform)
    monkeypatch.setattr(
        module, "resolve_target", lambda cli_platform, verb: (backend, tmp_path)
    )
    result = CliRunner().invoke(getattr(module, module.__name__.rsplit(".")[-1]), args)
    return backend, result


_PACKAGE_CASES = [
    # (flag args, platforms that read it)
    (["--team-id", "ABCDE12345"], ("ios",)),
    (["--signing-identity", "Developer ID Application: X"], ("ios", "macos")),
    (["--export-method", "ad-hoc"], ("ios",)),
    (["--export-method", "app-store"], ("ios",)),  # explicit default still counts
    (["--notarize"], ("macos",)),
    (["--no-notarize"], ("macos",)),
    (["--notary-profile", "kf"], ("macos",)),
]
_BUILD_CASES = [
    (["--team-id", "ABCDE12345"], ("ios",)),
    (["--signing-identity", "Apple Development"], ("ios",)),
    (["--export-method", "development"], ("ios",)),
]
_PLATFORMS = ("android", "ios", "linux", "macos", "windows")


def _cases(cases):
    return [
        pytest.param(args, platform, platform in readers, id=f"{args[0]}-{platform}")
        for args, readers in cases
        for platform in _PLATFORMS
    ]


@pytest.mark.parametrize(("args", "platform", "accepted"), _cases(_PACKAGE_CASES))
def test_package(monkeypatch, tmp_path, args, platform, accepted):
    backend, result = _invoke(monkeypatch, tmp_path, package_mod, platform, args)
    if accepted:
        assert result.exit_code == 0, result.output
        assert len(backend.calls) == 1
    else:
        assert result.exit_code == 1
        assert f"{args[0]}" in result.output
        assert f"is not valid for {platform}." in result.output
        assert not backend.calls


@pytest.mark.parametrize(("args", "platform", "accepted"), _cases(_BUILD_CASES))
def test_build(monkeypatch, tmp_path, args, platform, accepted):
    backend, result = _invoke(monkeypatch, tmp_path, build_mod, platform, args)
    if accepted:
        assert result.exit_code == 0, result.output
    else:
        assert result.exit_code == 1
        assert f"is not valid for {platform}." in result.output
        assert not backend.calls


def test_defaults_are_not_mistaken_for_use(monkeypatch, tmp_path):
    for module in (build_mod, package_mod):
        _, result = _invoke(monkeypatch, tmp_path, module, "windows", [])
        assert result.exit_code == 0, result.output


def test_several_unread_options_are_named_together(monkeypatch, tmp_path):
    _, result = _invoke(
        monkeypatch,
        tmp_path,
        package_mod,
        "linux",
        ["--team-id", "T", "--signing-identity", "S"],
    )
    assert result.exit_code == 1
    assert (
        "--team-id (ios only), --signing-identity (ios/macos only) are not valid "
        "for linux." in result.output
    )

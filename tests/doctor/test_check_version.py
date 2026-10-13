"""doctor's Version check: what a build will carry, without running pip."""

from __future__ import annotations

from kivyforge import versioning
from kivyforge.config.loader import load_config_from_text
from kivyforge.doctor.checks_common import check_version
from kivyforge.doctor.result import Status

BASE = '[project]\nname = "demo"\n{version}\n[tool.kivy]\napp_dir = "src"\n'
AUTO = """
[tool.kivy.android]
schema_version = 1
package = "org.example.demo"
version_code = "auto"
[tool.kivy.android.python]
version = "3.14.6"
"""


def config(version: str, extra: str = ""):
    return load_config_from_text(
        BASE.format(version=version) + extra, require_ios=False
    )


def test_static_shows_the_normalized_value():
    result = check_version(config('version = "v1.2"'))
    assert (result.status, result.detail) == (Status.PASS, "1.2")


def test_dynamic_names_the_backend_and_never_runs_pip(monkeypatch):
    def no_pip(*a, **k):
        raise AssertionError("doctor must not run pip")

    monkeypatch.setattr(versioning, "_run", no_pip)
    result = check_version(config('dynamic = ["version"]'))
    assert result.status is Status.PASS
    assert "setuptools.build_meta:__legacy__" in result.detail
    assert "network" in result.detail
    assert result.hint == ""


def test_dynamic_with_android_auto_says_the_code_waits_too():
    result = check_version(config('dynamic = ["version"]', AUTO))
    assert result.status is Status.PASS
    assert 'version_code = "auto"' in result.hint

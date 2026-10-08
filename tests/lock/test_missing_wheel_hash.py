"""A wheel the index publishes no hash for is refused, with the ways out (#97).

kivyforge pins every wheel by SHA-256. An index serving PEP 658 metadata but no
``#sha256=`` fragment lets pip resolve the wheel without downloading it, so
there is no hash to pin. The message has to say that, not "re-run with network
access", which is what it used to suggest.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kivyforge.lock.find_links import missing_wheel_hash_message
from kivyforge.lock.wheelruntime.builder import (
    WheelRuntimeBuildError,
    _locked_wheel_from_resolved,
)


def test_the_message_names_the_wheel_its_url_and_both_remedies():
    message = missing_wheel_hash_message(
        "pillow-12.3.0-cp314-cp314-android_24_arm64_v8a.whl",
        "https://wheels.example/pillow.whl",
        platform="android",
    )
    assert message.startswith("could not determine SHA-256 for wheel 'pillow-")
    assert "https://wheels.example/pillow.whl" in message
    assert "#sha256=" in message
    assert "[tool.kivy.android].find_links" in message
    assert "network access" not in message


def test_without_a_url_it_names_only_the_wheel():
    message = missing_wheel_hash_message("x-1-py3-none-any.whl", None, platform="ios")
    assert "'x-1-py3-none-any.whl'." in message


def test_the_wheel_runtime_builder_raises_it_for_its_platform(tmp_path):
    wheel = SimpleNamespace(
        filename="x-1-py3-none-any.whl",
        url="https://wheels.example/x.whl",
        sha256="",
        upload_time=None,
        size=None,
    )
    profile = SimpleNamespace(platform="linux")
    with pytest.raises(WheelRuntimeBuildError) as excinfo:
        _locked_wheel_from_resolved(profile, wheel, project_root=tmp_path)  # type: ignore[arg-type]
    assert "[tool.kivy.linux].find_links" in str(excinfo.value)

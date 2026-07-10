"""Fakes for doctor checks: a configurable Probe and a project config."""

from __future__ import annotations

import textwrap

import pytest

from kivyforge.config import load_config_from_text

from .probe_fakes import FakeProbe

__all__ = ["FakeProbe", "fake_probe", "config"]


@pytest.fixture
def fake_probe():
    return FakeProbe()


@pytest.fixture
def config():
    return load_config_from_text(
        textwrap.dedent(
            """
            [project]
            name = "myapp"
            version = "1.0.0"

            [tool.kivy]
            app_dir = "src"

            [tool.kivy.ios]
            schema_version = 1
            bundle_id = "org.example.myapp"
            deployment_target = "13.0"

            [tool.kivy.ios.python]
            version = "3.15.0"
            """
        ).strip()
    )

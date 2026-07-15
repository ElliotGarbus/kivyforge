"""Windows lock builder (hermetic; fake resolver + fake runtime provider)."""

from __future__ import annotations

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.platforms.windows.lock import WindowsBuildError, build_windows_lockfile

from .conftest import FakeRuntimeProvider, FakeWindowsResolver


def _config(text, tmp_path):
    return load_config_from_text(
        text, require_ios=False, require_windows=True, project_root=tmp_path
    )


class TestBuild:
    def test_happy_path(self, windows_pyproject, tmp_path, fake_windows_resolver):
        cfg = _config(windows_pyproject, tmp_path)
        lock = build_windows_lockfile(
            cfg,
            windows_pyproject,
            project_root=tmp_path,
            resolver=fake_windows_resolver,
            runtime_provider=FakeRuntimeProvider(),
        )
        names = {p.name for p in lock.packages}
        assert names == {"kivy", "kivy-deps-sdl2", "docutils"}
        assert lock.archs == ("amd64",)
        assert lock.platform == "windows"
        assert lock.python_runtime.version == "3.13.14"
        assert {a.arch for a in lock.python_runtime.artifacts} == {"amd64"}
        assert lock.python_runtime.floor is None
        assert lock.pyproject_sha256

    def test_single_win_amd64_variant(self, windows_pyproject, tmp_path):
        cfg = _config(windows_pyproject, tmp_path)
        resolver = FakeWindowsResolver()
        build_windows_lockfile(
            cfg,
            windows_pyproject,
            project_root=tmp_path,
            resolver=resolver,
            runtime_provider=FakeRuntimeProvider(),
        )
        assert resolver.calls[0]["request_tags"] == ("win_amd64",)
        assert len(resolver.calls[0]["variants"]) == 1

    def test_kivy_deps_are_ordinary_wheels(self, windows_pyproject, tmp_path):
        # kivy_deps.sdl2 flows through [[packages]] like any other compiled wheel.
        cfg = _config(windows_pyproject, tmp_path)
        lock = build_windows_lockfile(
            cfg,
            windows_pyproject,
            project_root=tmp_path,
            resolver=FakeWindowsResolver(),
            runtime_provider=FakeRuntimeProvider(),
        )
        sdl2 = next(p for p in lock.packages if p.name == "kivy-deps-sdl2")
        assert sdl2.version == "0.7.0"
        assert any(w.name.endswith("win_amd64.whl") for w in sdl2.wheels)

    def test_missing_wheel_fails(self, windows_pyproject, tmp_path):
        cfg = _config(windows_pyproject, tmp_path)
        with pytest.raises(WindowsBuildError, match="no win_amd64 wheel"):
            build_windows_lockfile(
                cfg,
                windows_pyproject,
                project_root=tmp_path,
                resolver=FakeWindowsResolver(drop_wheel=True),
                runtime_provider=FakeRuntimeProvider(),
            )

    def test_exclude_prunes(self, tmp_path):
        text = (
            "[project]\nname='a'\nversion='1'\nrequires-python='>=3.13'\n"
            "dependencies=['kivy']\n"
            "[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.windows]\nschema_version=1\napp_id='Example.A'\n"
            "exclude=['docutils']\n"
            "[tool.kivy.windows.python]\nversion='3.13.14'\n"
        )
        cfg = _config(text, tmp_path)
        lock = build_windows_lockfile(
            cfg,
            text,
            project_root=tmp_path,
            resolver=FakeWindowsResolver(),
            runtime_provider=FakeRuntimeProvider(),
        )
        assert "docutils" not in {p.name for p in lock.packages}

    def test_no_windows_table(self, tmp_path):
        text = (
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            "[tool.kivy.ios.python]\nversion='3.15.0'\n"
        )
        cfg = load_config_from_text(text, project_root=tmp_path)
        with pytest.raises(WindowsBuildError, match="no \\[tool.kivy.windows\\]"):
            build_windows_lockfile(cfg, text, project_root=tmp_path)

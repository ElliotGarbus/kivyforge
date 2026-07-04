"""macOS lock builder (hermetic; fake resolver + fake runtime provider)."""

from __future__ import annotations

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.lock.macos.builder import MacosBuildError, build_macos_lockfile

from .conftest import FakeMacosResolver, FakeRuntimeProvider


def _config(text, tmp_path):
    return load_config_from_text(
        text, require_ios=False, require_macos=True, project_root=tmp_path
    )


class TestBuild:
    def test_happy_path(self, macos_pyproject, tmp_path, fake_macos_resolver):
        cfg = _config(macos_pyproject, tmp_path)
        lock = build_macos_lockfile(
            cfg,
            macos_pyproject,
            project_root=tmp_path,
            resolver=fake_macos_resolver,
            runtime_provider=FakeRuntimeProvider(floor="11.0"),
        )
        names = {p.name for p in lock.packages}
        assert names == {"kivy", "more-itertools"}
        assert lock.archs == ("arm64", "x86_64")
        assert lock.python_runtime.version == "3.15.0"
        assert {a.arch for a in lock.python_runtime.artifacts} == {"arm64", "x86_64"}
        assert lock.pyproject_sha256

    def test_resolver_gets_arch_and_floor(self, macos_pyproject, tmp_path):
        cfg = _config(macos_pyproject, tmp_path)
        resolver = FakeMacosResolver()
        build_macos_lockfile(
            cfg,
            macos_pyproject,
            project_root=tmp_path,
            resolver=resolver,
            runtime_provider=FakeRuntimeProvider(),
        )
        call = resolver.calls[0]
        assert call["archs"] == ("arm64", "x86_64")
        assert call["floor"] == "11.0"  # DEFAULT_MACOS_FLOOR

    def test_minimum_system_version_drives_floor(self, tmp_path):
        text = (
            "[project]\nname='a'\nversion='1'\nrequires-python='>=3.15'\n"
            "dependencies=['kivy']\n"
            "[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.macos]\nschema_version=1\nbundle_id='o.x.a'\n"
            'minimum_system_version="12.0"\n'
            "[tool.kivy.macos.python]\nversion='3.15.0'\n"
        )
        cfg = _config(text, tmp_path)
        resolver = FakeMacosResolver()
        build_macos_lockfile(
            cfg,
            text,
            project_root=tmp_path,
            resolver=resolver,
            runtime_provider=FakeRuntimeProvider(),
        )
        assert resolver.calls[0]["floor"] == "12.0"

    def test_universal2_covers_both(self, macos_pyproject, tmp_path):
        cfg = _config(macos_pyproject, tmp_path)
        lock = build_macos_lockfile(
            cfg,
            macos_pyproject,
            project_root=tmp_path,
            resolver=FakeMacosResolver(universal2=True),
            runtime_provider=FakeRuntimeProvider(),
        )
        kivy = next(p for p in lock.packages if p.name == "kivy")
        assert len(kivy.wheels) == 1
        assert "universal2" in kivy.wheels[0].name

    def test_missing_arch_fails(self, macos_pyproject, tmp_path):
        cfg = _config(macos_pyproject, tmp_path)
        with pytest.raises(MacosBuildError, match="missing macOS wheel"):
            build_macos_lockfile(
                cfg,
                macos_pyproject,
                project_root=tmp_path,
                resolver=FakeMacosResolver(drop_arch="x86_64"),
                runtime_provider=FakeRuntimeProvider(),
            )

    def test_thin_arm64_only(self, tmp_path):
        text = (
            "[project]\nname='a'\nversion='1'\nrequires-python='>=3.15'\n"
            "dependencies=['kivy']\n"
            "[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.macos]\nschema_version=1\nbundle_id='o.x.a'\n"
            "archs=['arm64']\n"
            "[tool.kivy.macos.python]\nversion='3.15.0'\n"
        )
        cfg = _config(text, tmp_path)
        lock = build_macos_lockfile(
            cfg,
            text,
            project_root=tmp_path,
            resolver=FakeMacosResolver(),
            runtime_provider=FakeRuntimeProvider(),
        )
        assert lock.archs == ("arm64",)
        assert {a.arch for a in lock.python_runtime.artifacts} == {"arm64"}

    def test_minimum_below_runtime_floor_fails(self, tmp_path):
        text = (
            "[project]\nname='a'\nversion='1'\nrequires-python='>=3.15'\n"
            "dependencies=['kivy']\n"
            "[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.macos]\nschema_version=1\nbundle_id='o.x.a'\n"
            'minimum_system_version="10.9"\n'
            "[tool.kivy.macos.python]\nversion='3.15.0'\n"
        )
        cfg = _config(text, tmp_path)
        with pytest.raises(MacosBuildError, match="below the macOS"):
            build_macos_lockfile(
                cfg,
                text,
                project_root=tmp_path,
                resolver=FakeMacosResolver(),
                runtime_provider=FakeRuntimeProvider(floor="11.0"),
            )

    def test_exclude_prunes_transitive(self, tmp_path):
        text = (
            "[project]\nname='a'\nversion='1'\nrequires-python='>=3.15'\n"
            "dependencies=['kivy']\n"
            "[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.macos]\nschema_version=1\nbundle_id='o.x.a'\n"
            "exclude=['more-itertools']\n"
            "[tool.kivy.macos.python]\nversion='3.15.0'\n"
        )
        cfg = _config(text, tmp_path)
        lock = build_macos_lockfile(
            cfg,
            text,
            project_root=tmp_path,
            resolver=FakeMacosResolver(),
            runtime_provider=FakeRuntimeProvider(),
        )
        assert {p.name for p in lock.packages} == {"kivy"}

    def test_no_macos_table(self, tmp_path):
        text = (
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            "[tool.kivy.ios.python]\nversion='3.15.0'\n"
        )
        cfg = load_config_from_text(text, project_root=tmp_path)
        with pytest.raises(MacosBuildError, match="no \\[tool.kivy.macos\\]"):
            build_macos_lockfile(cfg, text, project_root=tmp_path)

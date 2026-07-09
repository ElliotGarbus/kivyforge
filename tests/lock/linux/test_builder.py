"""Linux lock builder (hermetic; fake resolver + fake runtime provider)."""

from __future__ import annotations

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.lock.linux import (
    LinuxBuildError,
    build_linux_lockfile,
    effective_glibc_floor,
)

from .conftest import FakeLinuxResolver, FakeRuntimeProvider


def _config(text, tmp_path):
    return load_config_from_text(
        text, require_ios=False, require_linux=True, project_root=tmp_path
    )


class TestBuild:
    def test_happy_path(self, linux_pyproject, tmp_path, fake_linux_resolver):
        cfg = _config(linux_pyproject, tmp_path)
        lock = build_linux_lockfile(
            cfg,
            linux_pyproject,
            project_root=tmp_path,
            resolver=fake_linux_resolver,
            runtime_provider=FakeRuntimeProvider(floor="2.17"),
        )
        names = {p.name for p in lock.packages}
        assert names == {"kivy", "more-itertools"}
        assert lock.archs == ("x86_64",)
        assert lock.platform == "linux"
        assert lock.python_runtime.version == "3.15.0"
        assert {a.arch for a in lock.python_runtime.artifacts} == {"x86_64"}
        assert lock.python_runtime.floor == "2.17"
        assert lock.pyproject_sha256

    def test_resolver_gets_full_tag_ladder(self, linux_pyproject, tmp_path):
        cfg = _config(linux_pyproject, tmp_path)
        resolver = FakeLinuxResolver()
        build_linux_lockfile(
            cfg,
            linux_pyproject,
            project_root=tmp_path,
            resolver=resolver,
            runtime_provider=FakeRuntimeProvider(),
        )
        request_tags = resolver.calls[0]["request_tags"]
        # Single variant carries the whole ladder in one request.
        assert "manylinux_2_17_x86_64" in request_tags
        assert "manylinux2014_x86_64" in request_tags
        assert "manylinux1_x86_64" in request_tags
        assert len(resolver.calls[0]["variants"]) == 1

    def test_glibc_floor_drives_ladder(self, tmp_path):
        text = (
            "[project]\nname='a'\nversion='1'\nrequires-python='>=3.15'\n"
            "dependencies=['kivy']\n"
            "[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.linux]\nschema_version=1\napp_id='o.x.a'\n"
            'glibc_floor="2.28"\n'
            "[tool.kivy.linux.python]\nversion='3.15.0'\n"
        )
        cfg = _config(text, tmp_path)
        resolver = FakeLinuxResolver()
        build_linux_lockfile(
            cfg,
            text,
            project_root=tmp_path,
            resolver=resolver,
            runtime_provider=FakeRuntimeProvider(),
        )
        request_tags = resolver.calls[0]["request_tags"]
        assert "manylinux_2_28_x86_64" in request_tags

    def test_effective_floor_derives_from_wheels(self, linux_pyproject, tmp_path):
        cfg = _config(linux_pyproject, tmp_path)
        lock = build_linux_lockfile(
            cfg,
            linux_pyproject,
            project_root=tmp_path,
            resolver=FakeLinuxResolver(),
            runtime_provider=FakeRuntimeProvider(floor="2.17"),
        )
        # kivy's compound manylinux_2_17.manylinux2014 wheel is level 2.17.
        assert effective_glibc_floor(lock) == "2.17"

    def test_missing_wheel_fails(self, linux_pyproject, tmp_path):
        cfg = _config(linux_pyproject, tmp_path)
        with pytest.raises(LinuxBuildError, match="no manylinux wheel"):
            build_linux_lockfile(
                cfg,
                linux_pyproject,
                project_root=tmp_path,
                resolver=FakeLinuxResolver(drop_wheel=True),
                runtime_provider=FakeRuntimeProvider(),
            )

    def test_floor_below_runtime_fails(self, tmp_path):
        text = (
            "[project]\nname='a'\nversion='1'\nrequires-python='>=3.15'\n"
            "dependencies=['kivy']\n"
            "[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.linux]\nschema_version=1\napp_id='o.x.a'\n"
            'glibc_floor="2.12"\n'
            "[tool.kivy.linux.python]\nversion='3.15.0'\n"
        )
        cfg = _config(text, tmp_path)
        with pytest.raises(LinuxBuildError, match="below the glibc"):
            build_linux_lockfile(
                cfg,
                text,
                project_root=tmp_path,
                resolver=FakeLinuxResolver(),
                runtime_provider=FakeRuntimeProvider(floor="2.17"),
            )

    def test_exclude_prunes_transitive(self, tmp_path):
        text = (
            "[project]\nname='a'\nversion='1'\nrequires-python='>=3.15'\n"
            "dependencies=['kivy']\n"
            "[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.linux]\nschema_version=1\napp_id='o.x.a'\n"
            "exclude=['more-itertools']\n"
            "[tool.kivy.linux.python]\nversion='3.15.0'\n"
        )
        cfg = _config(text, tmp_path)
        lock = build_linux_lockfile(
            cfg,
            text,
            project_root=tmp_path,
            resolver=FakeLinuxResolver(),
            runtime_provider=FakeRuntimeProvider(),
        )
        assert {p.name for p in lock.packages} == {"kivy"}

    def test_no_linux_table(self, tmp_path):
        text = (
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            "[tool.kivy.ios.python]\nversion='3.15.0'\n"
        )
        cfg = load_config_from_text(text, project_root=tmp_path)
        with pytest.raises(LinuxBuildError, match="no \\[tool.kivy.linux\\]"):
            build_linux_lockfile(cfg, text, project_root=tmp_path)

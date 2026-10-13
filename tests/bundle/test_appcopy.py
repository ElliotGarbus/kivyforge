"""Every backend's app_dir copy leaves out ``*.egg-info`` (APP_COPY_EXCLUDES).

One test over all five backends, driving each one's real copy function, so a
backend that grows a new copy path without the shared excludes fails here
rather than shipping a developer's install metadata inside an app.

iOS is covered for release builds only: a dev build symlinks app_dir and Xcode
copies the folder as-is, which no ignore list reaches (the same is already true
of ``__pycache__``).
"""

from __future__ import annotations

import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from kivyforge.config import load_config_from_text
from kivyforge.config.model import Config
from kivyforge.platforms.android.stage import bundle as android_bundle
from kivyforge.platforms.ios.staging import create_staging
from kivyforge.platforms.linux import bundle as linux_bundle
from kivyforge.platforms.macos import bundle as macos_bundle
from kivyforge.platforms.windows import bundle as windows_bundle

CONFIG = textwrap.dedent(
    """
    [project]
    name = "myapp"
    version = "1.2.3"

    [tool.kivy]
    app_dir = "src"
    entry_point = "main"

    [tool.kivy.ios]
    schema_version = 1
    bundle_id = "org.example.myapp"
    deployment_target = "13.0"

    [tool.kivy.ios.python]
    version = "3.15.0"

    [tool.kivy.ios.python.build_settings]
    byte_compile = false

    [tool.kivy.ios.signing]
    team_id = "ABCDE12345"
    auto_signing = true
    """
).strip()


def _desktop(module) -> Callable[[Config, Path, Path], Path]:
    def copy(config: Config, project_root: Path, dest: Path) -> Path:
        module._copy_app_sources(config, project_root, dest)
        return dest

    return copy


def _android(config: Config, project_root: Path, dest: Path) -> Path:
    android_bundle._copy_app(
        project_root / config.kivy.app_dir,
        dest,
        entry_point=config.kivy.entry_point,
        service_entry_points={},
    )
    return dest


def _ios(config: Config, project_root: Path, dest: Path) -> Path:
    layout = create_staging(config, project_root, release=True, python_version="3.15.0")
    return layout.app


@pytest.mark.parametrize(
    "copy_app",
    [
        _desktop(macos_bundle),
        _desktop(linux_bundle),
        _desktop(windows_bundle),
        _android,
        _ios,
    ],
    ids=["macos", "linux", "windows", "android", "ios-release"],
)
def test_app_copy_excludes_egg_info(tmp_path, copy_app):
    project_root = tmp_path / "proj"
    src = project_root / "src"
    # What `pip install -e .` leaves in a src layout, next to the app package.
    (src / "myapp.egg-info").mkdir(parents=True)
    (src / "myapp.egg-info" / "PKG-INFO").write_text("Version: 0.0.1\n")
    (src / "main.py").write_text("print('hi')\n")
    (src / "myapp").mkdir()
    (src / "myapp" / "__init__.py").write_text("")
    config = load_config_from_text(CONFIG)

    copied = copy_app(config, project_root, tmp_path / "out" / "app")

    assert (copied / "main.py").is_file()
    assert (copied / "myapp" / "__init__.py").is_file()
    assert not (copied / "myapp.egg-info").exists()

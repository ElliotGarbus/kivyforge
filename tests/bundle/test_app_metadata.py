"""Every backend's app_dir copy keeps the app's package metadata (#122).

An app can read its own metadata at runtime through ``importlib.metadata``:
its version, and the entry points it declares in ``[project.entry-points]``,
which is how plugin-based apps find their plugins. A packaged app is not
installed, so the only metadata it has is the ``<name>.egg-info`` that
setuptools writes into a src layout (``pip install -e .``, ``uv sync``, or
kivyforge's own lookup of a dynamic version). #115 excluded that folder from
app copies, and plugin discovery broke on the device; it was reverted.

This drives each backend's real copy function and then asks
``importlib.metadata``, searching only the copied app, for the distribution and
its entry point -- the call that failed in #122. iOS is covered for release
builds; a dev build symlinks app_dir, so the folder is there as is.
"""

from __future__ import annotations

import importlib.metadata
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
def test_app_copy_keeps_the_package_metadata(tmp_path, copy_app):
    project_root = tmp_path / "proj"
    src = project_root / "src"
    # What setuptools leaves in a src layout, next to the app package.
    info = src / "myapp.egg-info"
    info.mkdir(parents=True)
    (info / "PKG-INFO").write_text(
        "Metadata-Version: 2.1\nName: myapp\nVersion: 1.2.3\n"
    )
    (info / "entry_points.txt").write_text(
        "[myapp.boardstyle]\nchecked = myapp.boards:Checked\n"
    )
    (src / "main.py").write_text("print('hi')\n")
    (src / "myapp").mkdir()
    (src / "myapp" / "__init__.py").write_text("")
    config = load_config_from_text(CONFIG)

    copied = copy_app(config, project_root, tmp_path / "out" / "app")

    found = [
        d
        for d in importlib.metadata.distributions(path=[str(copied)])
        if d.metadata["Name"] == "myapp"
    ]
    assert len(found) == 1, "the app's metadata did not reach the app"
    assert found[0].version == "1.2.3"
    plugins = found[0].entry_points.select(group="myapp.boardstyle")
    assert [(e.name, e.value) for e in plugins] == [("checked", "myapp.boards:Checked")]

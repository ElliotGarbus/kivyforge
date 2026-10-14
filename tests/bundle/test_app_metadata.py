"""Every bundle's copy of app_dir carries the app's own package metadata (#122).

An app reads its own metadata at runtime through ``importlib.metadata``: its
version, and the entry points it declares, which is how plugin-based apps find
their plugins. A packaged app is not installed, so before
docs/design/dev/package-metadata-proposal.md the only metadata it had was the
``<name>.egg-info`` a setuptools dev install leaves in a src layout: #115
excluded that folder and plugin discovery broke on the device (#122), #123
reverted it, and its regression test asserted the folder ships.

That test is replaced here (Q6) by the behaviour it was guarding: each
platform's real copy path leaves the app's metadata reachable -- now the
generated ``.dist-info``, from ``[project]`` -- with or without a development
``egg-info``, and removes the development metadata that would otherwise compete
with it (2.2). The user's ``app_dir`` is never touched. iOS's copy is Xcode's,
so its path here is the Build Python script's metadata step, run by ``bash``
over a copy made as Xcode makes it, from the folder ``kivyforge build`` stages.

The generated files themselves are ``test_app_metadata_files.py``.
"""

from __future__ import annotations

import importlib.metadata as md
import os
import shutil
import subprocess
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest
from pbxproj import XcodeProject

from kivyforge.bundle import app_metadata
from kivyforge.config import load_config_from_text
from kivyforge.config.model import Config, ResolvedVersion
from kivyforge.config.version import with_version
from kivyforge.platforms.android.stage import bundle as android_bundle
from kivyforge.platforms.ios import buildsettings
from kivyforge.platforms.ios.staging import create_staging
from kivyforge.platforms.linux import bundle as linux_bundle
from kivyforge.platforms.macos import bundle as macos_bundle
from kivyforge.platforms.windows import bundle as windows_bundle

CONFIG = textwrap.dedent(
    """
    [project]
    name = "MyApp"
    version = "1.2.3"
    {dynamic}

    [project.entry-points."myapp.boardstyle"]
    checked = "myapp.boards:Checked"

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
)
GENERATED = "myapp-1.2.3.dist-info"
VENDORED = "vendored_lib-4.0.dist-info"


def config_for(*, dynamic: str = "") -> Config:
    return load_config_from_text(CONFIG.format(dynamic=dynamic))


# --------------------------------------------------------------------------- #
# The copy paths
# --------------------------------------------------------------------------- #

CopyApp = Callable[[Config, Path, Path], Path]


def _desktop(module) -> CopyApp:
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
        app_metadata=app_metadata.for_build(config),
    )
    return dest


def _ios(*, release: bool) -> CopyApp:
    def copy(config: Config, project_root: Path, dest: Path) -> Path:
        """Stage as ``kivyforge build`` does, copy as Xcode does, run the step."""
        layout = create_staging(
            config,
            project_root,
            release=release,
            python_version="3.15.0" if release else None,
        )
        # Copy Bundle Resources copies the folder reference's contents: a real
        # directory in the bundle, also when <app>-ios/app is a link (F6).
        shutil.copytree(layout.app, dest)
        _run_metadata_step(bundle=dest.parent, project_dir=layout.root)
        return dest

    return copy


def _run_metadata_step(*, bundle: Path, project_dir: Path) -> None:
    proc = subprocess.run(
        ["bash", "-c", "set -e\n" + buildsettings.APP_METADATA_SCRIPT],
        env={
            "PATH": os.environ["PATH"],
            "CODESIGNING_FOLDER_PATH": str(bundle),
            "PROJECT_DIR": str(project_dir),
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"metadata step failed: {proc.stdout}{proc.stderr}")


IOS = [pytest.mark.requires_posix, pytest.mark.requires_symlinks]
COPY_PATHS = [
    pytest.param(_desktop(macos_bundle), id="macos"),
    pytest.param(_desktop(linux_bundle), id="linux"),
    pytest.param(_desktop(windows_bundle), id="windows"),
    pytest.param(_android, id="android"),
    pytest.param(_ios(release=False), id="ios-debug", marks=IOS),
    pytest.param(_ios(release=True), id="ios-release", marks=IOS),
]


# --------------------------------------------------------------------------- #
# The app_dir
# --------------------------------------------------------------------------- #


def app_dir(project_root: Path) -> Path:
    src = project_root / "src"
    (src / "myapp").mkdir(parents=True)
    (src / "myapp" / "__init__.py").write_text("", encoding="utf-8")
    (src / "myapp" / "boards.py").write_text("class Checked: ...\n", encoding="utf-8")
    (src / "main.py").write_text("print('hi')\n", encoding="utf-8")
    return src


def egg_info(src: Path, folder: str, *, name: str, version: str, plugin: str):
    """A development egg-info, as setuptools writes one."""
    info = src / folder
    info.mkdir(parents=True)
    (info / "PKG-INFO").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )
    (info / "entry_points.txt").write_text(
        f"[myapp.boardstyle]\n{plugin} = myapp.boards:Checked\n", encoding="utf-8"
    )
    (info / "SOURCES.txt").write_text(f"{src}/main.py\n", encoding="utf-8")


def dist_info(src: Path, folder: str, *, name: str, version: str) -> None:
    info = src / folder
    info.mkdir()
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )


def plant_everything(src: Path) -> None:
    """Every kind of leftover 2.2 names, and what it must leave alone."""
    egg_info(src, "MyApp.egg-info", name="MyApp", version="0.0.1", plugin="stale")
    # A renamed project's leftover: entry_points() would still collect it.
    egg_info(src, "oldname.egg-info", name="oldname", version="0.1", plugin="old")
    # distutils wrote PKG-INFO itself as a file named <name>.egg-info.
    (src / "legacy.egg-info").write_text(
        "Metadata-Version: 1.0\nName: legacy\nVersion: 0.1\n", encoding="utf-8"
    )
    dist_info(src, "myapp-0.9.dist-info", name="MyApp", version="0.9")
    # The same name, spelled as Python still matches it.
    dist_info(src, "MYAPP-0.8.dist-info", name="MyApp", version="0.8")
    # pip install --target src vendored_lib: its metadata is the library's.
    dist_info(src, VENDORED, name="vendored-lib", version="4.0")
    (src / "vendored_lib").mkdir()
    (src / "vendored_lib" / "__init__.py").write_text("", encoding="utf-8")
    # Deeper than setuptools writes: not the app's to remove.
    egg_info(src / "myapp", "inner.egg-info", name="inner", version="1", plugin="in")


def snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None
        for p in sorted(root.rglob("*"))
    }


def apps_named(copied: Path, name: str) -> list[md.Distribution]:
    return [
        d
        for d in md.distributions(path=[str(copied)])
        if app_metadata.normalize_name(d.metadata["Name"] or "") == name
    ]


def assert_reachable(copied: Path) -> None:
    """What #122 broke: the app finds itself, its version and its plugins."""
    (found,) = apps_named(copied, "myapp")
    assert found.version == "1.2.3"
    plugins = found.entry_points.select(group="myapp.boardstyle")
    assert [(e.name, e.value) for e in plugins] == [("checked", "myapp.boards:Checked")]


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("copy_app", COPY_PATHS)
def test_no_egg_info_still_reachable(tmp_path, copy_app):
    """A hatch, flit, pdm or poetry project, a flat layout, a fresh checkout."""
    project_root = tmp_path / "proj"
    app_dir(project_root)

    copied = copy_app(config_for(), project_root, tmp_path / "out" / "app")

    assert_reachable(copied)
    assert (copied / GENERATED).is_dir()


@pytest.mark.parametrize("copy_app", COPY_PATHS)
def test_dev_install_egg_info_still_reachable(tmp_path, copy_app):
    """A src layout after ``pip install -e .``: #122's own case."""
    project_root = tmp_path / "proj"
    src = app_dir(project_root)
    egg_info(src, "MyApp.egg-info", name="MyApp", version="1.2.3", plugin="checked")

    copied = copy_app(config_for(), project_root, tmp_path / "out" / "app")

    assert_reachable(copied)


@pytest.mark.parametrize("copy_app", COPY_PATHS)
def test_development_metadata_is_removed_from_the_copy_only(tmp_path, copy_app):
    project_root = tmp_path / "proj"
    src = app_dir(project_root)
    plant_everything(src)
    before = snapshot(src)

    copied = copy_app(config_for(), project_root, tmp_path / "out" / "app")

    top = sorted(
        p.name for p in copied.iterdir() if p.name.endswith(("-info", ".egg-info"))
    )
    assert top == [GENERATED, VENDORED]
    assert (copied / "myapp" / "inner.egg-info" / "PKG-INFO").is_file()
    assert_reachable(copied)
    plugins = [
        e.name
        for d in md.distributions(path=[str(copied)])
        for e in d.entry_points
        if e.group == "myapp.boardstyle"
    ]
    assert plugins == ["checked"]  # nothing stale, nothing from oldname
    assert snapshot(src) == before


@pytest.mark.parametrize("copy_app", COPY_PATHS)
def test_dynamic_entry_points_leave_the_copy_alone(tmp_path, copy_app):
    """D2: only the backend knows them, so the dev egg-info stays the source."""
    project_root = tmp_path / "proj"
    src = app_dir(project_root)
    egg_info(src, "MyApp.egg-info", name="MyApp", version="1.2.3", plugin="checked")

    config = config_for(dynamic='dynamic = ["entry-points"]')
    copied = copy_app(config, project_root, tmp_path / "out" / "app")

    assert not (copied / GENERATED).exists()
    assert (copied / "MyApp.egg-info").is_dir()
    assert_reachable(copied)


# --------------------------------------------------------------------------- #
# iOS: staging and the Build Python script
# --------------------------------------------------------------------------- #


@pytest.mark.requires_symlinks
@pytest.mark.parametrize("release", [False, True], ids=["debug", "release"])
def test_ios_build_stages_the_folder(tmp_path, release):
    project_root = tmp_path / "proj"
    src = app_dir(project_root)
    egg_info(src, "MyApp.egg-info", name="MyApp", version="0.0.1", plugin="stale")

    layout = create_staging(
        config_for(),
        project_root,
        release=release,
        python_version="3.15.0" if release else None,
    )

    staged = layout.root / "_kivyforge_meta"
    assert [p.name for p in staged.iterdir()] == [GENERATED]
    assert (staged / GENERATED / "top_level.txt").read_text() == "main\nmyapp\n"
    # Nothing is written into app_dir, which a debug build's app/ links to.
    assert sorted(p.name for p in src.iterdir()) == [
        "MyApp.egg-info",
        "main.py",
        "myapp",
    ]


@pytest.mark.requires_symlinks
def test_ios_stages_nothing_for_dynamic_entry_points(tmp_path):
    project_root = tmp_path / "proj"
    app_dir(project_root)
    layout = create_staging(config_for(), project_root)
    assert (layout.root / "_kivyforge_meta").is_dir()

    create_staging(config_for(dynamic='dynamic = ["scripts"]'), project_root)

    assert not (layout.root / "_kivyforge_meta").exists()


@pytest.mark.requires_posix
@pytest.mark.requires_symlinks
def test_ios_script_refuses_a_linked_app_folder(tmp_path):
    """Never delete through a link: in a debug build it would reach app_dir."""
    project_root = tmp_path / "proj"
    src = app_dir(project_root)
    egg_info(src, "MyApp.egg-info", name="MyApp", version="0.0.1", plugin="stale")
    layout = create_staging(config_for(), project_root)
    bundle = tmp_path / "MyApp.app"
    bundle.mkdir()
    (bundle / "app").symlink_to(src)
    before = snapshot(src)

    with pytest.raises(RuntimeError, match="symlink"):
        _run_metadata_step(bundle=bundle, project_dir=layout.root)

    assert snapshot(src) == before


def test_ios_script_runs_the_metadata_step_last():
    script = buildsettings.BUILD_PYTHON_SCRIPT
    assert script.endswith(buildsettings.APP_METADATA_SCRIPT)
    assert script.index("install_python") < script.index("_kivyforge_meta")
    for needed in ('-L "$APP_BUNDLE_DIR"', "*.egg-info", "rsync -a"):
        assert needed in buildsettings.APP_METADATA_SCRIPT, needed


@pytest.mark.requires_symlinks
def test_regenerating_replaces_an_older_build_python_phase(tmp_path):
    """The phase is found by its exact text, so an older text must be known."""
    from kivyforge.platforms.ios.generator import XcodeProjectGenerator
    from kivyforge.platforms.ios.materialize import materialize_project

    project_root = tmp_path / "proj"
    app_dir(project_root)
    config = config_for()
    layout = materialize_project(config, project_root)
    pbxproj = layout.xcodeproj / "project.pbxproj"
    for previous in buildsettings.PREVIOUS_BUILD_PYTHON_SCRIPTS:
        project = XcodeProject.load(str(pbxproj))
        project.remove_run_script(buildsettings.BUILD_PYTHON_SCRIPT)
        project.add_run_script(previous, target_name=config.app_slug)
        project.save()

        XcodeProjectGenerator(config, layout).generate()

        project = XcodeProject.load(str(pbxproj))
        target = project.get_target_by_name(config.app_slug)
        assert target is not None
        scripts = [
            project.get_object(p).shellScript
            for p in target.buildPhases
            if project.get_object(p).isa == "PBXShellScriptBuildPhase"
        ]
        assert scripts == [buildsettings.BUILD_PYTHON_SCRIPT]


# --------------------------------------------------------------------------- #
# One version everywhere
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "version",
    [
        ResolvedVersion("1.2.3", source="static"),
        ResolvedVersion("1.2.4.dev1+gabc1234", source="backend"),
        ResolvedVersion("2.0rc1", source="override"),
    ],
    ids=lambda v: v.source,
)
def test_metadata_version_matches_every_artifact(tmp_path, version):
    from kivyforge.platforms.android.generate.project import write_app_build_gradle
    from kivyforge.platforms.ios.plist import build_info_plist as ios_plist
    from kivyforge.platforms.macos.plist import build_info_plist as macos_plist
    from kivyforge.platforms.windows.bundle import _resource_patch

    text = CONFIG.format(dynamic="") + textwrap.dedent(
        """
        [tool.kivy.macos]
        schema_version = 1
        bundle_id = "org.example.myapp"

        [tool.kivy.macos.python]
        version = "3.13.14"

        [tool.kivy.windows]
        schema_version = 1
        app_id = "Example.MyApp"

        [tool.kivy.windows.python]
        version = "3.13.14"

        [tool.kivy.android]
        schema_version = 1
        package = "org.example.myapp"

        [tool.kivy.android.python]
        version = "3.14.6"
        """
    )
    config = with_version(load_config_from_text(text), version)
    metadata = app_metadata.for_build(config)
    assert metadata is not None
    written = app_metadata.render(metadata, ["main"])["METADATA"].decode()
    assert f"\nVersion: {version.value}\n" in written

    assert (
        macos_plist(config, executable="x", icon_file=None)[
            "CFBundleShortVersionString"
        ]
        == version.value
    )
    assert ios_plist(config)["CFBundleShortVersionString"] == version.value
    assert _resource_patch(config, None).product_version_string == version.value
    write_app_build_gradle(
        tmp_path,
        config,
        config.android_required,
        python_version="3.14.6",
        runtime_root=tmp_path / "runtime",
        staged_libs=[],
    )
    gradle = (tmp_path / "app" / "build.gradle").read_text(encoding="utf-8")
    assert f"versionName '{version.value}'" in gradle

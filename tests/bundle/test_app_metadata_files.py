"""The ``.dist-info`` kivyforge writes for the app, and how Python reads it.

docs/design/dev/package-metadata-proposal.md, layer 1: the generator (2.1) and
the lookup contract -- ``importlib.metadata`` over the generated folder alone
finds the app by every spelling of its name, with its version, entry points and
modules (spike S0, F5). Where the folder goes in each bundle is
``test_app_metadata.py``.
"""

from __future__ import annotations

import importlib.metadata as md
import textwrap
from pathlib import Path

import pytest

from kivyforge.bundle import app_metadata
from kivyforge.bundle.app_metadata import AppMetadata, normalize_name
from kivyforge.config import load_config_from_text
from kivyforge.config.model import EntryPoint, ResolvedVersion
from kivyforge.config.version import with_version

PYPROJECT = textwrap.dedent(
    """
    [project]
    name = "Metaprobe.App"
    version = "1.2.3"

    [project.scripts]
    metaprobe-cli = "metaprobe_app.cli:main"

    [project.gui-scripts]
    metaprobe-gui = "metaprobe_app.cli:gui"

    [project.entry-points."metaprobe.plugins"]
    zeta = "metaprobe_app.plugins:Zeta"
    MyPlugin = "metaprobe_app.plugins:Mine"
    fancy = "metaprobe_app.extra:Fancy [fancy]"
    module-only = "metaprobe_app.loose"

    [project.entry-points.pytest11]
    probe = "metaprobe_app.pytest_plugin"

    [tool.kivy]
    app_dir = "src"
    """
)

ENTRY_POINTS_TXT = """\
[console_scripts]
metaprobe-cli = metaprobe_app.cli:main

[gui_scripts]
metaprobe-gui = metaprobe_app.cli:gui

[metaprobe.plugins]
MyPlugin = metaprobe_app.plugins:Mine
fancy = metaprobe_app.extra:Fancy [fancy]
module-only = metaprobe_app.loose
zeta = metaprobe_app.plugins:Zeta

[pytest11]
probe = metaprobe_app.pytest_plugin

"""


def config_of(text: str = PYPROJECT, version: ResolvedVersion | None = None):
    config = load_config_from_text(text, require_ios=False)
    return with_version(config, version) if version else config


def app_source(root: Path) -> Path:
    src = root / "src"
    (src / "metaprobe_app").mkdir(parents=True)
    (src / "metaprobe_app" / "__init__.py").write_text("", encoding="utf-8")
    (src / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (src / "helpers.py").write_text("", encoding="utf-8")
    (src / "assets").mkdir()  # no __init__.py: data, not a module
    (src / "assets" / "icon.png").write_bytes(b"\x89PNG")
    (src / "loose").mkdir()  # a namespace-ish folder, not listed either
    (src / "loose" / "thing.py").write_text("", encoding="utf-8")
    (src / "not-a-module.py").write_text("", encoding="utf-8")
    (src / "notes.txt").write_text("", encoding="utf-8")
    return src


def generate(tmp_path: Path, config=None) -> Path:
    config = config or config_of()
    metadata = app_metadata.for_build(config)
    assert metadata is not None
    src = app_source(tmp_path / "proj")
    top_level = app_metadata.top_level_names(src, metadata.main_module)
    out = tmp_path / "out"
    out.mkdir()
    return app_metadata.write_dist_info(metadata, out, top_level)


class TestGenerator:
    def test_folder_name_is_normalized_name_as_written(self, tmp_path):
        folder = generate(tmp_path)
        assert folder.name == "metaprobe_app-1.2.3.dist-info"
        assert (folder / "METADATA").read_bytes() == (
            b"Metadata-Version: 2.1\nName: Metaprobe.App\nVersion: 1.2.3\n"
        )

    @pytest.mark.parametrize(
        ("name", "normal"),
        [("Meta.Probe_App", "meta_probe_app"), ("A--b__C..d", "a_b_c_d")],
    )
    def test_normalize(self, name, normal):
        assert normalize_name(name) == normal

    def test_the_version_is_the_build_version(self, tmp_path):
        version = ResolvedVersion("1.2.4.dev3+g1a2b", source="backend")
        folder = generate(tmp_path, config_of(version=version))
        assert folder.name == "metaprobe_app-1.2.4.dev3+g1a2b.dist-info"
        assert b"Version: 1.2.4.dev3+g1a2b\n" in (folder / "METADATA").read_bytes()

    def test_entry_points_txt(self, tmp_path):
        """scripts and gui-scripts as their groups, dotted groups, values as
        written (extras, module only), and case kept: configparser would
        lowercase ``MyPlugin``."""
        folder = generate(tmp_path)
        assert (folder / "entry_points.txt").read_bytes() == ENTRY_POINTS_TXT.encode()

    def test_no_entry_points_txt_without_entry_points(self, tmp_path):
        config = config_of(
            '[project]\nname = "plain"\nversion = "1"\n[tool.kivy]\napp_dir = "src"\n'
        )
        folder = generate(tmp_path, config)
        assert sorted(p.name for p in folder.iterdir()) == [
            "INSTALLER",
            "METADATA",
            "top_level.txt",
        ]

    def test_installer(self, tmp_path):
        assert (generate(tmp_path) / "INSTALLER").read_bytes() == b"kivyforge\n"

    def test_non_ascii_is_utf8(self, tmp_path):
        metadata = AppMetadata(
            name="demo",
            version="1.0",
            entry_points=(EntryPoint("démo.plugins", "ñame", "démo:Ñ"),),
            main_module="main",
        )
        files = app_metadata.render(metadata, ["main"])
        assert files["entry_points.txt"] == "[démo.plugins]\nñame = démo:Ñ\n\n".encode()

    def test_top_level(self, tmp_path):
        """Modules and packages, not asset or ``__init__``-less folders (Q1)."""
        folder = generate(tmp_path)
        assert (folder / "top_level.txt").read_bytes() == (
            b"helpers\nmain\nmetaprobe_app\n"
        )

    def test_top_level_always_has_the_main_module(self, tmp_path):
        src = tmp_path / "src"
        (src / "pkg").mkdir(parents=True)
        (src / "pkg" / "start.py").write_text("", encoding="utf-8")
        assert app_metadata.top_level_names(src, "pkg.start") == ["pkg"]

    def test_byte_identical_across_runs(self, tmp_path):
        first, second = generate(tmp_path / "a"), generate(tmp_path / "b")
        names = sorted(p.name for p in first.iterdir())
        assert names == sorted(p.name for p in second.iterdir())
        for name in names:
            assert (first / name).read_bytes() == (second / name).read_bytes(), name

    def test_declaration_order_does_not_matter(self):
        metadata = app_metadata.for_build(config_of())
        assert metadata is not None
        shuffled = AppMetadata(
            name=metadata.name,
            version=metadata.version,
            entry_points=tuple(reversed(metadata.entry_points)),
            main_module=metadata.main_module,
        )
        assert app_metadata.render(metadata, ["main"]) == app_metadata.render(
            shuffled, ["main"]
        )

    def test_dynamic_entry_points_generate_nothing(self):
        text = PYPROJECT.replace(
            'version = "1.2.3"', 'version = "1.2.3"\ndynamic = ["entry-points"]'
        )
        assert app_metadata.for_build(config_of(text)) is None


class TestLookup:
    """S0: METADATA plus entry_points.txt, no RECORD, is enough for Python."""

    @pytest.fixture
    def on_path(self, tmp_path, monkeypatch):
        folder = generate(tmp_path)
        monkeypatch.syspath_prepend(str(folder.parent))
        return folder

    @pytest.mark.parametrize(
        "alias", ["metaprobe-app", "metaprobe_app", "Metaprobe.App", "METAPROBE-APP"]
    )
    def test_found_by_every_spelling(self, on_path, alias):
        assert md.version(alias) == "1.2.3"
        assert md.metadata(alias)["Name"] == "Metaprobe.App"

    def test_entry_points(self, on_path):
        plugins = md.entry_points(group="metaprobe.plugins")
        assert {(e.name, e.value) for e in plugins} == {
            ("MyPlugin", "metaprobe_app.plugins:Mine"),
            ("fancy", "metaprobe_app.extra:Fancy [fancy]"),
            ("module-only", "metaprobe_app.loose"),
            ("zeta", "metaprobe_app.plugins:Zeta"),
        }
        (fancy,) = plugins.select(name="fancy")
        assert fancy.extras == ["fancy"]
        assert fancy.dist is not None and fancy.dist.metadata["Name"] == "Metaprobe.App"
        scripts = md.entry_points(group="console_scripts").select(name="metaprobe-cli")
        assert [e.value for e in scripts] == ["metaprobe_app.cli:main"]

    def test_packages_distributions(self, on_path):
        found = md.packages_distributions()
        for module in ("main", "metaprobe_app", "helpers"):
            assert "Metaprobe.App" in found[module], module

    def test_no_record_no_requirements(self, on_path):
        dist = md.distribution("metaprobe-app")
        assert dist.files is None
        assert dist.requires is None

    def test_an_unnormalized_folder_is_not_found(self, tmp_path, monkeypatch):
        """F5, the reason for normalizing: the name ends at the first hyphen."""
        folder = generate(tmp_path)
        folder.rename(folder.with_name("metaprobe-app-1.2.3.dist-info"))
        monkeypatch.syspath_prepend(str(folder.parent))
        with pytest.raises(md.PackageNotFoundError):
            md.version("metaprobe-app")

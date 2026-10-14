"""The app's own package metadata, written into every bundle.

docs/design/dev/package-metadata-proposal.md. A packaged app is not an installed
distribution: ``importlib.metadata`` inside it finds the app's name, version and
entry points only through a ``.dist-info`` or ``.egg-info`` folder beside its
code. Until this module, that was whatever development ``egg-info`` setuptools
had left in ``app_dir`` -- stale, or missing for any project without a
setuptools dev install (#122).

kivyforge now writes ``<name>-<version>.dist-info`` from ``[project]`` into each
platform's copy of ``app_dir`` and removes the development metadata that copy
would otherwise carry. The removal is not tidiness: CPython files a ``.egg-info``
and a ``.dist-info`` of one name into one list in ``os.listdir`` order, so which
of the two wins depends on the filesystem (spike F1).

Nothing here writes to the user's ``app_dir``; every writer takes the bundle's
copy, or iOS's staging folder.
"""

from __future__ import annotations

import configparser
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from kivyforge.config.model import Config, EntryPoint, ProjectMeta
from kivyforge.report import diagnostics
from kivyforge.report.diagnostics import Diagnostic
from kivyforge.report.failures import ClassifiedError

#: The ``[project]`` keys that declare entry points. Listed in ``dynamic``, only
#: the build backend knows the full set (proposal 2.4).
ENTRY_POINT_KEYS = ("scripts", "gui-scripts", "entry-points")

#: ``[build-system].build-backend`` values that are setuptools. A project with
#: no ``[build-system]`` gets the second, PEP 517's default (proposal 2.3).
SETUPTOOLS_BACKENDS = ("setuptools.build_meta", "setuptools.build_meta:__legacy__")

#: Written to ``INSTALLER``, as the recording-installed-projects spec asks.
INSTALLER = "kivyforge"


class EntryPointsOutsideProject(ClassifiedError):
    """Entry points only in ``setup.cfg``/``setup.py``, none in ``[project]``."""

    code = diagnostics.METADATA_ENTRY_POINTS_OUTSIDE_PROJECT


def normalize_name(name: str) -> str:
    """A project name as a ``.dist-info`` folder must spell it.

    ``importlib.metadata`` takes a folder's distribution name from the text
    before its first hyphen (spike F5): ``metaprobe-app-1.2.3.dist-info`` is not
    found under any name, ``metaprobe_app-1.2.3.dist-info`` under all of them.
    """
    return re.sub(r"[-_.]+", "_", name).lower()


@dataclass(frozen=True)
class AppMetadata:
    """What one build writes."""

    #: ``[project].name`` as written: ``METADATA``'s ``Name``.
    name: str
    #: Normalized PEP 440, the same value the plist, ``versionName`` and the
    #: Windows resource carry.
    version: str
    entry_points: tuple[EntryPoint, ...]
    #: ``[tool.kivy].entry_point``, whose top-level module ``top_level.txt``
    #: always lists.
    main_module: str

    @property
    def dist_info(self) -> str:
        """The folder name: both fields normalized (the version already is)."""
        return f"{normalize_name(self.name)}-{self.version}.dist-info"


def dynamic_entry_points(project: ProjectMeta) -> tuple[str, ...]:
    """Which entry-point keys ``[project].dynamic`` lists."""
    return tuple(key for key in ENTRY_POINT_KEYS if key in project.dynamic)


def for_build(config: Config) -> AppMetadata | None:
    """The metadata this build writes; ``None`` when the backend supplies it.

    With entry points in ``dynamic`` kivyforge cannot know them all, so it
    writes nothing and removes nothing (D2): a development ``egg-info``, if
    there is one, stays the app's metadata. The verb has already warned.
    """
    if dynamic_entry_points(config.project):
        return None
    return AppMetadata(
        name=config.project.name,
        version=config.version_required.value,
        entry_points=config.project.entry_points,
        main_module=config.kivy.entry_point,
    )


# --------------------------------------------------------------------------- #
# The files
# --------------------------------------------------------------------------- #


def top_level_names(app_dir: Path, main_module: str) -> list[str]:
    """``top_level.txt``: what ``packages_distributions()`` maps to the app (Q1).

    Every top-level ``*.py`` module and every top-level directory holding an
    ``__init__.py``, read before byte-compiling, plus the module the app starts
    in. Asset folders and ``__init__``-less directories are not listed, as
    setuptools would not list them. ``top_level.txt`` rather than ``RECORD``,
    because byte-compiling, ``strip_source`` and Xcode keep changing the payload
    after the copy, and none of them changes what is at the top level.
    """
    names = {main_module.split(".")[0]}
    for child in app_dir.iterdir():
        if child.is_file() and child.suffix == ".py":
            name = child.stem
        elif child.is_dir() and (child / "__init__.py").is_file():
            name = child.name
        else:
            continue
        if name.isidentifier():
            names.add(name)
    return sorted(names)


def render_entry_points(entry_points: Iterable[EntryPoint]) -> str:
    """``entry_points.txt``, laid out as setuptools writes it.

    Written by hand, never with ``configparser``: its default lowercases names
    (``MyPlugin`` became ``myplugin``), and the spec makes them case-sensitive.
    Groups and the names in each are sorted, so the file depends only on what
    ``[project]`` declares, not on the order it declares it in.
    """
    groups: dict[str, list[EntryPoint]] = {}
    for entry in entry_points:
        groups.setdefault(entry.group, []).append(entry)
    return "".join(
        f"[{group}]\n"
        + "".join(
            f"{e.name} = {e.value}\n" for e in sorted(members, key=lambda e: e.name)
        )
        + "\n"
        for group, members in sorted(groups.items())
    )


def render(metadata: AppMetadata, top_level: Iterable[str]) -> dict[str, bytes]:
    """File name to content, UTF-8 with ``\\n`` line ends on every host.

    ``Metadata-Version: 2.1`` is the lowest that holds these fields. Neither
    ``RECORD`` (it must list the payload as finally shipped, which keeps
    changing after this) nor ``Requires-Dist`` (it would make
    ``pkg_resources.require()`` fail on dependencies an ``exclude`` drops on
    purpose) is written; the spec requires only ``METADATA``.
    """
    files = {
        "METADATA": (
            "Metadata-Version: 2.1\n"
            f"Name: {metadata.name}\n"
            f"Version: {metadata.version}\n"
        ),
        "INSTALLER": f"{INSTALLER}\n",
        "top_level.txt": "".join(f"{name}\n" for name in top_level),
    }
    if metadata.entry_points:
        files["entry_points.txt"] = render_entry_points(metadata.entry_points)
    return {name: text.encode("utf-8") for name, text in files.items()}


def write_dist_info(
    metadata: AppMetadata, parent: Path, top_level: Iterable[str]
) -> Path:
    """Write ``<parent>/<name>-<version>.dist-info``; return its path."""
    folder = parent / metadata.dist_info
    folder.mkdir()
    for name, content in render(metadata, top_level).items():
        (folder / name).write_bytes(content)
    return folder


# --------------------------------------------------------------------------- #
# Into a bundle's copy of app_dir
# --------------------------------------------------------------------------- #


def development_metadata(app_copy: Path, name: str) -> list[Path]:
    """What the generated folder must not share ``app_copy`` with (2.2, Q2).

    At the top level only, where setuptools writes: every ``*.egg-info`` --
    ``entry_points()`` collects from every distribution it finds, so the
    ``oldname.egg-info`` of a renamed project would keep injecting plugins --
    and any ``.dist-info`` of the app's own name. Other ``.dist-info`` folders
    stay: a library vendored with ``pip install --target`` keeps its metadata.
    """
    own = normalize_name(name)
    found = []
    for child in sorted(app_copy.iterdir()):
        if child.name.endswith(".egg-info"):
            found.append(child)
        elif child.name.endswith(".dist-info"):
            stem = child.name[: -len(".dist-info")]
            if normalize_name(stem.split("-", 1)[0]) == own:
                found.append(child)
    return found


def install(app_copy: Path, metadata: AppMetadata | None) -> Path | None:
    """Replace ``app_copy``'s development metadata with the generated folder.

    *app_copy* is the bundle's copy of ``app_dir``, never ``app_dir`` itself.
    Returns the folder written, or ``None`` when *metadata* is ``None`` (D2),
    which leaves the copy as it is.
    """
    if metadata is None:
        return None
    for path in development_metadata(app_copy, metadata.name):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    top_level = top_level_names(app_copy, metadata.main_module)
    return write_dist_info(metadata, app_copy, top_level)


# --------------------------------------------------------------------------- #
# Before a build: the declaration
# --------------------------------------------------------------------------- #


def check_declaration(project: ProjectMeta, project_root: Path) -> None:
    """Refuse entry points declared only in ``setup.cfg``/``setup.py`` (2.3, D1).

    With a ``[project]`` table, the spec lets no backend fill in a key
    ``[project]`` neither declares nor lists in ``dynamic``. setuptools still
    does, with a deprecation warning (spike F2), so these are entry points the
    project is about to lose -- and generating from ``[project]`` alone would
    lose them now, silently, which is #122. An empty ``[project.entry-points]``
    table declares nothing: setuptools 84 still used ``setup.py``'s with it
    (F7). Not detected: a ``setup.py`` that hides the word from a text search.
    """
    if project.build_backend not in SETUPTOOLS_BACKENDS:
        return
    if project.entry_points or dynamic_entry_points(project):
        return
    where = _entry_points_outside_project(project_root)
    if where is None:
        return
    raise EntryPointsOutsideProject(
        f"{where} declares entry points and [project] declares none. kivyforge "
        "writes the app's package metadata from [project], so the app would "
        "start without them; setuptools still reads them, but has deprecated "
        "doing so for a project with a [project] table.\n"
        f"  Fix: move them from {where} into [project.entry-points] "
        "(console_scripts into [project.scripts], gui_scripts into "
        "[project.gui-scripts]).",
        context={"path": where},
    )


def _entry_points_outside_project(project_root: Path) -> str | None:
    setup_cfg = project_root / "setup.cfg"
    if setup_cfg.is_file():
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(setup_cfg, encoding="utf-8")
        except (configparser.Error, UnicodeDecodeError):
            # setuptools reads it with configparser too, so a file this cannot
            # parse is one setuptools takes no entry points from either.
            parser = None
        if parser is not None and parser.has_section("options.entry_points"):
            if any(v.strip() for _, v in parser.items("options.entry_points")):
                return "setup.cfg"
    setup_py = project_root / "setup.py"
    if setup_py.is_file():
        text = setup_py.read_text(encoding="utf-8", errors="replace")
        if "entry_points" in text:
            return "setup.py"
    return None


def not_generated(
    project: ProjectMeta, project_root: Path, app_dir: str | None
) -> Diagnostic | None:
    """The warning for entry points the backend supplies (2.4, D2).

    ``context``: ``reason`` is ``dynamic``, or ``static-and-dynamic`` when
    ``[project]`` also declares some (the spec lets the backend add to them);
    ``fallback`` is the development ``egg-info`` that ships instead, or
    ``none``.
    """
    keys = dynamic_entry_points(project)
    if not keys:
        return None
    reason = "static-and-dynamic" if project.entry_points else "dynamic"
    fallback = _development_egg_info(project_root, app_dir, project.name)
    listed = ", ".join(keys)
    if fallback is None:
        outcome = "The app has no package metadata: importlib.metadata finds no "
        outcome += f"{project.name!r} inside it."
    else:
        outcome = f"The app gets {fallback} instead, as the last install wrote it."
    return Diagnostic(
        code=diagnostics.METADATA_NOT_GENERATED,
        severity=diagnostics.WARNING,
        message=f"[project].dynamic lists {listed}, so only the build backend "
        "knows the app's entry points, and kivyforge generates no package "
        f"metadata for it. {outcome}",
        remediation="declare the entry points in [project] and remove them from "
        "dynamic; until then, run `pip install -e .` (or `uv sync`) before each "
        "build so the egg-info is current.",
        context={"reason": reason, "fallback": fallback or "none"},
    )


def _development_egg_info(
    project_root: Path, app_dir: str | None, name: str
) -> str | None:
    source = project_root / app_dir if app_dir else None
    if source is None or not source.is_dir():
        return None
    own = normalize_name(name)
    for child in sorted(source.iterdir()):
        stem = child.name[: -len(".egg-info")]
        if child.name.endswith(".egg-info") and (
            normalize_name(stem.split("-", 1)[0]) == own
        ):
            return child.relative_to(project_root).as_posix()
    return None

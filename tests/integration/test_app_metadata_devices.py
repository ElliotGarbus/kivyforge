"""What ``importlib.metadata`` sees inside real apps (package-metadata layer 3).

``docs/design/dev/package-metadata-proposal.md`` section 5, layer 3. Each test
copies ``tests/fixtures/apps/metaprobe`` into a temporary directory, builds its
two dependency wheels, locks, builds, launches the app and reads back the report
its ``main.py`` writes: which copy of the app's metadata it finds, its version,
every entry point, ``packages_distributions()``, and whether a dependency's
entry point loads. Nothing is written to the repository.

Opt in per platform with ``--metaprobe macos,ios-sim,android-emu`` (any
subset). Once opted in, a missing tool **fails**: the option is a promise that
the platform is there. Needs the network (wheels, locks, the setuptools a dev
install fetches) and takes minutes per platform; the Android emulator and the
iOS simulator are booted if needed, and shut down at the end only if this run
booted them; an already booted simulator is preferred, and the probe app is
uninstalled from both at the end.

A report is accepted only from a build that succeeded, and only if it carries
the ``BUILD_MARK`` this run wrote into ``main.py``. The spike this replaces
once collected a stale report from an app a failed build had left installed.

``METAPROBE_SIMULATOR`` (a name or UDID) and ``METAPROBE_AVD`` choose the
devices; the defaults are the newest iPhone simulator and ``kf_api35_arm64``.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_toolchain

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "apps" / "metaprobe"
PLATFORMS = ("macos", "ios-sim", "android-emu")
LOCK_PLATFORM = {"macos": "macos", "ios-sim": "ios", "android-emu": "android"}

APP = "metaprobe-app"
APP_ID = "org.kivyforge.metaprobe"
VERSION = "1.2.3"
GENERATED = f"metaprobe_app-{VERSION}.dist-info"
ALIASES = ("metaprobe-app", "metaprobe_app", "Metaprobe.App")
AVD = os.environ.get("METAPROBE_AVD", "kf_api35_arm64")
ABI = "arm64_v8a"

#: What ``[project]`` declares, as ``(group, name, value)``.
APP_ENTRY_POINTS = sorted(
    [
        ["console_scripts", "metaprobe-cli", "metaprobe_app.cli:main"],
        ["gui_scripts", "metaprobe-gui", "metaprobe_app.cli:gui"],
        ["metaprobe.plugins", "CasePlugin", "metaprobe_app.plugins:CasePlugin"],
        ["metaprobe.plugins", "app-plugin", "metaprobe_app.plugins:AppPlugin"],
    ]
)
#: ``entry_points(group="metaprobe.plugins")``: the app's two, and one from each
#: dependency wheel, as ``[name, value, distribution]``.
PLUGINS = sorted(
    [
        ["CasePlugin", "metaprobe_app.plugins:CasePlugin", APP],
        ["app-plugin", "metaprobe_app.plugins:AppPlugin", APP],
        ["dep-plugin", "metaprobe_dep:Demo", "metaprobe-dep"],
        ["extra-plugin", "metaprobe_extra:Extra", "metaprobe-extra"],
    ]
)

# --------------------------------------------------------------------------- #
# Opting in
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def selected(pytestconfig) -> frozenset[str]:
    given = pytestconfig.getoption("--metaprobe")
    if not given:
        pytest.skip("no --metaprobe given; builds and launches real apps")
    chosen = frozenset(p.strip() for p in given.split(",") if p.strip())
    unknown = chosen - set(PLATFORMS)
    if unknown:
        raise pytest.UsageError(
            f"--metaprobe: unknown {', '.join(sorted(unknown))} "
            f"(choose from {', '.join(PLATFORMS)})"
        )
    return chosen


def _need(tool: str) -> str:
    found = shutil.which(tool)
    if found is None:
        pytest.fail(f"--metaprobe asked for a platform that needs {tool}, not on PATH")
    return found


# --------------------------------------------------------------------------- #
# Processes
# --------------------------------------------------------------------------- #


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    # The kivyforge this suite imports, not whichever one is installed.
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO), env.get("PYTHONPATH", "")) if p
    )
    env.setdefault("ANDROID_HOME", str(Path.home() / "Library" / "Android" / "sdk"))
    env.update(extra or {})
    return env


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 600,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        argv,
        cwd=cwd,
        env=env or _env(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        pytest.fail(_failure(" ".join(argv[:4]), proc))
    return proc


def _failure(what: str, proc: subprocess.CompletedProcess[str]) -> str:
    def tail(text: str) -> str:
        return "\n".join(text.splitlines()[-40:])

    return (
        f"{what} failed (exit {proc.returncode}); no report is collected from a "
        f"failed build.\n--- stdout ---\n{tail(proc.stdout)}\n"
        f"--- stderr ---\n{tail(proc.stderr)}"
    )


KIVYFORGE = [
    sys.executable,
    "-c",
    "from kivyforge.cli import main; main(prog_name='kivyforge')",
]

#: ``kivyforge`` that also logs every ``xcodebuild`` argv it runs to the file
#: named by its first argument: the Xcode-only rebuilds replay that command, as
#: Cmd-R does. ``kivyforge.cli`` is imported first because the iOS backend
#: imports it back; the backend's own name for ``run_command`` is replaced too.
CAPTURING_KIVYFORGE = [
    sys.executable,
    "-c",
    """\
import json, sys
import kivyforge.cli
from kivyforge.platforms.ios import cli as ios_cli
from kivyforge.platforms.ios.xcode import runner

log = sys.argv.pop(1)
real = runner.run_command

def capture(argv, *args, **kwargs):
    if argv and argv[0] == "xcodebuild":
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(list(argv)) + "\\n")
    return real(argv, *args, **kwargs)

runner.run_command = ios_cli.run_command = capture
kivyforge.cli.main(prog_name="kivyforge")
""",
]


def _kf(
    project: Path,
    *args: str,
    env: dict[str, str] | None = None,
    timeout: float = 1800,
    command: list[str] = KIVYFORGE,
) -> subprocess.CompletedProcess[str]:
    proc = _run(
        [*command, *args],
        cwd=project,
        env=_env(env),
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        pytest.fail(_failure(f"kivyforge {' '.join(args)}", proc))
    return proc


def _envelope(proc: subprocess.CompletedProcess[str]) -> dict:
    envelope = json.loads(proc.stdout)
    assert envelope["ok"], envelope
    return envelope


# --------------------------------------------------------------------------- #
# The project
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def wheelhouse(tmp_path_factory) -> Path:
    """The two dependency wheels, built from copies so the fixture stays clean."""
    work = tmp_path_factory.mktemp("metaprobe-deps")
    out = work / "wheels"
    for dep in sorted((FIXTURE / "deps").iterdir()):
        source = work / dep.name
        shutil.copytree(dep, source)
        _run(
            [sys.executable, "-m", "pip", "wheel", "--no-deps", "--quiet"]
            + ["--wheel-dir", str(out), str(source)]
        )
    built = sorted(p.name for p in out.glob("*.whl"))
    assert len(built) == 2, built
    return out


def _copy_fixture(dest: Path, wheels: Path) -> Path:
    shutil.copytree(FIXTURE, dest, ignore=shutil.ignore_patterns("deps"))
    shutil.copytree(wheels, dest / "wheels")
    return dest


class _Locked(dict[str, Path]):
    """One locked copy per platform, made on first use; tests copy it."""

    def __init__(self, tmp_path_factory, wheelhouse: Path) -> None:
        super().__init__()
        self._factory = tmp_path_factory
        self._wheelhouse = wheelhouse

    def __missing__(self, platform: str) -> Path:
        base = self._factory.mktemp(f"metaprobe-{platform}")
        project = _copy_fixture(base / "metaprobe", self._wheelhouse)
        _kf(project, "lock", "-p", LOCK_PLATFORM[platform])
        self[platform] = project
        return project


@pytest.fixture(scope="session")
def locked(tmp_path_factory, wheelhouse) -> dict[str, Path]:
    return _Locked(tmp_path_factory, wheelhouse)


def _project(locked: dict[str, Path], platform: str, tmp_path: Path) -> Path:
    project = tmp_path / "metaprobe"
    shutil.copytree(locked[platform], project, symlinks=True)
    return project


def _relock(platform: str, project: Path) -> None:
    """After an edit to ``pyproject.toml``, which the lock hashes."""
    _kf(project, "lock", "-p", LOCK_PLATFORM[platform])


def _edit_pyproject(project: Path, *edits: tuple[str, str]) -> None:
    path = project / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    for old, new in edits:
        assert old in text, old
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def _mark(project: Path) -> str:
    """Stamp ``main.py`` with a fresh ``BUILD_MARK``; return it."""
    mark = uuid.uuid4().hex
    main = project / "src" / "main.py"
    text = main.read_text(encoding="utf-8")
    new, count = re.subn(
        r'^BUILD_MARK = "[^"]*"$', f'BUILD_MARK = "{mark}"', text, flags=re.M
    )
    assert count == 1
    main.write_text(new, encoding="utf-8")
    return mark


def _dev_install_egg_info(project: Path) -> Path:
    """What ``pip install -e .`` or ``uv sync`` leaves in a src layout.

    pip's metadata preparation, isolated, makes setuptools write the egg-info
    into ``src/`` (``tests/test_pip_metadata_live.py``), with nothing installed.
    """
    _run(
        [sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed"]
        + ["--no-deps", "--quiet", "--report", os.devnull, str(project)],
        timeout=600,
    )
    found = sorted((project / "src").glob("*.egg-info"))
    assert [p.name for p in found] == ["metaprobe_app.egg-info"], found
    return found[0]


def _make_stale(egg_info: Path, version: str) -> None:
    """The egg-info of an install made before the last edits (#122's state)."""
    pkg_info = egg_info / "PKG-INFO"
    text = pkg_info.read_text(encoding="utf-8")
    pkg_info.write_text(
        re.sub(r"^Version: .*$", f"Version: {version}", text, flags=re.M),
        encoding="utf-8",
    )
    with (egg_info / "entry_points.txt").open("a", encoding="utf-8") as fh:
        fh.write("\n[metaprobe.plugins]\nstale-plugin = metaprobe_app.gone:Gone\n")


def _plant_renamed_project(project: Path) -> None:
    """A renamed project's leftover, whose plugins entry_points() would collect."""
    old = project / "src" / "oldprobe.egg-info"
    old.mkdir()
    (old / "PKG-INFO").write_text(
        "Metadata-Version: 2.1\nName: oldprobe\nVersion: 0.1\n", encoding="utf-8"
    )
    (old / "entry_points.txt").write_text(
        "[metaprobe.plugins]\nold-plugin = oldprobe:Old\n", encoding="utf-8"
    )


def _git(project: Path, *args: str) -> str:
    # No global or system config, so the user's signing or hooks cannot apply.
    env = _env(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        }
    )
    return _run(["git", *args], cwd=project, env=env).stdout.strip()


# --------------------------------------------------------------------------- #
# macOS
# --------------------------------------------------------------------------- #


def _report_from_lines(text: str) -> dict:
    for line in text.splitlines():
        if line.startswith("METAPROBE "):
            return json.loads(line[len("METAPROBE ") :])
    raise AssertionError(f"no METAPROBE line in the app's output:\n{text[-3000:]}")


def _macos_env(project: Path) -> dict[str, str]:
    # Without it the probe would write into the home directory.
    out = project.parent / "macos-out"
    out.mkdir(exist_ok=True)
    return {"METAPROBE_OUT": str(out)}


def _macos_report(project: Path, *, release: bool = False) -> dict:
    flags = ["--release"] if release else []
    proc = _kf(project, "run", "-p", "macos", *flags, env=_macos_env(project))
    return _report_from_lines(proc.stdout)


def _macos_launch(project: Path, app: Path) -> dict:
    """The built ``.app``'s executable, run as ``kivyforge run`` runs it."""
    (exe,) = (app / "Contents" / "MacOS").iterdir()
    proc = _run([str(exe)], env=_env(_macos_env(project)), timeout=300)
    return _report_from_lines(proc.stdout)


# --------------------------------------------------------------------------- #
# iOS simulator
# --------------------------------------------------------------------------- #


def _runtime_key(runtime: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", runtime.rsplit(".", 1)[-1]))


@pytest.fixture(scope="session")
def simulator(selected) -> Iterator[str]:
    if "ios-sim" not in selected:
        pytest.skip("ios-sim not in --metaprobe")
    _need("xcrun")
    listing = json.loads(
        _run(["xcrun", "simctl", "list", "devices", "available", "--json"]).stdout
    )
    wanted = os.environ.get("METAPROBE_SIMULATOR")
    candidates = []
    for runtime, devices in listing["devices"].items():
        if ".iOS-" not in runtime:
            continue
        for device in devices:
            if wanted in (device["udid"], device["name"]) or (
                not wanted and device["name"].startswith("iPhone")
            ):
                # The newest runtime, then a booted device, then by name.
                key = (_runtime_key(runtime), device["state"] == "Booted")
                candidates.append((key, device["name"], device["udid"]))
    if not candidates:
        pytest.fail(f"no available iOS simulator matches {wanted or 'iPhone*'}")
    newest = max(c[0] for c in candidates)
    (_, booted), _, udid = min(c for c in candidates if c[0] == newest)
    _run(["xcrun", "simctl", "boot", udid], check=False)
    _run(["xcrun", "simctl", "bootstatus", udid, "-b"], timeout=300)
    yield udid
    # Leave the device as found: it may be someone else's.
    _run(["xcrun", "simctl", "uninstall", udid, APP_ID], check=False)
    if not booted:  # booted here, so shut down here; someone else's stays up
        _run(["xcrun", "simctl", "shutdown", udid], check=False)


def _ios_build(project: Path, *, capture: Path | None = None) -> dict:
    args = ("build", "-p", "ios", "--simulator", "--json")
    if capture is None:
        return _envelope(_kf(project, *args))
    command = [*CAPTURING_KIVYFORGE, str(capture)]
    return _envelope(_kf(project, *args, command=command))


def _ios_app(project: Path, envelope: dict) -> Path:
    (app,) = [a for a in envelope["data"]["artifacts"] if a["kind"] == "app"]
    return project / app["path"]


def _ios_report(udid: str, app: Path, *, wait: float = 120) -> dict:
    simctl = ["xcrun", "simctl"]
    _run([*simctl, "uninstall", udid, APP_ID], check=False)
    _run([*simctl, "install", udid, str(app)])
    _run([*simctl, "launch", "--terminate-running-process", udid, APP_ID])
    container = Path(
        _run([*simctl, "get_app_container", udid, APP_ID, "data"]).stdout.strip()
    )
    # macOS has no `timeout`: poll for the file, then stop the app.
    deadline = time.monotonic() + wait
    try:
        while time.monotonic() < deadline:
            for path in (container / "Documents", container):
                report = path / "metaprobe.json"
                if report.is_file() and report.stat().st_size:
                    return json.loads(report.read_text(encoding="utf-8"))
            time.sleep(1)
    finally:
        _run([*simctl, "terminate", udid, APP_ID], check=False)
    raise AssertionError(f"no metaprobe.json in {container} after {wait:g} s")


def _codesign_ok(app: Path) -> None:
    _run(["codesign", "--verify", "--deep", "--strict", str(app)])


# --------------------------------------------------------------------------- #
# Android emulator
# --------------------------------------------------------------------------- #


def _adb_path() -> str:
    adb = Path(_env()["ANDROID_HOME"]) / "platform-tools" / "adb"
    if not adb.is_file():
        pytest.fail(f"--metaprobe android-emu: no adb at {adb} (set ANDROID_HOME)")
    return str(adb)


@pytest.fixture(scope="session")
def emulator(selected) -> Iterator[str]:
    if "android-emu" not in selected:
        pytest.skip("android-emu not in --metaprobe")
    adb = _adb_path()
    os.environ.setdefault("ANDROID_HOME", _env()["ANDROID_HOME"])
    from kivyforge.platforms.android import adb as adb_mod

    running = set(adb_mod.connected_devices())
    serial = adb_mod.resolve_device(prefer_emulator=True, avd=AVD)
    yield serial
    # Leave the device as found: it may be someone else's.
    _run([adb, "-s", serial, "uninstall", APP_ID], check=False)
    if serial not in running:  # booted here, so shut down here
        _run([adb, "-s", serial, "emu", "kill"], check=False)


def _android_report(
    project: Path, serial: str, *, release: bool = False, no_build: bool = False
) -> dict:
    adb = [_adb_path(), "-s", serial]
    # A clean install: an app left by an earlier run must not answer.
    _run([*adb, "uninstall", APP_ID], check=False)
    flags = ["--release"] if release else []
    flags += ["--no-build"] if no_build else []
    proc = _kf(
        project,
        "run",
        "-p",
        "android",
        "--emulator",
        "--avd",
        AVD,
        *([] if no_build else ["--abi", ABI]),
        "--no-follow",
        *flags,
    )
    if release:
        # Not debuggable, so run-as cannot read the file: reassemble the
        # per-key lines from the log `run` printed.
        report: dict = {}
        for line in proc.stdout.splitlines():
            _, sep, rest = line.partition("METAPROBE.")
            if sep:
                key, _, value = rest.partition(" ")
                report[key] = json.loads(value)
        assert report, f"no METAPROBE. lines in the log:\n{proc.stdout[-3000:]}"
        return report
    deadline = time.monotonic() + 60
    said = ""
    while time.monotonic() < deadline:
        read = _run(
            [*adb, "shell", "run-as", APP_ID, "cat", "files/metaprobe.json"],
            check=False,
        )
        if read.returncode == 0 and read.stdout.strip().startswith("{"):
            return json.loads(read.stdout)
        said = read.stdout + read.stderr
        time.sleep(2)
    raise AssertionError(f"no files/metaprobe.json for {APP_ID}:\n{said}")


def _apk_version_name(apk: Path) -> str:
    tools = Path(_env()["ANDROID_HOME"]) / "build-tools"
    aapt2 = max(tools.glob("*/aapt2"), key=lambda p: p.parent.name)
    badging = _run([str(aapt2), "dump", "badging", str(apk)]).stdout
    found = re.search(r"versionName='([^']*)'", badging)
    assert found, badging[:500]
    return found.group(1)


# --------------------------------------------------------------------------- #
# Collecting a report, any platform
# --------------------------------------------------------------------------- #


def _collect(
    platform: str,
    project: Path,
    request,
    *,
    release: bool = False,
    mark: str | None = None,
) -> dict:
    mark = mark or _mark(project)
    if platform == "macos":
        report = _macos_report(project, release=release)
    elif platform == "ios-sim":
        udid = request.getfixturevalue("simulator")
        report = _ios_report(udid, _ios_app(project, _ios_build(project)))
    else:
        serial = request.getfixturevalue("emulator")
        report = _android_report(project, serial, release=release)
    return _checked(platform, report, mark)


def _checked(platform: str, report: dict, mark: str) -> dict:
    # Shown with the failure, if there is one.
    print(f"{platform} report:", json.dumps(report, indent=1, sort_keys=True))
    assert "error" not in report, report["error"]
    assert report["build_mark"] == mark, "the report came from another build"
    return report


def _built_with_json(
    platform: str, project: Path, request, *, mark: str | None = None
) -> tuple[dict, dict]:
    """``build --json`` (for its version and diagnostics), then the app's report."""
    mark = mark or _mark(project)
    if platform == "macos":
        envelope = _envelope(_kf(project, "build", "-p", "macos", "--json"))
        (app,) = [a for a in envelope["data"]["artifacts"] if a["kind"] == "app"]
        report = _macos_launch(project, project / app["path"])
    elif platform == "ios-sim":
        envelope = _ios_build(project)
        udid = request.getfixturevalue("simulator")
        report = _ios_report(udid, _ios_app(project, envelope))
    else:
        args = ("build", "-p", "android", "--debug", "--abi", ABI, "--json")
        envelope = _envelope(_kf(project, *args))
        serial = request.getfixturevalue("emulator")
        report = _android_report(project, serial, no_build=True)
    return envelope, _checked(platform, report, mark)


@pytest.fixture
def platform_project(request, selected, locked, tmp_path):
    platform = request.param
    if platform not in selected:
        pytest.skip(f"{platform} not in --metaprobe")
    if platform == "macos" and sys.platform != "darwin":
        pytest.fail("--metaprobe macos needs a macOS host")
    if platform == "ios-sim":
        request.getfixturevalue("simulator")
    if platform == "android-emu":
        request.getfixturevalue("emulator")
    return platform, _project(locked, platform, tmp_path)


def _assert_finds_its_metadata(report: dict, version: str = VERSION) -> None:
    for alias in ALIASES:
        found = report[f"distribution:{alias}"]
        assert found is not None, f"{alias!r} not found"
        assert found["version"] == version, found
        assert found["name"] == APP, found
    assert report["app_entry_points"] == APP_ENTRY_POINTS
    assert report["plugins"] == PLUGINS
    assert report["loaded"] == "metaprobe_dep.Demo"


def _assert_generated(report: dict, version: str = VERSION) -> None:
    """The app's only metadata is the folder kivyforge wrote (2.1, 2.2)."""
    _assert_finds_its_metadata(report, version)
    (copy,) = report["app_copies"]
    assert Path(copy).name == f"metaprobe_app-{version}.dist-info", copy
    assert Path(copy).parent.name == "app", copy
    assert report["app_files"] is None  # no RECORD
    assert report["app_requires"] is None  # no Requires-Dist
    assert report["packages_distributions"] == {
        "main": [APP],
        "metaprobe_app": [APP],
        "assets": [],  # an asset folder is not a module
    }


# --------------------------------------------------------------------------- #
# Variants (proposal section 5, layer 3)
# --------------------------------------------------------------------------- #

RELEASE_PLATFORMS = ("macos", "android-emu")


@pytest.mark.parametrize("platform_project", PLATFORMS, indirect=True)
def test_dev_install_egg_info(platform_project, request):
    """The baseline: a src layout after ``pip install -e .`` finds its metadata.

    It passed on ``main`` through the egg-info; now through the generated
    folder, with the egg-info left in the source tree.
    """
    platform, project = platform_project
    egg_info = _dev_install_egg_info(project)

    report = _collect(platform, project, request)

    _assert_generated(report)
    assert egg_info.is_dir()


@pytest.mark.parametrize("platform_project", PLATFORMS, indirect=True)
def test_no_egg_info(platform_project, request):
    """No dev install: hatch, flit, a flat layout, a fresh CI checkout (#122)."""
    platform, project = platform_project

    report = _collect(platform, project, request)

    _assert_generated(report)


@pytest.mark.parametrize("platform_project", PLATFORMS, indirect=True)
def test_stale_egg_info(platform_project, request):
    """An old dev install and a renamed project's leftover reach nothing."""
    platform, project = platform_project
    _make_stale(_dev_install_egg_info(project), "0.0.1")
    _plant_renamed_project(project)

    report = _collect(platform, project, request)

    _assert_generated(report)  # no stale-plugin, no old-plugin, version 1.2.3


@pytest.mark.parametrize("platform_project", RELEASE_PLATFORMS, indirect=True)
def test_release(platform_project, request):
    """Byte-compiled and source-stripped, with a stale egg-info in the tree."""
    platform, project = platform_project
    _make_stale(_dev_install_egg_info(project), "0.0.1")

    report = _collect(platform, project, request, release=True)

    assert report["main_file"] == "main.pyc"
    _assert_generated(report)


@pytest.mark.parametrize("platform_project", ["ios-sim"], indirect=True)
def test_xcode_only_rebuilds(platform_project, request, tmp_path):
    """Cmd-R after ``kivyforge build`` (F6): Xcode re-copies ``app/`` -- the
    link to ``app_dir`` in a debug build -- and the Build Python script must
    remove the egg-info and copy the staged metadata in every time, before
    signing, without touching the source tree."""
    _, project = platform_project
    udid = request.getfixturevalue("simulator")
    egg_info = _dev_install_egg_info(project)
    _make_stale(egg_info, "0.0.1")
    captured = tmp_path / "xcodebuild.jsonl"
    mark = _mark(project)
    app = _ios_app(project, _ios_build(project, capture=captured))
    (argv,) = [
        json.loads(line)
        for line in captured.read_text(encoding="utf-8").splitlines()
        if json.loads(line)[-1] == "build"
    ]
    _codesign_ok(app)
    _assert_generated(_checked("ios-sim", _ios_report(udid, app), mark))

    def xcode_only() -> dict:
        _run(argv, timeout=1200)
        _codesign_ok(app)
        return _ios_report(udid, app)

    # 1. Nothing changed.
    _assert_generated(_checked("ios-sim", xcode_only(), mark))
    # 2. An edit in src/ reaches the app: the link loop still works.
    mark = _mark(project)
    _assert_generated(_checked("ios-sim", xcode_only(), mark))
    # 3. A dev install rewrites the egg-info; the bundle still has only ours.
    _make_stale(egg_info, "0.0.2")
    _assert_generated(_checked("ios-sim", xcode_only(), mark))
    assert "Version: 0.0.2" in (egg_info / "PKG-INFO").read_text(encoding="utf-8")


@pytest.mark.parametrize("platform_project", PLATFORMS, indirect=True)
def test_dynamic_version(platform_project, request):
    """setuptools-scm, one commit past a tag: one version in every place."""
    platform, project = platform_project
    _edit_pyproject(
        project,
        ('"setuptools>=64"]', '"setuptools>=64", "setuptools-scm>=8"]'),
        ('version = "1.2.3"', 'dynamic = ["version"]'),
    )
    with (project / "pyproject.toml").open("a", encoding="utf-8") as fh:
        fh.write("\n[tool.setuptools_scm]\n")
    _relock(platform, project)
    mark = _mark(project)  # before the commit: a dirty tree changes the version
    _git(project, "init", "-q")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "init")
    _git(project, "tag", "v1.2.3")
    (project / "CHANGES").write_text("one more\n", encoding="utf-8")
    _git(project, "add", "CHANGES")
    _git(project, "commit", "-q", "-m", "after the tag")

    envelope, report = _built_with_json(platform, project, request, mark=mark)

    version = envelope["data"]["version"]
    assert version["source"] == "backend"
    assert re.fullmatch(r"1\.2\.4\.dev1\+g[0-9a-f]+", version["value"]), version
    _assert_generated(report, version["value"])
    if platform == "android-emu":
        dest = project / "metaprobe-app-android" / "app" / "build" / "outputs"
        shipped = _apk_version_name(dest / "apk" / "debug" / "app-debug.apk")
    else:
        (app,) = [a for a in envelope["data"]["artifacts"] if a["kind"] == "app"]
        contents = "Contents/" if platform == "macos" else ""
        plist = (project / app["path"] / f"{contents}Info.plist").read_bytes()
        shipped = plistlib.loads(plist)["CFBundleShortVersionString"]
    assert shipped == version["value"]


@pytest.mark.parametrize("platform_project", PLATFORMS, indirect=True)
def test_dynamic_entry_points(platform_project, request):
    """D2: every entry point from ``setup.cfg``, all three keys in ``dynamic``.

    kivyforge cannot know them, so it warns, generates nothing and removes
    nothing; the dev install's egg-info carries them into the app. All three
    keys, because with ``scripts`` static and only ``entry-points`` dynamic
    setuptools 84 drops ``setup.cfg``'s groups without a word
    (``tests/bundle/test_app_metadata_live.py`` pins it).
    """
    platform, project = platform_project
    _edit_pyproject(
        project,
        (
            'version = "1.2.3"',
            'version = "1.2.3"\ndynamic = ["scripts", "gui-scripts", "entry-points"]',
        ),
        (
            "[project.scripts]\n"
            'metaprobe-cli = "metaprobe_app.cli:main"\n\n'
            "[project.gui-scripts]\n"
            'metaprobe-gui = "metaprobe_app.cli:gui"\n\n'
            '[project.entry-points."metaprobe.plugins"]\n'
            'app-plugin = "metaprobe_app.plugins:AppPlugin"\n'
            'CasePlugin = "metaprobe_app.plugins:CasePlugin"\n',
            "",
        ),
    )
    (project / "setup.cfg").write_text(
        "[options.entry_points]\n"
        "console_scripts =\n"
        "    metaprobe-cli = metaprobe_app.cli:main\n"
        "gui_scripts =\n"
        "    metaprobe-gui = metaprobe_app.cli:gui\n"
        "metaprobe.plugins =\n"
        "    app-plugin = metaprobe_app.plugins:AppPlugin\n"
        "    CasePlugin = metaprobe_app.plugins:CasePlugin\n",
        encoding="utf-8",
    )
    _relock(platform, project)
    egg_info = _dev_install_egg_info(project)

    envelope, report = _built_with_json(platform, project, request)

    (warning,) = [
        d for d in envelope["diagnostics"] if d["code"] == "KF-METADATA-NOT-GENERATED"
    ]
    assert warning["context"] == {
        "reason": "dynamic",
        "fallback": egg_info.relative_to(project).as_posix(),
    }
    _assert_finds_its_metadata(report)
    (copy,) = report["app_copies"]
    assert Path(copy).name == "metaprobe_app.egg-info", copy

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
booted them.

A report is accepted only from a build that succeeded, and only if it carries
the ``BUILD_MARK`` this run wrote into ``main.py``. The spike this replaces
once collected a stale report from an app a failed build had left installed.

``METAPROBE_SIMULATOR`` (a name or UDID) and ``METAPROBE_AVD`` choose the
devices; the defaults are the newest iPhone simulator and ``kf_api35_arm64``.
"""

from __future__ import annotations

import json
import os
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


def _kf(
    project: Path, *args: str, env: dict[str, str] | None = None, timeout=1800
) -> subprocess.CompletedProcess[str]:
    proc = _run(
        [*KIVYFORGE, *args],
        cwd=project,
        env=_env(env),
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        pytest.fail(_failure(f"kivyforge {' '.join(args)}", proc))
    return proc


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


# --------------------------------------------------------------------------- #
# macOS
# --------------------------------------------------------------------------- #


def _report_from_lines(text: str) -> dict:
    for line in text.splitlines():
        if line.startswith("METAPROBE "):
            return json.loads(line[len("METAPROBE ") :])
    raise AssertionError(f"no METAPROBE line in the app's output:\n{text[-3000:]}")


def _macos_report(project: Path, *, release: bool = False) -> dict:
    out = project.parent / "macos-out"
    out.mkdir(exist_ok=True)
    flags = ["--release"] if release else []
    proc = _kf(
        project,
        "run",
        "-p",
        "macos",
        *flags,
        env={"METAPROBE_OUT": str(out)},
        timeout=900,
    )
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
    if not booted:  # booted here, so shut down here; someone else's stays up
        _run(["xcrun", "simctl", "shutdown", udid], check=False)


def _ios_build(project: Path, *, env: dict[str, str] | None = None) -> dict:
    proc = _kf(project, "build", "-p", "ios", "--simulator", "--json", env=env)
    envelope = json.loads(proc.stdout)
    assert envelope["ok"], envelope
    return envelope


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
    if serial not in running:  # booted here, so shut down here
        _run([adb, "-s", serial, "emu", "kill"], check=False)


def _android_report(project: Path, serial: str, *, release: bool = False) -> dict:
    adb = [_adb_path(), "-s", serial]
    # A clean install: an app left by an earlier run must not answer.
    _run([*adb, "uninstall", APP_ID], check=False)
    flags = ["--release"] if release else []
    proc = _kf(
        project,
        "run",
        "-p",
        "android",
        "--emulator",
        "--avd",
        AVD,
        "--abi",
        ABI,
        "--no-follow",
        *flags,
        timeout=1800,
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


# --------------------------------------------------------------------------- #
# Collecting a report, any platform
# --------------------------------------------------------------------------- #


def _collect(platform: str, project: Path, request, *, release: bool = False) -> dict:
    mark = _mark(project)
    if platform == "macos":
        report = _macos_report(project, release=release)
    elif platform == "ios-sim":
        udid = request.getfixturevalue("simulator")
        report = _ios_report(udid, _ios_app(project, _ios_build(project)))
    else:
        serial = request.getfixturevalue("emulator")
        report = _android_report(project, serial, release=release)
    # Shown with the failure, if there is one.
    print(f"{platform} report:", json.dumps(report, indent=1, sort_keys=True))
    assert "error" not in report, report["error"]
    assert report["build_mark"] == mark, "the report came from another build"
    return report


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


def _assert_finds_its_metadata(report: dict) -> None:
    for alias in ALIASES:
        found = report[f"distribution:{alias}"]
        assert found is not None, f"{alias!r} not found: {report}"
        assert found["version"] == VERSION, found
        assert found["name"] == APP, found
    assert report["app_entry_points"] == APP_ENTRY_POINTS
    assert report["plugins"] == PLUGINS
    assert report["loaded"] == "metaprobe_dep.Demo"


# --------------------------------------------------------------------------- #
# Variants
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("platform_project", PLATFORMS, indirect=True)
def test_dev_install_egg_info(platform_project, request):
    """The baseline: a src layout after ``pip install -e .`` finds its metadata."""
    platform, project = platform_project
    _dev_install_egg_info(project)

    report = _collect(platform, project, request)

    _assert_finds_its_metadata(report)

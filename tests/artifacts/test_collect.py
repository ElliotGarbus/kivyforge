"""Phase 5 — collect_artifacts orchestration (steps 2-5), fully hermetic.

Uses path-based lock entries (no network) with real SHA-256 pins, an injected
subprocess runner in place of pip, and a real tar.gz/zip on disk.
"""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

import pytest

from kivyforge.artifacts import collect as collect_mod
from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.collect import (
    CollectError,
    _compile_pip_deps,
    _drop_wheel_data_files,
    collect_artifacts,
)
from kivyforge.artifacts.verify import sha256_file
from kivyforge.artifacts.wheels import BuildSlice
from kivyforge.config.model import DesktopBuildSettings
from kivyforge.lock.model import LockedPackage, LockedWheel
from kivyforge.platforms.ios.lock.model import (
    LockedXcframework,
    Lockfile,
    PythonXcframework,
)
from kivyforge.platforms.ios.staging import StagingLayout


def _make_python_tarball(root: Path) -> Path:
    src = root / "pysrc"
    (src / "Python.xcframework" / "ios-arm64").mkdir(parents=True)
    (src / "Python.xcframework" / "Info.plist").write_text("<plist/>")
    archive = root / "python.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(src / "Python.xcframework", arcname="Python.xcframework")
    return archive


def _make_wheel(path: Path, members: tuple[str, ...] = ()) -> Path:
    """A real (if tiny) wheel: collect reads its member list after pip runs."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("pkg-1.0.dist-info/METADATA", "Name: pkg\n")
        for member in members:
            zf.writestr(member, "")
    return path


def _make_xcframework_zip(root: Path, name: str) -> Path:
    src = root / f"{name}-src"
    (src / f"{name}.xcframework" / "ios-arm64").mkdir(parents=True)
    (src / f"{name}.xcframework" / "Info.plist").write_text("<plist/>")
    archive = root / f"{name}.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for p in (src / f"{name}.xcframework").rglob("*"):
            zf.write(p, p.relative_to(src))
    return archive


@pytest.fixture
def layout(tmp_path):
    root = tmp_path / "app-ios"
    for d in (
        root,
        root / "Frameworks",
        root / "pip-deps-device",
        root / "pip-deps-simulator",
        root / "Resources",
    ):
        d.mkdir(parents=True)
    return StagingLayout(root=root)


@pytest.fixture
def cache(tmp_path):
    return ArtifactCache(root=tmp_path / "cache")


def test_collect_installs_python_wheels_and_frameworks(tmp_path, layout, cache):
    art = tmp_path / "art"
    art.mkdir()
    py_tar = _make_python_tarball(art)
    wheel = art / "kivy-3.0.0-cp315-cp315-ios_13_0_arm64_iphoneos.whl"
    _make_wheel(wheel)
    native = _make_xcframework_zip(art, "SDL3")

    lock = Lockfile(
        requires_python=">=3.15",
        packages=(
            LockedPackage(
                name="kivy",
                version="3.0.0",
                wheels=(
                    LockedWheel(
                        name=wheel.name,
                        sha256=sha256_file(wheel),
                        path=str(wheel.relative_to(tmp_path)),
                    ),
                ),
            ),
        ),
        python_xcframework=PythonXcframework(
            version="3.15.0",
            url="https://example/python.tar.gz",
            sha256=sha256_file(py_tar),
        ),
        kivyforge_version="3.0.0.dev0",
        generated_at="2026-01-01T00:00:00Z",
        lock_inputs_sha256="d" * 64,
        tool_kivyforge_schema_version=1,
        xcframeworks=(
            LockedXcframework(
                name="SDL3",
                version="3.0.0",
                sha256=sha256_file(native),
                slices=("ios-arm64",),
                path=str(native.relative_to(tmp_path)),
                archive_format="zip",
            ),
        ),
    )

    class FakeDownloader:
        def fetch_to(self, url, dest):
            # Python.xcframework is the only url-based artifact here.
            import shutil

            shutil.copyfile(py_tar, dest)

    pip_calls = []

    def fake_runner(cmd, capture_output=True, text=True):
        pip_calls.append(cmd)
        # Simulate pip laying down a wheel-embedded .frameworks dir inside
        # the slice-specific pip-deps (device build → pip-deps-device/).
        emb = layout.pip_deps_device / "kivy.frameworks" / "ANGLE.xcframework"
        emb.mkdir(parents=True)
        (emb / "Info.plist").write_text("<plist/>")

        class P:
            returncode = 0
            stdout = ""
            stderr = ""

        return P()

    collect_artifacts(
        lock,
        layout,
        build_slices=[BuildSlice("device", "arm64", "13.0")],
        project_root=tmp_path,
        cache=cache,
        downloader=FakeDownloader(),
        runner=fake_runner,
    )

    # Python.xcframework extracted in place.
    assert (layout.python_xcframework / "Info.plist").is_file()
    # pip install invoked once with the wheel + cross-install flags.
    assert len(pip_calls) == 1
    assert "--platform" in pip_calls[0]
    assert any(c.endswith(wheel.name) for c in pip_calls[0])
    # wheel-embedded + native frameworks both landed in Frameworks/.
    assert (layout.frameworks / "ANGLE.xcframework").is_dir()
    assert (layout.frameworks / "SDL3.xcframework").is_dir()
    assert not (layout.pip_deps_device / "kivy.frameworks").exists()


def test_collect_zero_dep_app_stamps_empty_slice(tmp_path, layout, cache):
    # An app with no third-party deps installs nothing, but collection must still
    # stamp the slice as collected so the Build Python guard accepts the (empty)
    # slice instead of failing the build.
    art = tmp_path / "art"
    art.mkdir()
    py_tar = _make_python_tarball(art)

    lock = Lockfile(
        requires_python=">=3.15",
        packages=(),
        python_xcframework=PythonXcframework(
            version="3.15.0",
            url="https://example/python.tar.gz",
            sha256=sha256_file(py_tar),
        ),
        kivyforge_version="3.0.0.dev0",
        generated_at="2026-01-01T00:00:00Z",
        lock_inputs_sha256="d" * 64,
        tool_kivyforge_schema_version=1,
        xcframeworks=(),
    )

    class FakeDownloader:
        def fetch_to(self, url, dest):
            import shutil

            shutil.copyfile(py_tar, dest)

    def fake_runner(cmd, capture_output=True, text=True):
        raise AssertionError("pip must not run when there are no wheels")

    collect_artifacts(
        lock,
        layout,
        build_slices=[BuildSlice("simulator", "arm64", "13.0")],
        project_root=tmp_path,
        cache=cache,
        downloader=FakeDownloader(),
        runner=fake_runner,
    )

    marker = layout.root / "pip-deps-simulator.collected"
    assert marker.is_file()
    assert layout.pip_deps_simulator.is_dir()
    assert not any(layout.pip_deps_simulator.iterdir())  # empty, but collected


def test_collect_zero_dep_app_clears_the_previous_slice(tmp_path, layout, cache):
    # Removing the last dependency used to skip the clean slate along with pip,
    # so the slice kept the previous collect's packages and the app shipped them.
    art = tmp_path / "art"
    art.mkdir()
    py_tar = _make_python_tarball(art)
    previous = layout.pip_deps_simulator / "pyobjus"
    previous.mkdir(parents=True)
    (previous / "pyobjus.cpython-315-iphonesimulator.so").write_text("")

    lock = Lockfile(
        requires_python=">=3.15",
        packages=(),
        python_xcframework=PythonXcframework(
            version="3.15.0",
            url="https://example/python.tar.gz",
            sha256=sha256_file(py_tar),
        ),
        kivyforge_version="3.0.0.dev0",
        generated_at="2026-01-01T00:00:00Z",
        lock_inputs_sha256="d" * 64,
        tool_kivyforge_schema_version=1,
    )

    class FakeDownloader:
        def fetch_to(self, url, dest):
            import shutil

            shutil.copyfile(py_tar, dest)

    def boom(*a, **k):
        raise AssertionError("pip should not run with no packages")

    collect_artifacts(
        lock,
        layout,
        build_slices=[BuildSlice("simulator", "arm64", "13.0")],
        project_root=tmp_path,
        cache=cache,
        downloader=FakeDownloader(),
        runner=boom,
    )

    assert layout.pip_deps_simulator.is_dir()
    assert not any(layout.pip_deps_simulator.iterdir())
    assert (layout.root / "pip-deps-simulator.collected").is_file()


def test_collect_both_slices_installs_each_pip_deps(tmp_path, layout, cache):
    # A bare `kivyforge build` collects device + simulator: Python.xcframework is
    # fetched once, but pip-deps is installed into BOTH slice directories so
    # either Xcode destination builds without re-running the toolchain.
    art = tmp_path / "art"
    art.mkdir()
    py_tar = _make_python_tarball(art)
    wheel = art / "purepkg-1.0-py3-none-any.whl"
    _make_wheel(wheel)

    lock = Lockfile(
        requires_python=">=3.15",
        packages=(
            LockedPackage(
                name="purepkg",
                version="1.0",
                wheels=(
                    LockedWheel(
                        name=wheel.name,
                        sha256=sha256_file(wheel),
                        path=str(wheel.relative_to(tmp_path)),
                    ),
                ),
            ),
        ),
        python_xcframework=PythonXcframework(
            version="3.15.0",
            url="https://example/python.tar.gz",
            sha256=sha256_file(py_tar),
        ),
        kivyforge_version="3.0.0.dev0",
        generated_at="2026-01-01T00:00:00Z",
        lock_inputs_sha256="d" * 64,
        tool_kivyforge_schema_version=1,
    )

    class FakeDownloader:
        def fetch_to(self, url, dest):
            import shutil

            shutil.copyfile(py_tar, dest)

    target_dirs = []

    def fake_runner(cmd, capture_output=True, text=True):
        target_dirs.append(cmd[cmd.index("--target") + 1])

        class P:
            returncode = 0
            stdout = ""
            stderr = ""

        return P()

    collect_artifacts(
        lock,
        layout,
        build_slices=[
            BuildSlice("device", "arm64", "13.0"),
            BuildSlice("simulator", "arm64", "13.0"),
        ],
        project_root=tmp_path,
        cache=cache,
        downloader=FakeDownloader(),
        runner=fake_runner,
    )

    # Python.xcframework extracted exactly once (shared, slice-independent).
    assert (layout.python_xcframework / "Info.plist").is_file()
    # pip ran once per slice, each into its own slice-specific pip-deps dir.
    assert target_dirs == [
        str(layout.pip_deps_device),
        str(layout.pip_deps_simulator),
    ]


def test_collect_no_packages_skips_pip(tmp_path, layout, cache):
    art = tmp_path / "art"
    art.mkdir()
    py_tar = _make_python_tarball(art)
    lock = Lockfile(
        requires_python=">=3.15",
        packages=(),
        python_xcframework=PythonXcframework(
            version="3.15.0",
            url="https://example/python.tar.gz",
            sha256=sha256_file(py_tar),
        ),
        kivyforge_version="3.0.0.dev0",
        generated_at="2026-01-01T00:00:00Z",
        lock_inputs_sha256="d" * 64,
        tool_kivyforge_schema_version=1,
    )

    class FakeDownloader:
        def fetch_to(self, url, dest):
            import shutil

            shutil.copyfile(py_tar, dest)

    def boom(*a, **k):  # pip must not be called with zero wheels
        raise AssertionError("pip should not run with no packages")

    collect_artifacts(
        lock,
        layout,
        build_slices=[BuildSlice("device", "arm64", "13.0")],
        project_root=tmp_path,
        cache=cache,
        downloader=FakeDownloader(),
        runner=boom,
    )
    assert (layout.python_xcframework / "Info.plist").is_file()


class TestDropWheelDataFiles:
    """A wheel's ``.data/data/`` tree never reaches an iOS pip-deps slice."""

    def _install(self, slice_dir: Path, *rel: str) -> None:
        for r in rel:
            (slice_dir / r).parent.mkdir(parents=True, exist_ok=True)
            (slice_dir / r).write_text("x")

    def test_data_files_are_removed_and_empty_dirs_pruned(self, tmp_path):
        """pyobjus's real shape: Python 2 examples and Obj-C test sources."""
        slice_dir = tmp_path / "pip-deps-device"
        self._install(
            slice_dir,
            "pyobjus/__init__.py",
            "share/pyobjus-examples/properties.py",
            "share/pyobjus-examples/ball-example/main.py",
            "objc_classes/objc_classes/test/testlib.m",
        )
        wheel = _make_wheel(
            tmp_path / "pyobjus-1.2.5-cp315-cp315-ios_13_0_arm64_iphoneos.whl",
            (
                "pyobjus/__init__.py",
                "pyobjus-1.2.5.data/data/share/pyobjus-examples/properties.py",
                "pyobjus-1.2.5.data/data/share/pyobjus-examples/ball-example/main.py",
                "pyobjus-1.2.5.data/data/objc_classes/objc_classes/test/testlib.m",
            ),
        )
        _drop_wheel_data_files(wheel, slice_dir)
        assert sorted(
            p.relative_to(slice_dir).as_posix() for p in slice_dir.rglob("*")
        ) == ["pyobjus", "pyobjus/__init__.py"]

    def test_a_data_file_inside_a_package_leaves_the_package(self, tmp_path):
        slice_dir = tmp_path / "pip-deps-device"
        self._install(slice_dir, "pkg/__init__.py", "pkg/extra.txt")
        wheel = _make_wheel(
            tmp_path / "pkg-1.0-py3-none-any.whl",
            ("pkg/__init__.py", "pkg-1.0.data/data/pkg/extra.txt"),
        )
        _drop_wheel_data_files(wheel, slice_dir)
        assert (slice_dir / "pkg/__init__.py").is_file()
        assert not (slice_dir / "pkg/extra.txt").exists()

    def test_a_data_file_at_the_prefix_root_is_removed(self, tmp_path):
        slice_dir = tmp_path / "pip-deps-device"
        self._install(slice_dir, "README.txt")
        wheel = _make_wheel(
            tmp_path / "pkg-1.0-py3-none-any.whl", ("pkg-1.0.data/data/README.txt",)
        )
        _drop_wheel_data_files(wheel, slice_dir)
        assert slice_dir.is_dir()
        assert not any(slice_dir.iterdir())

    def test_purelib_and_platlib_are_not_data(self, tmp_path):
        """Only the ``data`` scheme goes; the importable schemes stay."""
        slice_dir = tmp_path / "pip-deps-device"
        self._install(slice_dir, "pkg/__init__.py")
        wheel = _make_wheel(
            tmp_path / "pkg-1.0-py3-none-any.whl",
            ("pkg-1.0.data/purelib/pkg/__init__.py",),
        )
        _drop_wheel_data_files(wheel, slice_dir)
        assert (slice_dir / "pkg/__init__.py").is_file()

    def test_a_path_outside_the_slice_is_never_touched(self, tmp_path):
        slice_dir = tmp_path / "pip-deps-device"
        slice_dir.mkdir()
        outside = tmp_path / "keep.txt"
        outside.write_text("x")
        wheel = _make_wheel(
            tmp_path / "pkg-1.0-py3-none-any.whl", ("pkg-1.0.data/data/../keep.txt",)
        )
        _drop_wheel_data_files(wheel, slice_dir)
        assert outside.is_file()


def test_collect_drops_wheel_data_files_from_the_slice(tmp_path, layout, cache):
    """The wiring: what pip lays down from ``.data/data`` is gone after collect."""
    art = tmp_path / "art"
    art.mkdir()
    py_tar = _make_python_tarball(art)
    wheel = _make_wheel(
        art / "pyobjus-1.2.5-cp315-cp315-ios_13_0_arm64_iphoneos.whl",
        ("pyobjus-1.2.5.data/data/share/pyobjus-examples/properties.py",),
    )
    lock = Lockfile(
        requires_python=">=3.15",
        packages=(
            LockedPackage(
                name="pyobjus",
                version="1.2.5",
                wheels=(
                    LockedWheel(
                        name=wheel.name,
                        sha256=sha256_file(wheel),
                        path=str(wheel.relative_to(tmp_path)),
                    ),
                ),
            ),
        ),
        python_xcframework=PythonXcframework(
            version="3.15.0",
            url="https://example/python.tar.gz",
            sha256=sha256_file(py_tar),
        ),
        kivyforge_version="3.0.0.dev0",
        generated_at="2026-01-01T00:00:00Z",
        lock_inputs_sha256="d" * 64,
        tool_kivyforge_schema_version=1,
        xcframeworks=(),
    )

    class FakeDownloader:
        def fetch_to(self, url, dest):
            import shutil

            shutil.copyfile(py_tar, dest)

    def fake_runner(cmd, capture_output=True, text=True):
        # What `pip install --target` does with the wheel above.
        pkg = layout.pip_deps_device / "pyobjus"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        examples = layout.pip_deps_device / "share" / "pyobjus-examples"
        examples.mkdir(parents=True)
        (examples / "properties.py").write_text("print car.propInt\n")

        class P:
            returncode = 0
            stdout = ""
            stderr = ""

        return P()

    collect_artifacts(
        lock,
        layout,
        build_slices=[BuildSlice("device", "arm64", "13.0")],
        project_root=tmp_path,
        cache=cache,
        downloader=FakeDownloader(),
        runner=fake_runner,
    )

    assert (layout.pip_deps_device / "pyobjus" / "__init__.py").is_file()
    assert not (layout.pip_deps_device / "share").exists()


class TestCompilePipDeps:
    """``byte_compile``/``strip_source`` for a collected pip-deps slice
    (pyproject-ios §build_settings). ``select_compiler`` is stubbed here (it
    has its own tests in tests/bundle/test_pycompile.py); the interesting
    behavior at this layer is the tri-state resolution and the
    degrade-vs-error split.
    """

    def _select(self, monkeypatch, result):
        monkeypatch.setattr(collect_mod, "select_compiler", lambda **kw: result)

    def _deps_with_module(self, tmp_path):
        deps = tmp_path / "pip-deps-device"
        (deps / "pkg").mkdir(parents=True)
        (deps / "pkg" / "mod.py").write_text("x = 1\n")
        return deps

    def test_release_default_compiles_and_strips(self, tmp_path, monkeypatch):
        self._select(monkeypatch, ())
        deps = self._deps_with_module(tmp_path)
        _compile_pip_deps(
            deps,
            python_version="3.15.0",
            release=True,
            build_settings=None,
            echo=lambda m: None,
        )
        assert not (deps / "pkg" / "mod.py").exists()
        assert (deps / "pkg" / "mod.pyc").is_file()

    def test_dev_build_skips(self, tmp_path, monkeypatch):
        self._select(monkeypatch, ())
        deps = self._deps_with_module(tmp_path)
        _compile_pip_deps(
            deps,
            python_version="3.15.0",
            release=False,
            build_settings=None,
            echo=lambda m: None,
        )
        assert (deps / "pkg" / "mod.py").exists()

    def test_false_never_compiles(self, tmp_path, monkeypatch):
        self._select(monkeypatch, ())
        deps = self._deps_with_module(tmp_path)
        _compile_pip_deps(
            deps,
            python_version="3.15.0",
            release=True,
            build_settings=DesktopBuildSettings(byte_compile=False),
            echo=lambda m: None,
        )
        assert (deps / "pkg" / "mod.py").exists()

    def test_default_degrades_when_no_compiler_found(self, tmp_path, monkeypatch):
        self._select(monkeypatch, None)
        deps = tmp_path / "pip-deps-device"
        deps.mkdir()
        messages = []
        _compile_pip_deps(
            deps,
            python_version="3.15.0",
            release=True,
            build_settings=None,
            echo=messages.append,
        )
        assert any("not byte-compiling" in m for m in messages)
        # The notice must say how to fix it, not just what happened.
        assert any("Fix: install a final CPython" in m for m in messages)

    def test_explicit_true_fails_when_no_compiler_found(self, tmp_path, monkeypatch):
        self._select(monkeypatch, None)
        deps = tmp_path / "pip-deps-device"
        deps.mkdir()
        with pytest.raises(CollectError, match="byte_compile = true"):
            _compile_pip_deps(
                deps,
                python_version="3.15.0",
                release=True,
                build_settings=DesktopBuildSettings(byte_compile=True),
                echo=lambda m: None,
            )

    def test_missing_dir_is_a_noop(self, tmp_path, monkeypatch):
        # _install_wheels may not create slice_pip_deps at all when a slice
        # has zero third-party deps.
        self._select(monkeypatch, ())
        deps = tmp_path / "pip-deps-device"
        _compile_pip_deps(  # no raise
            deps,
            python_version="3.15.0",
            release=True,
            build_settings=None,
            echo=lambda m: None,
        )


class TestCollectArtifactsByteCompileWiring:
    def test_release_reaches_the_pip_deps_slice(
        self, tmp_path, layout, cache, monkeypatch
    ):
        monkeypatch.setattr(collect_mod, "select_compiler", lambda **kw: ())
        art = tmp_path / "art"
        art.mkdir()
        py_tar = _make_python_tarball(art)
        wheel = art / "purepkg-1.0-py3-none-any.whl"
        _make_wheel(wheel)

        lock = Lockfile(
            requires_python=">=3.15",
            packages=(
                LockedPackage(
                    name="purepkg",
                    version="1.0",
                    wheels=(
                        LockedWheel(
                            name=wheel.name,
                            sha256=sha256_file(wheel),
                            path=str(wheel.relative_to(tmp_path)),
                        ),
                    ),
                ),
            ),
            python_xcframework=PythonXcframework(
                version="3.15.0",
                url="https://example/python.tar.gz",
                sha256=sha256_file(py_tar),
            ),
            kivyforge_version="3.0.0.dev0",
            generated_at="2026-01-01T00:00:00Z",
            lock_inputs_sha256="d" * 64,
            tool_kivyforge_schema_version=1,
        )

        class FakeDownloader:
            def fetch_to(self, url, dest):
                import shutil

                shutil.copyfile(py_tar, dest)

        def fake_runner(cmd, capture_output=True, text=True):
            # Simulate pip actually installing a pure-Python module.
            target = Path(cmd[cmd.index("--target") + 1])
            (target / "purepkg.py").write_text("x = 1\n")

            class P:
                returncode = 0
                stdout = ""
                stderr = ""

            return P()

        collect_artifacts(
            lock,
            layout,
            build_slices=[BuildSlice("device", "arm64", "13.0")],
            project_root=tmp_path,
            cache=cache,
            downloader=FakeDownloader(),
            runner=fake_runner,
            release=True,
            build_settings=DesktopBuildSettings(byte_compile=True, strip_source=True),
        )

        assert not (layout.pip_deps_device / "purepkg.py").exists()
        assert (layout.pip_deps_device / "purepkg.pyc").is_file()

    def test_dev_build_never_compiles(self, tmp_path, layout, cache):
        art = tmp_path / "art"
        art.mkdir()
        py_tar = _make_python_tarball(art)
        wheel = art / "purepkg-1.0-py3-none-any.whl"
        _make_wheel(wheel)

        lock = Lockfile(
            requires_python=">=3.15",
            packages=(
                LockedPackage(
                    name="purepkg",
                    version="1.0",
                    wheels=(
                        LockedWheel(
                            name=wheel.name,
                            sha256=sha256_file(wheel),
                            path=str(wheel.relative_to(tmp_path)),
                        ),
                    ),
                ),
            ),
            python_xcframework=PythonXcframework(
                version="3.15.0",
                url="https://example/python.tar.gz",
                sha256=sha256_file(py_tar),
            ),
            kivyforge_version="3.0.0.dev0",
            generated_at="2026-01-01T00:00:00Z",
            lock_inputs_sha256="d" * 64,
            tool_kivyforge_schema_version=1,
        )

        class FakeDownloader:
            def fetch_to(self, url, dest):
                import shutil

                shutil.copyfile(py_tar, dest)

        def fake_runner(cmd, capture_output=True, text=True):
            target = Path(cmd[cmd.index("--target") + 1])
            (target / "purepkg.py").write_text("x = 1\n")

            class P:
                returncode = 0
                stdout = ""
                stderr = ""

            return P()

        collect_artifacts(
            lock,
            layout,
            build_slices=[BuildSlice("device", "arm64", "13.0")],
            project_root=tmp_path,
            cache=cache,
            downloader=FakeDownloader(),
            runner=fake_runner,
            # release defaults to False; build_settings defaults to "release".
        )

        assert (layout.pip_deps_device / "purepkg.py").exists()


class TestRemovedXcframeworks:
    """An xcframework leaves Frameworks/ with the wheel or lock entry that staged it.

    Collect only ever added to Frameworks/, so after kivy left the lock
    SDL3.xcframework stayed staged, and the project linked and embedded it in
    every later build.
    """

    def _lock(self, tmp_path, py_tar, *, wheel=None, native=None):
        packages = ()
        if wheel is not None:
            packages = (
                LockedPackage(
                    name="kivy",
                    version="3.0.0",
                    wheels=(
                        LockedWheel(
                            name=wheel.name,
                            sha256=sha256_file(wheel),
                            path=str(wheel.relative_to(tmp_path)),
                        ),
                    ),
                ),
            )
        xcframeworks = ()
        if native is not None:
            xcframeworks = (
                LockedXcframework(
                    name="Sentry",
                    version="8.0.0",
                    sha256=sha256_file(native),
                    slices=("ios-arm64",),
                    path=str(native.relative_to(tmp_path)),
                    archive_format="zip",
                ),
            )
        return Lockfile(
            requires_python=">=3.15",
            packages=packages,
            python_xcframework=PythonXcframework(
                version="3.15.0",
                url="https://example/python.tar.gz",
                sha256=sha256_file(py_tar),
            ),
            kivyforge_version="3.0.0.dev0",
            generated_at="2026-01-01T00:00:00Z",
            lock_inputs_sha256="d" * 64,
            tool_kivyforge_schema_version=1,
            xcframeworks=xcframeworks,
        )

    def _collect(self, tmp_path, layout, cache, py_tar, lock):
        def fake_pip(cmd, capture_output=True, text=True):
            # What pip leaves for the kivy wheel: SDL3 inside kivy.frameworks/.
            slice_ = "ios-arm64_x86_64-simulator"
            xc = layout.pip_deps_simulator / "kivy.frameworks" / "SDL3.xcframework"
            (xc / slice_ / "SDL3.framework").mkdir(parents=True)
            (xc / slice_ / "SDL3.framework" / "SDL3").write_text("binary")
            (xc / "Info.plist").write_text("<plist/>")

            class P:
                returncode = 0
                stdout = ""
                stderr = ""

            return P()

        class FakeDownloader:
            def fetch_to(self, url, dest):
                import shutil

                shutil.copyfile(py_tar, dest)

        collect_artifacts(
            lock,
            layout,
            build_slices=[BuildSlice("simulator", "arm64", "13.0")],
            project_root=tmp_path,
            cache=cache,
            downloader=FakeDownloader(),
            runner=fake_pip,
        )

    def _native_zip(self, art: Path) -> Path:
        src = art / "Sentry-src" / "Sentry.xcframework"
        (src / "ios-arm64" / "Sentry.framework").mkdir(parents=True)
        (src / "ios-arm64" / "Sentry.framework" / "Sentry").write_text("binary")
        (src / "Info.plist").write_text("<plist/>")
        archive = art / "Sentry.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for p in src.rglob("*"):
                zf.write(p, p.relative_to(src.parent))
        return archive

    @pytest.fixture
    def art(self, tmp_path):
        art = tmp_path / "art"
        art.mkdir()
        wheel = _make_wheel(
            art / "kivy-3.0.0-cp315-cp315-ios_13_0_arm64_iphonesimulator.whl"
        )
        return _make_python_tarball(art), wheel, self._native_zip(art)

    def _staged(self, layout) -> list[str]:
        return sorted(p.name for p in layout.frameworks.iterdir())

    def test_dropping_the_wheel_and_native_entry_unstages_both(
        self, tmp_path, layout, cache, art
    ):
        py_tar, wheel, native = art
        full = self._lock(tmp_path, py_tar, wheel=wheel, native=native)
        self._collect(tmp_path, layout, cache, py_tar, full)
        assert self._staged(layout) == ["SDL3.xcframework", "Sentry.xcframework"]

        self._collect(tmp_path, layout, cache, py_tar, self._lock(tmp_path, py_tar))

        assert self._staged(layout) == []

    def test_only_what_left_the_lock_is_unstaged(self, tmp_path, layout, cache, art):
        py_tar, wheel, native = art
        full = self._lock(tmp_path, py_tar, wheel=wheel, native=native)
        self._collect(tmp_path, layout, cache, py_tar, full)

        with_kivy = self._lock(tmp_path, py_tar, wheel=wheel)
        self._collect(tmp_path, layout, cache, py_tar, with_kivy)

        assert self._staged(layout) == ["SDL3.xcframework"]
        sdl3 = layout.frameworks / "SDL3.xcframework"
        assert (sdl3 / "ios-arm64_x86_64-simulator/SDL3.framework/SDL3").is_file()

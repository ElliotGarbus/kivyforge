"""Stage-step unit tests: jniLibs flattening, wheel selection, bundle (android/04)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kivyforge.lock.model import LockedPackage, LockedWheel
from kivyforge.platforms.android.stage import wheels as wheels_mod
from kivyforge.platforms.android.stage.bundle import BundleError, assemble_bundle
from kivyforge.platforms.android.stage.jnilibs import (
    JniLibsError,
    JniLibsStager,
    dotted_module_name,
    stage_runtime_libs,
    stage_site_packages_extensions,
    stage_wheel_libs_dir,
)
from kivyforge.platforms.android.stage.wheels import (
    WheelStageError,
    install_wheels,
    select_wheel,
)


def _write(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class TestJniLibs:
    def test_flatten_and_manifest(self, tmp_path):
        sp = tmp_path / "sp"
        _write(sp / "jnius" / "jnius.cpython-314-x86_64-linux-android.so")
        _write(sp / "kivy" / "core" / "_ev.cpython-314-x86_64-linux-android.so")
        stager = JniLibsStager(dest=tmp_path / "jni")
        count = stage_site_packages_extensions(stager, sp, wheel_name="kivy")
        assert count == 2
        manifest = stager.manifest()
        assert manifest == {
            "jnius.jnius": "libpy.jnius.jnius.so",
            "kivy.core._ev": "libpy.kivy.core._ev.so",
        }
        assert (tmp_path / "jni" / "libpy.jnius.jnius.so").is_file()

    def test_flat_libs_ingested_verbatim(self, tmp_path):
        libs = tmp_path / ".libs"
        _write(libs / "libSDL2.so")
        _write(libs / "libSDL2_image.so")
        stager = JniLibsStager(dest=tmp_path / "jni")
        count = stage_wheel_libs_dir(stager, libs, wheel_name="kivy")
        assert count == 2
        assert (tmp_path / "jni" / "libSDL2.so").is_file()
        assert stager.manifest() == {}  # soname libs are not manifest entries

    def test_nested_libs_is_a_malformed_wheel(self, tmp_path):
        libs = tmp_path / ".libs"
        _write(libs / "x86_64" / "libSDL2.so")
        stager = JniLibsStager(dest=tmp_path / "jni")
        with pytest.raises(JniLibsError, match="flat"):
            stage_wheel_libs_dir(stager, libs, wheel_name="kivy")

    def test_identical_duplicate_dedupes_silently(self, tmp_path):
        a = _write(tmp_path / "a" / "libSDL2.so", b"same")
        b = _write(tmp_path / "b" / "libSDL2.so", b"same")
        stager = JniLibsStager(dest=tmp_path / "jni")
        stager.add_shared_library(a, provider="runtime")
        stager.add_shared_library(b, provider="wheel kivy")  # no raise

    def test_conflicting_duplicate_aborts_naming_both(self, tmp_path):
        a = _write(tmp_path / "a" / "libSDL2.so", b"one")
        b = _write(tmp_path / "b" / "libSDL2.so", b"two")
        stager = JniLibsStager(dest=tmp_path / "jni")
        stager.add_shared_library(a, provider="runtime")
        with pytest.raises(JniLibsError, match="runtime and wheel kivy"):
            stager.add_shared_library(b, provider="wheel kivy")

    def test_runtime_split(self, tmp_path):
        prefix_lib = tmp_path / "prefix" / "lib"
        _write(prefix_lib / "libpython3.14.so")
        _write(prefix_lib / "libssl_python.so")
        _write(prefix_lib / "libssl.so")  # plain copy: NOT shipped
        _write(
            prefix_lib
            / "python3.14"
            / "lib-dynload"
            / "_ssl.cpython-314-x86_64-linux-android.so"
        )
        stager = JniLibsStager(dest=tmp_path / "jni")
        shared, extensions = stage_runtime_libs(
            stager, prefix_lib, python_stem="python3.14"
        )
        assert (shared, extensions) == (2, 1)
        staged = {p.name for p in (tmp_path / "jni").iterdir()}
        assert staged == {"libpython3.14.so", "libssl_python.so", "libpy._ssl.so"}

    def test_manifest_write(self, tmp_path):
        sp = tmp_path / "sp"
        _write(sp / "mod.cpython-314-x86_64-linux-android.so")
        stager = JniLibsStager(dest=tmp_path / "jni")
        stage_site_packages_extensions(stager, sp, wheel_name="m")
        out = stager.write_manifest(tmp_path / "bootstrap")
        assert json.loads(out.read_text()) == {"mod": "libpy.mod.so"}

    def test_dotted_name(self, tmp_path):
        sp = tmp_path
        so = _write(sp / "pkg" / "sub" / "_c.cpython-314-arm64.so")
        assert dotted_module_name(so, sp) == "pkg.sub._c"


def _pkg(*tags: str) -> LockedPackage:
    wheels = tuple(
        LockedWheel(
            name=f"p-1.0-cp314-cp314-{tag}.whl"
            if tag != "py3-none-any"
            else "p-1.0-py3-none-any.whl",
            url=f"https://x/{tag}.whl",
            sha256="a" * 64,
        )
        for tag in tags
    )
    return LockedPackage(name="p", version="1.0", wheels=wheels)


class TestSelectWheel:
    def test_exact_abi(self):
        pkg = _pkg("android_24_arm64_v8a", "android_24_x86_64")
        assert "arm64_v8a" in select_wheel(pkg, abi="arm64_v8a", min_sdk=24).name

    def test_floor_rule_prefers_highest_compatible(self):
        pkg = _pkg("android_21_x86_64", "android_24_x86_64", "android_26_x86_64")
        chosen = select_wheel(pkg, abi="x86_64", min_sdk=24)
        assert "android_24_x86_64" in chosen.name

    def test_lower_tag_accepted_when_only_option(self):
        pkg = _pkg("android_21_x86_64")
        assert select_wheel(pkg, abi="x86_64", min_sdk=24)

    def test_pure_python_shared(self):
        pkg = _pkg("py3-none-any")
        assert select_wheel(pkg, abi="arm64_v8a", min_sdk=24).is_pure_python

    def test_missing_abi_raises(self):
        pkg = _pkg("android_24_x86_64")
        with pytest.raises(WheelStageError, match="arm64_v8a"):
            select_wheel(pkg, abi="arm64_v8a", min_sdk=24)

    def test_non_numeric_api_tag_ignored(self):
        # A malformed/foreign platform tag with a non-numeric "api" segment
        # must not crash selection — it is simply not a candidate.
        pkg = _pkg("android_24_arm64_v8a")
        wheels = list(pkg.wheels) + [
            LockedWheel(
                name="p-1.0-cp314-cp314-android_x_arm64_v8a.whl",
                url="https://x/android_x_arm64_v8a.whl",
                sha256="a" * 64,
            )
        ]
        pkg2 = LockedPackage(name="p", version="1.0", wheels=tuple(wheels))
        chosen = select_wheel(pkg2, abi="arm64_v8a", min_sdk=24)
        assert "android_24_arm64_v8a" in chosen.name

    def test_multiple_pure_python_wheels_first_one_wins(self):
        pkg = _pkg("py3-none-any")
        wheels = tuple(pkg.wheels) * 2
        pkg2 = LockedPackage(name="p", version="1.0", wheels=wheels)
        chosen = select_wheel(pkg2, abi="arm64_v8a", min_sdk=24)
        assert chosen.is_pure_python


class TestInstallWheels:
    def test_no_wheel_files_creates_empty_target(self, tmp_path):
        target = tmp_path / "target"
        install_wheels([], target, python_version="3.14.0")
        assert target.is_dir()

    def test_success_invokes_pip_with_expected_flags(self, tmp_path, monkeypatch):
        target = tmp_path / "target"
        wheel = tmp_path / "kivy-3.0.0-cp314-cp314-android_24_arm64_v8a.whl"
        wheel.write_bytes(b"x")
        pure = tmp_path / "attrs-24.0.0-py3-none-any.whl"
        pure.write_bytes(b"x")
        captured = {}

        def fake_run(cmd, capture_output, text):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(wheels_mod.subprocess, "run", fake_run)
        install_wheels(
            [wheel, pure],
            target,
            python_version="3.14.0",
            python_executable="/usr/bin/python3.14",
        )
        cmd = captured["cmd"]
        assert cmd[0] == "/usr/bin/python3.14"
        assert "--no-index" in cmd
        assert "--target" in cmd
        assert str(target) in cmd
        assert "android_24_arm64_v8a" in cmd
        assert "any" not in cmd  # the "any" tag is never passed to pip
        assert str(wheel) in cmd
        assert str(pure) in cmd

    def test_default_python_executable_is_sys_executable(self, tmp_path, monkeypatch):
        wheel = tmp_path / "p-1.0-py3-none-any.whl"
        wheel.write_bytes(b"x")
        captured = {}

        def fake_run(cmd, capture_output, text):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(wheels_mod.subprocess, "run", fake_run)
        install_wheels([wheel], tmp_path / "target", python_version="3.14.0")
        assert captured["cmd"][0] == wheels_mod.sys.executable

    def test_pip_failure_wrapped(self, tmp_path, monkeypatch):
        wheel = tmp_path / "p-1.0-py3-none-any.whl"
        wheel.write_bytes(b"x")

        def fake_run(cmd, capture_output, text):
            return subprocess.CompletedProcess(
                cmd, 1, stdout="", stderr="ERROR: no such wheel"
            )

        monkeypatch.setattr(wheels_mod.subprocess, "run", fake_run)
        with pytest.raises(WheelStageError, match="could not install"):
            install_wheels([wheel], tmp_path / "target", python_version="3.14.0")


class TestBundle:
    def _stage(self, tmp_path, *, skew: bool = False):
        stdlib = tmp_path / "stdlib-src"
        _write(stdlib / "os.py", b"# os")
        _write(stdlib / "encodings" / "__init__.py")
        _write(stdlib / "lib-dynload" / "_ssl.so")  # excluded
        _write(stdlib / "__pycache__" / "os.pyc")  # excluded
        _write(stdlib / "data.gz")  # excluded (AGP decompression trap)
        sp = {}
        for abi in ("arm64_v8a", "x86_64"):
            root = tmp_path / f"sp-{abi}"
            _write(root / "jnius" / "__init__.py", b"# jnius")
            _write(root / "jnius" / f"jnius.{abi}.so")  # excluded per-ABI
            _write(root / ".libs" / "libSDL2.so")  # excluded (hoisted)
            if skew and abi == "x86_64":
                _write(root / "jnius" / "__init__.py", b"# DIFFERENT")
            sp[abi] = root
        app = tmp_path / "app-src"
        _write(app / "main.py", b"print('hi')")
        return stdlib, sp, app

    def test_assemble(self, tmp_path):
        stdlib, sp, app = self._stage(tmp_path)
        bundle = tmp_path / "bundle"
        stamp = assemble_bundle(
            bundle,
            stdlib_src=stdlib,
            site_packages_by_abi=sp,
            canonical_abi="arm64_v8a",
            app_src=app,
            finder_source="# finder",
            kivy_bootstrap_source="# kivy contract",
            ext_manifest_json="{}",
        )
        assert (bundle / "stdlib" / "os.py").is_file()
        assert not (bundle / "stdlib" / "lib-dynload").exists()
        assert not (bundle / "stdlib" / "data.gz").exists()
        assert (bundle / "site-packages" / "jnius" / "__init__.py").is_file()
        assert not list((bundle / "site-packages").rglob("*.so"))
        assert not (bundle / "site-packages" / ".libs").exists()
        assert (bundle / "app" / "main.py").is_file()
        assert (bundle / "bootstrap" / "ext_manifest.json").is_file()
        assert (bundle / "bootstrap" / "_kivyforge_bootstrap.py").is_file()
        # Kivy imports this by name to reach the Activity; if it is missing the
        # app starts and then fails as soon as Kivy needs the Activity.
        assert (
            bundle / "bootstrap" / "_kivy_bootstrap.py"
        ).read_text() == "# kivy contract"
        assert (bundle / "VERSION").read_text() == stamp

    def _kwargs(self, tmp_path):
        stdlib, sp, app = self._stage(tmp_path)
        return dict(
            stdlib_src=stdlib,
            site_packages_by_abi=sp,
            canonical_abi="arm64_v8a",
            app_src=app,
            finder_source="# finder",
            kivy_bootstrap_source="# kivy contract",
            ext_manifest_json="{}",
        )

    def test_byte_compile_keeps_source_in_the_pycache_layout(self, tmp_path):
        """With the source shipped, .pyc belongs in __pycache__ — that is where
        an import next to a .py looks for it."""
        bundle = tmp_path / "bundle"
        assemble_bundle(bundle, byte_compile=(), **self._kwargs(tmp_path))
        assert (bundle / "app" / "main.py").is_file()
        assert list((bundle / "app" / "__pycache__").glob("main.*.pyc"))
        assert not (bundle / "app" / "main.pyc").exists()

    def test_strip_source_uses_the_sourceless_layout(self, tmp_path):
        """PEP 3147 sourceless imports only look for foo.pyc at the source's own
        path; compiling into __pycache__ and deleting the .py would ship a
        bundle that imports nothing at all."""
        bundle = tmp_path / "bundle"
        assemble_bundle(
            bundle, byte_compile=(), strip_source=True, **self._kwargs(tmp_path)
        )
        assert (bundle / "app" / "main.pyc").is_file()
        assert not (bundle / "app" / "main.py").exists()
        assert not list(bundle.rglob("*.py"))
        assert not list(bundle.rglob("__pycache__"))
        # The finder and Kivy's contract module have to survive the strip.
        assert (bundle / "bootstrap" / "_kivyforge_bootstrap.pyc").is_file()
        assert (bundle / "bootstrap" / "_kivy_bootstrap.pyc").is_file()

    def test_byte_compiled_stamp_is_deterministic(self, tmp_path):
        """Hash-based .pyc, not mtime-based: an mtime in every .pyc would make
        the bundle stamp differ per machine and re-unpack for no reason."""
        one = assemble_bundle(
            tmp_path / "b1",
            byte_compile=(),
            strip_source=True,
            **self._kwargs(tmp_path),
        )
        two = assemble_bundle(
            tmp_path / "b2",
            byte_compile=(),
            strip_source=True,
            **self._kwargs(tmp_path),
        )
        assert one == two

    def test_pyc_carries_no_host_paths(self, tmp_path):
        """A .pyc records the path it was compiled from; the default would ship
        the build machine's directory layout inside the APK."""
        bundle = tmp_path / "bundle"
        assemble_bundle(
            bundle, byte_compile=(), strip_source=True, **self._kwargs(tmp_path)
        )
        blob = (bundle / "app" / "main.pyc").read_bytes()
        assert str(tmp_path).encode() not in blob
        # Bundle-relative, so tracebacks still name the file.
        assert b"main.py" in blob

    def test_syntax_error_fails_the_build(self, tmp_path):
        kwargs = self._kwargs(tmp_path)
        _write(kwargs["app_src"] / "broken.py", b"def (:\n")
        with pytest.raises(BundleError, match="byte-compiling"):
            assemble_bundle(tmp_path / "bundle", byte_compile=(), **kwargs)

    def test_no_byte_compile_leaves_source_alone(self, tmp_path):
        bundle = tmp_path / "bundle"
        assemble_bundle(bundle, **self._kwargs(tmp_path))
        assert (bundle / "app" / "main.py").is_file()
        assert not list(bundle.rglob("*.pyc"))

    def test_missing_entry_point_fails(self, tmp_path):
        stdlib, sp, app = self._stage(tmp_path)
        with pytest.raises(BundleError, match="entry point"):
            assemble_bundle(
                tmp_path / "bundle",
                stdlib_src=stdlib,
                site_packages_by_abi=sp,
                canonical_abi="arm64_v8a",
                app_src=app,
                entry_point="nope",
                finder_source="# finder",
                kivy_bootstrap_source="# kivy contract",
                ext_manifest_json="{}",
            )

    def test_dotted_and_package_entry_points_accepted(self, tmp_path):
        stdlib, sp, app = self._stage(tmp_path)
        _write(app / "pkg" / "__init__.py")
        _write(app / "pkg" / "start.py", b"# start")
        kwargs = dict(
            stdlib_src=stdlib,
            site_packages_by_abi=sp,
            canonical_abi="arm64_v8a",
            app_src=app,
            finder_source="# finder",
            kivy_bootstrap_source="# kivy contract",
            ext_manifest_json="{}",
        )
        assemble_bundle(tmp_path / "b-dotted", entry_point="pkg.start", **kwargs)
        # A package entry point runs its __init__.py (common pyproject spec).
        assemble_bundle(tmp_path / "b-package", entry_point="pkg", **kwargs)

    def test_missing_service_entry_point_names_the_service(self, tmp_path):
        """A service's entry point fails in its own process, where nothing is
        watching, so an unresolvable one has to fail the build instead."""
        stdlib, sp, app = self._stage(tmp_path)
        with pytest.raises(BundleError, match="services.*'Downloader'"):
            assemble_bundle(
                tmp_path / "bundle",
                stdlib_src=stdlib,
                site_packages_by_abi=sp,
                canonical_abi="arm64_v8a",
                app_src=app,
                service_entry_points={"Downloader": "svc.worker"},
                finder_source="# finder",
                kivy_bootstrap_source="# kivy contract",
                ext_manifest_json="{}",
            )

    def test_present_service_entry_point_passes(self, tmp_path):
        stdlib, sp, app = self._stage(tmp_path)
        _write(app / "svc" / "__init__.py")
        _write(app / "svc" / "worker.py", b"# worker")
        assemble_bundle(
            tmp_path / "bundle",
            stdlib_src=stdlib,
            site_packages_by_abi=sp,
            canonical_abi="arm64_v8a",
            app_src=app,
            service_entry_points={"Downloader": "svc.worker"},
            finder_source="# finder",
            kivy_bootstrap_source="# kivy contract",
            ext_manifest_json="{}",
        )

    def test_stamp_tracks_content(self, tmp_path):
        stdlib, sp, app = self._stage(tmp_path)
        kwargs = dict(
            stdlib_src=stdlib,
            site_packages_by_abi=sp,
            canonical_abi="arm64_v8a",
            app_src=app,
            finder_source="# finder",
            kivy_bootstrap_source="# kivy contract",
            ext_manifest_json="{}",
        )
        stamp1 = assemble_bundle(tmp_path / "b1", **kwargs)
        stamp2 = assemble_bundle(tmp_path / "b2", **kwargs)
        assert stamp1 == stamp2  # deterministic
        _write(app / "extra.py", b"new = 1")
        stamp3 = assemble_bundle(tmp_path / "b3", **kwargs)
        assert stamp3 != stamp1

    def test_dist_info_record_wheel_exempt_from_identity(self, tmp_path):
        # RECORD/WHEEL differ per ABI by design (they list the ABI wheel's own
        # files/tags); the identity assertion must not trip on them.
        stdlib, sp, app = self._stage(tmp_path)
        for abi, root in sp.items():
            _write(root / "p-1.0.dist-info" / "RECORD", abi.encode())
            _write(root / "p-1.0.dist-info" / "WHEEL", abi.encode())
            _write(root / "p-1.0.dist-info" / "direct_url.json", abi.encode())
            _write(root / "p-1.0.dist-info" / "METADATA", b"same")
        bundle = tmp_path / "bundle"
        assemble_bundle(
            bundle,
            stdlib_src=stdlib,
            site_packages_by_abi=sp,
            canonical_abi="arm64_v8a",
            app_src=app,
            finder_source="# finder",
            kivy_bootstrap_source="# kivy contract",
            ext_manifest_json="{}",
        )  # must not raise
        info = bundle / "site-packages" / "p-1.0.dist-info"
        assert (info / "RECORD").is_file()  # canonical ABI's copy ships
        # per-ABI install-source record never ships (leaks host paths)
        assert not (info / "direct_url.json").exists()

    def test_console_scripts_never_ship(self, tmp_path):
        """pip generates bin/ launchers for the *host*, so a Windows install
        puts .exe wrappers in an Android APK. They also embed the per-ABI
        target path, so they differ between slices and trip the identity
        assertion — which is how this surfaced: a two-ABI build failed with
        "ABI content skew ... 'bin/filetype.exe'"."""
        stdlib, sp, app = self._stage(tmp_path)
        for abi, root in sp.items():
            _write(root / "bin" / "filetype.exe", f"launcher for {abi}".encode())
        bundle = tmp_path / "bundle"
        assemble_bundle(
            bundle,
            stdlib_src=stdlib,
            site_packages_by_abi=sp,
            canonical_abi="arm64_v8a",
            app_src=app,
            finder_source="# finder",
            kivy_bootstrap_source="# kivy contract",
            ext_manifest_json="{}",
        )  # must not raise despite the per-ABI difference
        assert not (bundle / "site-packages" / "bin").exists()

    def test_abi_content_skew_fails(self, tmp_path):
        stdlib, sp, app = self._stage(tmp_path, skew=True)
        with pytest.raises(BundleError, match="ABI content skew"):
            assemble_bundle(
                tmp_path / "bundle",
                stdlib_src=stdlib,
                site_packages_by_abi=sp,
                canonical_abi="arm64_v8a",
                app_src=app,
                finder_source="# finder",
                kivy_bootstrap_source="# kivy contract",
                ext_manifest_json="{}",
            )

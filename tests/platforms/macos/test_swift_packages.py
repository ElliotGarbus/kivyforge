"""Swift packages built into the macOS ``.app`` (#201), with ``xcodebuild`` faked.

The layout the fake writes is the one the spike measured
(macos-swift-packages-spike-findings.md, step 2).
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from kivyforge.lock.model import LockedSwiftPackage
from kivyforge.platforms.macos import AppBundleError, bundle
from kivyforge.platforms.macos.swift_packages import (
    ROOT,
    build_swift_packages,
    package_identity,
    render_manifest,
    xcodebuild_command,
)
from kivyforge.report import diagnostics, exit_codes

from .test_bundle import _config, _lock, _project

_REV = "5d1d0d8836996aead64c0d76e2aaaa6c18a7d58c"
PROMISES = LockedSwiftPackage(
    name="Promises",
    products=("Promises", "FBLPromises"),
    url="https://github.com/google/promises.git",
    requirement={"from": "2.4.0"},
    revision=_REV,
    version="2.4.0",
)
SHIM = LockedSwiftPackage(name="Shim", products=("SwiftBridge",), path="swift-shims")


class FakeXcodebuild:
    """Writes ``xcodebuild``'s Release products for the packages it is told of."""

    def __init__(
        self,
        *,
        frameworks=(ROOT, "SwiftBridge"),
        bundles=("Promises_FBLPromises", "ResProbe_ResProbe"),
        returncode=0,
        output="",
        raises: OSError | None = None,
    ):
        self.frameworks = frameworks
        self.bundles = bundles
        self.returncode = returncode
        self.output = output
        self.raises = raises
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, cmd, *, cwd, echo):
        self.calls.append((cmd, cwd))
        if self.raises is not None:
            raise self.raises
        derived = Path(cmd[cmd.index("-derivedDataPath") + 1])
        products = derived / "Build" / "Products" / "Release"
        for name in self.frameworks:
            fw = products / "PackageFrameworks" / f"{name}.framework"
            (fw / "Versions" / "A" / "Resources").mkdir(parents=True)
            (fw / "Versions" / "A" / name).write_bytes(b"\xcf\xfa\xed\xfe")
            (fw / "Versions" / "Current").symlink_to("A")
            (fw / name).symlink_to(f"Versions/Current/{name}")
        for name in self.bundles:
            res = products / f"{name}.bundle" / "Contents" / "Resources"
            res.mkdir(parents=True)
            (res / "PrivacyInfo.xcprivacy").write_text("<plist/>")
        return self.returncode, self.output


def _shim_project(tmp_path: Path) -> Path:
    (tmp_path / "swift-shims").mkdir()
    (tmp_path / "swift-shims" / "Package.swift").write_text("// shim")
    return tmp_path


def _build(tmp_path, fake, packages=(PROMISES, SHIM)):
    contents = tmp_path / "App.app" / "Contents"
    contents.mkdir(parents=True)
    placed = build_swift_packages(
        packages,
        contents,
        project_root=_shim_project(tmp_path),
        work_dir=tmp_path / "spm",
        arch="arm64",
        minimum_system_version="12.0",
        run=fake,
        echo=lambda *a: None,
    )
    return contents, placed


class TestPackageIdentity:
    @pytest.mark.parametrize(
        ("source", "identity"),
        [
            ({"url": "https://github.com/google/promises.git"}, "promises"),
            (
                {"url": "https://github.com/firebase/firebase-ios-sdk/"},
                "firebase-ios-sdk",
            ),
            ({"url": "git@github.com:org/KeychainAccess.git"}, "keychainaccess"),
            ({"url": "git@host:Repo"}, "repo"),
            ({"path": "swift-shims"}, "swift-shims"),
            ({"path": "vendor/MyKit/"}, "mykit"),
        ],
    )
    def test_last_component_lowercased(self, source, identity):
        sp = LockedSwiftPackage(name="X", products=("X",), **source)
        assert package_identity(sp) == identity


class TestRenderManifest:
    def test_one_dynamic_product_over_every_locked_product(self, tmp_path):
        text = render_manifest(
            (SHIM, PROMISES), project_root=tmp_path, minimum_system_version="12.0"
        )
        assert "// swift-tools-version:5.9" in text
        assert '.macOS("12.0")' in text
        assert f'.library(name: "{ROOT}", type: .dynamic, targets: ["{ROOT}"])' in text
        # A remote package builds the locked revision, not its version rule.
        assert (
            '.package(url: "https://github.com/google/promises.git", '
            f'revision: "{_REV}")' in text
        )
        assert "from:" not in text
        # A local one by absolute path: the root package lives under build/.
        local = (tmp_path / "swift-shims").resolve()
        assert f'.package(path: "{local}")' in text
        # Products name their package by identity, not by the pyproject key.
        assert '.product(name: "Promises", package: "promises")' in text
        assert '.product(name: "FBLPromises", package: "promises")' in text
        assert '.product(name: "SwiftBridge", package: "swift-shims")' in text
        assert '.unsafeFlags(["-Xlinker", "-ObjC"])' in text

    def test_deterministic_order(self, tmp_path):
        kw = {"project_root": tmp_path, "minimum_system_version": "11.0"}
        assert render_manifest((SHIM, PROMISES), **kw) == render_manifest(
            (PROMISES, SHIM), **kw
        )

    def test_quotes_are_escaped(self, tmp_path):
        odd = LockedSwiftPackage(name="Odd", products=('A"B',), path='we"ird')
        text = render_manifest(
            (odd,), project_root=tmp_path, minimum_system_version="11.0"
        )
        assert '.product(name: "A\\"B", package: "we\\"ird")' in text

    def test_remote_without_revision_is_a_lock_problem(self, tmp_path):
        unpinned = LockedSwiftPackage(name="P", products=("P",), url="https://x/p")
        with pytest.raises(AppBundleError, match="no pinned revision") as exc:
            render_manifest(
                (unpinned,), project_root=tmp_path, minimum_system_version="11.0"
            )
        assert exc.value.code == diagnostics.LOCK_UNREADABLE
        assert exc.value.exit_code == exit_codes.LOCK_DRIFT


class TestXcodebuildCommand:
    def test_settings_the_spike_needed(self, tmp_path):
        cmd = xcodebuild_command(tmp_path / "dd", arch="arm64")
        assert cmd[0] == "xcodebuild"
        assert cmd[cmd.index("-scheme") + 1] == ROOT
        assert cmd[cmd.index("-destination") + 1] == "generic/platform=macOS"
        assert cmd[cmd.index("-configuration") + 1] == "Release"
        assert cmd[cmd.index("-derivedDataPath") + 1] == str(tmp_path / "dd")
        for setting in (
            "ARCHS=arm64",
            "ONLY_ACTIVE_ARCH=NO",
            "CODE_SIGNING_ALLOWED=NO",
            "LD_RUNPATH_SEARCH_PATHS=@loader_path/../../..",
            "-skipPackagePluginValidation",
            "-skipMacroValidation",
        ):
            assert setting in cmd
        assert cmd[-1] == "build"


@pytest.mark.requires_symlinks
class TestBuildSwiftPackages:
    def test_writes_the_root_package_and_runs_in_it(self, tmp_path):
        fake = FakeXcodebuild()
        _build(tmp_path, fake)
        ((cmd, cwd),) = fake.calls
        assert cwd == tmp_path / "spm"
        assert "ARCHS=arm64" in cmd
        manifest = (tmp_path / "spm" / "Package.swift").read_text(encoding="utf-8")
        assert '.macOS("12.0")' in manifest
        assert (tmp_path / "spm" / "Sources" / ROOT / f"{ROOT}.swift").is_file()

    def test_frameworks_to_frameworks_bundles_to_resources(self, tmp_path):
        contents, placed = _build(tmp_path, FakeXcodebuild())
        fw = contents / "Frameworks"
        assert sorted(p.name for p in fw.iterdir()) == [
            f"{ROOT}.framework",
            "SwiftBridge.framework",
        ]
        # The versioned layout's symlinks survive the copy.
        assert os.readlink(fw / f"{ROOT}.framework" / "Versions" / "Current") == "A"
        assert (fw / f"{ROOT}.framework" / ROOT).is_symlink()
        res = contents / "Resources"
        assert (res / "Promises_FBLPromises.bundle" / "Contents" / "Resources").is_dir()
        assert (res / "ResProbe_ResProbe.bundle").is_dir()
        assert len(placed) == 4

    def test_products_of_a_previous_build_are_not_staged(self, tmp_path):
        _build(tmp_path, FakeXcodebuild())
        # The next build drops the shim and its framework.
        contents = tmp_path / "Next.app" / "Contents"
        contents.mkdir(parents=True)
        build_swift_packages(
            (PROMISES,),
            contents,
            project_root=tmp_path,
            work_dir=tmp_path / "spm",
            arch="arm64",
            minimum_system_version="12.0",
            run=FakeXcodebuild(frameworks=(ROOT,), bundles=()),
            echo=lambda *a: None,
        )
        assert [p.name for p in (contents / "Frameworks").iterdir()] == [
            f"{ROOT}.framework"
        ]
        assert not (contents / "Resources").exists()

    def test_nothing_declared_runs_nothing(self, tmp_path):
        fake = FakeXcodebuild()
        assert _build(tmp_path, fake, packages=())[1] == []
        assert fake.calls == []

    def test_xcodebuild_failure_is_a_build_failure(self, tmp_path):
        output = "\n".join(
            [*(f"noise {i}" for i in range(100)), "Foo.swift:3: error: no such module"]
        )
        fake = FakeXcodebuild(returncode=65, output=output)
        with pytest.raises(AppBundleError) as exc:
            _build(tmp_path, fake)
        assert exc.value.code == diagnostics.BUILD_TOOL_FAILED
        assert exc.value.exit_code == exit_codes.BUILD_FAILURE
        assert exc.value.context == {"tool": "xcodebuild", "task": "build"}
        message = str(exc.value)
        assert "error: no such module" in message
        assert "noise 0" not in message
        assert "Package.swift" in message

    def test_missing_xcodebuild_is_the_machine(self, tmp_path):
        fake = FakeXcodebuild(raises=FileNotFoundError(2, "No such file"))
        with pytest.raises(AppBundleError, match="could not run xcodebuild") as exc:
            _build(tmp_path, fake)
        assert exc.value.code == diagnostics.TOOLCHAIN_MISSING
        assert exc.value.exit_code == exit_codes.ENVIRONMENT_ERROR

    def test_no_root_framework_is_a_missing_artifact(self, tmp_path):
        fake = FakeXcodebuild(frameworks=("SwiftBridge",))
        with pytest.raises(AppBundleError, match=f"no {ROOT}.framework") as exc:
            _build(tmp_path, fake)
        assert exc.value.code == diagnostics.ARTIFACT_MISSING

    def test_missing_local_package_fails_before_xcodebuild(self, tmp_path):
        gone = LockedSwiftPackage(name="Gone", products=("G",), path="nowhere")
        fake = FakeXcodebuild()
        with pytest.raises(AppBundleError, match="nowhere/Package.swift") as exc:
            _build(tmp_path, fake, packages=(gone,))
        assert exc.value.context == {"package": "Gone", "path": "nowhere"}
        assert fake.calls == []

    def test_refuses_to_overwrite_what_the_bundle_has(self, tmp_path):
        contents = tmp_path / "App.app" / "Contents"
        (contents / "Frameworks" / "SwiftBridge.framework").mkdir(parents=True)
        with pytest.raises(AppBundleError, match="already has") as exc:
            build_swift_packages(
                (PROMISES,),
                contents,
                project_root=tmp_path,
                work_dir=tmp_path / "spm",
                arch="arm64",
                minimum_system_version="12.0",
                run=FakeXcodebuild(),
                echo=lambda *a: None,
            )
        assert exc.value.context == {
            "path": "Contents/Frameworks/SwiftBridge.framework"
        }


@pytest.mark.requires_symlinks
class TestInTheBundle:
    def test_staged_before_signing_from_build_spm(self, tmp_path, faked, monkeypatch):
        root = _project(tmp_path)
        _shim_project(root)
        lock = dataclasses.replace(_lock(), swift_packages=(PROMISES, SHIM))
        fake = FakeXcodebuild()
        signed: list[bool] = []
        app_dir = tmp_path / "out"

        def sign(app):
            fw = app / "Contents" / "Frameworks" / f"{ROOT}.framework"
            signed.append(fw.is_dir())
            return 1

        monkeypatch.setattr(bundle, "sign_bundle_adhoc", sign)
        app = bundle.build_app_bundle(
            _config(),
            lock,
            root,
            staging_dir=app_dir,
            swift_runner=fake,
            echo=lambda *a: None,
        )
        ((cmd, cwd),) = fake.calls
        assert cwd == app_dir / "spm"
        assert signed == [True]
        assert (app / "Contents" / "Frameworks" / "SwiftBridge.framework").is_dir()
        assert (app / "Contents" / "Resources" / "ResProbe_ResProbe.bundle").is_dir()
        # No minimum_system_version: the Info.plist's default floor.
        manifest = (cwd / "Package.swift").read_text(encoding="utf-8")
        assert '.macOS("11.0")' in manifest

    def test_no_packages_no_xcodebuild(self, tmp_path, faked):
        fake = FakeXcodebuild()
        bundle.build_app_bundle(
            _config(),
            _lock(),
            _project(tmp_path),
            staging_dir=tmp_path / "out",
            swift_runner=fake,
            echo=lambda *a: None,
        )
        assert fake.calls == []
        assert not (tmp_path / "out" / "spm").exists()


class TestRunXcodebuild:
    def test_shows_fetches_and_quiet_spells_only(self, monkeypatch, tmp_path):
        from kivyforge.platforms.macos import swift_packages as sp

        seen: dict = {}

        def fake_run_streaming(cmd, *, cwd, on_segment, on_quiet):
            seen["cwd"] = cwd
            shown = [
                on_segment(line)
                for line in (
                    "Fetching from https://github.com/google/promises (cached)",
                    "CompileSwift normal arm64 Foo.swift",
                    "Resolved source packages:",
                )
            ]
            on_quiet(95.0)
            return 0, "\n".join(map(str, shown))

        monkeypatch.setattr(sp, "run_streaming", fake_run_streaming)
        lines: list[str] = []
        code, transcript = sp._run_xcodebuild(
            ["xcodebuild"], cwd=tmp_path, echo=lines.append
        )
        assert code == 0 and seen["cwd"] == tmp_path
        assert transcript == "True\nFalse\nTrue"
        assert lines == [
            "  xcodebuild: Fetching from https://github.com/google/promises (cached)",
            "  xcodebuild: Resolved source packages:",
            "  xcodebuild: still building (1m 35s)",
        ]


@pytest.mark.requires_symlinks
def test_a_refused_copy_names_the_product(tmp_path, monkeypatch):
    from kivyforge.platforms.macos import swift_packages as sp

    def refuse(src, dst, **kw):
        raise PermissionError(13, "Permission denied", str(dst))

    monkeypatch.setattr(sp.shutil, "copytree", refuse)
    with pytest.raises(AppBundleError, match=f"could not stage {ROOT}.framework"):
        _build(tmp_path, FakeXcodebuild())

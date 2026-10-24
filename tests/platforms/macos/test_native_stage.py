"""Native-binary staging into ``Contents/Helpers`` and ``Contents/Frameworks``.

macos-native-binaries-placement-proposal §3: classification by Mach-O type,
refusals, flat case-insensitive placement, and the link check, all before
anything is copied into the bundle.
"""

from __future__ import annotations

import hashlib
import os
import struct
import zipfile
from pathlib import Path

import pytest

from kivyforge.lock.wheelruntime.model import (
    LockedNativeBinary,
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)
from kivyforge.platforms.macos import AppBundleError, machotools
from kivyforge.platforms.macos.native_stage import stage_native_binaries
from kivyforge.report import diagnostics
from tests.platforms.macos import macho_fixtures as mf

FRAMEWORKS_RPATH = ("@executable_path/../Frameworks",)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lock(*native_binaries):
    return WheelRuntimeLock(
        platform="macos",
        requires_python=">=3.15",
        packages=(),
        python_runtime=PythonRuntime(
            provider="pbs",
            version="3.15.0",
            artifacts=(RuntimeArtifact(arch="arm64", url="https://e/a", sha256="c"),),
        ),
        archs=("arm64",),
        kivyforge_version="0.1.0",
        generated_at="2026-01-01T00:00:00Z",
        lock_inputs_sha256="d" * 64,
        tool_kivyforge_schema_version=1,
        native_binaries=tuple(native_binaries),
    )


def _file(root: Path, rel: str, data: bytes, name: str | None = None):
    mf.write(root / rel, data)
    return LockedNativeBinary(name or Path(rel).name, "1.0", _sha256(data), path=rel)


def _zip(root: Path, rel: str, members: dict[str, bytes], name: str | None = None):
    archive = root / rel
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as zf:
        for member, data in members.items():
            zf.writestr(member, data)
    return LockedNativeBinary(
        name or Path(rel).stem, "1.0", _sha256(archive.read_bytes()), path=rel
    )


class _Run:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.contents = root / "App.app" / "Contents"
        self.contents.mkdir(parents=True)
        self.echoed: list[str] = []
        self.notes: list[tuple[str, str, dict]] = []

    def __call__(self, *entries, arch: str = "arm64"):
        return stage_native_binaries(
            _lock(*entries),
            self.contents,
            target_arch=arch,
            project_root=self.root,
            echo=self.echoed.append,
            note=lambda code, msg, ctx=None: self.notes.append((code, msg, ctx or {})),
        )

    def placed(self) -> set[str]:
        return {
            p.relative_to(self.contents).as_posix()
            for p in self.contents.rglob("*")
            if p.is_file()
        }


@pytest.fixture
def run(tmp_path):
    return _Run(tmp_path)


class TestPlacement:
    def test_empty_is_noop(self, run):
        assert run() == []
        assert run.placed() == set()

    def test_executable_goes_to_helpers(self, run):
        data = mf.helper()
        run(_file(run.root, "binaries/roll", data))
        staged = run.contents / "Helpers" / "roll"
        assert staged.read_bytes() == data
        assert os.access(staged, os.X_OK)
        assert run.placed() == {"Helpers/roll"}

    def test_dylib_goes_to_frameworks_with_its_name(self, run):
        data = mf.dylib("libgreet.dylib")
        run(_file(run.root, "binaries/libgreet.dylib", data, name="libgreet"))
        assert (run.contents / "Frameworks" / "libgreet.dylib").read_bytes() == data
        assert run.placed() == {"Frameworks/libgreet.dylib"}

    def test_nothing_under_resources_bin(self, run):
        run(_file(run.root, "binaries/roll", mf.helper()))
        assert not (run.contents / "Resources" / "bin").exists()

    def test_archive_is_flattened_per_type(self, run):
        run(
            _zip(
                run.root,
                "binaries/sdk.zip",
                {
                    "sdk-1.0/bin/ffmpeg": mf.helper(rpaths=FRAMEWORKS_RPATH),
                    "sdk-1.0/lib/libav.dylib": mf.dylib("libav.dylib"),
                },
            )
        )
        assert run.placed() == {"Helpers/ffmpeg", "Frameworks/libav.dylib"}
        assert os.access(run.contents / "Helpers" / "ffmpeg", os.X_OK)

    def test_universal_binary_with_the_target_slice(self, run):
        data = mf.fat(
            mf.helper(cpu_type=machotools.CPU_TYPE_X86_64), mf.helper(), wide=True
        )
        run(_file(run.root, "binaries/roll", data))
        assert (run.contents / "Helpers" / "roll").read_bytes() == data

    def test_missing_target_slice_is_refused(self, run):
        data = mf.helper(cpu_type=machotools.CPU_TYPE_X86_64)
        with pytest.raises(AppBundleError, match="has no arm64 code") as exc:
            run(_file(run.root, "binaries/roll", data))
        assert "it has x86_64" in str(exc.value)
        assert run.placed() == set()


class TestNotCode:
    def test_single_file_script_is_refused(self, run):
        with pytest.raises(AppBundleError) as exc:
            run(_file(run.root, "binaries/tool.sh", b"#!/bin/sh\necho hi\n", "tool"))
        assert exc.value.code == diagnostics.MACOS_NATIVE_NOT_CODE
        assert exc.value.context == {"binary": "tool", "path": "binaries/tool.sh"}
        assert "include_files" in str(exc.value)
        assert run.placed() == set()

    def test_archive_data_is_skipped_with_a_warning(self, run):
        run(
            _zip(
                run.root,
                "binaries/sdk.zip",
                {
                    "bin/tool": mf.helper(),
                    "LICENSE": b"MIT",
                    "include/sdk.h": b"int f(void);",
                },
                name="sdk",
            )
        )
        assert run.placed() == {"Helpers/tool"}
        ((code, message, context),) = run.notes
        assert code == diagnostics.MACOS_NATIVE_NOT_CODE
        assert "skipped 2 archive members" in message
        assert "sdk: LICENSE" in message and "sdk: include/sdk.h" in message
        assert context["binary"] == "sdk"
        assert any("skipped 2 archive members" in line for line in run.echoed)

    def test_skip_listing_is_capped(self, run):
        members = {f"doc/{i:02}.txt": b"x" for i in range(13)}
        members["bin/tool"] = mf.helper()
        run(_zip(run.root, "binaries/sdk.zip", members))
        ((_, message, _),) = run.notes
        assert "skipped 13 archive members" in message
        assert "and 3 more" in message

    def test_two_archives_may_both_carry_a_license(self, run):
        run(
            _zip(run.root, "binaries/a.zip", {"a": mf.helper(), "LICENSE": b"a"}),
            _zip(run.root, "binaries/b.zip", {"b": mf.helper(), "LICENSE": b"b"}),
        )
        assert run.placed() == {"Helpers/a", "Helpers/b"}

    def test_java_class_in_archive_is_data(self, run):
        # Same magic as a universal Mach-O; the slice count gives it away.
        java = struct.pack(">IHH", 0xCAFEBABE, 0, 65) + b"\x00" * 32
        run(_zip(run.root, "binaries/x.zip", {"A.class": java, "t": mf.helper()}))
        assert run.placed() == {"Helpers/t"}
        assert "A.class" in run.notes[0][1]

    def test_resource_bundle_without_code_is_skipped(self, run):
        run(
            _zip(
                run.root,
                "binaries/x.zip",
                {"t": mf.helper(), "Data.bundle/Info.plist": b"<plist/>"},
            )
        )
        assert run.placed() == {"Helpers/t"}


class TestUnsupported:
    @pytest.mark.parametrize(
        ("filetype", "kind"),
        [(machotools.MH_BUNDLE, "MH_BUNDLE"), (0x1, "MH_OBJECT")],
    )
    def test_other_mach_o_types(self, run, filetype, kind):
        with pytest.raises(AppBundleError) as exc:
            run(_file(run.root, "binaries/plug.so", mf.thin(filetype), "plug"))
        assert exc.value.code == diagnostics.MACOS_NATIVE_UNSUPPORTED
        assert kind in str(exc.value)
        assert exc.value.context == {"binary": "plug", "path": "binaries/plug.so"}

    def test_slices_that_disagree(self, run):
        data = mf.fat(
            mf.helper(cpu_type=machotools.CPU_TYPE_X86_64), mf.dylib("x.dylib")
        )
        with pytest.raises(AppBundleError, match="slices disagree") as exc:
            run(_file(run.root, "binaries/odd", data))
        assert exc.value.code == diagnostics.MACOS_NATIVE_UNSUPPORTED

    def test_damaged_header(self, run):
        data = mf.helper()[:20]
        with pytest.raises(AppBundleError, match="cannot be read") as exc:
            run(_file(run.root, "binaries/broken", data))
        assert exc.value.code == diagnostics.MACOS_NATIVE_UNSUPPORTED

    @pytest.mark.parametrize(
        "members",
        [
            {"Foo.framework/Versions/A/Foo": mf.dylib("Foo")},
            {"Foo.FRAMEWORK/Foo": mf.dylib("Foo")},
            {"Tool.app/Contents/MacOS/Tool": mf.helper()},
            {
                "plug/Contents/Info.plist": b"<plist/>",
                "plug/Contents/MacOS/p": mf.helper(),
            },
            {"flat/Info.plist": b"<plist/>", "flat/p": mf.helper()},
        ],
    )
    def test_code_inside_a_bundle(self, run, members):
        with pytest.raises(AppBundleError, match="a bundle") as exc:
            run(_zip(run.root, "binaries/x.zip", members, name="x"))
        assert exc.value.code == diagnostics.MACOS_NATIVE_UNSUPPORTED
        assert run.placed() == set()


class TestCollisions:
    def test_same_name_in_one_location_is_refused(self, run):
        with pytest.raises(AppBundleError, match="Contents/Helpers/tool"):
            run(
                _file(run.root, "binaries/a/tool", mf.helper(), "A"),
                _file(run.root, "binaries/b/tool", mf.helper(rpaths=("x",)), "B"),
            )
        assert run.placed() == set()

    def test_names_differing_only_in_case_are_refused(self, run):
        with pytest.raises(AppBundleError, match="differ only in case"):
            run(
                _zip(
                    run.root, "binaries/a.zip", {"libZ.dylib": mf.dylib("libZ.dylib")}
                ),
                _zip(
                    run.root, "binaries/b.zip", {"libz.dylib": mf.dylib("libz.dylib")}
                ),
            )

    def test_case_clash_inside_one_archive(self, run):
        with pytest.raises(AppBundleError, match="differ only in case"):
            run(
                _zip(
                    run.root,
                    "binaries/a.zip",
                    {"x/tool": mf.helper(), "y/TOOL": mf.helper(rpaths=("x",))},
                )
            )

    def test_locations_are_separate(self, run):
        run(
            _zip(run.root, "binaries/a.zip", {"bin/greet": mf.helper()}),
            _zip(run.root, "binaries/b.zip", {"lib/greet": mf.dylib("greet")}),
        )
        assert run.placed() == {"Helpers/greet", "Frameworks/greet"}


class TestLinks:
    def test_helper_expecting_a_sibling_is_refused(self, run):
        with pytest.raises(AppBundleError) as exc:
            run(
                _file(run.root, "b/tool", mf.helper(deps=("@loader_path/libx.dylib",))),
                _file(run.root, "b/libx.dylib", mf.dylib("libx.dylib")),
            )
        assert exc.value.code == diagnostics.MACOS_NATIVE_LOAD_PATH
        assert exc.value.context == {
            "binary": "tool",
            "library": "libx.dylib",
            "process": "the helper tool",
            "dependency": "@loader_path/libx.dylib",
        }
        assert "Contents/Helpers/libx.dylib" in str(exc.value)
        assert run.placed() == set()

    def test_apples_layout_passes(self, run):
        run(
            _file(
                run.root,
                "b/tool",
                mf.helper(deps=("@rpath/libx.dylib",), rpaths=FRAMEWORKS_RPATH),
            ),
            _file(run.root, "b/libx.dylib", mf.dylib("libx.dylib")),
        )
        assert run.placed() == {"Helpers/tool", "Frameworks/libx.dylib"}
        assert run.notes == []

    def test_errors_are_capped(self, run):
        deps = tuple(f"@loader_path/lib{i:02}.dylib" for i in range(12))
        libs = [
            _file(run.root, f"b/lib{i:02}.dylib", mf.dylib(f"lib{i:02}.dylib"))
            for i in range(12)
        ]
        with pytest.raises(AppBundleError, match=r"\.\.\. and 2 more\."):
            run(_file(run.root, "b/tool", mf.helper(deps=deps)), *libs)

    def test_preload_is_a_warning_and_uses_the_interpreters_rpath(self, run):
        python = run.contents / "Resources" / "python" / "bin" / "python3"
        mf.write(python, mf.helper(rpaths=("@executable_path/../lib",)))
        run(
            _file(
                run.root,
                "b/libA.dylib",
                mf.dylib("libA.dylib", deps=("@rpath/libB.dylib",)),
            ),
            _file(run.root, "b/libB.dylib", mf.dylib("libB.dylib")),
        )
        assert run.placed() >= {"Frameworks/libA.dylib", "Frameworks/libB.dylib"}
        ((code, message, context),) = run.notes
        assert code == diagnostics.MACOS_NATIVE_LOAD_PATH
        assert "Contents/Resources/python/lib/libB.dylib" in message
        assert context["process"] == "Python (ctypes)"
        assert any(
            "loads only if the app loads libB.dylib first" in e for e in run.echoed
        )

    def test_weak_link_is_a_warning(self, run):
        run(
            _file(
                run.root,
                "b/tool",
                mf.helper(deps=(("@loader_path/libx.dylib", "weak"),)),
            ),
            _file(run.root, "b/libx.dylib", mf.dylib("libx.dylib")),
        )
        assert run.placed() == {"Helpers/tool", "Frameworks/libx.dylib"}
        assert [n[0] for n in run.notes] == [diagnostics.MACOS_NATIVE_LOAD_PATH]


class TestFetchGuards:
    def test_zip_traversal_rejected(self, run):
        entry = _zip(run.root, "binaries/evil.zip", {"../escape": b"nope"})
        with pytest.raises(AppBundleError, match="unsafe path"):
            run(entry)

    def test_hash_mismatch_raises_app_error(self, run):
        mf.write(run.root / "binaries/roll", mf.helper())
        with pytest.raises(AppBundleError):
            run(LockedNativeBinary("roll", "1.0", "0" * 64, path="binaries/roll"))

    def test_missing_vendored_file_raises_app_error(self, run):
        with pytest.raises(AppBundleError):
            run(LockedNativeBinary("roll", "1.0", "0" * 64, path="binaries/absent"))

"""The shared include_files model (include-files-proposal §4.3, §4.8)."""

from __future__ import annotations

import hashlib
import os
import struct
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from kivyforge.artifacts import include_files
from kivyforge.artifacts.include_files import (
    ArtifactContentMismatch,
    IncludeDrift,
    IncludeFilesError,
    IncludeNativeCode,
    IncludeReserved,
    IncludeSourceFormat,
)
from kivyforge.config.model import Config, IncludeFile
from kivyforge.doctor.result import Status
from kivyforge.lock.model import LockedIncludeFile
from kivyforge.report import diagnostics, exit_codes


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "GoogleService-Info.plist").write_bytes(b"<plist/>")
    (tmp_path / "assets" / "sounds" / "deep").mkdir(parents=True)
    (tmp_path / "assets" / "sounds" / "ding.caf").write_bytes(b"ding")
    (tmp_path / "assets" / "sounds" / "deep" / "dong.caf").write_bytes(b"dong")
    return tmp_path


PLIST = IncludeFile(dest=".", sources=("config/GoogleService-Info.plist",))
SOUNDS = IncludeFile(dest="Sounds", sources=("assets/sounds",))
_CONFIG = cast(Config, SimpleNamespace(ios=SimpleNamespace(include_files=(PLIST,))))


@dataclass(frozen=True)
class _Lock:
    include_files: tuple[LockedIncludeFile, ...]
    packages: tuple[str, ...] = ("kivy",)
    generated_at: str = "2026-01-01T00:00:00Z"


class TestExpand:
    def test_a_file_lands_in_dest_under_its_own_name(self, project):
        [item] = include_files.expand([PLIST], project)
        assert item.path == "GoogleService-Info.plist"
        assert item.source == "config/GoogleService-Info.plist"
        assert item.dest == "."
        assert item.key == (".", "config/GoogleService-Info.plist")

    def test_a_directory_contributes_its_contents_subfolders_kept(self, project):
        items = include_files.expand([SOUNDS], project)
        assert [(i.source, i.path) for i in items] == [
            ("assets/sounds/deep/dong.caf", "Sounds/deep/dong.caf"),
            ("assets/sounds/ding.caf", "Sounds/ding.caf"),
        ]

    def test_a_backslash_dest_is_posix_in_the_path_and_verbatim_in_the_key(
        self, project
    ):
        entry = IncludeFile(dest="Resources\\data", sources=("assets/sounds/ding.caf",))
        [item] = include_files.expand([entry], project)
        assert item.path == "Resources/data/ding.caf"
        assert item.dest == "Resources\\data"

    def test_a_missing_source_names_it(self, project):
        entry = IncludeFile(dest=".", sources=("nope.json",))
        with pytest.raises(IncludeFilesError, match="nope.json"):
            include_files.expand([entry], project)


class TestPins:
    def test_one_pin_per_file_sorted_by_key(self, project):
        pins = include_files.hash_pins([SOUNDS, PLIST], project)
        assert [p.key for p in pins] == sorted(p.key for p in pins)
        assert {p.source: p.sha256 for p in pins} == {
            "config/GoogleService-Info.plist": _sha(b"<plist/>"),
            "assets/sounds/ding.caf": _sha(b"ding"),
            "assets/sounds/deep/dong.caf": _sha(b"dong"),
        }

    def test_current_until_a_file_is_edited_added_or_deleted(self, project):
        entries = [SOUNDS, PLIST]
        pins = include_files.hash_pins(entries, project)
        assert include_files.pins_current(pins, entries, project)
        assert include_files.pins_current(reversed(pins), entries, project)

        (project / "assets" / "sounds" / "ding.caf").write_bytes(b"DING")
        assert not include_files.pins_current(pins, entries, project)

        pins = include_files.hash_pins(entries, project)
        (project / "assets" / "sounds" / "new.caf").write_bytes(b"new")
        assert not include_files.pins_current(pins, entries, project)

        pins = include_files.hash_pins(entries, project)
        (project / "assets" / "sounds" / "deep" / "dong.caf").unlink()
        assert not include_files.pins_current(pins, entries, project)

    def test_a_missing_source_is_not_current(self, project):
        pins = include_files.hash_pins([PLIST], project)
        (project / "config" / "GoogleService-Info.plist").unlink()
        assert not include_files.pins_current(pins, [PLIST], project)

    def test_no_entries_and_no_pins_is_current(self, project):
        assert include_files.pins_current((), (), project)

    def test_pin_changes_lists_each_kind(self):
        old = [
            LockedIncludeFile("a.json", ".", "1"),
            LockedIncludeFile("b.json", ".", "2"),
        ]
        new = [
            LockedIncludeFile("b.json", ".", "3"),
            LockedIncludeFile("c.json", "Data", "4"),
        ]
        assert include_files.pin_changes(old, new) == [
            "  ~ include_files: a.json -> . (removed)",
            "  ~ include_files: b.json -> . (changed)",
            "  ~ include_files: c.json -> Data (added)",
        ]

    def test_refresh_returns_the_same_lock_when_nothing_changed(self, project):
        lock = _Lock(tuple(include_files.hash_pins([PLIST], project)))
        refreshed = include_files.refresh(
            lock, _CONFIG, project_root=project, platform="ios"
        )
        assert refreshed is lock

    def test_refresh_rewrites_only_the_pins(self, project):
        stale = LockedIncludeFile("config/GoogleService-Info.plist", ".", "stale")
        lock = _Lock((stale,))
        refreshed = include_files.refresh(
            lock, _CONFIG, project_root=project, platform="ios"
        )
        assert refreshed.include_files == tuple(
            include_files.hash_pins([PLIST], project)
        )
        assert refreshed.packages == lock.packages
        assert refreshed.generated_at != lock.generated_at


class TestVerifyPins:
    def test_matching_pins_pass(self, project):
        items = include_files.expand([SOUNDS], project)
        pins = include_files.hash_pins([SOUNDS], project)
        include_files.verify_pins(items, pins, platform="ios")

    def test_an_edited_file_is_drift(self, project):
        pins = include_files.hash_pins([PLIST], project)
        (project / "config" / "GoogleService-Info.plist").write_bytes(b"edited")
        items = include_files.expand([PLIST], project)
        with pytest.raises(IncludeDrift, match="has changed") as info:
            include_files.verify_pins(items, pins, platform="ios")
        assert info.value.code == diagnostics.LOCK_DRIFT
        assert info.value.exit_code == exit_codes.LOCK_DRIFT
        assert "kivyforge lock -p ios" in str(info.value)

    def test_a_file_with_no_pin_is_drift(self, project):
        items = include_files.expand([PLIST], project)
        with pytest.raises(IncludeDrift, match="records no hash"):
            include_files.verify_pins(items, (), platform="macos")

    def test_a_pin_with_no_file_is_drift(self, project):
        pins = include_files.hash_pins([SOUNDS], project)
        (project / "assets" / "sounds" / "ding.caf").unlink()
        items = include_files.expand([SOUNDS], project)
        with pytest.raises(IncludeDrift, match="no longer exists") as info:
            include_files.verify_pins(items, pins, platform="ios")
        assert info.value.context == {"source": "assets/sounds/ding.caf"}


class TestPlacement:
    def test_refuse_reserved_carries_the_items_path_and_source(self, project):
        items = include_files.expand([PLIST], project)
        with pytest.raises(IncludeReserved, match="mine") as info:
            include_files.refuse_reserved(items, lambda item: "mine")
        assert info.value.code == diagnostics.INCLUDE_RESERVED
        assert info.value.exit_code == exit_codes.CONFIG_ERROR
        assert info.value.context == {
            "path": "GoogleService-Info.plist",
            "source": "config/GoogleService-Info.plist",
        }

    def test_refuse_reserved_passes_what_the_callback_allows(self, project):
        include_files.refuse_reserved(
            include_files.expand([SOUNDS], project), lambda item: None
        )

    @pytest.mark.parametrize(
        "name", ["Localizable.xcstrings", "Main.storyboard", "View.xib", "X.XIB"]
    )
    def test_a_compiled_format_file_is_refused(self, project, name):
        (project / name).write_bytes(b"x")
        items = include_files.expand([IncludeFile(".", (name,))], project)
        with pytest.raises(IncludeSourceFormat, match="would ship and do nothing"):
            include_files.refuse_unprocessed(items, native_key="[native]")

    def test_an_asset_catalog_is_refused_from_inside_it(self, project):
        catalog = project / "Media.xcassets" / "Icon.imageset"
        catalog.mkdir(parents=True)
        (catalog / "Contents.json").write_text("{}")
        items = include_files.expand([IncludeFile(".", ("Media.xcassets",))], project)
        with pytest.raises(IncludeSourceFormat, match="asset catalog") as info:
            include_files.refuse_unprocessed(items, native_key="[native]")
        assert info.value.code == diagnostics.INCLUDE_SOURCE_FORMAT

    def test_a_dest_that_names_a_compiled_format_is_refused(self, project):
        entry = IncludeFile("Base.storyboard", ("assets/sounds/ding.caf",))
        items = include_files.expand([entry], project)
        with pytest.raises(IncludeSourceFormat, match="storyboard"):
            include_files.refuse_unprocessed(items, native_key="[native]")

    @pytest.mark.parametrize(
        "head",
        [
            struct.pack(">I", 0xFEEDFACF) + b"\0" * 12,
            struct.pack("<I", 0xFEEDFACF) + b"\0" * 12,
            struct.pack(">II", 0xCAFEBABE, 2) + b"\0" * 8,
            b"!<arch>\nlibfoo.o/",
        ],
        ids=["macho-be", "macho-le", "fat", "archive"],
    )
    def test_native_code_is_refused_and_pointed_at_its_channel(self, project, head):
        (project / "blob.bin").write_bytes(head)
        items = include_files.expand([IncludeFile(".", ("blob.bin",))], project)
        with pytest.raises(IncludeNativeCode, match=r"\[native\]") as info:
            include_files.refuse_unprocessed(items, native_key="[native]")
        assert info.value.code == diagnostics.INCLUDE_NATIVE_CODE

    def test_a_java_class_file_is_data(self, project):
        # 0xCAFEBABE then a Java version (major 52+) as the "arch count".
        (project / "A.class").write_bytes(struct.pack(">IHH", 0xCAFEBABE, 0, 52))
        assert include_files.native_kind(project / "A.class") is None

    def test_data_files_pass(self, project):
        include_files.refuse_unprocessed(
            include_files.expand([SOUNDS, PLIST], project), native_key="[native]"
        )


class TestStaging:
    def test_copy_items_lays_out_each_path_once(self, project, tmp_path):
        out = tmp_path / "out"
        twice = IncludeFile(".", ("config/GoogleService-Info.plist",))
        items = include_files.expand([PLIST, SOUNDS, twice], project)
        copied = include_files.copy_items(items, out)
        assert copied == [
            "GoogleService-Info.plist",
            "Sounds/deep/dong.caf",
            "Sounds/ding.caf",
        ]
        assert (out / "Sounds" / "deep" / "dong.caf").read_bytes() == b"dong"

    def test_on_existing_hears_only_about_files_it_did_not_write(
        self, project, tmp_path
    ):
        out = tmp_path / "out"
        out.mkdir()
        (out / "GoogleService-Info.plist").write_bytes(b"generated")
        heard: list[str] = []
        items = include_files.expand([PLIST, PLIST], project)
        include_files.copy_items(items, out, on_existing=heard.append)
        assert heard == ["GoogleService-Info.plist"]

    def test_the_record_round_trips_and_survives_a_failed_copy(self, project, tmp_path):
        out = tmp_path / "out"
        items = include_files.expand([PLIST, SOUNDS], project)
        calls = {"n": 0}

        def flaky(src: Path, dst: Path) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("disk full")
            dst.write_bytes(src.read_bytes())

        with pytest.raises(OSError):
            include_files.copy_items(items, out, record=".rec", copy=flaky)
        assert (out / ".rec").read_text() == "GoogleService-Info.plist\n"

        include_files.copy_items(items, out, record=".rec")
        include_files.remove_recorded(out, ".rec")
        assert not (out / ".rec").exists()
        assert not (out / "GoogleService-Info.plist").exists()
        assert not (out / "Sounds" / "ding.caf").exists()

    def test_remove_recorded_ignores_paths_that_escape(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        (tmp_path / "keep").write_text("x")
        (out / ".rec").write_text("../keep\n\n")
        include_files.remove_recorded(out, ".rec")
        assert (tmp_path / "keep").exists()

    def test_remove_recorded_without_a_record_is_a_no_op(self, tmp_path):
        include_files.remove_recorded(tmp_path, ".rec")

    @pytest.mark.requires_posix
    def test_copy_fresh_keeps_mode_and_times_and_replaces_a_read_only_copy(
        self, tmp_path
    ):
        src = tmp_path / "run.sh"
        src.write_bytes(b"#!/bin/sh\n")
        src.chmod(0o555)
        os.utime(src, ns=(1_000_000_000, 2_000_000_000))
        dst = tmp_path / "out.sh"
        include_files.copy_fresh(src, dst)
        include_files.copy_fresh(src, dst)
        assert dst.read_bytes() == b"#!/bin/sh\n"
        assert dst.stat().st_mode & 0o777 == 0o555
        assert dst.stat().st_mtime_ns == 2_000_000_000

    @pytest.mark.requires_posix
    def test_copy_fresh_drops_extended_attributes(self, tmp_path):
        # App Store Connect refuses a bundle with com.apple.quarantine on any
        # file; shutil.copy2 would carry it across.
        src = tmp_path / "data.json"
        src.write_text("{}")
        dst = tmp_path / "copy.json"
        if sys.platform == "darwin":
            name = "com.apple.quarantine"
            subprocess.run(
                ["xattr", "-w", name, "0081;00000000;Safari;", str(src)], check=True
            )

            def names(path: Path) -> list[str]:
                out = subprocess.run(
                    ["xattr", str(path)], check=True, capture_output=True, text=True
                ).stdout
                return out.split()
        else:
            name = "user.kivyforge"
            os.setxattr(src, name, b"1")  # pyright: ignore[reportAttributeAccessIssue]

            def names(path: Path) -> list[str]:
                return os.listxattr(path)  # pyright: ignore[reportAttributeAccessIssue]

        assert name in names(src)
        include_files.copy_fresh(src, dst)
        assert name not in names(dst)


class TestProductCheck:
    @pytest.fixture
    def expected(self, project):
        return include_files.expected_contents(
            include_files.expand([PLIST, SOUNDS], project)
        )

    @pytest.fixture
    def product(self, project, tmp_path):
        app = tmp_path / "Demo.app"
        include_files.copy_items(include_files.expand([PLIST, SOUNDS], project), app)
        return app

    def test_last_copy_wins(self, project):
        (project / "other").mkdir()
        (project / "other" / "GoogleService-Info.plist").write_bytes(b"second")
        later = IncludeFile(".", ("other/GoogleService-Info.plist",))
        contents = include_files.expected_contents(
            include_files.expand([PLIST, later], project)
        )
        assert contents["GoogleService-Info.plist"] == (
            "other/GoogleService-Info.plist",
            _sha(b"second"),
        )

    def test_an_intact_tree_has_no_mismatches(self, expected, product):
        assert include_files.tree_mismatches(expected, product) == []

    def test_a_missing_and_an_altered_file_are_both_named(self, expected, product):
        (product / "GoogleService-Info.plist").write_bytes(b"binary plist")
        (product / "Sounds" / "ding.caf").unlink()
        mismatches = include_files.tree_mismatches(expected, product)
        assert [(m.path, m.actual) for m in mismatches] == [
            ("GoogleService-Info.plist", _sha(b"binary plist")),
            ("Sounds/ding.caf", None),
        ]
        with pytest.raises(ArtifactContentMismatch) as info:
            include_files.raise_for_mismatches(mismatches, artifact="build/Demo.app")
        err = info.value
        assert err.code == diagnostics.ARTIFACT_CONTENT
        assert err.exit_code == exit_codes.BUILD_FAILURE
        assert "Sounds/ding.caf (from assets/sounds/ding.caf): missing" in str(err)
        assert err.context == {
            "path": "GoogleService-Info.plist",
            "source": "config/GoogleService-Info.plist",
            "artifact": "build/Demo.app",
            "expected": _sha(b"<plist/>"),
            "actual": _sha(b"binary plist"),
        }

    def test_no_mismatches_raises_nothing(self):
        include_files.raise_for_mismatches([], artifact="x")

    def test_a_zip_is_read_under_its_prefix(self, expected, product, tmp_path):
        ipa = tmp_path / "Demo.ipa"
        with zipfile.ZipFile(ipa, "w") as zf:
            zf.writestr("Payload/Demo.app/", "")
            for path in expected:
                zf.write(product / path, f"Payload/Demo.app/{path}")
        assert include_files.zip_mismatches(expected, ipa, "Payload/Demo.app/") == []

        with zipfile.ZipFile(ipa, "w") as zf:
            zf.writestr("Payload/Demo.app/Sounds/ding.caf", b"other")
        mismatches = include_files.zip_mismatches(expected, ipa, "Payload/Demo.app/")
        assert {m.path: m.actual for m in mismatches} == {
            "GoogleService-Info.plist": None,
            "Sounds/deep/dong.caf": None,
            "Sounds/ding.caf": _sha(b"other"),
        }


class TestDoctorCheck:
    def test_no_entries_skips(self, project):
        result = include_files.doctor_check((), (), project, platform="ios")
        assert result.status is Status.SKIP
        assert "tool.kivy.ios.include_files" in result.detail

    def test_matching_files_pass(self, project):
        pins = include_files.hash_pins([PLIST, SOUNDS], project)
        result = include_files.doctor_check(
            [PLIST, SOUNDS], pins, project, platform="macos"
        )
        assert result.status is Status.PASS
        assert result.detail == "3 file(s) match the lock"

    def test_each_kind_of_drift_is_named(self, project):
        pins = include_files.hash_pins([PLIST, SOUNDS], project)
        (project / "assets" / "sounds" / "ding.caf").write_bytes(b"changed")
        (project / "assets" / "sounds" / "deep" / "dong.caf").unlink()
        (project / "assets" / "sounds" / "new.caf").write_bytes(b"new")
        (project / "config" / "GoogleService-Info.plist").unlink()
        result = include_files.doctor_check(
            [PLIST, SOUNDS], pins, project, platform="ios"
        )
        assert result.status is Status.WARN
        for part in (
            "config/GoogleService-Info.plist (missing)",
            "assets/sounds/ding.caf (changed)",
            "assets/sounds/new.caf (not in the lock)",
            "assets/sounds/deep/dong.caf (deleted)",
        ):
            assert part in result.detail
        assert "kivyforge lock -p ios" in (result.hint or "")

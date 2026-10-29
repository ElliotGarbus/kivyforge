"""Which source each package may come from (kivyforge.lock.sources, #86)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

from kivyforge.lock.model import LockedPackage, LockedWheel, PackageDep
from kivyforge.lock.sources import (
    PYPI_URL,
    RECORD_KEY,
    IndexTracker,
    NamedIndex,
    SourceUnavailable,
    changed_local_wheels,
    drop_moved_pins,
    ignore_unrecorded_indexes,
    index_base,
    keep_recorded_dependencies,
    local_names,
    local_wheels,
    read_record,
    source_changes,
    source_policy,
    wheel_changes,
)
from kivyforge.report import diagnostics


def _wheel(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_bytes(b"")
    return path


class TestLocalNames:
    def test_names_from_wheel_filenames_whatever_the_tags(self, tmp_path):
        _wheel(tmp_path, "Kivy-2.3.1-cp314-cp314-android_24_arm64_v8a.whl")
        _wheel(tmp_path, "my_pkg-1.0-py3-none-any.whl")
        _wheel(tmp_path, "notes.txt")
        assert local_names([str(tmp_path)]) == {"kivy", "my-pkg"}

    def test_an_unparseable_wheel_name_is_skipped(self, tmp_path):
        _wheel(tmp_path, "garbage.whl")
        assert local_names([str(tmp_path)]) == set()

    def test_local_wheels_for_one_package(self, tmp_path):
        a = _wheel(tmp_path, "Kivy-2.3.1-cp314-cp314-android_24_arm64_v8a.whl")
        b = _wheel(tmp_path, "kivy-2.3.1-cp314-cp314-android_24_x86_64.whl")
        _wheel(tmp_path, "pyjnius-1.8.0-cp314-cp314-android_24_x86_64.whl")
        assert local_wheels([str(tmp_path)], "KIVY") == [a, b]


class TestSourcePolicy:
    def test_rank_is_overlay_extras_then_named_then_pypi(self):
        policy = source_policy(
            [],
            ["https://a.example/simple", "https://b.example/simple/"],
            named=[
                ("corp", "https://corp.example/simple", False),
                ("mobile", "https://m.example/simple", True),
            ],
        )
        assert policy.rank == (
            NamedIndex("extra-1", "https://a.example/simple/"),
            NamedIndex("extra-2", "https://b.example/simple/"),
            NamedIndex("corp", "https://corp.example/simple/"),
            NamedIndex("pypi", PYPI_URL),
        )
        assert policy.explicit == (NamedIndex("mobile", "https://m.example/simple/"),)

    def test_extra_index_urls_cover_explicit_but_not_pypi(self):
        policy = source_policy(
            [],
            ["https://a.example/simple/"],
            named=[("mobile", "https://m.example/simple/", True)],
        )
        assert policy.extra_index_urls == [
            "https://a.example/simple/",
            "https://m.example/simple/",
        ]

    def test_a_pin_outranks_a_local_wheel(self, tmp_path):
        _wheel(tmp_path, "kivy-2.3.1-py3-none-any.whl")
        _wheel(tmp_path, "plyer-2.1-py3-none-any.whl")
        policy = source_policy(
            [str(tmp_path)],
            [],
            named=[("mobile", "https://m.example/simple/", False)],
            pins={"Kivy": "mobile"},
        )
        assert not policy.is_local("kivy")
        assert policy.is_local("plyer")
        assert policy.pinned_to("kivy") == NamedIndex(
            "mobile", "https://m.example/simple/"
        )

    def test_pinned_to_pypi_without_declaring_it(self):
        policy = source_policy([], [], pins={"pyjnius": "pypi"})
        assert policy.pinned_to("PyJNIus") == NamedIndex("pypi", PYPI_URL)

    def test_environment_is_what_the_shim_reads(self, tmp_path):
        _wheel(tmp_path, "kivy-2.3.1-py3-none-any.whl")
        policy = source_policy(
            [str(tmp_path)], ["https://a.example/simple"], pins={"x": "pypi"}
        )
        data = json.loads(policy.environment(tmp_path / "record.json"))
        assert data["record"] == str(tmp_path / "record.json")
        assert data["find_links"] == [str(tmp_path)]
        assert data["local_names"] == ["kivy"]
        assert data["rank"] == [
            ["extra-1", "https://a.example/simple/"],
            ["pypi", PYPI_URL],
        ]
        assert data["pins"] == {"x": "pypi"}

    def test_index_base_has_one_trailing_slash(self):
        assert index_base("https://x/simple") == "https://x/simple/"
        assert index_base("https://x/simple//") == "https://x/simple/"


class TestUnavailable:
    def test_pinned_package(self):
        policy = source_policy([], [], pins={"pyjnius": "pypi"}, platform="android")
        error = policy.unavailable("pyjnius", "android_24_x86_64")
        assert isinstance(error, SourceUnavailable)
        assert error.code == diagnostics.LOCK_SOURCE_UNAVAILABLE
        assert error.exit_code == 1
        assert "pinned to index 'pypi'" in str(error)
        assert error.context == {
            "distribution": "pyjnius",
            "source": "pypi",
            "variant": "android_24_x86_64",
        }

    def test_local_package(self, tmp_path):
        _wheel(tmp_path, "kivy-2.3.1-cp314-cp314-android_24_arm64_v8a.whl")
        policy = source_policy([str(tmp_path)], [], platform="android")
        error = policy.unavailable("kivy", "android_24_x86_64")
        assert error is not None
        assert "[tool.kivy.android].find_links" in str(error)
        assert error.context["source"] == "find_links"

    def test_unpinned_index_package_keeps_pips_message(self):
        assert source_policy([], []).unavailable("numpy", "x") is None

    def test_messages_encode_in_cp1252(self, tmp_path):
        _wheel(tmp_path, "kivy-1-py3-none-any.whl")
        policy = source_policy([str(tmp_path)], [], pins={"p": "pypi"}, platform="ios")
        for error in (policy.unavailable("p", "v"), policy.unavailable("kivy", "v")):
            str(error).encode("cp1252")


class TestRecord:
    def test_read_record(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_text(json.dumps({"https://f/x.whl": "https://i/simple/"}))
        assert read_record(path) == {"https://f/x.whl": "https://i/simple/"}

    def test_missing_or_corrupt_record_is_empty(self, tmp_path):
        assert read_record(tmp_path / "nope.json") == {}
        (tmp_path / "bad.json").write_text("{")
        assert read_record(tmp_path / "bad.json") == {}

    def test_tracker_one_index_across_variants(self):
        tracker = IndexTracker()
        for arch in ("a", "b"):
            tracker.add(
                {
                    "install": [
                        {
                            "metadata": {"name": "Kivy"},
                            "download_info": {"url": f"https://gh/kivy-{arch}.whl"},
                        }
                    ],
                    RECORD_KEY: {f"https://gh/kivy-{arch}.whl": "https://m/simple/"},
                }
            )
        assert tracker.index_of("kivy") == "https://m/simple/"

    def test_tracker_mixed_or_local_or_unknown_is_none(self):
        tracker = IndexTracker()
        tracker.add(
            {
                "install": [
                    {"metadata": {"name": "a"}, "download_info": {"url": "u1"}},
                    {"metadata": {"name": "b"}, "download_info": {"url": "u2"}},
                    {"metadata": {"name": "c"}, "download_info": {"url": "u3"}},
                ],
                RECORD_KEY: {"u1": "https://x/", "u2": "find_links"},
            }
        )
        tracker.add(
            {
                "install": [
                    {"metadata": {"name": "a"}, "download_info": {"url": "u4"}}
                ],
                RECORD_KEY: {"u4": "https://y/"},
            }
        )
        assert tracker.index_of("a") is None
        assert tracker.index_of("b") is None
        assert tracker.index_of("c") is None
        assert tracker.index_of("never-seen") is None


def _locked(name, *, path=False, index=None):
    wheel = (
        LockedWheel(name=f"{name}.whl", sha256="0" * 64, path=f"wheels/{name}.whl")
        if path
        else LockedWheel(name=f"{name}.whl", sha256="0" * 64, url=f"https://f/{name}")
    )
    return LockedPackage(name=name, version="1", wheels=(wheel,), source_index=index)


class TestDropMovedPins:
    def test_remote_lock_but_now_local(self, tmp_path):
        _wheel(tmp_path, "kivy-1-py3-none-any.whl")
        policy = source_policy([str(tmp_path)], [])
        pins = {"kivy": "1", "other": "1"}
        locked = [_locked("kivy"), _locked("other")]
        assert drop_moved_pins(pins, locked, policy) == {"other": "1"}

    def test_path_lock_but_no_longer_local(self):
        policy = source_policy([], [])
        assert (
            drop_moved_pins({"kivy": "1"}, [_locked("kivy", path=True)], policy) == {}
        )

    def test_path_lock_but_now_pinned(self, tmp_path):
        _wheel(tmp_path, "kivy-1-py3-none-any.whl")
        policy = source_policy([str(tmp_path)], [], pins={"kivy": "pypi"})
        assert (
            drop_moved_pins({"kivy": "1"}, [_locked("kivy", path=True)], policy) == {}
        )

    def test_pinned_index_changed_or_unrecorded(self):
        policy = source_policy([], [], pins={"a": "pypi", "b": "pypi", "c": "pypi"})
        locked = [
            _locked("a", index="https://other/simple/"),
            _locked("b"),  # a lock written before #86 records no index
            _locked("c", index=PYPI_URL),
        ]
        pins = {"a": "1", "b": "1", "c": "1"}
        assert drop_moved_pins(pins, locked, policy) == {"c": "1"}

    def test_unchanged_sources_keep_every_pin(self, tmp_path):
        _wheel(tmp_path, "kivy-1-py3-none-any.whl")
        policy = source_policy([str(tmp_path)], [])
        pins = {"kivy": "1", "other": "1"}
        locked = [_locked("kivy", path=True), _locked("other")]
        assert drop_moved_pins(pins, locked, policy) == pins


@dataclasses.dataclass(frozen=True)
class _Lock:
    packages: tuple


def _lock(packages):
    return _Lock(tuple(packages))


class TestCheckHelpers:
    def test_source_changes_name_a_move_at_the_same_version(self):
        old = [_locked("kivy", index=PYPI_URL), _locked("x", index=PYPI_URL)]
        new = [
            _locked("kivy", path=True),
            _locked("x", index="https://m/simple/"),
        ]
        assert source_changes(old, new) == [
            f"  ~ kivy: from {PYPI_URL} -> from find_links",
            f"  ~ x: from {PYPI_URL} -> from https://m/simple/",
        ]

    def test_source_changes_ignore_version_moves_and_new_packages(self):
        old = [_locked("kivy", index=PYPI_URL)]
        moved = dataclasses.replace(_locked("kivy", path=True), version="2")
        assert source_changes(old, [moved, _locked("new")]) == []

    def test_wheel_changes_name_a_rebuilt_wheel(self):
        old = [_locked("kivymd", path=True), _locked("x")]
        rebuilt = dataclasses.replace(
            old[0],
            wheels=(dataclasses.replace(old[0].wheels[0], sha256="1" * 64),),
        )
        assert wheel_changes(old, [rebuilt, _locked("x")]) == [
            f"  ~ kivymd: kivymd.whl changed (sha256 {'0' * 12} -> {'1' * 12})"
        ]

    def test_wheel_changes_ignore_version_moves(self):
        old = [_locked("kivymd", path=True)]
        moved = dataclasses.replace(
            old[0],
            version="2",
            wheels=(dataclasses.replace(old[0].wheels[0], sha256="1" * 64),),
        )
        assert wheel_changes(old, [moved]) == []

    def test_an_old_lock_without_indexes_is_not_drift(self):
        old = _lock([_locked("kivy"), _locked("x", index="https://a/")])
        new = _lock([_locked("kivy", index=PYPI_URL), _locked("x", index="https://b/")])
        result = ignore_unrecorded_indexes(old, new)
        by_name = {p.name: p.source_index for p in result.packages}
        # kivy was never recorded: ignored. x was: a change still shows.
        assert by_name == {"kivy": None, "x": "https://b/"}

    def test_dependency_edges_of_unchanged_wheels_are_not_drift(self):
        """A pre-#190 desktop lock records extra-gated edges."""
        unfiltered = (PackageDep("asynckivy"), PackageDep("pytest"))
        old = _lock(
            [
                dataclasses.replace(_locked("kivymd"), dependencies=unfiltered),
                dataclasses.replace(_locked("kivy"), dependencies=unfiltered),
            ]
        )
        rebuilt = dataclasses.replace(
            _locked("kivy"),
            wheels=(dataclasses.replace(_locked("kivy").wheels[0], sha256="1" * 64),),
        )
        filtered = (PackageDep("asynckivy"),)
        new = _lock(
            [
                dataclasses.replace(_locked("kivymd"), dependencies=filtered),
                dataclasses.replace(rebuilt, dependencies=filtered),
            ]
        )
        result = keep_recorded_dependencies(old, new)
        by_name = {p.name: p.dependencies for p in result.packages}
        # kivymd's wheel held: its recorded edges stay. kivy's changed: new ones.
        assert by_name == {"kivymd": unfiltered, "kivy": filtered}


class TestChangedLocalWheels:
    """A wheel replaced in find_links leaves the lock inputs unchanged (#190)."""

    def _pinned(self, tmp_path, content: bytes) -> LockedPackage:
        path = _wheel(tmp_path / "wheels", "kivymd.whl")
        path.write_bytes(content)
        wheel = LockedWheel(
            name="kivymd.whl",
            sha256=hashlib.sha256(content).hexdigest(),
            path="wheels/kivymd.whl",
        )
        return LockedPackage(name="kivymd", version="1", wheels=(wheel,))

    def test_an_unchanged_wheel_is_not_reported(self, tmp_path):
        package = self._pinned(tmp_path, b"one")
        assert changed_local_wheels([package], tmp_path) == {}

    def test_a_replaced_wheel_is_reported(self, tmp_path):
        package = self._pinned(tmp_path, b"one")
        (tmp_path / "wheels" / "kivymd.whl").write_bytes(b"two")
        assert changed_local_wheels([package], tmp_path) == {
            "kivymd": ["  ~ kivymd: wheels/kivymd.whl changed since it was locked"]
        }

    def test_a_deleted_wheel_is_reported(self, tmp_path):
        package = self._pinned(tmp_path, b"one")
        (tmp_path / "wheels" / "kivymd.whl").unlink()
        assert changed_local_wheels([package], tmp_path) == {
            "kivymd": ["  - kivymd: wheels/kivymd.whl is missing"]
        }

    def test_index_wheels_are_not_read(self, tmp_path):
        assert changed_local_wheels([_locked("kivy")], tmp_path) == {}

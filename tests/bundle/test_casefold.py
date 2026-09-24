"""Case-only path collisions vs. case-insensitive filesystems (test-matrix §5.6).

The pure helpers are tested hermetically. ``TestRealHostProducer`` is the part
§5.6 asked for: it stages an archive holding the real terminfo pair onto
whatever filesystem the test host has, so the Ubuntu unit legs prove the
case-sensitive path still stages and the Windows legs prove the
case-insensitive path is refused up front rather than dying in ``copytree``.
"""

from __future__ import annotations

import sys
import tarfile
import tempfile
from pathlib import Path

import pytest

from kivyforge.bundle import casefold
from kivyforge.bundle.casefold import (
    case_collision_problem,
    case_collisions,
    is_case_insensitive,
)
from kivyforge.lock.wheelruntime.model import PythonRuntime, RuntimeArtifact
from kivyforge.platforms.linux import AppDirError
from kivyforge.platforms.linux import runtime_stage as linux_stage
from kivyforge.platforms.macos import AppBundleError
from kivyforge.platforms.macos import runtime_stage as macos_stage
from kivyforge.platforms.windows import WindowsBundleError
from kivyforge.platforms.windows import runtime_stage as windows_stage

# The pair every python-build-standalone linux-gnu runtime ships (25 such
# groups, all under share/terminfo), observed failing on WSL2 /mnt/c 2026-09-22.
PAIR = ("python/share/terminfo/h/hp70092A", "python/share/terminfo/h/hp70092a")


class TestCaseCollisions:
    def test_none(self):
        assert case_collisions(["python/bin/python3", "python/lib/x.py"]) == []

    def test_the_terminfo_pair(self):
        assert case_collisions([*PAIR, "python/bin/python3"]) == [PAIR]

    def test_directory_members_collide_too(self):
        # tar lists directories; terminfo ships both E/ and e/.
        names = ["python/share/terminfo/E/", "python/share/terminfo/e"]
        assert case_collisions(names) == [
            ("python/share/terminfo/E", "python/share/terminfo/e")
        ]

    def test_groups_are_sorted_and_stable(self):
        names = ["b/X", "a/q", "b/x", "a/Q", "a/Q"]
        assert case_collisions(names) == [("a/Q", "a/q"), ("b/X", "b/x")]


class TestIsCaseInsensitive:
    @pytest.mark.requires_windows
    def test_windows_is_case_insensitive(self, tmp_path):
        assert is_case_insensitive(tmp_path) is True

    @pytest.mark.skipif(sys.platform != "linux", reason="ext4-style host only")
    def test_linux_is_case_sensitive(self, tmp_path):
        assert is_case_insensitive(tmp_path) is False

    def test_leaves_no_probe_behind(self, tmp_path):
        is_case_insensitive(tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_probes_the_nearest_existing_ancestor(self, tmp_path):
        # The stagers ask about their destination before creating it.
        assert is_case_insensitive(tmp_path / "not" / "yet") == is_case_insensitive(
            tmp_path
        )
        assert not (tmp_path / "not").exists()

    def test_unprobeable_reports_false(self, tmp_path, monkeypatch):
        def _deny(*a, **k):
            raise PermissionError("read-only")

        monkeypatch.setattr(casefold.tempfile, "mkstemp", _deny)
        assert is_case_insensitive(tmp_path) is False


class TestCaseCollisionProblem:
    def test_no_collisions_never_probes(self, tmp_path, monkeypatch):
        # The common case (every macOS/Windows runtime measured) must cost no
        # filesystem write at all.
        def _boom(d):
            raise AssertionError("probed without a collision")

        monkeypatch.setattr(casefold, "is_case_insensitive", _boom)
        assert (
            case_collision_problem(["a", "b"], "rt.tar.gz", writes_to=[tmp_path])
            is None
        )

    def test_case_sensitive_destination_is_fine(self, tmp_path, monkeypatch):
        monkeypatch.setattr(casefold, "is_case_insensitive", lambda d: False)
        assert case_collision_problem(PAIR, "rt.tar.gz", writes_to=[tmp_path]) is None

    def test_names_the_pair_the_count_and_the_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(casefold, "is_case_insensitive", lambda d: True)
        problem = case_collision_problem(PAIR, "rt.tar.gz", writes_to=[tmp_path])
        assert problem is not None
        assert "rt.tar.gz contains 1 path(s) that differ only by case" in problem
        assert f"{PAIR[0]} and {PAIR[1]}" in problem
        assert str(tmp_path) in problem

    def test_names_the_directory_that_is_insensitive(self, tmp_path, monkeypatch):
        ok, bad = tmp_path / "ext4", tmp_path / "ntfs"
        monkeypatch.setattr(casefold, "is_case_insensitive", lambda d: d == bad)
        problem = case_collision_problem(PAIR, "rt.tar.gz", writes_to=[ok, bad])
        assert problem is not None and str(bad) in problem and str(ok) not in problem


# ---- the stagers ----------------------------------------------------------- #


def _archive_with_pair(path):
    """A PBS-shaped archive that also carries the terminfo case pair."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "python"
        (root / "bin").mkdir(parents=True)
        (root / "bin" / "python3").write_bytes(b"x")
        with tarfile.open(path, "w:gz") as tf:
            tf.add(root, arcname="python")
            for i, name in enumerate(PAIR):
                src = root.parent / f"entry{i}"
                src.write_bytes(name.encode())
                tf.add(src, arcname=name)


def _runtime(arch):
    return PythonRuntime(
        provider="python-build-standalone",
        version="3.13.14",
        artifacts=(
            RuntimeArtifact(arch=arch, url=f"https://e/{arch}.tar.gz", sha256="x"),
        ),
        floor="2.17",
    )


@pytest.mark.parametrize(
    ("stage", "arch", "error", "hint"),
    [
        (linux_stage, "x86_64", AppDirError, "not /mnt/c"),
        (macos_stage, "arm64", AppBundleError, "case-sensitive APFS volume"),
        (windows_stage, "amd64", WindowsBundleError, "cannot be staged on a Windows"),
    ],
)
def test_stagers_refuse_before_extracting(
    tmp_path, monkeypatch, stage, arch, error, hint
):
    archive = tmp_path / "rt.tar.gz"
    _archive_with_pair(archive)
    monkeypatch.setattr(stage, "_fetch", lambda *a, **k: archive)
    monkeypatch.setattr(casefold, "is_case_insensitive", lambda d: True)
    home = tmp_path / "bundle" / "python"
    with pytest.raises(error, match="differ only by case") as exc:
        stage.stage_runtime(_runtime(arch), arch, home, project_root=tmp_path)
    assert hint in str(exc.value)
    assert not home.exists()  # refused before anything was written


class TestRealHostProducer:
    """No mocks: the host's own filesystem decides (test-matrix §5.6)."""

    def _stage(self, tmp_path, monkeypatch):
        archive = tmp_path / "rt.tar.gz"
        _archive_with_pair(archive)
        monkeypatch.setattr(linux_stage, "_fetch", lambda *a, **k: archive)
        home = tmp_path / "AppDir" / "usr" / "python"
        linux_stage.stage_runtime(
            _runtime("x86_64"), "x86_64", home, project_root=tmp_path
        )
        return home

    @pytest.mark.skipif(sys.platform != "linux", reason="case-sensitive host only")
    def test_case_sensitive_host_stages_both(self, tmp_path, monkeypatch):
        home = self._stage(tmp_path, monkeypatch)
        h = home / "share" / "terminfo" / "h"
        assert (h / "hp70092A").read_bytes() == PAIR[0].encode()
        assert (h / "hp70092a").read_bytes() == PAIR[1].encode()

    @pytest.mark.requires_windows
    def test_case_insensitive_host_is_refused_up_front(self, tmp_path, monkeypatch):
        # Before this check the same staging died partway in copytree with a
        # bare shutil.Error (the 2026-09-22 WSL2 /mnt/c reproduction).
        with pytest.raises(AppDirError, match="differ only by case"):
            self._stage(tmp_path, monkeypatch)

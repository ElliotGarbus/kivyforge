"""The bundle work directory, the swap and the copy that keep the previous output.

The work directory gets mkdir's mode, not mkdtemp's owner-only 0700. Swapping
it in must leave the previous tree whole and no temp tree behind when the OS
refuses a step. Copying a package into dist/ must leave a previous file of the
same name whole until the copy succeeds, including when it is interrupted.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from kivyforge.bundle import workdir
from kivyforge.bundle.workdir import copy_in, make_work_dir, swap_in


@pytest.fixture
def umask():
    old = os.umask(0o022)
    yield os.umask
    os.umask(old)


@pytest.mark.requires_posix
@pytest.mark.parametrize(("mask", "mode"), [(0o022, 0o755), (0o077, 0o700)])
def test_mode_follows_the_umask(tmp_path, umask, mask, mode):
    umask(mask)
    work = make_work_dir(tmp_path, prefix=".x.tmp-")
    assert stat.S_IMODE(work.stat().st_mode) == mode


@pytest.mark.requires_posix
def test_umask_is_left_as_it_was(tmp_path, umask):
    umask(0o027)
    make_work_dir(tmp_path, prefix=".x.tmp-")
    assert os.umask(0o027) == 0o027


def test_created_under_parent_with_prefix(tmp_path):
    work = make_work_dir(tmp_path, prefix=".My App.app.tmp-")
    assert work.parent == tmp_path
    assert work.name.startswith(".My App.app.tmp-")
    assert work.is_dir()


def _tree(path: Path, text: str) -> Path:
    path.mkdir()
    (path / "held").write_text(text)
    return path


@pytest.fixture
def refuse(monkeypatch):
    """Make ``os.replace`` refuse each rename whose source *pick* selects."""
    real = os.replace

    def install(pick):
        def replace(src, dst, **kw):
            if pick(Path(src).name):
                raise PermissionError(13, "Permission denied", str(src))
            real(src, dst, **kw)

        monkeypatch.setattr(os, "replace", replace)

    return install


def test_swap_in_with_no_previous_tree(tmp_path):
    swap_in(_tree(tmp_path / ".A.tmp-1", "new"), tmp_path / "A")
    assert (tmp_path / "A" / "held").read_text() == "new"
    assert [p.name for p in tmp_path.iterdir()] == ["A"]


def test_swap_in_replaces_and_deletes_the_previous_tree(tmp_path):
    dest = _tree(tmp_path / "A", "old")
    swap_in(_tree(tmp_path / ".A.tmp-1", "new"), dest)
    assert (dest / "held").read_text() == "new"
    assert [p.name for p in tmp_path.iterdir()] == ["A"]


def test_refused_move_into_place_restores_the_previous_tree(tmp_path, refuse):
    dest = _tree(tmp_path / "A", "old")
    work = _tree(tmp_path / ".A.tmp-1", "new")
    refuse(lambda name: name == work.name)
    with pytest.raises(PermissionError):
        swap_in(work, dest)
    assert (dest / "held").read_text() == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["A"]


def test_refused_move_aside_keeps_the_previous_tree(tmp_path, refuse):
    dest = _tree(tmp_path / "A", "old")
    refuse(lambda name: name == "A")
    with pytest.raises(PermissionError):
        swap_in(_tree(tmp_path / ".A.tmp-1", "new"), dest)
    assert (dest / "held").read_text() == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["A"]


def test_failed_restore_keeps_the_previous_tree_and_the_first_error(tmp_path, refuse):
    # Both the move into place and the move back are refused. The error raised
    # is the first one, and the previous tree survives beside A for recovery.
    dest = _tree(tmp_path / "A", "old")
    work = _tree(tmp_path / ".A.tmp-1", "new")
    refuse(lambda name: name == work.name or name.startswith(".A.old-"))
    with pytest.raises(PermissionError) as raised:
        swap_in(work, dest)
    assert raised.value.filename == str(work)
    [aside] = tmp_path.iterdir()
    assert aside.name.startswith(".A.old-")
    assert (aside / "held").read_text() == "old"


def test_undeletable_previous_tree_does_not_fail_the_swap(tmp_path, monkeypatch):
    # The new tree is already in place when the old one is deleted, so a file
    # in it that cannot be removed is left behind, not raised.
    dest = _tree(tmp_path / "A", "old")
    work = _tree(tmp_path / ".A.tmp-1", "new")
    real_unlink = os.unlink

    def unlink(path, *a, **kw):
        if os.path.basename(path) == "held":
            raise PermissionError(13, "Permission denied", str(path))
        real_unlink(path, *a, **kw)

    monkeypatch.setattr(os, "unlink", unlink)
    swap_in(work, dest)
    assert (dest / "held").read_text() == "new"
    [leftover] = tmp_path.glob(".A.old-*")
    assert (leftover / "held").read_text() == "old"


# --- copy_in: a single file into dist/ ---------------------------------------


@pytest.fixture
def package(tmp_path) -> Path:
    src = tmp_path / "build" / "app-release.apk"
    src.parent.mkdir()
    src.write_bytes(b"new package")
    return src


def _dist(tmp_path: Path) -> Path:
    return tmp_path / "dist" / "android"


def _fail_copy_partway(monkeypatch, exc: BaseException) -> None:
    """Make the copy write part of the file, then raise *exc*."""

    def copy2(src, dst, **kw):
        Path(dst).write_bytes(b"new pa")
        raise exc

    monkeypatch.setattr(workdir.shutil, "copy2", copy2)


def test_copy_in_creates_the_folder_and_copies_the_bytes(tmp_path, package):
    dest = _dist(tmp_path) / "demo-1.0.0.apk"
    copy_in(package, dest)
    assert dest.read_bytes() == b"new package"
    assert package.read_bytes() == b"new package"  # a copy, not a move
    assert [p.name for p in dest.parent.iterdir()] == ["demo-1.0.0.apk"]


def test_copy_in_folder_creation_failure_writes_nothing(tmp_path, package):
    # A file where dist/android belongs: mkdir(exist_ok=True) still raises,
    # before any rename or write, so the restore path never runs.
    (tmp_path / "dist").mkdir()
    blocker = _dist(tmp_path)
    blocker.write_bytes(b"not a folder")
    with pytest.raises(FileExistsError):
        copy_in(package, blocker / "demo-1.0.0.apk")
    assert blocker.read_bytes() == b"not a folder"
    assert [p.name for p in (tmp_path / "dist").iterdir()] == ["android"]


@pytest.mark.parametrize(
    "exc", [OSError(28, "No space left on device"), KeyboardInterrupt()]
)
def test_copy_in_failure_restores_the_previous_file(
    tmp_path, package, monkeypatch, exc
):
    dest = _dist(tmp_path) / "demo-1.0.0.apk"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"old package")
    _fail_copy_partway(monkeypatch, exc)
    with pytest.raises(type(exc)):
        copy_in(package, dest)
    assert dest.read_bytes() == b"old package"
    assert [p.name for p in dest.parent.iterdir()] == ["demo-1.0.0.apk"]


def test_copy_in_failure_with_no_previous_file_leaves_nothing(
    tmp_path, package, monkeypatch
):
    dest = _dist(tmp_path) / "demo-1.0.0.apk"
    _fail_copy_partway(monkeypatch, OSError(28, "No space left on device"))
    with pytest.raises(OSError):
        copy_in(package, dest)
    assert list(dest.parent.iterdir()) == []


def test_copy_in_failed_restore_keeps_the_previous_file_and_the_first_error(
    tmp_path, package, monkeypatch, refuse
):
    dest = _dist(tmp_path) / "demo-1.0.0.apk"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"old package")
    _fail_copy_partway(monkeypatch, OSError(28, "No space left on device"))
    # The rename aside goes through; the rename back is refused.
    refuse(lambda name: name.startswith(".demo-1.0.0.apk.old-"))
    with pytest.raises(OSError) as raised:
        copy_in(package, dest, timeout=0)
    assert raised.value.errno == 28
    [aside] = dest.parent.iterdir()
    assert aside.name.startswith(".demo-1.0.0.apk.old-")
    assert aside.read_bytes() == b"old package"


def test_copy_in_retries_a_held_previous_file(tmp_path, package, monkeypatch):
    # A file a previous package wrote seconds ago may still be held by the
    # Windows antivirus scanner; the rename aside waits for it.
    dest = _dist(tmp_path) / "demo-1.0.0.apk"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"old package")
    real = os.replace
    refusals = [2]

    def replace(src, dst, **kw):
        if Path(src) == dest and refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Permission denied", str(src))
        real(src, dst, **kw)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(workdir.time, "sleep", lambda s: None)
    copy_in(package, dest)
    assert refusals == [0]
    assert dest.read_bytes() == b"new package"
    assert [p.name for p in dest.parent.iterdir()] == ["demo-1.0.0.apk"]


def test_copy_in_previous_file_held_past_the_timeout(tmp_path, package, refuse):
    dest = _dist(tmp_path) / "demo-1.0.0.apk"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"old package")
    refuse(lambda name: name == "demo-1.0.0.apk")
    with pytest.raises(PermissionError):
        copy_in(package, dest, timeout=0)
    assert dest.read_bytes() == b"old package"
    assert [p.name for p in dest.parent.iterdir()] == ["demo-1.0.0.apk"]


def test_copy_in_again_replaces_the_same_name_and_keeps_other_versions(
    tmp_path, package
):
    folder = _dist(tmp_path)
    folder.mkdir(parents=True)
    (folder / "demo-0.9.0.apk").write_bytes(b"older version")
    (folder / "demo-1.0.0.apk").write_bytes(b"old package")
    copy_in(package, folder / "demo-1.0.0.apk")
    assert (folder / "demo-1.0.0.apk").read_bytes() == b"new package"
    assert (folder / "demo-0.9.0.apk").read_bytes() == b"older version"
    assert sorted(p.name for p in folder.iterdir()) == [
        "demo-0.9.0.apk",
        "demo-1.0.0.apk",
    ]


def test_copy_in_keeps_metadata_like_copy2(tmp_path, package):
    # copy2, not copyfile: the copy keeps the source's modification time, so
    # dist/ shows when the package was built rather than when it was copied.
    os.utime(package, (1_000_000_000, 1_000_000_000))
    dest = _dist(tmp_path) / "demo-1.0.0.apk"
    copy_in(package, dest)
    assert dest.stat().st_mtime == pytest.approx(1_000_000_000)

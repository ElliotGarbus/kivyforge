"""The bundle work directory: mkdir's mode, and a swap that keeps the previous tree.

The work directory gets mkdir's mode, not mkdtemp's owner-only 0700. Swapping
it in must leave the previous tree whole and no temp tree behind when the OS
refuses a step.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from kivyforge.bundle.workdir import make_work_dir, swap_in


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

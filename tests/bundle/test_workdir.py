"""The bundle work directory gets mkdir's mode, not mkdtemp's owner-only 0700."""

from __future__ import annotations

import os
import stat

import pytest

from kivyforge.bundle.workdir import make_work_dir


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

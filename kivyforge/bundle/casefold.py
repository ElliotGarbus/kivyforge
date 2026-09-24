"""Case-insensitive filesystems vs. archives whose paths differ only by case.

A runtime archive can hold two entries a case-insensitive filesystem cannot:
every python-build-standalone ``linux-gnu`` runtime ships 25 such pairs, all in
``python/share/terminfo`` (``h/hp70092A`` beside ``h/hp70092a``, ``E/`` beside
``e/``). Staged onto NTFS — WSL2 building onto ``/mnt/c``, observed 2026-09-22
(test-matrix.md §5.6) — the copy dies partway with a bare ``shutil.Error``;
extracted onto a case-insensitive APFS volume, ``tarfile`` does not fail at all
and silently merges the pair instead.

So the stagers ask before extracting: :func:`case_collision_problem` returns a
message when the archive has such pairs *and* a directory it is about to write
into cannot hold them. The filesystem is only probed when collisions exist, so
an archive without any (every macOS and Windows runtime measured so far) costs
nothing and changes nothing.
"""

from __future__ import annotations

import os
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path


def case_collisions(names: Iterable[str]) -> list[tuple[str, ...]]:
    """Groups of paths in *names* that are equal once case is folded.

    Each group is sorted, and the groups are sorted, so the result is stable.
    Trailing ``/`` (a directory member) is ignored, so a directory and a file
    whose names fold together collide as well.
    """
    groups: defaultdict[str, set[str]] = defaultdict(set)
    for name in names:
        name = name.rstrip("/")
        groups[name.casefold()].add(name)
    return sorted(tuple(sorted(g)) for g in groups.values() if len(g) > 1)


def is_case_insensitive(directory: Path) -> bool:
    """Whether *directory*'s filesystem treats ``aB`` and ``Ab`` as one name.

    Probes the nearest existing ancestor (the stagers ask about directories
    they have not created yet) by creating a temporary file and looking for it
    under its case-swapped name. A directory that cannot be probed reports
    ``False``: this check exists to explain a failure clearly, never to cause
    one it cannot demonstrate.
    """
    probe_dir = directory
    while not probe_dir.exists():
        if probe_dir.parent == probe_dir:
            return False
        probe_dir = probe_dir.parent
    try:
        fd, path = tempfile.mkstemp(prefix=".kfCaseProbe", dir=probe_dir)
    except OSError:
        return False
    os.close(fd)
    try:
        name = os.path.basename(path)
        return os.path.exists(os.path.join(probe_dir, name.swapcase()))
    finally:
        os.unlink(path)


def case_collision_problem(
    names: Iterable[str], archive_name: str, *, writes_to: Iterable[Path]
) -> str | None:
    """Explain why *archive_name* cannot be staged into *writes_to*, or ``None``.

    ``None`` when the archive has no case-only collisions, or when every
    directory it will be written into is case-sensitive.
    """
    collisions = case_collisions(names)
    if not collisions:
        return None
    blocked = [d for d in writes_to if is_case_insensitive(d)]
    if not blocked:
        return None
    first = collisions[0]
    return (
        f"{archive_name} contains {len(collisions)} path(s) that differ only "
        f"by case (e.g. {first[0]} and {first[1]}), and {blocked[0]} is on a "
        "case-insensitive filesystem, which cannot hold both. Staging there "
        "would fail partway or silently merge them.\n"
        "  Build from a case-sensitive filesystem."
    )

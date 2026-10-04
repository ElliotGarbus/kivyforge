#!/usr/bin/env python3
"""Keep the code vendored from python-for-android in step with a pinned revision.

The Android bootstrap's ``android`` package and part of its ``PythonActivity``
come from python-for-android (p4a), unchanged. ``P4A_VENDOR.toml`` (in
``kivyforge/platforms/android/bootstrap/templates/p4a/``) is the one list of
what is vendored and from which revision:

- ``[[file]]``: a whole p4a file, copied unchanged.
- ``[[block]]`` with ``target``: one or more adjacent members of a p4a Java
  file, pasted into a kivyforge file between ``// BEGIN p4a <name>`` and
  ``// END p4a <name>``. ``first`` and ``last`` are the stripped first lines of
  the first and last member; the block runs to the end of the last member.
  When ``sources`` lists several p4a files, the block must read the same in
  each.
- ``[[block]]`` with ``fragment``: the same, written to a file of its own,
  which the render step swaps in.

Commands:

- ``check``: fetch the pinned revision and require every file, block and
  fragment to match it. Line endings are normalised to LF on both sides,
  since a Windows checkout may carry CRLF. Run in CI.
- ``drift [--to REF]``: list the p4a commits since the pin that touch a
  vendored path, and show what an update to ``REF`` (default ``develop``)
  would change.
- ``update --rev SHA``: rewrite every vendored file, block and fragment at
  ``SHA``, move the pin, and print the diff for review. kivyforge's own code
  is never touched.

All paths in ``P4A_VENDOR.toml`` are relative to the bootstrap's
``templates/`` directory, except ``source``/``sources``, which are paths in the
p4a repository. Set ``GITHUB_TOKEN`` to lift the GitHub API rate limit for
``drift``.

Usage: python scripts/sync_p4a.py check|drift|update
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_ROOT = REPO_ROOT / "kivyforge/platforms/android/bootstrap/templates"
MANIFEST = TEMPLATES_ROOT / "p4a" / "P4A_VENDOR.toml"

# (rev, p4a path) -> file text
Fetch = Callable[[str, str], str]


class SyncError(Exception):
    """The manifest is malformed, a source is unreachable, or an anchor moved."""


@dataclass(frozen=True)
class VendoredFile:
    path: str
    source: str


@dataclass(frozen=True)
class Block:
    name: str
    sources: tuple[str, ...]
    first: str
    last: str
    target: str | None
    fragment: str | None


@dataclass(frozen=True)
class Manifest:
    repo: str
    rev: str
    files: tuple[VendoredFile, ...]
    blocks: tuple[Block, ...]


def load_manifest(path: Path | None = None) -> Manifest:
    path = path or MANIFEST
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    try:
        upstream = data["upstream"]
        files = tuple(
            VendoredFile(path=f["path"], source=f["source"])
            for f in data.get("file", [])
        )
        blocks = []
        for b in data.get("block", []):
            sources = b.get("sources") or [b["source"]]
            target, fragment = b.get("target"), b.get("fragment")
            if (target is None) == (fragment is None):
                raise SyncError(
                    f"block {b['name']!r}: give exactly one of target or fragment"
                )
            blocks.append(
                Block(
                    name=b["name"],
                    sources=tuple(sources),
                    first=b["first"],
                    last=b.get("last", b["first"]),
                    target=target,
                    fragment=fragment,
                )
            )
        return Manifest(
            repo=upstream["repo"],
            rev=upstream["rev"],
            files=files,
            blocks=tuple(blocks),
        )
    except KeyError as exc:
        raise SyncError(f"{path}: missing key {exc}") from exc


# --- Java member extraction --------------------------------------------------


def _code_braces(line: str, in_comment: bool) -> tuple[str, bool]:
    """The braces and semicolons in ``line`` that are code, not comment or
    literal, and whether a block comment is still open at its end."""
    out = []
    i = 0
    while i < len(line):
        if in_comment:
            end = line.find("*/", i)
            if end < 0:
                return "".join(out), True
            in_comment = False
            i = end + 2
            continue
        ch = line[i]
        if line.startswith("//", i):
            break
        if line.startswith("/*", i):
            in_comment = True
            i += 2
            continue
        if ch in "\"'":
            i += 1
            while i < len(line) and line[i] != ch:
                i += 2 if line[i] == "\\" else 1
        elif ch in "{};":
            out.append(ch)
        i += 1
    return "".join(out), in_comment


def _member_end(lines: list[str], start: int) -> int:
    """Index of the last line of the member that begins at ``lines[start]``:
    where its braces balance, or its first top-level ``;`` for a field."""
    depth = 0
    opened = False
    in_comment = False
    for k in range(start, len(lines)):
        code, in_comment = _code_braces(lines[k], in_comment)
        for ch in code:
            if ch == "{":
                depth += 1
                opened = True
            elif ch == "}":
                depth -= 1
                if opened and depth == 0:
                    return k
            elif ch == ";" and not opened and depth == 0:
                return k
    raise SyncError(f"member starting {lines[start].strip()!r} never ends")


def _unique_line(lines: list[str], anchor: str, where: str) -> int:
    hits = [i for i, line in enumerate(lines) if line.strip() == anchor]
    if len(hits) != 1:
        raise SyncError(
            f"{where}: expected exactly one line {anchor!r}, found {len(hits)}"
        )
    return hits[0]


def extract_block(text: str, first: str, last: str, where: str = "source") -> str:
    """The lines from ``first`` through the end of the member at ``last``."""
    lines = _lf(text).splitlines(keepends=True)
    start = _unique_line(lines, first, where)
    last_start = _unique_line(lines, last, where)
    if last_start < start:
        raise SyncError(f"{where}: {last!r} comes before {first!r}")
    end = _member_end(lines, last_start)
    return "".join(lines[start : end + 1])


def _fence(name: str) -> tuple[str, str]:
    return f"// BEGIN p4a {name}", f"// END p4a {name}"


def fenced_span(text: str, name: str, where: str) -> tuple[int, int]:
    """Character offsets of the content between ``name``'s fence lines."""
    begin, end = _fence(name)
    lines = text.splitlines(keepends=True)
    b = _unique_line(lines, begin, where)
    e = _unique_line(lines, end, where)
    if e < b:
        raise SyncError(f"{where}: {end!r} comes before {begin!r}")
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    return offsets[b + 1], offsets[e]


def read_fenced(text: str, name: str, where: str) -> str:
    start, end = fenced_span(text, name, where)
    return text[start:end]


def replace_fenced(text: str, name: str, content: str, where: str) -> str:
    start, end = fenced_span(text, name, where)
    return text[:start] + content + text[end:]


# --- upstream ----------------------------------------------------------------


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def _github_request(url: str) -> bytes:
    request = urllib.request.Request(url)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:  # noqa: S310
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise SyncError(f"{url}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SyncError(f"could not reach {url} ({exc.reason})") from exc


def github_fetch(repo: str) -> Fetch:
    cache: dict[tuple[str, str], str] = {}

    def fetch(rev: str, path: str) -> str:
        key = (rev, path)
        if key not in cache:
            url = f"https://raw.githubusercontent.com/{repo}/{rev}/{path}"
            cache[key] = _lf(_github_request(url).decode("utf-8"))
        return cache[key]

    return fetch


def upstream_block(block: Block, rev: str, fetch: Fetch) -> str:
    """The block's text at ``rev``; every listed source must agree."""
    texts = {
        source: extract_block(
            fetch(rev, source), block.first, block.last, f"{source}@{rev[:12]}"
        )
        for source in block.sources
    }
    distinct = set(texts.values())
    if len(distinct) != 1:
        raise SyncError(
            f"block {block.name!r}: its sources differ at {rev[:12]} "
            f"({', '.join(block.sources)}); split it per source or choose one"
        )
    return distinct.pop()


# --- local -------------------------------------------------------------------


def _local(rel: str) -> Path:
    return TEMPLATES_ROOT / rel


def _read_local(rel: str) -> str | None:
    path = _local(rel)
    if not path.is_file():
        return None
    return _lf(path.read_text(encoding="utf-8"))


def local_block(block: Block) -> str | None:
    if block.fragment is not None:
        return _read_local(block.fragment)
    assert block.target is not None
    text = _read_local(block.target)
    if text is None:
        return None
    return read_fenced(text, block.name, block.target)


# --- commands ----------------------------------------------------------------


def check(manifest: Manifest, fetch: Fetch) -> list[str]:
    problems: list[str] = []
    for f in manifest.files:
        try:
            expected = fetch(manifest.rev, f.source)
        except SyncError as exc:
            problems.append(str(exc))
            continue
        actual = _read_local(f.path)
        if actual is None:
            problems.append(f"{f.path}: vendored file is missing")
        elif actual != expected:
            problems.append(f"{f.path} differs from p4a {f.source}")
    for block in manifest.blocks:
        try:
            expected = upstream_block(block, manifest.rev, fetch)
            actual = local_block(block)
        except SyncError as exc:
            problems.append(str(exc))
            continue
        where = block.fragment or block.target
        if actual is None:
            problems.append(f"{where}: missing (block {block.name!r})")
        elif actual != expected:
            problems.append(
                f"{where}: block {block.name!r} differs from p4a "
                f"{', '.join(block.sources)}"
            )
    return problems


def _diff(old: str, new: str, label: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            f"a/{label}",
            f"b/{label}",
        )
    )


def planned_changes(
    manifest: Manifest, to_rev: str, fetch: Fetch
) -> list[tuple[str, str, str]]:
    """``(local path, current text, text at to_rev)`` for every vendored path
    whose content would change, with blocks spliced into their target."""
    changes: dict[str, tuple[str, str]] = {}

    def current(rel: str) -> str:
        if rel in changes:
            return changes[rel][1]
        text = _read_local(rel) or ""
        changes[rel] = (text, text)
        return text

    for f in manifest.files:
        current(f.path)
        changes[f.path] = (changes[f.path][0], fetch(to_rev, f.source))
    for block in manifest.blocks:
        new_block = upstream_block(block, to_rev, fetch)
        if block.fragment is not None:
            current(block.fragment)
            changes[block.fragment] = (changes[block.fragment][0], new_block)
        else:
            assert block.target is not None
            text = current(block.target)
            spliced = replace_fenced(text, block.name, new_block, block.target)
            changes[block.target] = (changes[block.target][0], spliced)
    return [(rel, old, new) for rel, (old, new) in changes.items() if old != new]


def _tracked_sources(manifest: Manifest) -> list[str]:
    paths = {f.source for f in manifest.files}
    for block in manifest.blocks:
        paths.update(block.sources)
    return sorted(paths)


def commits_since_pin(manifest: Manifest, to_ref: str) -> list[tuple[str, str]]:
    """``(sha, subject)`` for each commit between the pin and ``to_ref`` that
    touches a vendored path, oldest first."""
    url = (
        f"https://api.github.com/repos/{manifest.repo}/compare/"
        f"{manifest.rev}...{to_ref}"
    )
    data = json.loads(_github_request(url))
    tracked = set(_tracked_sources(manifest))
    if not tracked & {f["filename"] for f in data.get("files", [])}:
        return []
    found = []
    for commit in data.get("commits", []):
        detail = json.loads(
            _github_request(
                f"https://api.github.com/repos/{manifest.repo}/commits/{commit['sha']}"
            )
        )
        if tracked & {f["filename"] for f in detail.get("files", [])}:
            subject = commit["commit"]["message"].splitlines()[0]
            found.append((commit["sha"], subject))
    return found


def _resolve(repo: str, ref: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref
    url = f"https://api.github.com/repos/{repo}/commits/{ref}"
    return json.loads(_github_request(url))["sha"]


def set_pin(manifest_text: str, rev: str) -> str:
    new, count = re.subn(
        r'(?m)^(rev\s*=\s*)"[0-9a-f]{40}"',
        lambda m: f'{m.group(1)}"{rev}"',
        manifest_text,
    )
    if count != 1:
        raise SyncError('P4A_VENDOR.toml: expected exactly one rev = "<sha>" line')
    return new


def _write_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def update(manifest: Manifest, rev: str, fetch: Fetch) -> list[tuple[str, str, str]]:
    changes = planned_changes(manifest, rev, fetch)
    for rel, _old, new in changes:
        _write_lf(_local(rel), new)
    _write_lf(MANIFEST, set_pin(_lf(MANIFEST.read_text(encoding="utf-8")), rev))
    return changes


def main(argv: list[str] | None = None, fetch: Fetch | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="require the vendored code to match the pin")
    drift_p = sub.add_parser("drift", help="what changed upstream since the pin")
    drift_p.add_argument("--to", default="develop", help="p4a ref (default develop)")
    update_p = sub.add_parser("update", help="move the pin and rewrite vendored code")
    update_p.add_argument("--rev", required=True, help="p4a commit or ref")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest()
        fetch = fetch or github_fetch(manifest.repo)
        if args.command == "check":
            problems = check(manifest, fetch)
            if problems:
                print("p4a vendor check FAILED:", file=sys.stderr)
                for problem in problems:
                    print(f"  - {problem}", file=sys.stderr)
                print(
                    "\n  Vendored p4a code must match the revision pinned in "
                    "P4A_VENDOR.toml. Change it with 'sync_p4a.py update', and "
                    "put kivyforge's own changes outside the vendored files and "
                    "the BEGIN/END p4a fences.",
                    file=sys.stderr,
                )
                return 1
            count = len(manifest.files) + len(manifest.blocks)
            print(f"  {count} vendored items match p4a {manifest.rev[:12]}")
            return 0
        if args.command == "drift":
            to_rev = _resolve(manifest.repo, args.to)
            commits = commits_since_pin(manifest, to_rev)
            print(f"p4a {manifest.rev[:12]}..{args.to} ({to_rev[:12]})")
            if not commits:
                print("  no commits touch a vendored path")
            for sha, subject in commits:
                print(f"  {sha[:12]} {subject}")
            for rel, old, new in planned_changes(manifest, to_rev, fetch):
                print(_diff(old, new, rel), end="")
            return 0
        rev = _resolve(manifest.repo, args.rev)
        changes = update(manifest, rev, fetch)
        for rel, old, new in changes:
            print(_diff(old, new, rel), end="")
        print(
            f"pinned p4a {rev[:12]}; {len(changes)} vendored path(s) changed",
            file=sys.stderr,
        )
        return 0
    except SyncError as exc:
        print(f"sync_p4a: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

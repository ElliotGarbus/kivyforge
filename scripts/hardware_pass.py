"""The hardware pass: what to run on real hardware, and a dated record of it.

Roadmap item 5's last piece: "a short script that prints the exact commands
for a manual pass and records the results into the matrix doc's log, so a
hardware session produces a dated artifact instead of a memory."

The checklist lives in ``docs/design/dev/hardware-checklist.toml`` (one entry
per check, with its commands and pass criteria); results go into
``docs/design/dev/test-matrix.md`` section 7 as ordinary dated rows.

    python scripts/hardware_pass.py list
    python scripts/hardware_pass.py show android-device
    python scripts/hardware_pass.py record android-device --result pass \\
        --device "Pixel 8a, Android 17" --note "smoke + launch fine"

Nothing here prompts: every input is an argument, so an agent can run a pass
as well as a person (AGENTS.md, "Nothing may wait for input").
"""

from __future__ import annotations

import argparse
import datetime
import platform
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECKLIST = REPO / "docs" / "design" / "dev" / "hardware-checklist.toml"
MATRIX = REPO / "docs" / "design" / "dev" / "test-matrix.md"

STATUSES = ("runnable", "needs-credentials", "blocked", "no-hardware")
HOSTS = ("windows", "macos", "linux")
RESULTS = ("pass", "fail", "blocked")

#: The heading that follows the section 7 table; rows are appended above it.
LOG_END = "\n### Known-unverified, stated plainly"

_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RECORDED = re.compile(
    r"^\| (\d{4}-\d{2}-\d{2}) \|.*\*\*(PASS|FAIL|BLOCKED)\*\*.*"
    r"Checklist item `([a-z0-9-]+)`",
    re.M,
)


class ChecklistError(Exception):
    """The checklist or the matrix doc is not in the shape this tool needs."""


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    status: str
    hosts: tuple[str, ...]
    target: str
    tier: str
    needs: tuple[str, ...]
    commands: tuple[str, ...]
    passes: tuple[str, ...]
    record: tuple[str, ...] = ()
    previous: str = ""
    blocked_on: str = ""


# --- loading ----------------------------------------------------------------


def load_checklist(path: Path = CHECKLIST) -> list[Item]:
    """Parse and validate the checklist; raise ``ChecklistError`` on any fault.

    Validated up front and completely, because a hardware session is the worst
    time to find a typo: the phone is plugged in and the person is waiting.
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ChecklistError(f"cannot read {path}: {exc}") from exc
    if data.get("schema_version") != 1:
        raise ChecklistError(f"{path}: schema_version must be 1")
    raw_items = data.get("item")
    if not isinstance(raw_items, list) or not raw_items:
        raise ChecklistError(f"{path}: no [[item]] entries")

    items: list[Item] = []
    seen: set[str] = set()
    for n, raw in enumerate(raw_items, 1):
        where = f"{path.name} item {n}"
        item = _parse_item(raw, where)
        if item.id in seen:
            raise ChecklistError(f"{where}: duplicate id {item.id!r}")
        seen.add(item.id)
        items.append(item)
    return items


def _parse_item(raw: dict, where: str) -> Item:
    def text(key: str, *, required: bool = True) -> str:
        value = raw.get(key, "")
        if not isinstance(value, str) or (required and not value.strip()):
            raise ChecklistError(f"{where}: {key!r} must be a non-empty string")
        return value

    def lines(key: str, *, required: bool = True) -> tuple[str, ...]:
        value = raw.get(key, [])
        if not isinstance(value, list) or not all(
            isinstance(v, str) and v.strip() for v in value
        ):
            raise ChecklistError(f"{where}: {key!r} must be a list of strings")
        if required and not value:
            raise ChecklistError(f"{where}: {key!r} must not be empty")
        return tuple(value)

    known = {
        "id", "title", "status", "hosts", "target", "tier", "needs",
        "commands", "pass", "record", "previous", "blocked_on",
    }  # fmt: skip
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ChecklistError(f"{where}: unknown field(s) {unknown}")

    item_id = text("id")
    if not _ID.match(item_id):
        raise ChecklistError(f"{where}: id {item_id!r} must be lowercase-hyphenated")
    where = f"{where} ({item_id})"
    status = text("status")
    if status not in STATUSES:
        raise ChecklistError(f"{where}: status {status!r} is not one of {STATUSES}")
    hosts = lines("hosts")
    bad_hosts = [h for h in hosts if h not in HOSTS]
    if bad_hosts:
        raise ChecklistError(f"{where}: unknown host(s) {bad_hosts}; use {HOSTS}")
    blocked_on = text("blocked_on", required=False)
    if status == "blocked" and not blocked_on.strip():
        raise ChecklistError(f"{where}: a blocked item must say what it is blocked on")

    return Item(
        id=item_id,
        title=text("title"),
        status=status,
        hosts=hosts,
        target=text("target"),
        tier=text("tier"),
        needs=lines("needs"),
        commands=lines("commands"),
        passes=lines("pass"),
        record=lines("record", required=False),
        previous=text("previous", required=False),
        blocked_on=blocked_on,
    )


def find(items: list[Item], item_id: str) -> Item:
    for item in items:
        if item.id == item_id:
            return item
    raise ChecklistError(
        f"no checklist item {item_id!r}; known: {', '.join(i.id for i in items)}"
    )


# --- the host ---------------------------------------------------------------


def current_host() -> str | None:
    return {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(
        platform.system()
    )


def describe_host() -> str:
    """The section 7 "Host" column. Says WSL2 vs bare metal, as section 4 asks."""
    system = platform.system()
    if system == "Darwin":
        return f"macOS {platform.mac_ver()[0] or platform.release()} ({platform.machine()})"
    if system == "Windows":
        return (
            f"Windows {platform.release()} ({platform.version()}, {platform.machine()})"
        )
    if system == "Linux":
        pretty = _os_release_name() or "Linux"
        kind = "WSL2" if "microsoft" in platform.release().lower() else "bare metal"
        return f"{pretty}, kernel {platform.release()} ({kind}, {platform.machine()})"
    return f"{system} {platform.release()}"


def _os_release_name() -> str:
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def repo_commit(repo: Path = REPO) -> str:
    """Short HEAD, marked when the tree has uncommitted changes."""

    def git(*args: str) -> str | None:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=repo,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return proc.stdout.strip() if proc.returncode == 0 else None

    head = git("rev-parse", "--short", "HEAD")
    if not head:
        return "unknown"
    dirty = git("status", "--porcelain", "--untracked-files=no")
    return f"{head} + uncommitted changes" if dirty else head


# --- the log ----------------------------------------------------------------


def last_results(matrix_text: str) -> dict[str, tuple[str, str]]:
    """``{item id: (date, RESULT)}`` from rows this tool wrote, latest last."""
    found: dict[str, tuple[str, str]] = {}
    for match in _RECORDED.finditer(matrix_text):
        date, result, item_id = match.groups()
        found[item_id] = (date, result)
    return found


def _cell(value: str) -> str:
    """Free text made safe for one markdown table cell."""
    return " ".join(value.replace("|", "\\|").split())


def format_row(
    item: Item,
    *,
    date: str,
    host: str,
    result: str,
    device: str,
    note: str,
    commit: str,
) -> str:
    note_text = f" {_cell(note)}" if note.strip() else ""
    if note_text and not note_text.rstrip().endswith((".", "!", "?")):
        note_text += "."
    return (
        f"| {date} | {item.target} | {item.tier}, hardware pass | {_cell(host)} | "
        f"**{result.upper()}** on {_cell(device)}.{note_text} "
        f"Checklist item `{item.id}`; kivyforge `{commit}`. |"
    )


def append_row(matrix_path: Path, row: str) -> None:
    """Add *row* as the last row of the section 7 results table."""
    text = matrix_path.read_text(encoding="utf-8")
    if text.count(LOG_END) != 1:
        raise ChecklistError(
            f"{matrix_path}: expected exactly one {LOG_END.strip()!r} heading "
            "after the section 7 table; cannot tell where the log ends"
        )
    cut = text.index(LOG_END)
    before = text[:cut].rstrip("\n")
    if not before.splitlines()[-1].startswith("| "):
        raise ChecklistError(
            f"{matrix_path}: the line before {LOG_END.strip()!r} is not a table "
            "row, so section 7's table is not where this tool expects it"
        )
    matrix_path.write_text(
        before + "\n" + row + "\n" + text[cut:], encoding="utf-8", newline=""
    )


# --- commands ---------------------------------------------------------------


def cmd_list(items: list[Item], matrix_text: str, host: str | None) -> str:
    recorded = last_results(matrix_text)
    groups: dict[str, list[Item]] = {
        "Runnable on this host": [],
        "Runnable on another host": [],
        "Needs credentials the owner does not hold": [],
        "Blocked": [],
        "No hardware available": [],
    }
    for item in items:
        if item.status == "runnable":
            key = (
                "Runnable on this host"
                if host in item.hosts
                else "Runnable on another host"
            )
        else:
            key = {
                "needs-credentials": "Needs credentials the owner does not hold",
                "blocked": "Blocked",
                "no-hardware": "No hardware available",
            }[item.status]
        groups[key].append(item)

    out = [
        f"Hardware pass checklist ({len(items)} items); this host: {host or 'unknown'}"
    ]
    for heading, members in groups.items():
        if not members:
            continue
        out.append("")
        out.append(f"{heading}:")
        for item in members:
            last = recorded.get(item.id)
            when = f"last {last[1]} {last[0]}" if last else "not recorded yet"
            out.append(f"  {item.id:<22} [{', '.join(item.hosts)}] {when}")
            out.append(f"      {item.title}")
    out.append("")
    out.append("Show one with: python scripts/hardware_pass.py show <id>")
    return "\n".join(out)


def cmd_show(item: Item) -> str:
    out = [f"{item.id}: {item.title}", f"Status: {item.status}"]
    if item.blocked_on:
        out.append(f"Blocked on: {item.blocked_on}")
    out.append(f"Hosts: {', '.join(item.hosts)}")
    out.append("")
    out.append("Needs:")
    out += [f"  - {line}" for line in item.needs]
    out.append("")
    out.append("Run (from the repo root):")
    out += [f"  {n}. {line}" for n, line in enumerate(item.commands, 1)]
    out.append("")
    out.append("Passes only if all of these hold:")
    out += [f"  - {line}" for line in item.passes]
    if item.record:
        out.append("")
        out.append("Also note (recorded, not required):")
        out += [f"  - {line}" for line in item.record]
    if item.previous:
        out.append("")
        out.append(f"Previous results: {item.previous}")
    out.append("")
    out.append("Record the result:")
    out.append(
        f"  python scripts/hardware_pass.py record {item.id} --result pass|fail|blocked "
        '--device "<device, OS version>" --note "<what you saw>"'
    )
    return "\n".join(out)


def cmd_record(
    item: Item,
    *,
    result: str,
    device: str,
    note: str,
    date: str,
    host: str,
    commit: str,
    matrix: Path,
    dry_run: bool,
) -> str:
    if result not in RESULTS:
        raise ChecklistError(f"result {result!r} is not one of {RESULTS}")
    if not device.strip():
        raise ChecklistError("--device must name the hardware the check ran on")
    if not _DATE.match(date):
        raise ChecklistError(f"--date {date!r} is not YYYY-MM-DD")
    row = format_row(
        item,
        date=date,
        host=host,
        result=result,
        device=device,
        note=note,
        commit=commit,
    )
    if not dry_run:
        append_row(matrix, row)
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hardware_pass.py",
        description="Run and record the hardware checks CI cannot (test-matrix.md section 6).",
    )
    parser.add_argument(
        "--checklist", type=Path, default=CHECKLIST, help=argparse.SUPPRESS
    )
    parser.add_argument("--matrix", type=Path, default=MATRIX, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="every item, grouped by whether it can run here")
    show = sub.add_parser("show", help="the commands and pass criteria for one item")
    show.add_argument("id")
    rec = sub.add_parser("record", help="append a dated result row to section 7")
    rec.add_argument("id")
    rec.add_argument("--result", required=True, choices=RESULTS)
    rec.add_argument("--device", required=True, help='e.g. "Pixel 8a, Android 17"')
    rec.add_argument("--note", default="", help="what you saw, in a sentence or two")
    rec.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    rec.add_argument(
        "--dry-run", action="store_true", help="print the row without writing it"
    )
    args = parser.parse_args(argv)

    try:
        items = load_checklist(args.checklist)
        if args.command == "list":
            text = (
                args.matrix.read_text(encoding="utf-8") if args.matrix.is_file() else ""
            )
            print(cmd_list(items, text, current_host()))
        elif args.command == "show":
            print(cmd_show(find(items, args.id)))
        else:
            row = cmd_record(
                find(items, args.id),
                result=args.result,
                device=args.device,
                note=args.note,
                date=args.date or datetime.date.today().isoformat(),
                host=describe_host(),
                commit=repo_commit(),
                matrix=args.matrix,
                dry_run=args.dry_run,
            )
            print(row)
            if not args.dry_run:
                print(
                    f"\nAppended to {args.matrix}. Commit it with the pass.",
                    file=sys.stderr,
                )
    except ChecklistError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

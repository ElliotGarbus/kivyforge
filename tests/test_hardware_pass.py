"""scripts/hardware_pass.py: the runnable hardware checklist (roadmap item 5).

Hermetic: the checklist and matrix are real files read from the repo or small
copies in tmp_path; nothing touches hardware.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "hardware_pass", REPO / "scripts" / "hardware_pass.py"
)
assert _spec and _spec.loader
hp = importlib.util.module_from_spec(_spec)
sys.modules["hardware_pass"] = hp
_spec.loader.exec_module(hp)

MINIMAL_ITEM = """
[[item]]
id = "demo-check"
title = "A demo check"
status = "runnable"
hosts = ["windows", "linux"]
target = "Demo `x86_64`"
tier = "T5"
needs = ["a thing"]
commands = ["do it"]
pass = ["it worked"]
"""

MATRIX = """\
## 7. Results log

| Date | Target | Tier | Host | Result |
|---|---|---|---|---|
| 2026-09-01 | Something | T1 | Somewhere | An older row. |

### Known-unverified, stated plainly

- nothing
"""


def _checklist(
    tmp_path: Path, body: str = MINIMAL_ITEM, header: str = "schema_version = 1\n"
) -> Path:
    path = tmp_path / "checklist.toml"
    path.write_text(header + body, encoding="utf-8")
    return path


def _item(**overrides):
    base = dict(
        id="demo-check",
        title="A demo check",
        status="runnable",
        hosts=("windows",),
        target="Demo `x86_64`",
        tier="T5",
        needs=("a thing",),
        commands=("do it",),
        passes=("it worked",),
    )
    base.update(overrides)
    return hp.Item(**base)


# --- the real checklist -------------------------------------------------------


class TestRealChecklist:
    def test_it_loads_and_validates(self):
        items = hp.load_checklist()
        assert len(items) >= 10
        assert {i.status for i in items} <= set(hp.STATUSES)

    def test_section_6_lists_exactly_the_checklist_items(self):
        # The drift test: test-matrix.md section 6 is the human-readable list,
        # the TOML the runnable one. They must name the same items.
        text = hp.MATRIX.read_text(encoding="utf-8")
        section6 = text[
            text.index("## 6. Manual checklist") : text.index("## 7. Results log")
        ]
        listed = set(re.findall(r"^\| `([a-z0-9-]+)` \|", section6, re.M))
        assert listed == {i.id for i in hp.load_checklist()}

    def test_the_real_matrix_accepts_a_row(self, tmp_path):
        # Guards against section 7 being reshaped so that `record` no longer
        # finds where the table ends.
        copy = tmp_path / "test-matrix.md"
        shutil.copyfile(hp.MATRIX, copy)
        item = hp.find(hp.load_checklist(), "android-device")
        row = hp.format_row(
            item,
            date="2026-09-28",
            host="h",
            result="pass",
            device="d",
            note="",
            commit="c",
        )
        hp.append_row(copy, row)
        text = copy.read_text(encoding="utf-8")
        lines = text.splitlines()
        k = lines.index(row)
        assert lines[k - 1].startswith("| 2026-"), "the row must extend the table"
        assert lines[k + 2] == hp.LOG_END.strip()
        assert hp.last_results(text)["android-device"] == ("2026-09-28", "PASS")


# --- validation -------------------------------------------------------------


class TestValidation:
    def test_a_minimal_item_loads(self, tmp_path):
        [item] = hp.load_checklist(_checklist(tmp_path))
        assert item.id == "demo-check" and item.hosts == ("windows", "linux")

    @pytest.mark.parametrize(
        ("edit", "message"),
        [
            (
                lambda b: b.replace('status = "runnable"', 'status = "maybe"'),
                "status 'maybe'",
            ),
            (
                lambda b: b.replace('"windows", "linux"', '"windows", "bsd"'),
                "unknown host(s) ['bsd']",
            ),
            (
                lambda b: b.replace('id = "demo-check"', 'id = "Demo Check"'),
                "lowercase-hyphenated",
            ),
            (
                lambda b: b.replace('pass = ["it worked"]', "pass = []"),
                "'pass' must not be empty",
            ),
            (
                lambda b: b.replace('needs = ["a thing"]', 'needs = "a thing"'),
                "'needs' must be a list",
            ),
            (
                lambda b: b.replace('title = "A demo check"\n', ""),
                "'title' must be a non-empty string",
            ),
            (lambda b: b + 'colour = "blue"\n', "unknown field(s) ['colour']"),
            (
                lambda b: b.replace('status = "runnable"', 'status = "blocked"'),
                "must say what it is blocked on",
            ),
        ],
    )
    def test_each_rule_fires(self, tmp_path, edit, message):
        with pytest.raises(hp.ChecklistError, match=re.escape(message)):
            hp.load_checklist(_checklist(tmp_path, edit(MINIMAL_ITEM)))

    def test_a_duplicate_id_is_refused(self, tmp_path):
        with pytest.raises(hp.ChecklistError, match="duplicate id 'demo-check'"):
            hp.load_checklist(_checklist(tmp_path, MINIMAL_ITEM + MINIMAL_ITEM))

    def test_the_schema_version_is_checked(self, tmp_path):
        with pytest.raises(hp.ChecklistError, match="schema_version must be 1"):
            hp.load_checklist(_checklist(tmp_path, header="schema_version = 2\n"))

    def test_no_items_is_refused(self, tmp_path):
        with pytest.raises(hp.ChecklistError, match="no \\[\\[item\\]\\] entries"):
            hp.load_checklist(_checklist(tmp_path, body=""))

    def test_an_unknown_id_names_the_known_ones(self, tmp_path):
        items = hp.load_checklist(_checklist(tmp_path))
        with pytest.raises(hp.ChecklistError, match="known: demo-check"):
            hp.find(items, "nope")


# --- rows ---------------------------------------------------------------------


class TestRows:
    def test_the_row_format(self):
        row = hp.format_row(
            _item(),
            date="2026-09-28",
            host="Windows 11",
            result="pass",
            device="Pixel 8a, Android 17",
            note="all fine",
            commit="abc1234",
        )
        assert row == (
            "| 2026-09-28 | Demo `x86_64` | T5, hardware pass | Windows 11 | "
            "**PASS** on Pixel 8a, Android 17. all fine. "
            "Checklist item `demo-check`; kivyforge `abc1234`. |"
        )

    def test_free_text_cannot_break_the_table(self):
        row = hp.format_row(
            _item(), date="2026-09-28", host="h", result="fail",
            device="a | b", note="line one\nline | two", commit="c",
        )  # fmt: skip
        assert "\n" not in row
        assert "a \\| b" in row and "line one line \\| two." in row

    def test_an_empty_note_adds_nothing(self):
        row = hp.format_row(
            _item(),
            date="2026-09-28",
            host="h",
            result="blocked",
            device="d",
            note="  ",
            commit="c",
        )
        assert "**BLOCKED** on d. Checklist item" in row

    def test_last_results_keeps_the_latest(self):
        rows = [
            hp.format_row(
                _item(), date=d, host="h", result=r, device="d", note="", commit="c"
            )
            for d, r in (("2026-09-01", "fail"), ("2026-09-02", "pass"))
        ]
        assert hp.last_results("\n".join(rows)) == {
            "demo-check": ("2026-09-02", "PASS")
        }

    def test_append_puts_the_row_last_in_the_table(self, tmp_path):
        matrix = tmp_path / "m.md"
        matrix.write_text(MATRIX, encoding="utf-8")
        hp.append_row(matrix, "| new | row |")
        lines = matrix.read_text(encoding="utf-8").splitlines()
        i = lines.index("| new | row |")
        assert lines[i - 1].startswith("| 2026-09-01 |")
        assert (
            lines[i + 1] == ""
            and lines[i + 2] == "### Known-unverified, stated plainly"
        )

    def test_append_refuses_without_the_heading(self, tmp_path):
        matrix = tmp_path / "m.md"
        matrix.write_text("| a | b |\n", encoding="utf-8")
        with pytest.raises(hp.ChecklistError, match="cannot tell where the log ends"):
            hp.append_row(matrix, "| x |")

    def test_append_refuses_when_the_table_is_not_there(self, tmp_path):
        matrix = tmp_path / "m.md"
        matrix.write_text(
            "prose\n\n### Known-unverified, stated plainly\n", encoding="utf-8"
        )
        with pytest.raises(hp.ChecklistError, match="is not a table row"):
            hp.append_row(matrix, "| x |")


# --- record -------------------------------------------------------------------


class TestRecord:
    def _record(self, tmp_path, **kw):
        matrix = tmp_path / "m.md"
        matrix.write_text(MATRIX, encoding="utf-8")
        args = dict(
            result="pass", device="d", note="", date="2026-09-28", host="h",
            commit="c", matrix=matrix, dry_run=False,
        )  # fmt: skip
        args.update(kw)
        return hp.cmd_record(_item(), **args), matrix

    def test_record_writes_the_row(self, tmp_path):
        row, matrix = self._record(tmp_path)
        assert row in matrix.read_text(encoding="utf-8")

    def test_dry_run_writes_nothing(self, tmp_path):
        row, matrix = self._record(tmp_path, dry_run=True)
        assert matrix.read_text(encoding="utf-8") == MATRIX
        assert row.startswith("| 2026-09-28 |")

    @pytest.mark.parametrize(
        ("kw", "message"),
        [
            ({"result": "meh"}, "result 'meh'"),
            ({"device": "  "}, "--device must name the hardware"),
            ({"date": "28/09/2026"}, "is not YYYY-MM-DD"),
        ],
    )
    def test_bad_input_is_refused(self, tmp_path, kw, message):
        with pytest.raises(hp.ChecklistError, match=re.escape(message)):
            self._record(tmp_path, **kw)


# --- the command line ---------------------------------------------------------


class TestMain:
    def test_list_show_and_record(self, tmp_path, capsys, monkeypatch):
        checklist = _checklist(tmp_path)
        matrix = tmp_path / "m.md"
        matrix.write_text(MATRIX, encoding="utf-8")
        common = ["--checklist", str(checklist), "--matrix", str(matrix)]
        monkeypatch.setattr(hp, "current_host", lambda: "windows")
        monkeypatch.setattr(hp, "describe_host", lambda: "Test host")
        monkeypatch.setattr(hp, "repo_commit", lambda: "deadbee")

        assert hp.main([*common, "list"]) == 0
        out = capsys.readouterr().out
        assert "Runnable on this host:" in out and "demo-check" in out
        assert "not recorded yet" in out

        assert hp.main([*common, "show", "demo-check"]) == 0
        out = capsys.readouterr().out
        assert "1. do it" in out and "- it worked" in out

        argv = [
            *common,
            "record",
            "demo-check",
            "--result",
            "pass",
            "--device",
            "Phone",
            "--date",
            "2026-09-28",
        ]
        assert hp.main(argv) == 0
        assert capsys.readouterr().out.startswith(
            "| 2026-09-28 | Demo `x86_64` | T5, hardware pass | Test host |"
        )

        assert hp.main([*common, "list"]) == 0
        assert "last PASS 2026-09-28" in capsys.readouterr().out

    def test_an_unknown_item_exits_1(self, tmp_path, capsys):
        checklist = _checklist(tmp_path)
        assert hp.main(["--checklist", str(checklist), "show", "nope"]) == 1
        assert "no checklist item 'nope'" in capsys.readouterr().err


# --- the host -----------------------------------------------------------------


class TestHost:
    def test_wsl2_is_named(self, monkeypatch):
        monkeypatch.setattr(hp.platform, "system", lambda: "Linux")
        monkeypatch.setattr(
            hp.platform, "release", lambda: "6.6.87.2-microsoft-standard-WSL2"
        )
        monkeypatch.setattr(hp.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(hp, "_os_release_name", lambda: "Ubuntu 26.04 LTS")
        assert hp.describe_host() == (
            "Ubuntu 26.04 LTS, kernel 6.6.87.2-microsoft-standard-WSL2 (WSL2, x86_64)"
        )

    def test_bare_metal_linux_is_named(self, monkeypatch):
        monkeypatch.setattr(hp.platform, "system", lambda: "Linux")
        monkeypatch.setattr(hp.platform, "release", lambda: "6.8.0-40-generic")
        monkeypatch.setattr(hp.platform, "machine", lambda: "aarch64")
        monkeypatch.setattr(hp, "_os_release_name", lambda: "Debian GNU/Linux 13")
        assert "(bare metal, aarch64)" in hp.describe_host()

    def test_this_host_is_described(self):
        assert hp.describe_host()
        assert hp.current_host() in (*hp.HOSTS, None)

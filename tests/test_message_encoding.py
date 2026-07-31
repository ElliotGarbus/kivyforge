"""User-facing strings must survive a legacy Windows console encoding.

Python writes to a *real* Windows console through the console API, so rich
typography renders there regardless. The failure mode is a **redirected**
stream — ``kivyforge build > build.log``, a CI step capturing output, a
subprocess pipe — where Python falls back to the locale encoding (cp1252 on
most Windows installs) and any character outside it raises
``UnicodeEncodeError`` *from inside the print*, turning a cosmetic issue into
a crashed build.

cp1252 is the bar rather than plain ASCII deliberately. kivyforge's messages
use em dashes and section signs heavily (300+ occurrences); those encode fine
in cp1252, so demanding ASCII would be churn with no failure to prevent. What
must not appear are characters cp1252 has no room for — arrows, box drawing,
the maths comparisons — which is exactly the set this pins.

Docstrings and comments are out of scope: they are never written to a stream.
The one exception is a Click command's docstring, which becomes its ``--help``
text, so those are checked too.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "kivyforge"
_ENCODING = "cp1252"


def _unencodable(text: str) -> set[str]:
    bad = set()
    for ch in text:
        try:
            ch.encode(_ENCODING)
        except UnicodeEncodeError:
            bad.add(ch)
    return bad


def _strings_under(node: ast.AST) -> list[str]:
    """Every string constant beneath *node*, f-string literal parts included."""
    return [
        n.value
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def _decorator_names(fn: ast.FunctionDef) -> set[str]:
    names = set()
    for dec in fn.decorator_list:
        for n in ast.walk(dec):
            name = getattr(n, "attr", None) or getattr(n, "id", None)
            if name:
                names.add(name)
    return names


def _offenders() -> list[str]:
    out: list[str] = []
    for path in sorted(_ROOT.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - vendored/templated sources
            continue
        for node in ast.walk(tree):
            texts: list[str] = []
            if isinstance(node, ast.Raise):
                texts = _strings_under(node)
            elif isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(
                    node.func, "id", None
                )
                if name in ("echo", "secho"):
                    texts = _strings_under(node)
                else:
                    for kw in node.keywords:
                        if kw.arg in ("help", "short_help"):
                            texts += _strings_under(kw.value)
            elif isinstance(node, ast.FunctionDef):
                # A Click command's docstring is its --help text.
                if {"command", "group"} & _decorator_names(node):
                    texts = [ast.get_docstring(node) or ""]
            for text in texts:
                bad = _unencodable(text)
                if bad:
                    rel = path.relative_to(_ROOT.parent)
                    out.append(
                        f"{rel}:{node.lineno} {''.join(sorted(bad))!r} in "
                        f"{text.strip()[:60]!r}"
                    )
    return out


def test_user_facing_strings_survive_a_redirected_windows_stream():
    offenders = _offenders()
    assert not offenders, (
        "These strings can reach a stream and cannot encode as "
        f"{_ENCODING}, so printing them raises UnicodeEncodeError when output "
        "is redirected on Windows:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("sample", ["a → b", "├── tree", "glibc ≥ 2.17"])
def test_the_guard_detects_what_it_claims_to(sample):
    """The check is only worth having if it actually catches these."""
    assert _unencodable(sample)


def test_house_typography_is_not_flagged():
    """Em dash / section sign / ellipsis are fine and must stay allowed."""
    assert not _unencodable("built — see §3 for details …")

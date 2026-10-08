"""Every HTTP request kivyforge makes carries its own User-Agent (#97).

Cloudflare R2's public bucket URLs answer Python's default
``Python-urllib/3.x`` with 403, so a wheel pip resolved from an R2-hosted index
failed to download at build time.
"""

from __future__ import annotations

import ast
import io
from pathlib import Path

import kivyforge
from kivyforge import __version__
from kivyforge.artifacts import download as download_mod
from kivyforge.artifacts.download import UrllibDownloader
from kivyforge.lock.wheelruntime import pbs_github
from kivyforge.net import USER_AGENT, request

PACKAGE = Path(kivyforge.__file__).parent


def test_the_agent_names_kivyforge_and_its_version():
    assert USER_AGENT == f"kivyforge/{__version__}"


def test_request_sets_the_agent_and_keeps_other_headers():
    req = request("https://h/x", {"Accept": "a/b"})
    assert req.get_header("User-agent") == USER_AGENT
    assert req.get_header("Accept") == "a/b"


def test_the_downloader_sends_it(tmp_path, monkeypatch):
    sent = []

    def fake_urlopen(req):
        sent.append(req)
        resp = io.BytesIO(b"abc")
        resp.headers = {}  # type: ignore[attr-defined]
        return resp

    monkeypatch.setattr(download_mod.urllib.request, "urlopen", fake_urlopen)
    UrllibDownloader().fetch_to("https://h/x.whl", tmp_path / "x.whl")
    (req,) = sent
    assert req.full_url == "https://h/x.whl"
    assert req.get_header("User-agent") == USER_AGENT


def test_the_github_api_headers_carry_it(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert pbs_github._request_headers()["User-Agent"] == USER_AGENT


def test_no_urlopen_is_handed_a_bare_url():
    """A new call site passing a string would silently send urllib's agent."""
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "urlopen"
            ):
                continue
            arg = node.args[0] if node.args else None
            built_here = (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Name)
                and arg.func.id == "request"
            )
            if not built_here and path.name != "pbs_github.py":
                offenders.append(f"{path.relative_to(PACKAGE)}:{node.lineno}")
    assert offenders == []

"""The shared artifact downloader shows progress (#84 follow-up).

`build` downloads the Python runtime and every wheel through this downloader
whenever the artifact cache is cold. It used to report nothing, so a first
build, or one after `clean --cache`, was silent for the whole download.
"""

from __future__ import annotations

import io

import pytest
from click.testing import CliRunner

from kivyforge.artifacts import download as download_mod
from kivyforge.artifacts.download import UrllibDownloader, download_label
from kivyforge.cli import run as run_mod
from kivyforge.cli._output import reporting
from kivyforge.report.transfers import report_transfer, transfers_to


class _Response(io.BytesIO):
    def __init__(self, body: bytes, length: str | None):
        super().__init__(body)
        self.headers = {} if length is None else {"Content-Length": length}


@pytest.fixture
def served(monkeypatch):
    def serve(body: bytes, *, length: str | None):
        monkeypatch.setattr(
            download_mod.urllib.request, "urlopen", lambda url: _Response(body, length)
        )

    return serve


class TestDownloadLabel:
    def test_a_wheel_keeps_its_name_version_and_platform(self):
        assert (
            download_label("Kivy-2.3.1-cp314-cp314-android_24_x86_64.whl")
            == "Kivy-2.3.1 (android_24_x86_64)"
        )

    def test_other_files_keep_their_name(self):
        name = "python-3.14.6-aarch64-linux-android.tar.gz"
        assert download_label(name) == name


class TestUrllibDownloader:
    def test_reports_bytes_against_content_length(self, tmp_path, served):
        body = b"x" * (200 * 1024)  # several 64 KiB reads
        served(body, length=str(len(body)))
        seen = []
        with transfers_to(lambda *a: seen.append(a)):
            UrllibDownloader().fetch_to(
                "https://h/p/runtime.tar.gz", tmp_path / "r.tar.gz"
            )
        assert (tmp_path / "r.tar.gz").read_bytes() == body
        assert seen[0] == ("[download] r.tar.gz", 0, len(body), "bytes")
        assert seen[-1] == ("[download] r.tar.gz", len(body), len(body), "bytes")
        assert len(seen) >= 4

    def test_no_content_length_still_downloads(self, tmp_path, served):
        served(b"abc", length=None)
        seen = []
        with transfers_to(lambda *a: seen.append(a)):
            UrllibDownloader().fetch_to("https://h/x", tmp_path / "x")
        assert (tmp_path / "x").read_bytes() == b"abc"
        assert {total for _l, _d, total, _u in seen} == {0}  # the renderer ignores 0

    def test_without_a_sink_nothing_is_reported(self, tmp_path, served):
        served(b"abc", length="3")
        UrllibDownloader().fetch_to("https://h/x", tmp_path / "x")  # must not raise


class TestSink:
    def test_the_sink_is_scoped(self):
        seen = []
        with transfers_to(lambda *a: seen.append(a)):
            report_transfer("a", 1, 2)
        report_transfer("b", 1, 2)
        assert seen == [("a", 1, 2, "bytes")]

    def test_reporting_routes_downloads_to_stderr(self, capsys):
        with reporting("build", json_out=False, no_color=True):
            report_transfer("[download] Kivy-2.3.1 (android_24_x86_64)", 9, 9)
        captured = capsys.readouterr()
        assert "[download] Kivy-2.3.1 (android_24_x86_64)  100% of 1 kB" in captured.err
        assert captured.out == ""

    def test_run_routes_downloads_too(self, monkeypatch):
        """run has no reporting() context, but its implicit build downloads."""
        monkeypatch.setattr(
            run_mod,
            "_run",
            lambda **kw: report_transfer("[download] wheel", 5, 5),
        )
        result = CliRunner().invoke(run_mod.run, [])
        assert result.exit_code == 0, result.output
        assert "[download] wheel  100%" in result.stderr
        assert "[download]" not in result.stdout

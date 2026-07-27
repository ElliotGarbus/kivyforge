"""Tests for kivyforge/lock/wheelruntime/resolver.py.

Covers ``Variant``, ``PipWheelResolver`` (with ``_run_report`` monkeypatched),
``_absorb`` edge cases, ``_run_report`` (with subprocess monkeypatched), the
pip-version guard, and ``get_wheel_resolver``. No network or real pip
invocation is needed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kivyforge.lock.wheelruntime.resolver import (
    MIN_PIP_VERSION,
    PipWheelResolver,
    Variant,
    WheelResolverError,
    _indent,
    get_wheel_resolver,
    version_str,
)


@pytest.fixture(autouse=True)
def _modern_host_pip(monkeypatch):
    monkeypatch.setattr(
        "kivyforge.lock.wheelruntime.resolver.pip_version", lambda _exe: (99, 0)
    )


# ---------------------------------------------------------------------------
# Variant
# ---------------------------------------------------------------------------


class TestVariant:
    def test_request_tags_no_extras(self):
        v = Variant(arch="x86_64", platform_tag="macosx_11_0_x86_64")
        assert v.request_tags == ("macosx_11_0_x86_64",)

    def test_request_tags_includes_extras_in_order(self):
        v = Variant(
            arch="x86_64",
            platform_tag="manylinux_2_28_x86_64",
            extra_platform_tags=("manylinux_2_17_x86_64", "linux_x86_64"),
        )
        assert v.request_tags == (
            "manylinux_2_28_x86_64",
            "manylinux_2_17_x86_64",
            "linux_x86_64",
        )


# ---------------------------------------------------------------------------
# _indent
# ---------------------------------------------------------------------------


class TestIndent:
    def test_single_line(self):
        assert _indent("hello") == "    hello"

    def test_multiline(self):
        assert _indent("line1\nline2") == "    line1\n    line2"

    def test_empty_string_returns_empty(self):
        assert _indent("") == ""

    def test_none_treated_as_empty(self):
        assert _indent(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# get_wheel_resolver
# ---------------------------------------------------------------------------


class TestGetWheelResolver:
    def test_pip_returns_pip_resolver(self):
        r = get_wheel_resolver("pip")
        assert isinstance(r, PipWheelResolver)

    def test_unknown_backend_raises(self):
        with pytest.raises(WheelResolverError, match="unknown resolver backend"):
            get_wheel_resolver("uv")

    def test_custom_python_executable_forwarded(self):
        r = get_wheel_resolver("pip", python_executable="/usr/bin/python3")
        assert isinstance(r, PipWheelResolver)
        assert r._python == "/usr/bin/python3"


# ---------------------------------------------------------------------------
# PipWheelResolver.resolve — empty requirements fast path
# ---------------------------------------------------------------------------


class TestPipWheelResolverEmpty:
    def test_empty_requirements_returns_empty_list(self):
        pr = PipWheelResolver()
        result = pr.resolve(
            [],
            python_version="3.15.0",
            variants=(Variant(arch="x86_64", platform_tag="macosx_11_0_x86_64"),),
            extra_index_urls=[],
        )
        assert result == []


# ---------------------------------------------------------------------------
# pip version guard
# ---------------------------------------------------------------------------


class TestPipVersionGuard:
    def test_old_pip_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.lock.wheelruntime.resolver.pip_version",
            lambda _exe: (20, 0),
        )
        pr = PipWheelResolver()
        with pytest.raises(WheelResolverError, match="kivyforge needs pip"):
            pr.resolve(
                ["kivy"],
                python_version="3.15.0",
                variants=(Variant(arch="x86_64", platform_tag="macosx_11_0_x86_64"),),
                extra_index_urls=[],
            )

    def test_unknown_pip_does_not_block(self, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.lock.wheelruntime.resolver.pip_version", lambda _exe: None
        )
        monkeypatch.setattr(
            PipWheelResolver, "_run_report", lambda *a, **k: {"install": []}
        )
        pr = PipWheelResolver()
        assert (
            pr.resolve(
                ["kivy"],
                python_version="3.15.0",
                variants=(Variant(arch="x86_64", platform_tag="macosx_11_0_x86_64"),),
                extra_index_urls=[],
            )
            == []
        )

    def test_modern_pip_proceeds(self, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.lock.wheelruntime.resolver.pip_version",
            lambda _exe: MIN_PIP_VERSION,
        )
        monkeypatch.setattr(
            PipWheelResolver, "_run_report", lambda *a, **k: {"install": []}
        )
        pr = PipWheelResolver()
        assert (
            pr.resolve(
                ["kivy"],
                python_version="3.15.0",
                variants=(Variant(arch="x86_64", platform_tag="macosx_11_0_x86_64"),),
                extra_index_urls=[],
            )
            == []
        )

    def test_version_str_roundtrip(self):
        assert version_str(MIN_PIP_VERSION) == "24.3"


# ---------------------------------------------------------------------------
# PipWheelResolver._absorb — called directly with synthetic pip report items
# ---------------------------------------------------------------------------


def _wheel_item(
    name: str = "kivy",
    version: str = "3.0.0",
    filename: str = "kivy-3.0.0-cp315-cp315-macosx_11_0_x86_64.whl",
    sha256: str = "a" * 64,
) -> dict:
    url = f"https://files.pythonhosted.org/packages/aa/{filename}"
    return {
        "metadata": {
            "name": name,
            "version": version,
            "requires_python": ">=3.10",
            "requires_dist": [],
        },
        "download_info": {
            "url": url,
            "archive_info": {"hashes": {"sha256": sha256}},
        },
    }


class TestPipWheelResolverAbsorb:
    def _absorb(self, item, merged=None, seen=None):
        pr = PipWheelResolver()
        if merged is None:
            merged = {}
        if seen is None:
            seen = {}
        pr._absorb(item, merged, seen)
        return merged, seen

    def test_non_wheel_url_raises(self):
        item = _wheel_item(filename="kivy-3.0.0.tar.gz")
        item["download_info"]["url"] = "https://example.com/kivy-3.0.0.tar.gz"
        with pytest.raises(WheelResolverError, match="non-wheel source"):
            self._absorb(item)

    def test_new_package_added_to_merged(self):
        merged, _ = self._absorb(_wheel_item())
        assert "kivy" in merged
        assert merged["kivy"].version == "3.0.0"

    def test_wheel_added_to_package(self):
        merged, _ = self._absorb(_wheel_item())
        assert len(merged["kivy"].wheels) == 1

    def test_duplicate_filename_not_added_twice(self):
        item = _wheel_item()
        merged: dict = {}
        seen: dict = {}
        pr = PipWheelResolver()
        pr._absorb(item, merged, seen)
        pr._absorb(item, merged, seen)
        assert len(merged["kivy"].wheels) == 1

    def test_second_variant_wheel_appended(self):
        pr = PipWheelResolver()
        merged: dict = {}
        seen: dict = {}
        item1 = _wheel_item(filename="kivy-3.0.0-cp315-cp315-macosx_11_0_x86_64.whl")
        item2 = _wheel_item(filename="kivy-3.0.0-cp315-cp315-macosx_11_0_arm64.whl")
        pr._absorb(item1, merged, seen)
        pr._absorb(item2, merged, seen)
        assert len(merged["kivy"].wheels) == 2

    def test_version_mismatch_across_variants_raises(self):
        pr = PipWheelResolver()
        merged: dict = {}
        seen: dict = {}
        v1 = _wheel_item(
            version="3.0.0",
            filename="kivy-3.0.0-cp315-cp315-macosx_11_0_x86_64.whl",
        )
        v2 = _wheel_item(
            version="3.0.1",
            filename="kivy-3.0.1-cp315-cp315-macosx_11_0_arm64.whl",
        )
        pr._absorb(v1, merged, seen)
        with pytest.raises(WheelResolverError, match="inconsistent versions"):
            pr._absorb(v2, merged, seen)

    def test_matching_version_across_variants_ok(self):
        pr = PipWheelResolver()
        merged: dict = {}
        seen: dict = {}
        v1 = _wheel_item(
            version="3.0.0",
            filename="kivy-3.0.0-cp315-cp315-macosx_11_0_x86_64.whl",
        )
        v2 = _wheel_item(
            version="3.0.0",
            filename="kivy-3.0.0-cp315-cp315-macosx_11_0_arm64.whl",
        )
        pr._absorb(v1, merged, seen)
        pr._absorb(v2, merged, seen)
        assert merged["kivy"].version == "3.0.0"
        assert len(merged["kivy"].wheels) == 2

    def test_requires_python_captured(self):
        merged, _ = self._absorb(_wheel_item())
        assert merged["kivy"].requires_python == ">=3.10"

    def test_sha256_captured(self):
        merged, _ = self._absorb(_wheel_item(sha256="b" * 64))
        assert merged["kivy"].wheels[0].sha256 == "b" * 64

    def test_canonical_name_normalises_hyphens(self):
        item = _wheel_item(
            name="more-itertools",
            filename="more_itertools-10.5.0-py3-none-any.whl",
        )
        merged, _ = self._absorb(item)
        assert "more-itertools" in merged


# ---------------------------------------------------------------------------
# PipWheelResolver._run_report — subprocess mocked
# ---------------------------------------------------------------------------


class TestPipWheelResolverRunReport:
    def test_nonzero_returncode_raises(self, monkeypatch):
        def fake_run(cmd, **kw):
            result = MagicMock()
            result.returncode = 1
            result.stderr = "ERROR: no matching distribution found"
            result.stdout = ""
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr = PipWheelResolver()
        with pytest.raises(WheelResolverError, match="pip could not resolve wheels"):
            pr._run_report(
                ["bad-pkg"],
                python_version="3.15.0",
                platform_tags=("macosx_11_0_x86_64",),
                abis=("cp315",),
                extra_index_urls=[],
                find_links=[],
                offline=False,
            )

    def test_offline_adds_no_index_flag(self, monkeypatch):
        captured: list[list[str]] = []

        def fake_run(cmd, **kw):
            captured.append(list(cmd))
            report_path = Path(next(a for a in cmd if a.endswith("report.json")))
            report_path.write_text(json.dumps({"install": []}))
            result = MagicMock()
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr = PipWheelResolver()
        pr._run_report(
            ["kivy"],
            python_version="3.15.0",
            platform_tags=("macosx_11_0_x86_64",),
            abis=("cp315",),
            extra_index_urls=[],
            find_links=[],
            offline=True,
        )
        assert "--no-index" in captured[0]

    def test_find_links_added_to_command(self, monkeypatch):
        captured: list[list[str]] = []

        def fake_run(cmd, **kw):
            captured.append(list(cmd))
            report_path = Path(next(a for a in cmd if a.endswith("report.json")))
            report_path.write_text(json.dumps({"install": []}))
            result = MagicMock()
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr = PipWheelResolver()
        pr._run_report(
            ["kivy"],
            python_version="3.15.0",
            platform_tags=("macosx_11_0_x86_64",),
            abis=("cp315",),
            extra_index_urls=[],
            find_links=["/wheels"],
            offline=False,
        )
        assert "--find-links" in captured[0]
        idx = captured[0].index("--find-links")
        assert captured[0][idx + 1] == "/wheels"

    def test_extra_index_url_added(self, monkeypatch):
        captured: list[list[str]] = []

        def fake_run(cmd, **kw):
            captured.append(list(cmd))
            report_path = Path(next(a for a in cmd if a.endswith("report.json")))
            report_path.write_text(json.dumps({"install": []}))
            result = MagicMock()
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr = PipWheelResolver()
        pr._run_report(
            ["kivy"],
            python_version="3.15.0",
            platform_tags=("macosx_11_0_x86_64",),
            abis=("cp315",),
            extra_index_urls=["https://custom.index/simple"],
            find_links=[],
            offline=False,
        )
        assert "--extra-index-url" in captured[0]

    def test_multiple_platform_tags_all_passed(self, monkeypatch):
        captured: list[list[str]] = []

        def fake_run(cmd, **kw):
            captured.append(list(cmd))
            report_path = Path(next(a for a in cmd if a.endswith("report.json")))
            report_path.write_text(json.dumps({"install": []}))
            result = MagicMock()
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr = PipWheelResolver()
        pr._run_report(
            ["kivy"],
            python_version="3.15.0",
            platform_tags=("manylinux_2_28_x86_64", "manylinux_2_17_x86_64"),
            abis=("cp315",),
            extra_index_urls=[],
            find_links=[],
            offline=False,
        )
        assert captured[0].count("--platform") == 2
        assert "manylinux_2_28_x86_64" in captured[0]
        assert "manylinux_2_17_x86_64" in captured[0]


# ---------------------------------------------------------------------------
# PipWheelResolver.resolve — end-to-end with _run_report mocked
# ---------------------------------------------------------------------------


class TestPipWheelResolverResolve:
    def test_empty_requirements_no_subprocess(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("subprocess called")),
        )
        pr = PipWheelResolver()
        assert (
            pr.resolve(
                [],
                python_version="3.15.0",
                variants=(Variant(arch="x86_64", platform_tag="macosx_11_0_x86_64"),),
                extra_index_urls=[],
            )
            == []
        )

    def test_resolve_merges_two_variants(self, monkeypatch):
        variant_items = [
            [_wheel_item(filename="kivy-3.0.0-cp315-cp315-macosx_11_0_x86_64.whl")],
            [_wheel_item(filename="kivy-3.0.0-cp315-cp315-macosx_11_0_arm64.whl")],
        ]
        call_iter = iter(variant_items)

        def fake_run_report(self_inner, requirements, **kwargs):
            return {"install": next(call_iter)}

        monkeypatch.setattr(PipWheelResolver, "_run_report", fake_run_report)
        pr = PipWheelResolver()
        packages = pr.resolve(
            ["kivy>=3.0"],
            python_version="3.15.0",
            variants=(
                Variant(arch="x86_64", platform_tag="macosx_11_0_x86_64"),
                Variant(arch="arm64", platform_tag="macosx_11_0_arm64"),
            ),
            extra_index_urls=[],
        )
        assert len(packages) == 1
        assert packages[0].name == "kivy"
        assert len(packages[0].wheels) == 2

    def test_resolve_raises_on_version_mismatch_between_variants(self, monkeypatch):
        variant_items = [
            [
                _wheel_item(
                    version="3.0.0",
                    filename="kivy-3.0.0-cp315-cp315-macosx_11_0_x86_64.whl",
                )
            ],
            [
                _wheel_item(
                    version="3.0.1",
                    filename="kivy-3.0.1-cp315-cp315-macosx_11_0_arm64.whl",
                )
            ],
        ]
        call_iter = iter(variant_items)

        def fake_run_report(self_inner, requirements, **kwargs):
            return {"install": next(call_iter, [])}

        monkeypatch.setattr(PipWheelResolver, "_run_report", fake_run_report)
        pr = PipWheelResolver()
        with pytest.raises(WheelResolverError, match="inconsistent versions"):
            pr.resolve(
                ["kivy>=3.0"],
                python_version="3.15.0",
                variants=(
                    Variant(arch="x86_64", platform_tag="macosx_11_0_x86_64"),
                    Variant(arch="arm64", platform_tag="macosx_11_0_arm64"),
                ),
                extra_index_urls=[],
            )

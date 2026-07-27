"""Tests for kivyforge/platforms/android/lock/resolver.py.

Covers PipResolver (with ``_run_report`` monkeypatched), ``_absorb`` edge
cases, ``_run_report`` (with subprocess monkeypatched), the pip-version
guard, and ``get_resolver``. No network or real pip invocation is needed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kivyforge.platforms.android.lock.markers import android_marker_environment
from kivyforge.platforms.android.lock.resolver import (
    MIN_ANDROID_PIP_VERSION,
    PipResolver,
    ResolverError,
    _indent,
    abi_platform_tag,
    get_resolver,
    version_str,
)


@pytest.fixture(autouse=True)
def _modern_host_pip(monkeypatch):
    """Default every test to a modern host pip so resolve() isn't gated on the
    machine running the suite. Guard-specific tests re-patch this as needed.
    """
    monkeypatch.setattr(
        "kivyforge.platforms.android.lock.resolver.pip_version",
        lambda _exe: (99, 0),
    )


# ---------------------------------------------------------------------------
# abi_platform_tag
# ---------------------------------------------------------------------------


class TestAbiPlatformTag:
    def test_format(self):
        assert abi_platform_tag(24, "arm64_v8a") == "android_24_arm64_v8a"

    def test_different_min_sdk(self):
        assert abi_platform_tag(21, "x86_64") == "android_21_x86_64"


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
# get_resolver
# ---------------------------------------------------------------------------


class TestGetResolver:
    def test_pip_returns_pip_resolver(self):
        r = get_resolver("pip")
        assert isinstance(r, PipResolver)

    def test_unknown_backend_raises(self):
        with pytest.raises(ResolverError, match="unknown resolver backend"):
            get_resolver("uv")

    def test_custom_python_executable_forwarded(self):
        r = get_resolver("pip", python_executable="/usr/bin/python3")
        assert isinstance(r, PipResolver)
        assert r._python == "/usr/bin/python3"


# ---------------------------------------------------------------------------
# PipResolver.resolve — empty requirements fast path
# ---------------------------------------------------------------------------


class TestPipResolverEmpty:
    def test_empty_requirements_returns_empty_list(self):
        pr = PipResolver()
        result = pr.resolve(
            [],
            python_version="3.14.0",
            min_sdk=24,
            abis=("arm64_v8a", "x86_64"),
            extra_index_urls=[],
        )
        assert result == []


# ---------------------------------------------------------------------------
# pip version guard (PEP 738 android tags require pip >= 25.1)
# ---------------------------------------------------------------------------


class TestPipVersionGuard:
    def test_old_pip_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.platforms.android.lock.resolver.pip_version",
            lambda _exe: (25, 0),
        )
        pr = PipResolver()
        with pytest.raises(ResolverError, match=r"pip >= 25\.1"):
            pr.resolve(
                ["kivy"],
                python_version="3.14.0",
                min_sdk=24,
                abis=("arm64_v8a",),
                extra_index_urls=[],
            )

    def test_unknown_pip_does_not_block(self, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.platforms.android.lock.resolver.pip_version",
            lambda _exe: None,
        )
        monkeypatch.setattr(PipResolver, "_run_report", lambda *a, **k: {"install": []})
        pr = PipResolver()
        assert (
            pr.resolve(
                ["kivy"],
                python_version="3.14.0",
                min_sdk=24,
                abis=("arm64_v8a",),
                extra_index_urls=[],
            )
            == []
        )

    def test_modern_pip_proceeds(self, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.platforms.android.lock.resolver.pip_version",
            lambda _exe: (25, 1),
        )
        monkeypatch.setattr(PipResolver, "_run_report", lambda *a, **k: {"install": []})
        pr = PipResolver()
        assert (
            pr.resolve(
                ["kivy"],
                python_version="3.14.0",
                min_sdk=24,
                abis=("arm64_v8a",),
                extra_index_urls=[],
            )
            == []
        )

    def test_version_str_roundtrip(self):
        assert version_str(MIN_ANDROID_PIP_VERSION) == "25.1"


# ---------------------------------------------------------------------------
# PipResolver._absorb — called directly with synthetic pip report items
# ---------------------------------------------------------------------------


def _wheel_item(
    name: str = "kivy",
    version: str = "3.0.0",
    filename: str = "kivy-3.0.0-cp314-cp314-android_24_arm64_v8a.whl",
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


_TARGET_ENV = android_marker_environment(python_version="3.14.0", abi="arm64_v8a")


class TestPipResolverAbsorb:
    def _absorb(self, item, merged=None, seen=None):
        pr = PipResolver()
        if merged is None:
            merged = {}
        if seen is None:
            seen = {}
        pr._absorb(item, merged, seen, _TARGET_ENV)
        return merged, seen

    def test_non_wheel_url_raises(self):
        item = _wheel_item(filename="kivy-3.0.0.tar.gz")
        item["download_info"]["url"] = "https://example.com/kivy-3.0.0.tar.gz"
        with pytest.raises(ResolverError, match="non-wheel source"):
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
        pr = PipResolver()
        pr._absorb(item, merged, seen, _TARGET_ENV)
        pr._absorb(item, merged, seen, _TARGET_ENV)  # same item again
        assert len(merged["kivy"].wheels) == 1

    def test_second_abi_wheel_appended(self):
        pr = PipResolver()
        merged: dict = {}
        seen: dict = {}
        item1 = _wheel_item(filename="kivy-3.0.0-cp314-cp314-android_24_arm64_v8a.whl")
        item2 = _wheel_item(filename="kivy-3.0.0-cp314-cp314-android_24_x86_64.whl")
        pr._absorb(item1, merged, seen, _TARGET_ENV)
        pr._absorb(item2, merged, seen, _TARGET_ENV)
        assert len(merged["kivy"].wheels) == 2

    def test_version_mismatch_across_abis_raises(self):
        pr = PipResolver()
        merged: dict = {}
        seen: dict = {}
        arm = _wheel_item(
            version="3.0.0",
            filename="kivy-3.0.0-cp314-cp314-android_24_arm64_v8a.whl",
        )
        x86 = _wheel_item(
            version="3.0.1",
            filename="kivy-3.0.1-cp314-cp314-android_24_x86_64.whl",
        )
        pr._absorb(arm, merged, seen, _TARGET_ENV)
        with pytest.raises(ResolverError, match="inconsistent versions"):
            pr._absorb(x86, merged, seen, _TARGET_ENV)

    def test_matching_version_across_abis_ok(self):
        pr = PipResolver()
        merged: dict = {}
        seen: dict = {}
        arm = _wheel_item(
            version="3.0.0",
            filename="kivy-3.0.0-cp314-cp314-android_24_arm64_v8a.whl",
        )
        x86 = _wheel_item(
            version="3.0.0",
            filename="kivy-3.0.0-cp314-cp314-android_24_x86_64.whl",
        )
        pr._absorb(arm, merged, seen, _TARGET_ENV)
        pr._absorb(x86, merged, seen, _TARGET_ENV)
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
# PipResolver._run_report — subprocess mocked
# ---------------------------------------------------------------------------


class TestPipResolverRunReport:
    def _make_report(self, install_items: list[dict]) -> dict:
        return {"install": install_items, "environment": {}}

    def test_success_returns_parsed_json(self, monkeypatch):
        report_data = self._make_report([])

        def fake_run(cmd, **kw):
            report_path = Path(next(a for a in cmd if a.endswith("report.json")))
            report_path.write_text(json.dumps(report_data))
            result = MagicMock()
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr = PipResolver()
        result = pr._run_report(
            ["kivy"],
            python_version="3.14.0",
            platform_tag="android_24_arm64_v8a",
            abis=("cp314", "abi3", "none"),
            extra_index_urls=[],
            find_links=[],
            offline=False,
            marker_environment=_TARGET_ENV,
        )
        assert result == report_data

    def test_nonzero_returncode_raises(self, monkeypatch):
        def fake_run(cmd, **kw):
            result = MagicMock()
            result.returncode = 1
            result.stderr = "ERROR: no matching distribution found"
            result.stdout = ""
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr = PipResolver()
        with pytest.raises(ResolverError, match="pip could not resolve"):
            pr._run_report(
                ["bad-pkg"],
                python_version="3.14.0",
                platform_tag="android_24_arm64_v8a",
                abis=("cp314",),
                extra_index_urls=[],
                find_links=[],
                offline=False,
                marker_environment=_TARGET_ENV,
            )

    def test_json_parse_error_raises(self, monkeypatch):
        def fake_run(cmd, **kw):
            report_path = Path(next(a for a in cmd if a.endswith("report.json")))
            report_path.write_text("not valid json {{")
            result = MagicMock()
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr = PipResolver()
        with pytest.raises(ResolverError, match="could not read pip report"):
            pr._run_report(
                ["kivy"],
                python_version="3.14.0",
                platform_tag="android_24_arm64_v8a",
                abis=("cp314",),
                extra_index_urls=[],
                find_links=[],
                offline=False,
                marker_environment=_TARGET_ENV,
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
        pr = PipResolver()
        pr._run_report(
            ["kivy"],
            python_version="3.14.0",
            platform_tag="android_24_arm64_v8a",
            abis=("cp314",),
            extra_index_urls=[],
            find_links=[],
            offline=True,
            marker_environment=_TARGET_ENV,
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
        pr = PipResolver()
        pr._run_report(
            ["kivy"],
            python_version="3.14.0",
            platform_tag="android_24_arm64_v8a",
            abis=("cp314",),
            extra_index_urls=[],
            find_links=["/wheels"],
            offline=False,
            marker_environment=_TARGET_ENV,
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
        pr = PipResolver()
        pr._run_report(
            ["kivy"],
            python_version="3.14.0",
            platform_tag="android_24_arm64_v8a",
            abis=("cp314",),
            extra_index_urls=["https://custom.index/simple"],
            find_links=[],
            offline=False,
            marker_environment=_TARGET_ENV,
        )
        assert "--extra-index-url" in captured[0]

    def test_marker_env_passed_via_environment_variable(self, monkeypatch):
        captured_env = {}

        def fake_run(cmd, *, env, **kw):
            captured_env.update(env)
            report_path = Path(next(a for a in cmd if a.endswith("report.json")))
            report_path.write_text(json.dumps({"install": []}))
            result = MagicMock()
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr = PipResolver()
        pr._run_report(
            ["kivy"],
            python_version="3.14.0",
            platform_tag="android_24_arm64_v8a",
            abis=("cp314",),
            extra_index_urls=[],
            find_links=[],
            offline=False,
            marker_environment=_TARGET_ENV,
        )
        from kivyforge.lock._pip_shim import MARKER_ENV_VAR

        assert json.loads(captured_env[MARKER_ENV_VAR]) == _TARGET_ENV


# ---------------------------------------------------------------------------
# PipResolver.resolve — end-to-end with _run_report mocked
# ---------------------------------------------------------------------------


class TestPipResolverResolve:
    def test_empty_requirements_no_subprocess(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("subprocess called")),
        )
        pr = PipResolver()
        assert (
            pr.resolve(
                [],
                python_version="3.14.0",
                min_sdk=24,
                abis=("arm64_v8a",),
                extra_index_urls=[],
            )
            == []
        )

    def test_resolve_merges_two_abis(self, monkeypatch):
        abi_items = [
            [_wheel_item(filename="kivy-3.0.0-cp314-cp314-android_24_arm64_v8a.whl")],
            [_wheel_item(filename="kivy-3.0.0-cp314-cp314-android_24_x86_64.whl")],
        ]
        call_iter = iter(abi_items)

        def fake_run_report(self_inner, requirements, **kwargs):
            return {"install": next(call_iter)}

        monkeypatch.setattr(PipResolver, "_run_report", fake_run_report)
        pr = PipResolver()
        packages = pr.resolve(
            ["kivy>=3.0"],
            python_version="3.14.0",
            min_sdk=24,
            abis=("arm64_v8a", "x86_64"),
            extra_index_urls=[],
        )
        assert len(packages) == 1
        assert packages[0].name == "kivy"
        assert len(packages[0].wheels) == 2

    def test_resolve_returns_multiple_packages(self, monkeypatch):
        kivy_whl = _wheel_item(
            filename="kivy-3.0.0-cp314-cp314-android_24_arm64_v8a.whl"
        )
        mi_whl = _wheel_item(
            name="more-itertools",
            version="10.5.0",
            filename="more_itertools-10.5.0-py3-none-any.whl",
        )
        call_iter = iter([[kivy_whl, mi_whl]] * 2)

        def fake_run_report(self_inner, requirements, **kwargs):
            return {"install": next(call_iter)}

        monkeypatch.setattr(PipResolver, "_run_report", fake_run_report)
        pr = PipResolver()
        packages = pr.resolve(
            ["kivy", "more-itertools"],
            python_version="3.14.0",
            min_sdk=24,
            abis=("arm64_v8a", "x86_64"),
            extra_index_urls=[],
        )
        names = {p.name for p in packages}
        assert "kivy" in names
        assert "more-itertools" in names

    def test_resolve_raises_on_version_mismatch_between_abis(self, monkeypatch):
        abi_items = [
            [
                _wheel_item(
                    version="3.0.0",
                    filename="kivy-3.0.0-cp314-cp314-android_24_arm64_v8a.whl",
                )
            ],
            [
                _wheel_item(
                    version="3.0.1",
                    filename="kivy-3.0.1-cp314-cp314-android_24_x86_64.whl",
                )
            ],
        ]
        call_iter = iter(abi_items)

        def fake_run_report(self_inner, requirements, **kwargs):
            return {"install": next(call_iter, [])}

        monkeypatch.setattr(PipResolver, "_run_report", fake_run_report)
        pr = PipResolver()
        with pytest.raises(ResolverError, match="inconsistent versions"):
            pr.resolve(
                ["kivy>=3.0"],
                python_version="3.14.0",
                min_sdk=24,
                abis=("arm64_v8a", "x86_64"),
                extra_index_urls=[],
            )

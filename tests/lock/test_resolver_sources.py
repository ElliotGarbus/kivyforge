"""The source rules in all three pip resolvers (#86).

Each resolver runs pip through the shim with ``KIVYFORGE_SOURCE_POLICY`` set,
reads the shim's record back into its report, fills in each package's index,
and classifies a failure whose package has a fixed source. pip itself is faked
at the ``run_streaming`` seam.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kivyforge.lock import _pip_shim
from kivyforge.lock.resolver import IndexUnreachable
from kivyforge.lock.sources import (
    RECORD_KEY,
    SourceFilterUnavailable,
    SourceUnavailable,
    source_policy,
)
from kivyforge.lock.wheelruntime import resolver as desktop_mod
from kivyforge.platforms.android.lock import resolver as android_mod
from kivyforge.platforms.android.lock.markers import android_marker_environment
from kivyforge.platforms.ios.lock import resolver as ios_mod
from kivyforge.platforms.ios.lock.markers import ios_marker_environment
from kivyforge.report import diagnostics, exit_codes
from tests.streaming_fake import streaming

#: What pip reports as the hash of a download that had no body.
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _android(policy):
    return android_mod.PipResolver()._run_report(
        ["kivy"],
        python_version="3.14.0",
        platform_tag="android_24_arm64_v8a",
        abis=("cp314",),
        extra_index_urls=[],
        find_links=list(policy.find_links),
        offline=False,
        marker_environment=android_marker_environment(
            python_version="3.14.0", abi="arm64_v8a"
        ),
        sources=policy,
    )


def _ios(policy):
    return ios_mod.PipResolver()._run_report(
        ["kivy"],
        python_version="3.14.0",
        platform_tag="ios_13_0_arm64_iphoneos",
        abis=("cp314",),
        extra_index_urls=[],
        find_links=list(policy.find_links),
        offline=False,
        marker_environment=ios_marker_environment(
            python_version="3.14.0", slice_suffix="arm64_iphoneos"
        ),
        sources=policy,
    )


def _desktop(policy):
    return desktop_mod.PipWheelResolver()._run_report(
        ["kivy"],
        python_version="3.14.0",
        platform_tags=("macosx_11_0_arm64",),
        abis=("cp314",),
        extra_index_urls=[],
        find_links=list(policy.find_links),
        offline=False,
        sources=policy,
    )


RESOLVERS = [
    pytest.param(android_mod, _android, id="android"),
    pytest.param(ios_mod, _ios, id="ios"),
    pytest.param(desktop_mod, _desktop, id="desktop"),
]


def _fake_pip(returncode=0, *, record=None, output="", seen=None):
    def fake_run(cmd, env=None, **_kw):
        if seen is not None:
            seen["cmd"] = cmd
            seen["env"] = env
        assert env is not None
        policy = json.loads(env[_pip_shim.SOURCE_POLICY_ENV_VAR])
        if returncode == 0:
            report = Path(next(a for a in cmd if a.endswith("report.json")))
            report.write_text(json.dumps({"install": []}))
            Path(policy["record"]).write_text(json.dumps(record or {}))
        return SimpleNamespace(returncode=returncode, stdout=output, stderr="")

    return streaming(fake_run)


@pytest.mark.parametrize(("module", "run"), RESOLVERS)
class TestRunReport:
    def test_runs_the_shim_with_the_policy_and_returns_its_record(
        self, module, run, monkeypatch
    ):
        seen: dict = {}
        record = {"https://files/kivy.whl": "https://m.example/simple/"}
        monkeypatch.setattr(
            module, "run_streaming", _fake_pip(record=record, seen=seen)
        )
        policy = source_policy([], ["https://m.example/simple"], platform="x")
        report = run(policy)
        assert report[RECORD_KEY] == record
        assert seen["cmd"][1] == _pip_shim.__file__
        policy_json = json.loads(seen["env"][_pip_shim.SOURCE_POLICY_ENV_VAR])
        assert policy_json["rank"][0] == ["extra-1", "https://m.example/simple/"]
        i = seen["cmd"].index("--extra-index-url")
        assert seen["cmd"][i + 1] == "https://m.example/simple/"

    def test_a_shim_that_cannot_patch_pip_is_reported_as_such(
        self, module, run, monkeypatch
    ):
        output = "kivyforge 1 cannot apply its source rules with pip 99"
        monkeypatch.setattr(
            module,
            "run_streaming",
            _fake_pip(_pip_shim.SOURCE_FILTER_UNAVAILABLE, output=output),
        )
        with pytest.raises(SourceFilterUnavailable, match="cannot apply"):
            run(source_policy([], []))

    def test_a_local_package_with_no_fitting_wheel_is_classified(
        self, module, run, monkeypatch, tmp_path
    ):
        (tmp_path / "kivy-2.3.1-py3-none-any.whl").write_bytes(b"")
        output = (
            "ERROR: Could not find a version that satisfies the requirement "
            "kivy==2.3.1 (from versions: none)"
        )
        monkeypatch.setattr(module, "run_streaming", _fake_pip(1, output=output))
        with pytest.raises(SourceUnavailable) as caught:
            run(source_policy([str(tmp_path)], [], platform="android"))
        assert caught.value.context["distribution"] == "kivy"
        assert caught.value.context["source"] == "find_links"

    def test_an_empty_file_from_pips_cache_is_retried_without_it(
        self, module, run, monkeypatch
    ):
        poisoned = (
            "ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS "
            "FILE.\n    kivy==2.3.1 from https://github.com/x/Kivy.whl#sha256=0788:\n"
            "        Expected sha256 20da914a3abff114448106df16161184eb283283d544\n"
            f"             Got        {EMPTY_SHA256}\n"
        )
        cmds = []
        good = _fake_pip(record={})

        def fake(cmd, **kwargs):
            cmds.append(list(cmd))
            if len(cmds) == 1:
                return _fake_pip(1, output=poisoned)(cmd, **kwargs)
            return good(cmd, **kwargs)

        monkeypatch.setattr(module, "run_streaming", fake)
        report = run(source_policy([], []))
        assert report["install"] == []
        assert "--no-cache-dir" not in cmds[0]
        assert cmds[1][cmds[1].index("install") + 1] == "--no-cache-dir"
        assert sorted(cmds[1]) == sorted([*cmds[0], "--no-cache-dir"])

    def test_a_real_hash_mismatch_is_not_retried(self, module, run, monkeypatch):
        output = (
            "ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS "
            "FILE.\n        Expected sha256 20da914a\n             Got        78c5a39f\n"
        )
        calls = []

        def fake(cmd, **kwargs):
            calls.append(cmd)
            return _fake_pip(1, output=output)(cmd, **kwargs)

        monkeypatch.setattr(module, "run_streaming", fake)
        with pytest.raises(Exception, match="pip could not resolve"):
            run(source_policy([], []))
        assert len(calls) == 1

    def test_a_lost_connection_is_its_own_failure(self, module, run, monkeypatch):
        output = (
            "WARNING: Retrying (Retry(total=4, connect=None, read=None)) after "
            "connection broken by 'ConnectionResetError(10054)': /simple/kivy/\n"
            "ERROR: Could not install packages due to an OSError: "
            "HTTPSConnectionPool(host='files.pythonhosted.org', port=443): Max "
            "retries exceeded with url: /packages/pyjnius.whl.metadata (Caused by "
            "NameResolutionError(\"Failed to resolve 'files.pythonhosted.org'\"))\n"
        )
        monkeypatch.setattr(module, "run_streaming", _fake_pip(1, output=output))
        with pytest.raises(IndexUnreachable) as caught:
            run(source_policy([], []))
        assert caught.value.code == diagnostics.LOCK_INDEX_UNREACHABLE
        assert caught.value.exit_code == exit_codes.ENVIRONMENT_ERROR
        assert caught.value.context["host"] == "files.pythonhosted.org"
        message = str(caught.value)
        assert "no wheel" not in message
        assert "retry with network access" in message
        message.encode("cp1252")

    def test_retries_that_recovered_do_not_make_a_lost_connection(
        self, module, run, monkeypatch
    ):
        output = (
            "WARNING: Retrying (Retry(total=4)) after connection broken by "
            "'ReadTimeoutError(\"Read timed out.\")': /simple/kivy/\n"
            "ERROR: Could not find a version that satisfies the requirement "
            "kivy (from versions: none)"
        )
        monkeypatch.setattr(module, "run_streaming", _fake_pip(1, output=output))
        with pytest.raises(Exception, match="pip could not resolve") as caught:
            run(source_policy([], []))
        assert not isinstance(caught.value, IndexUnreachable)

    def test_an_index_package_keeps_pips_own_failure(self, module, run, monkeypatch):
        output = (
            "ERROR: Could not find a version that satisfies the requirement "
            "kivy (from versions: none)"
        )
        monkeypatch.setattr(module, "run_streaming", _fake_pip(1, output=output))
        with pytest.raises(Exception, match="pip could not resolve") as caught:
            run(source_policy([], []))
        assert not isinstance(caught.value, SourceUnavailable)


def test_desktop_resolver_keeps_host_markers(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(desktop_mod, "run_streaming", _fake_pip(seen=seen))
    _desktop(source_policy([], []))
    assert seen["env"][_pip_shim.HOST_MARKERS_ENV_VAR] == "1"


@pytest.mark.parametrize(
    ("module", "resolver", "kwargs"),
    [
        pytest.param(
            android_mod,
            android_mod.PipResolver,
            {"min_sdk": 24, "abis": ("arm64_v8a", "x86_64")},
            id="android",
        ),
        pytest.param(
            ios_mod,
            ios_mod.PipResolver,
            {"deployment_target": "13.0", "simulator_archs": ("arm64",)},
            id="ios",
        ),
        pytest.param(
            desktop_mod,
            desktop_mod.PipWheelResolver,
            {
                "variants": (
                    desktop_mod.Variant("arm64", "macosx_11_0_arm64"),
                    desktop_mod.Variant("x86_64", "macosx_11_0_x86_64"),
                )
            },
            id="desktop",
        ),
    ],
)
def test_resolve_records_each_packages_index(module, resolver, kwargs, monkeypatch):
    monkeypatch.setattr(module, "pip_version", lambda _exe: (99, 0))
    variant = iter(range(10))

    def fake_run_report(self, requirements, **_kw):
        n = next(variant)
        url = f"https://gh/kivy-{n}.whl"
        local = f"file:///wheels/plyer-{n}-py3-none-any.whl"
        return {
            "install": [
                {
                    "metadata": {"name": "kivy", "version": "2.3.1"},
                    "download_info": {
                        "url": url,
                        "archive_info": {"hashes": {"sha256": "0" * 64}},
                    },
                },
                {
                    "metadata": {"name": "plyer", "version": "2.1"},
                    "download_info": {
                        "url": local,
                        "archive_info": {"hashes": {"sha256": "1" * 64}},
                    },
                },
            ],
            RECORD_KEY: {url: "https://m.example/simple/", local: "find_links"},
        }

    monkeypatch.setattr(resolver, "_run_report", fake_run_report)
    packages = resolver().resolve(
        ["kivy", "plyer"],
        python_version="3.14.0",
        extra_index_urls=[],
        **kwargs,
    )
    by_name = {p.name: p for p in packages}
    assert by_name["kivy"].source_index == "https://m.example/simple/"
    assert by_name["plyer"].source_index is None

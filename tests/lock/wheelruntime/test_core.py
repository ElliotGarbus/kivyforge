"""Prove the wheel+runtime core is platform-agnostic.

A throwaway "faux-linux" profile (manylinux-style tags, per-arch coverage, no
universal fat wheel) drives the *same* generic builder/serializer macOS uses.
This is the concrete demonstration that adding Linux/Windows/Android is writing a
thin profile — not copying the engine.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.lock.wheelruntime import (
    PythonRuntime,
    ResolvedPackage,
    ResolvedWheel,
    RuntimeArtifact,
    Variant,
    build_wheel_runtime_lock,
    dumps,
    loads,
)
from kivyforge.lock.wheelruntime.profile import PlatformLockProfile
from kivyforge.lock.wheelruntime.resolver import PipWheelResolver, WheelResolverError
from kivyforge.platforms.macos.lock import MacosProfile


class FauxLinuxProfile(PlatformLockProfile):
    """A minimal second profile: reuses config.macos as a stand-in overlay.

    Its ``variants()`` are deliberately **not** read from the macOS overlay's
    ``archs``: the point here is that the core is generic over however many
    archs a profile declares, which must stay testable even though no shipping
    platform is multi-arch today (macOS is arm64-only, Linux x86_64-only,
    Windows amd64-only).
    """

    platform = "faux"
    ARCHS = ("x86_64", "arm64")

    def overlay(self, config):
        return config.macos

    def missing_overlay_error(self):
        return "no overlay"

    def python_version(self, config):
        return config.macos_required.python_version or "3.15.0"

    def variants(self, config):
        return tuple(
            Variant(arch=a, platform_tag=f"manylinux_2_28_{a}") for a in self.ARCHS
        )

    def wheel_covers(self, platform_tag, archs):
        arch = platform_tag.rsplit("_", 1)[-1] if "_" in platform_tag else None
        # manylinux_2_28_x86_64 -> x86_64 needs the two-token suffix
        for a in archs:
            if platform_tag.endswith(a):
                return {a}
        return {arch} & set(archs) if arch else set()

    def runtime_provider(self, config):  # pragma: no cover - injected in tests
        raise NotImplementedError

    def coverage_error(self, name, missing):
        return f"{name} missing {missing}"

    def wheel_scope_hint(self):
        return "hint"


class FakeResolver:
    def resolve(
        self,
        requirements,
        *,
        python_version,
        variants,
        extra_index_urls,
        find_links=None,
        offline=False,
    ):
        wheels = [
            ResolvedWheel(
                filename=f"kivy-3.0.0-cp315-cp315-{v.platform_tag}.whl",
                url=f"https://example.com/kivy-{v.arch}.whl",
                sha256="a" * 64,
            )
            for v in variants
        ]
        return [ResolvedPackage(name="kivy", version="3.0.0", wheels=wheels)]


class FakeProvider:
    name = "python-build-standalone"

    def resolve(self, version, archs, *, offline=False):
        return PythonRuntime(
            provider=self.name,
            version=version,
            artifacts=tuple(
                RuntimeArtifact(arch=a, url=f"https://e/{a}", sha256="c" * 64)
                for a in archs
            ),
        )


# Reuses the macOS overlay purely as a stand-in for "some platform overlay";
# the profile applies its own archs, manylinux-style tags, and coverage on top.
_PYPROJECT = (
    "[project]\nname='myapp'\nversion='1'\nrequires-python='>=3.15'\n"
    "dependencies=['kivy']\n"
    "[tool.kivy]\napp_dir='src'\n"
    "[tool.kivy.macos]\nschema_version=1\nbundle_id='org.example.myapp'\n"
    "[tool.kivy.macos.python]\nversion='3.15.0'\n"
)


def _config(tmp_path):
    return load_config_from_text(
        _PYPROJECT, require_ios=False, require_macos=True, project_root=tmp_path
    )


class TestCoreIsPlatformAgnostic:
    def test_second_profile_builds_and_round_trips(self, tmp_path):
        cfg = _config(tmp_path)
        lock = build_wheel_runtime_lock(
            FauxLinuxProfile(),
            cfg,
            _PYPROJECT,
            project_root=tmp_path,
            resolver=FakeResolver(),
            runtime_provider=FakeProvider(),
        )
        assert lock.platform == "faux"
        assert lock.archs == ("x86_64", "arm64")
        # A distinct, non-macOS platform tag proves the tags come from the profile.
        assert lock.packages[0].wheels[0].name.endswith("manylinux_2_28_x86_64.whl")
        again = loads(dumps(lock), platform="faux")
        assert again.platform == "faux"
        assert again.archs == ("x86_64", "arm64")
        assert {a.arch for a in again.python_runtime.artifacts} == {
            "x86_64",
            "arm64",
        }

    def test_macos_profile_is_a_profile_instance(self):
        assert isinstance(MacosProfile(), PlatformLockProfile)
        assert MacosProfile().platform == "macos"


class TestRunReportReadsUtf8:
    """pip writes ``--report`` as UTF-8; reading it must not use the OS default.

    On Windows the default codec is cp1252, which cannot decode common bytes
    (e.g. 0x8f) that appear once package metadata contains non-ASCII text.
    Regression: the resolver used to crash with UnicodeDecodeError there.
    """

    def _resolver_reading(self, monkeypatch, report_text):
        pr = PipWheelResolver(python_executable="python")

        def fake_run(cmd, *args, **kwargs):
            report_path = Path(next(a for a in cmd if a.endswith("report.json")))
            report_path.write_text(report_text, encoding="utf-8")

            class _Proc:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Proc()

        monkeypatch.setattr(subprocess, "run", fake_run)
        return pr._run_report(
            ["pkg"],
            python_version="3.13.0",
            platform_tags=("win_amd64",),
            abis=("cp313",),
            extra_index_urls=[],
            find_links=[],
            offline=False,
        )

    def test_non_cp1252_bytes_in_report(self, monkeypatch):
        # "Ï" (U+00CF) encodes to bytes C3 8F in UTF-8; 0x8f is undefined in
        # cp1252, so a default-codec read would raise here.
        report = json.dumps({"install": [{"name": "Ï-pkg"}]})
        assert "\u00cf".encode() == b"\xc3\x8f"
        result = self._resolver_reading(monkeypatch, report)
        assert result["install"][0]["name"] == "Ï-pkg"

    def test_invalid_report_raises_resolver_error(self, monkeypatch):
        with pytest.raises(WheelResolverError, match="could not read pip report"):
            self._resolver_reading(monkeypatch, "not valid json {{")

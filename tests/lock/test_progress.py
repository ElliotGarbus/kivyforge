"""Lock progress for iOS and the desktop backends (#88).

Android has shown its work since #87; these pin the same behavior for the
backends that used to run their slow steps captured: the pip resolves, the
python.org iOS framework download, and ``swift package resolve``.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

import kivyforge.lock.wheelruntime.resolver as desktop_resolver
import kivyforge.platforms.ios.lock.resolver as ios_resolver
import kivyforge.platforms.ios.lock.spm as spm
from kivyforge.config.model import SwiftPackageDep
from kivyforge.lock.wheelruntime.resolver import PipWheelResolver, Variant
from kivyforge.platforms.ios.lock import python_meta
from kivyforge.platforms.ios.lock.resolver import PipResolver
from kivyforge.platforms.ios.lock.spm import SpmResolverError, XcodeSpmResolver
from kivyforge.report.transfers import transfers_to

WHEEL = "https://files.example/Kivy-2.3.1-cp313-cp313-manylinux_2_28_x86_64.whl"


def _pip_streaming(captured: list[list[str]], *, segments=(), returncode=0):
    """A ``run_streaming`` that plays pip output and writes an empty report."""

    def run_streaming(cmd, *, on_segment, env=None, on_quiet=None, **_kw):
        captured.append(list(cmd))
        report = Path(cmd[cmd.index("--report") + 1])
        report.write_text(json.dumps({"install": []}), encoding="utf-8")
        for segment in segments:
            on_segment(segment)
        if on_quiet is not None:
            on_quiet(31.0)
        return returncode, "\n".join(segments)

    return run_streaming


PIP_OUTPUT = (
    f"Downloading {WHEEL} (12.0 MB)",
    "Progress 4096 of 12000000",
    "Progress 12000000 of 12000000",
)


class TestDesktopPipResolve:
    def test_downloads_become_transfers_and_steps_become_lines(self, monkeypatch):
        captured: list[list[str]] = []
        monkeypatch.setattr(
            desktop_resolver,
            "run_streaming",
            _pip_streaming(captured, segments=PIP_OUTPUT),
        )
        monkeypatch.setattr(desktop_resolver, "pip_version", lambda _python: None)
        lines: list[str] = []
        transfers: list[tuple] = []
        PipWheelResolver(
            on_progress=lines.append, on_transfer=lambda *a: transfers.append(a)
        ).resolve(
            ["kivy"],
            python_version="3.13.14",
            variants=(Variant(arch="x86_64", platform_tag="manylinux_2_28_x86_64"),),
            extra_index_urls=[],
        )
        assert "--progress-bar" in captured[0]
        assert captured[0][captured[0].index("--progress-bar") + 1] == "raw"
        assert lines[0] == "[lock] x86_64: resolving wheels"
        assert lines[-1] == "[lock] x86_64: still resolving (31s)"
        assert transfers == [
            ("[lock] x86_64: Kivy-2.3.1", 4096, 12000000, "bytes"),
            ("[lock] x86_64: Kivy-2.3.1", 12000000, 12000000, "bytes"),
        ]

    def test_no_callbacks_no_output(self, monkeypatch):
        captured: list[list[str]] = []
        monkeypatch.setattr(
            desktop_resolver,
            "run_streaming",
            _pip_streaming(captured, segments=PIP_OUTPUT),
        )
        monkeypatch.setattr(desktop_resolver, "pip_version", lambda _python: None)
        PipWheelResolver().resolve(
            ["kivy"],
            python_version="3.13.14",
            variants=(Variant(arch="x86_64", platform_tag="manylinux_2_28_x86_64"),),
            extra_index_urls=[],
        )
        assert captured  # resolved, silently

    def test_a_failure_quotes_pip_without_byte_counts(self, monkeypatch):
        failing = (*PIP_OUTPUT, "ERROR: No matching distribution found for kivy")
        monkeypatch.setattr(
            desktop_resolver,
            "run_streaming",
            _pip_streaming([], segments=failing, returncode=1),
        )
        with pytest.raises(desktop_resolver.WheelResolverError) as info:
            PipWheelResolver()._run_report(
                ["kivy"],
                python_version="3.13.14",
                platform_tags=("manylinux_2_28_x86_64",),
                abis=("cp313",),
                extra_index_urls=[],
                find_links=[],
                offline=False,
            )
        assert "No matching distribution found for kivy" in str(info.value)
        assert "Progress " not in str(info.value)


class TestDesktopBuilderWiresProgress:
    def test_the_default_resolver_gets_the_callbacks(self, monkeypatch, tmp_path):
        from kivyforge.config.loader import load_config_from_text
        from kivyforge.lock.wheelruntime import profile
        from kivyforge.platforms.linux.lock import build_linux_lockfile
        from tests.platforms.linux.lock.conftest import (
            FakeLinuxResolver,
            FakeRuntimeProvider,
        )

        seen: dict = {}

        def get_wheel_resolver(backend="pip", **kwargs):
            seen.update(kwargs)
            return FakeLinuxResolver()

        monkeypatch.setattr(profile, "get_wheel_resolver", get_wheel_resolver)
        config = load_config_from_text(
            '[project]\nname = "myapp"\nversion = "1.0.0"\nrequires-python = ">=3.13"\n'
            'dependencies = ["kivy>=3.0,<4", "more-itertools>=10.5"]\n'
            '[tool.kivy]\napp_dir = "src"\n'
            '[tool.kivy.linux]\nschema_version = 1\napp_id = "org.example.myapp"\n'
            '[tool.kivy.linux.python]\nversion = "3.13.14"\n',
            require_ios=False,
            require_linux=True,
        )

        def on_progress(_line):
            return None

        def on_transfer(*_args):
            return None

        build_linux_lockfile(
            config,
            project_root=tmp_path,
            runtime_provider=FakeRuntimeProvider(),
            on_progress=on_progress,
            on_transfer=on_transfer,
        )
        assert seen == {"on_progress": on_progress, "on_transfer": on_transfer}


class TestIosPipResolve:
    def test_downloads_become_transfers_and_steps_become_lines(self, monkeypatch):
        captured: list[list[str]] = []
        segments = (
            "Downloading https://files.example/kivy-3.0.0-cp315-cp315-ios_13_0_arm64_iphoneos.whl",
            "Progress 100 of 200",
        )
        monkeypatch.setattr(
            ios_resolver, "run_streaming", _pip_streaming(captured, segments=segments)
        )
        monkeypatch.setattr(ios_resolver, "pip_version", lambda _python: None)
        lines: list[str] = []
        transfers: list[tuple] = []
        PipResolver(
            on_progress=lines.append, on_transfer=lambda *a: transfers.append(a)
        ).resolve(
            ["kivy"],
            python_version="3.15.0",
            deployment_target="13.0",
            extra_index_urls=[],
            simulator_archs=("arm64",),
        )
        assert all("--progress-bar" in cmd for cmd in captured)
        assert lines[0] == "[lock] arm64_iphoneos: resolving wheels"
        assert transfers[0] == ("[lock] arm64_iphoneos: kivy-3.0.0", 100, 200, "bytes")


class TestPythonOrgDownload:
    def test_the_framework_download_is_a_byte_bar(self, monkeypatch):
        data = b"x" * 150_000

        class Response(io.BytesIO):
            headers = {"Content-Length": str(len(data))}

        monkeypatch.setattr(
            python_meta.urllib.request, "urlopen", lambda *_a, **_k: Response(data)
        )
        monkeypatch.setattr(
            python_meta, "_read_ios_floor_from_fileobj", lambda _f: "13.0"
        )
        events: list[tuple] = []
        with transfers_to(lambda *a: events.append(a)):
            python_meta.PythonOrgProvider()._download(
                "https://www.python.org/x.tar.gz", "3.15.0"
            )
        labels = {e[0] for e in events}
        assert labels == {"[download] Python.xcframework 3.15.0"}
        assert events[0][1:3] == (0, len(data))
        assert events[-1][1:3] == (len(data), len(data))


class TestSwiftPackageResolve:
    PKG = SwiftPackageDep(
        name="KeychainAccess",
        products=("KeychainAccess",),
        url="https://github.com/kishikawakatsumi/KeychainAccess.git",
        requirement={"exact": "4.2.2"},
    )

    def _fake(self, monkeypatch, *, returncode=0, segments=()):
        def run_streaming(cmd, *, on_segment, on_quiet=None, **_kw):
            package_path = Path(cmd[cmd.index("--package-path") + 1])
            (package_path / "Package.resolved").write_text(
                json.dumps(
                    {
                        "pins": [
                            {
                                "location": self.PKG.url,
                                "state": {"revision": "abc123", "version": "4.2.2"},
                            }
                        ],
                        "version": 2,
                    }
                ),
                encoding="utf-8",
            )
            for segment in segments:
                on_segment(segment)
            if on_quiet is not None:
                on_quiet(45.0)
            return returncode, "\n".join(segments)

        monkeypatch.setattr(spm, "run_streaming", run_streaming)

    def test_fetches_and_quiet_spells_are_shown(self, monkeypatch, tmp_path):
        self._fake(
            monkeypatch,
            segments=(
                f"Fetching {self.PKG.url}",
                "Computing version for KeychainAccess",
            ),
        )
        lines: list[str] = []
        pins = XcodeSpmResolver(on_progress=lines.append).resolve(
            [self.PKG], project_root=tmp_path
        )
        assert pins[0].revision == "abc123"
        assert lines == [
            "[lock] swift: resolving KeychainAccess",
            f"[lock] swift: Fetching {self.PKG.url}",
            "[lock] swift: still resolving (45s)",
        ]

    def test_a_failure_quotes_swift(self, monkeypatch, tmp_path):
        self._fake(
            monkeypatch,
            returncode=1,
            segments=("error: the package could not be resolved",),
        )
        with pytest.raises(SpmResolverError, match="could not be resolved"):
            XcodeSpmResolver().resolve([self.PKG], project_root=tmp_path)

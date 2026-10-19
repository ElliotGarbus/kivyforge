"""One host gate for every target verb (common design doc 02).

Every verb that acts on a target reaches it through
``kivyforge.cli._platform.resolve_target``, which runs ``require_host``: iOS and
macOS build on macOS, Windows on Windows, Linux on x86_64 Linux (a Raspberry Pi
is a target only), Android anywhere. ``init`` and ``doctor`` are deliberately
not gated. These tests call the real gate — the suite-wide autouse fixture in
``tests/conftest.py`` no-ops it everywhere else — so a regression that unwires
it, or a verb that stops going through it, fails here.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from kivyforge.capabilities import collect
from kivyforge.cli import _platform, main
from kivyforge.cli._common import ToolchainError
from kivyforge.platforms import HostCapabilityError, get_platform
from kivyforge.report import diagnostics, exit_codes

# Captured at import, before the autouse fixture replaces the module attribute
# with a no-op: these tests need the genuine gate.
_real_require_host = _platform.require_host

# Every verb that acts on a target. A new one belongs here, and in the gate.
GATED_VERBS = ("lock", "build", "run", "package", "open", "status", "upgrade")

PYPROJECT = "[project]\nname = 'hostprobe'\nversion = '0.1.0'\n"


@pytest.fixture
def host(monkeypatch):
    """Restore the real gate and fake the host it sees."""
    monkeypatch.setattr(_platform, "require_host", _real_require_host)

    def fake(system: str, machine: str) -> None:
        monkeypatch.setattr("platform.system", lambda: system)
        monkeypatch.setattr("platform.machine", lambda: machine)

    return fake


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestHostTable:
    @pytest.mark.parametrize(
        ("target", "system", "machine", "allowed"),
        [
            ("ios", "Darwin", "arm64", True),
            ("ios", "Linux", "x86_64", False),
            ("ios", "Windows", "amd64", False),
            ("macos", "Darwin", "arm64", True),
            ("macos", "Linux", "x86_64", False),
            ("macos", "Windows", "amd64", False),
            ("windows", "Windows", "amd64", True),
            # arm64 Windows cross-builds by design (arm64-windows.md §7).
            ("windows", "Windows", "arm64", True),
            ("windows", "Darwin", "arm64", False),
            ("windows", "Linux", "x86_64", False),
            ("linux", "Linux", "x86_64", True),
            ("linux", "Linux", "aarch64", False),
            ("linux", "Darwin", "arm64", False),
            ("linux", "Windows", "amd64", False),
            ("android", "Darwin", "arm64", True),
            ("android", "Linux", "x86_64", True),
            ("android", "Linux", "aarch64", True),
            ("android", "Windows", "amd64", True),
        ],
    )
    def test_check_host(self, target, system, machine, allowed):
        backend = get_platform(target)
        if allowed:
            backend.check_host(host_system=system, host_machine=machine)
            return
        with pytest.raises(HostCapabilityError):
            backend.check_host(host_system=system, host_machine=machine)

    def test_a_pi_host_is_told_to_cross_build(self):
        with pytest.raises(HostCapabilityError) as info:
            get_platform("linux").check_host(
                host_system="Linux", host_machine="aarch64"
            )
        message = str(info.value)
        assert "x86_64 Linux host" in message
        assert "'aarch64'" in message
        assert "Raspberry Pi" in message

    def test_the_os_rule_is_checked_first(self):
        """Linux on Windows names the OS, not the CPU."""
        with pytest.raises(HostCapabilityError, match="requires a Linux host"):
            get_platform("linux").check_host(
                host_system="Windows", host_machine="amd64"
            )

    def test_capabilities_publishes_the_cpu_rule(self):
        machines = {p.name: p.host_machines for p in collect().platforms}
        assert machines == {
            "ios": (),
            "macos": (),
            "linux": ("x86_64",),
            "windows": (),
            "android": (),
        }


class TestRequireHost:
    def test_classified_as_host_incapable(self, host):
        host("Windows", "amd64")
        with pytest.raises(ToolchainError) as info:
            _platform.require_host(get_platform("ios"))
        assert info.value.code == diagnostics.HOST_INCAPABLE
        assert info.value.exit_code == exit_codes.ENVIRONMENT_ERROR
        assert "requires macOS with Xcode" in str(info.value)
        assert "Windows" in str(info.value)  # names the host it actually found

    def test_capable_host_passes(self, host):
        host("Darwin", "arm64")
        _platform.require_host(get_platform("ios"))  # must not raise


class TestEveryTargetVerbIsGated:
    @pytest.mark.parametrize("verb", GATED_VERBS)
    def test_ios_off_macos(self, verb, host, project):
        host("Linux", "x86_64")
        result = CliRunner().invoke(main, [verb, "-p", "ios"])
        assert result.exit_code == exit_codes.ENVIRONMENT_ERROR, result.output
        assert "requires macOS with Xcode" in result.output

    @pytest.mark.parametrize("verb", [v for v in GATED_VERBS if v != "run"])
    def test_envelope_names_the_refused_target(self, verb, host, project):
        host("Windows", "amd64")
        result = CliRunner().invoke(main, [verb, "-p", "macos", "--json"])
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is False
        assert envelope["platform"] == "macos"
        (diagnostic,) = envelope["diagnostics"]
        assert diagnostic["code"] == diagnostics.HOST_INCAPABLE

    @pytest.mark.parametrize(
        ("target", "system", "machine"),
        [
            # Desktop locks used to resolve off-host; they no longer do.
            ("macos", "Windows", "amd64"),
            ("linux", "Windows", "amd64"),
            ("windows", "Darwin", "arm64"),
            ("linux", "Linux", "aarch64"),
        ],
    )
    def test_lock_follows_the_table(self, target, system, machine, host, project):
        host(system, machine)
        result = CliRunner().invoke(main, ["lock", "-p", target])
        assert result.exit_code == exit_codes.ENVIRONMENT_ERROR, result.output

    def test_build_on_a_pi_is_refused(self, host, project):
        host("Linux", "aarch64")
        result = CliRunner().invoke(main, ["build", "-p", "linux"])
        assert result.exit_code == exit_codes.ENVIRONMENT_ERROR, result.output
        assert "Raspberry Pi" in result.output

    def test_android_is_never_refused(self, host, project):
        host("Linux", "aarch64")
        result = CliRunner().invoke(main, ["status", "-p", "android", "--json"])
        envelope = json.loads(result.stdout)
        codes = [d["code"] for d in envelope["diagnostics"]]
        assert diagnostics.HOST_INCAPABLE not in codes


class TestUngatedVerbs:
    def test_init_writes_every_platform_on_any_host(self, host, project):
        host("Linux", "x86_64")
        targets = ["ios", "macos", "windows", "linux", "android"]
        args = ["init"] + [arg for t in targets for arg in ("-p", t)]
        result = CliRunner().invoke(main, args)
        assert result.exit_code == 0, result.output
        text = (project / "pyproject.toml").read_text(encoding="utf-8")
        for target in targets:
            assert f"[tool.kivy.{target}]" in text

    def test_doctor_explains_instead_of_refusing(self, host, project, monkeypatch):
        host("Windows", "amd64")
        monkeypatch.setattr(get_platform("ios"), "doctor", lambda cwd, **kw: [])
        result = CliRunner().invoke(main, ["doctor", "-p", "ios", "--json"])
        envelope = json.loads(result.stdout)
        assert envelope["platform"] == "ios"
        codes = [d["code"] for d in envelope["diagnostics"]]
        assert diagnostics.HOST_INCAPABLE not in codes

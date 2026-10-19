"""``KF-IOS-KIVY-UNSUPPORTED``: Kivy 2.x refused on iOS (#109).

kivyforge builds Kivy 3 only on iOS, and the mobile wheel index serves no Kivy
2.x iOS wheel, so a project that required 2.x used to fail inside pip's
resolver with pip's wording and nothing said that 2.x is unsupported. Two
checks now say so (``ios-compat-package-proposal.md``, stage 0): ``lock``
refuses a ``kivy`` requirement that admits no 3.x release before resolving and
a resolved ``kivy`` below ``3.0.0.dev0`` after; ``build`` applies the second to
the lock it reads. Both checks, both verbs, both outputs. No network, no
toolchain: the resolver is the hermetic fake, and ``build`` fails before it
stages anything.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli import lock as lock_cli
from kivyforge.cli._common import ToolchainError
from kivyforge.cli.build import build
from kivyforge.cli.lock import lock
from kivyforge.config import load_config_from_text
from kivyforge.lock.model import LockedPackage, LockedWheel
from kivyforge.platforms.ios import cli as ios_cli
from kivyforge.platforms.ios.lock import (
    BuildError,
    KivyUnsupported,
    Lockfile,
    PythonXcframework,
    build_lockfile,
    check_kivy_supported,
    dumps,
)
from kivyforge.platforms.ios.lock.builder import check_kivy_requirements
from kivyforge.report import diagnostics, exit_codes
from kivyforge.report.failures import ClassifiedError
from tests.lock_hash import inputs_sha
from tests.platforms.ios.lock.conftest import FakePythonProvider, FakeResolver

CODE = "KF-IOS-KIVY-UNSUPPORTED"
SENTENCE = "Kivy 2.x is not supported on iOS"


def _pyproject(kivy: str) -> str:
    # json.dumps gives a double-quoted TOML string, which keeps a marker's own
    # double quotes legal.
    return (
        textwrap.dedent(
            f"""
            [project]
            name = "myapp"
            version = "1.0.0"
            requires-python = ">=3.15"
            dependencies = [{json.dumps(kivy)}]

            [tool.kivy]
            app_dir = "src"

            [tool.kivy.ios]
            schema_version = 1
            bundle_id = "org.example.myapp"
            deployment_target = "13.0"

            [tool.kivy.ios.python]
            version = "3.15.0"
            """
        ).strip()
        + "\n"
    )


def _build(kivy: str, resolver: FakeResolver | None = None):
    return build_lockfile(
        load_config_from_text(_pyproject(kivy)),
        resolver=resolver or FakeResolver(),
        python_provider=FakePythonProvider(),
    )


def _kivy_package(version: str) -> LockedPackage:
    name = f"kivy-{version}-cp315-cp315-ios_13_0_arm64_iphoneos.whl"
    return LockedPackage(
        name="kivy",
        version=version,
        wheels=(
            LockedWheel(
                name=name,
                url=f"https://example/{name}",
                path=None,
                sha256="a" * 64,
                upload_time=None,
                size=None,
            ),
        ),
        direct_requirement=True,
    )


class TestRequirement:
    """Before resolving: a ``kivy`` requirement that admits no 3.x release."""

    REFUSED = [
        "kivy<3",
        "kivy<3.0.0",
        "kivy<=2.3.1",
        "kivy==2.3.1",
        "kivy===2.3.1",
        "kivy==2.*",
        "kivy~=2.3",
        "kivy>=2.0,<3.0",
        "Kivy<3",
        'kivy<3; sys_platform == "ios"',
    ]
    ALLOWED = [
        "kivy",
        "kivy>=3.0,<4",
        "kivy==3.0.0",
        "kivy==3.*",
        "kivy~=3.0",
        "kivy<4",
        "kivy>=3.0.0.dev0",
        # Rejects only 2.3.1, not every 2.x: pip's problem if nothing is left.
        "kivy!=2.3.1",
        # ``<3.0.0a0`` admits ``3.0.0.dev0``: a pre-release cap keeps earlier
        # pre-releases (PEP 440), and that is still Kivy 3.
        "kivy<3.0.0a0",
        # Not an iOS requirement at all.
        'kivy<3; sys_platform != "ios"',
        "kivy[full]<4",
    ]

    @pytest.mark.parametrize("requirement", REFUSED)
    def test_refused_before_resolving(self, requirement):
        resolver = FakeResolver()
        with pytest.raises(KivyUnsupported) as info:
            _build(requirement, resolver)
        assert resolver.calls == [], "pip must not run for a 2.x-only requirement"
        assert SENTENCE in str(info.value)
        assert info.value.context == {"requirement": requirement}

    @pytest.mark.parametrize("requirement", ALLOWED)
    def test_allowed_requirement_resolves(self, requirement):
        resolver = FakeResolver()
        lock = _build(requirement, resolver)
        assert len(resolver.calls) == 1
        assert any(p.name == "kivy" for p in lock.packages)

    def test_other_packages_are_not_kivy(self):
        check_kivy_requirements(["kivymd<3", "kivy-garden<2"], python_version="3.15.0")

    def test_classification(self):
        """The code is the contract (AGENTS.md): exit 1, a configuration error."""
        with pytest.raises(KivyUnsupported) as info:
            _build("kivy<3")
        exc = info.value
        assert isinstance(exc, BuildError)
        assert isinstance(exc, ClassifiedError)
        assert exc.code == diagnostics.IOS_KIVY_UNSUPPORTED == CODE
        assert exc.exit_code == exit_codes.CONFIG_ERROR
        wrapped = ToolchainError.wrap(exc)
        assert wrapped.code == CODE
        assert wrapped.remediation.startswith("require Kivy 3")
        assert "kivy-ios serves Kivy 2.x" in str(exc)


class TestResolved:
    """After resolving: the index handed back a ``kivy`` below 3.0.0.dev0."""

    def test_resolved_2x_refused(self):
        with pytest.raises(KivyUnsupported) as info:
            _build("kivy", FakeResolver(kivy_version="2.3.1"))
        assert "the lock would pin kivy 2.3.1" in str(info.value)
        assert SENTENCE in str(info.value)
        assert info.value.context == {"version": "2.3.1"}

    @pytest.mark.parametrize("version", ["3.0.0.dev0", "3.0.0rc1", "3.0.0", "3.1.2"])
    def test_resolved_3x_locks(self, version):
        lock = _build("kivy", FakeResolver(kivy_version=version))
        kivy = next(p for p in lock.packages if p.name == "kivy")
        assert kivy.version == version

    def test_no_kivy_passes(self):
        """An app that does not use Kivy has nothing to check."""
        check_kivy_supported(())
        check_kivy_supported([_kivy_package("3.0.0")])

    def test_lock_check_names_the_file(self):
        with pytest.raises(
            KivyUnsupported, match=r"^pylock\.ios\.toml pins kivy 2\.3\.1"
        ):
            check_kivy_supported([_kivy_package("2.3.1")], lockfile="pylock.ios.toml")


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def hermetic_lock(monkeypatch):
    """Route ``kivyforge lock -p ios`` through the fakes; returns the installer.

    Call it with the ``kivy`` version the fake index should serve.
    """

    def install(kivy_version: str = "3.0.0") -> FakeResolver:
        resolver = FakeResolver(kivy_version=kivy_version)
        provider = FakePythonProvider()
        real_build = lock_cli.build_lockfile

        def fake_build(config, **kwargs):
            kwargs.update(resolver=resolver, python_provider=provider)
            return real_build(config, **kwargs)

        monkeypatch.setattr(lock_cli, "build_lockfile", fake_build)
        return resolver

    return install


class TestLockCli:
    def test_human(self, runner, tmp_path, hermetic_lock):
        hermetic_lock()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            Path(fs, "pyproject.toml").write_text(_pyproject("kivy<3"))
            result = runner.invoke(lock, ["-p", "ios"])
            assert result.exit_code == exit_codes.CONFIG_ERROR, result.output
            assert "requires 'kivy<3'" in result.output
            assert SENTENCE in result.output
            assert "Fix: require Kivy 3" in result.output
            assert not Path(fs, "pylock.ios.toml").exists()

    def test_json_requirement(self, runner, tmp_path, hermetic_lock):
        resolver = hermetic_lock()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            Path(fs, "pyproject.toml").write_text(_pyproject("kivy<3"))
            result = runner.invoke(lock, ["-p", "ios", "--json"])
            envelope = json.loads(result.stdout)  # one document, nothing else
            assert result.exit_code == exit_codes.CONFIG_ERROR
            assert envelope["command"] == "lock"
            assert envelope["platform"] == "ios"
            assert envelope["ok"] is False
            [diagnostic] = envelope["diagnostics"]
            assert diagnostic["code"] == CODE
            assert diagnostic["severity"] == "error"
            assert SENTENCE in diagnostic["message"]
            assert diagnostic["remediation"].startswith("require Kivy 3")
            assert diagnostic["context"] == {"requirement": "kivy<3"}
            assert resolver.calls == []
            assert not Path(fs, "pylock.ios.toml").exists()

    def test_json_resolved(self, runner, tmp_path, hermetic_lock):
        hermetic_lock(kivy_version="2.3.1")
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            Path(fs, "pyproject.toml").write_text(_pyproject("kivy"))
            result = runner.invoke(lock, ["-p", "ios", "--json"])
            envelope = json.loads(result.stdout)
            assert result.exit_code == exit_codes.CONFIG_ERROR
            assert envelope["ok"] is False
            [diagnostic] = envelope["diagnostics"]
            assert diagnostic["code"] == CODE
            assert diagnostic["context"] == {"version": "2.3.1"}
            assert not Path(fs, "pylock.ios.toml").exists()


def _write_project(fs: str, *, kivy_version: str) -> Path:
    """A project whose ``pyproject.toml`` allows Kivy 3 but whose lock pins 2.x.

    That is a lock written by hand, or by a kivyforge from before the check:
    in sync, so only the new check can refuse it.
    """
    root = Path(fs)
    pyproject = _pyproject("kivy")
    (root / "pyproject.toml").write_text(pyproject)
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hi')\n")
    lock = Lockfile(
        requires_python=">=3.15",
        packages=(_kivy_package(kivy_version),),
        python_xcframework=PythonXcframework(
            version="3.15.0", url="https://example/py.tar.gz", sha256="c" * 64
        ),
        kivyforge_version="3.0.0.dev0",
        generated_at="2026-01-01T00:00:00Z",
        lock_inputs_sha256=inputs_sha(pyproject, "ios"),
        tool_kivyforge_schema_version=1,
    )
    (root / "pylock.ios.toml").write_text(dumps(lock))
    return root


@pytest.fixture(autouse=True)
def no_staging(monkeypatch):
    """``build`` must refuse the lock before it touches the toolchain or disk."""

    def reached(*args, **kwargs):
        raise AssertionError("build staged the project despite a Kivy 2.x lock")

    monkeypatch.setattr(ios_cli, "create_staging", reached)
    monkeypatch.setattr(ios_cli, "default_simulator_arch", lambda: "arm64")


class TestBuildCli:
    def test_human(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs, kivy_version="2.3.1")
            result = runner.invoke(build, ["-p", "ios"])
            assert result.exit_code == exit_codes.CONFIG_ERROR, result.output
            assert "pylock.ios.toml pins kivy 2.3.1" in result.output
            assert SENTENCE in result.output
            assert "Fix: require Kivy 3" in result.output

    def test_json(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs, kivy_version="2.3.1")
            result = runner.invoke(build, ["-p", "ios", "--json"])
            envelope = json.loads(result.stdout)  # one document, nothing else
            assert result.exit_code == exit_codes.CONFIG_ERROR
            assert envelope["command"] == "build"
            assert envelope["platform"] == "ios"
            assert envelope["ok"] is False
            # Nothing was produced, so nothing is reported (AGENTS.md).
            assert envelope["data"]["artifacts"] == []
            [diagnostic] = envelope["diagnostics"]
            assert diagnostic["code"] == CODE
            assert diagnostic["severity"] == "error"
            assert "pylock.ios.toml pins kivy 2.3.1" in diagnostic["message"]
            assert diagnostic["context"] == {"version": "2.3.1"}

    def test_kivy_3_lock_passes_the_check(self, runner, tmp_path):
        """The check, not something later, is what refused the 2.x lock."""
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs, kivy_version="3.0.0")
            result = runner.invoke(build, ["-p", "ios"])
            # The staging stub is what raised: the check let the build go on.
            assert isinstance(result.exception, AssertionError)
            assert CODE not in result.output
            assert SENTENCE not in result.output

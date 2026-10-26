"""Re-resolving with the existing lock as the preference (#126)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli.lock import lock
from kivyforge.lock.model import LockedPackage
from kivyforge.lock.prefer import (
    PinsConflict,
    constraint_args,
    preferred_pins,
    resolve_preferring,
)
from kivyforge.report import diagnostics, exit_codes
from tests.platforms.linux.lock.conftest import FakeLinuxResolver, FakeRuntimeProvider


def _locked(name: str, version: str) -> LockedPackage:
    return LockedPackage(name=name, version=version, wheels=())


class _Boom(Exception):
    pass


class TestPreferredPins:
    def test_every_locked_version_is_kept(self):
        locked = [_locked("Kivy", "2.3.1"), _locked("more_itertools", "10.5.0")]
        assert preferred_pins(locked, ["kivy>=2.3"]) == {
            "kivy": "2.3.1",
            "more-itertools": "10.5.0",
        }

    def test_a_direct_requirement_that_excludes_its_pin_releases_it(self):
        locked = [_locked("kivy", "2.3.1"), _locked("pyjnius", "1.6.1")]
        assert preferred_pins(locked, ["kivy>=2.4", "pyjnius"]) == {"pyjnius": "1.6.1"}

    def test_a_pre_release_pin_still_satisfies_its_range(self):
        locked = [_locked("kivy", "3.0.0.dev202610051055")]
        assert preferred_pins(locked, ["kivy>=3.0.0.dev0"]) == {
            "kivy": "3.0.0.dev202610051055"
        }


class TestConstraintArgs:
    def test_no_pins_no_arguments(self, tmp_path):
        assert constraint_args(tmp_path, {}) == []
        assert list(tmp_path.iterdir()) == []

    def test_pins_become_a_constraints_file(self, tmp_path):
        args = constraint_args(tmp_path, {"kivy": "2.3.1", "attrs": "24.1.0"})
        assert args[0] == "-c"
        text = Path(args[1]).read_text(encoding="utf-8")
        assert text == "attrs==24.1.0\nkivy==2.3.1\n"


class TestResolvePreferring:
    def test_the_pins_are_used_when_they_resolve(self):
        seen = []

        def resolve(pins):
            seen.append(dict(pins))
            return "resolved"

        assert (
            resolve_preferring(
                resolve, {"kivy": "2.3.1"}, errors=(_Boom,), platform="linux"
            )
            == "resolved"
        )
        assert seen == [{"kivy": "2.3.1"}]

    def test_pins_that_conflict_raise_pins_conflict(self):
        def resolve(pins):
            if pins:
                raise _Boom("Cannot install kivy==2.3.1 and kivy>=2.4")
            return "fine without pins"

        with pytest.raises(PinsConflict) as info:
            resolve_preferring(
                resolve, {"kivy": "2.3.1"}, errors=(_Boom,), platform="linux"
            )
        assert info.value.code == diagnostics.LOCK_PINS_CONFLICT
        assert info.value.exit_code == exit_codes.CONFIG_ERROR
        message = str(info.value)
        assert "kivyforge lock -p linux --update" in message
        assert "Cannot install kivy==2.3.1" in message
        message.encode("cp1252")  # reaches a redirected Windows console

    def test_a_failure_without_pins_is_reported_as_itself(self):
        def resolve(pins):
            raise _Boom("no wheel for 'kivy'" + (" (pinned)" if pins else ""))

        with pytest.raises(_Boom, match="^no wheel for 'kivy'$"):
            resolve_preferring(
                resolve, {"kivy": "2.3.1"}, errors=(_Boom,), platform="linux"
            )


# --------------------------------------------------------------------------- #
# Through the builder and the CLI
# --------------------------------------------------------------------------- #

PYPROJECT = textwrap.dedent(
    """
    [project]
    name = "myapp"
    version = "1.0.0"
    requires-python = ">=3.13"
    dependencies = ["kivy>=3.0,<4", "more-itertools>=10.5"]

    [tool.kivy]
    app_dir = "src"

    [tool.kivy.linux]
    schema_version = 1
    app_id = "org.example.myapp"

    [tool.kivy.linux.python]
    version = "3.13.14"
    """
)


@pytest.fixture
def fake_linux(monkeypatch):
    """`lock -p linux` with hermetic fakes; returns the resolver to inspect."""
    import kivyforge.platforms.linux.lock as linux_lock

    resolver = FakeLinuxResolver()
    real_build = linux_lock.build_linux_lockfile

    def build(config, **kwargs):
        kwargs.pop("on_warning", None)
        return real_build(
            config,
            resolver=resolver,
            runtime_provider=FakeRuntimeProvider(),
            **kwargs,
        )

    monkeypatch.setattr(linux_lock, "build_linux_lockfile", build)
    return resolver


class TestLockKeepsPins:
    def _project(self, fs: str) -> Path:
        path = Path(fs) / "pyproject.toml"
        path.write_text(PYPROJECT, encoding="utf-8")
        return path

    def test_a_first_lock_has_nothing_to_prefer(self, fake_linux, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            self._project(fs)
            result = runner.invoke(lock, ["-p", "linux"])
            assert result.exit_code == 0, result.output
        assert all(call["constraints"] == {} for call in fake_linux.calls)

    def test_an_input_change_re_resolves_preferring_the_lock(
        self, fake_linux, tmp_path
    ):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            path = self._project(fs)
            runner.invoke(lock, ["-p", "linux"])
            fake_linux.calls.clear()
            path.write_text(
                PYPROJECT.replace(
                    'app_id = "org.example.myapp"\n',
                    'app_id = "org.example.myapp"\nexclude = ["docutils"]\n',
                ),
                encoding="utf-8",
            )
            result = runner.invoke(lock, ["-p", "linux"])
            assert result.exit_code == 0, result.output
        constraints = fake_linux.calls[0]["constraints"]
        assert constraints == {"kivy": "3.0.0", "more-itertools": "10.5.0"}

    def test_update_prefers_nothing(self, fake_linux, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            self._project(fs)
            runner.invoke(lock, ["-p", "linux"])
            fake_linux.calls.clear()
            result = runner.invoke(lock, ["-p", "linux", "--update"])
            assert result.exit_code == 0, result.output
        assert fake_linux.calls
        assert all(call["constraints"] == {} for call in fake_linux.calls)

    def test_check_prefers_the_lock(self, fake_linux, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            self._project(fs)
            runner.invoke(lock, ["-p", "linux"])
            fake_linux.calls.clear()
            result = runner.invoke(lock, ["-p", "linux", "--check"])
            assert result.exit_code == 0, result.output
        assert fake_linux.calls[0]["constraints"] == {
            "kivy": "3.0.0",
            "more-itertools": "10.5.0",
        }

    def test_a_pins_conflict_is_classified(self, fake_linux, tmp_path, monkeypatch):
        from kivyforge.lock.wheelruntime.resolver import WheelResolverError

        real_resolve = fake_linux.resolve

        def resolve(requirements, **kwargs):
            if kwargs.get("constraints"):
                raise WheelResolverError("Cannot install kivy==3.0.0")
            return real_resolve(requirements, **kwargs)

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            path = self._project(fs)
            runner.invoke(lock, ["-p", "linux"])
            monkeypatch.setattr(fake_linux, "resolve", resolve)
            path.write_text(
                PYPROJECT.replace('"kivy>=3.0,<4"', '"kivy>=3.0,<5"'),
                encoding="utf-8",
            )
            result = runner.invoke(lock, ["-p", "linux", "--json"])
        assert result.exit_code == exit_codes.CONFIG_ERROR, result.output
        assert diagnostics.LOCK_PINS_CONFLICT in result.stdout
        assert "--update" in result.stdout

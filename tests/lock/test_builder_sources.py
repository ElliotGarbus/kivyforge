"""The source rules through a lock builder and the ``lock`` verb (#86).

Linux stands in for the wheel+runtime family; Android and iOS build their
policy the same way (``source_policy``), checked per platform below.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli.lock import lock
from kivyforge.lock.sources import SourceUnavailable
from kivyforge.report import diagnostics, exit_codes
from tests.lock.test_prefer import PYPROJECT
from tests.platforms.linux.lock.conftest import FakeLinuxResolver, FakeRuntimeProvider

WHEELHOUSE = PYPROJECT.replace(
    'app_id = "org.example.myapp"\n',
    'app_id = "org.example.myapp"\nfind_links = ["wheels"]\n',
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


def _project(fs: str, text: str = PYPROJECT, *, wheel: str | None = None) -> Path:
    path = Path(fs) / "pyproject.toml"
    path.write_text(text, encoding="utf-8")
    if wheel:
        (Path(fs) / "wheels").mkdir(exist_ok=True)
        (Path(fs) / "wheels" / wheel).write_bytes(b"")
    return path


class TestBuilderPassesThePolicy:
    def test_local_names_and_platform(self, fake_linux, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _project(fs, WHEELHOUSE, wheel="kivy-3.0.0-cp313-cp313-linux_x86_64.whl")
            result = runner.invoke(lock, ["-p", "linux"])
            assert result.exit_code == 0, result.output
        policy = fake_linux.calls[0]["sources"]
        assert policy.platform == "linux"
        assert policy.local_names == frozenset({"kivy"})
        assert policy.rank[-1].name == "pypi"

    def test_a_package_that_became_local_loses_only_its_pin(self, fake_linux, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            path = _project(fs)
            assert runner.invoke(lock, ["-p", "linux"]).exit_code == 0
            fake_linux.calls.clear()
            _project(fs, WHEELHOUSE, wheel="kivy-3.0.0-cp313-cp313-linux_x86_64.whl")
            assert path.read_text(encoding="utf-8") == WHEELHOUSE
            result = runner.invoke(lock, ["-p", "linux"])
            assert result.exit_code == 0, result.output
        # kivy was locked from PyPI and is now a local name: its pin goes, the
        # rest stay.
        assert fake_linux.calls[0]["constraints"] == {"more-itertools": "10.5.0"}


class TestSourceUnavailable:
    def test_is_classified_through_the_verb(self, fake_linux, tmp_path, monkeypatch):
        def resolve(requirements, **kwargs):
            raise SourceUnavailable(
                "kivy has wheels in [tool.kivy.linux].find_links ...",
                context={
                    "distribution": "kivy",
                    "source": "find_links",
                    "variant": "x",
                },
            )

        monkeypatch.setattr(fake_linux, "resolve", resolve)
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _project(fs)
            result = runner.invoke(lock, ["-p", "linux", "--json"])
        assert result.exit_code == exit_codes.CONFIG_ERROR, result.output
        assert diagnostics.LOCK_SOURCE_UNAVAILABLE in result.stdout

    def test_is_not_mistaken_for_a_pins_conflict(
        self, fake_linux, tmp_path, monkeypatch
    ):
        real_resolve = fake_linux.resolve
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _project(fs)
            assert runner.invoke(lock, ["-p", "linux"]).exit_code == 0

            def resolve(requirements, **kwargs):
                raise SourceUnavailable("no wheel", context={"distribution": "kivy"})

            monkeypatch.setattr(fake_linux, "resolve", resolve)
            _project(fs, PYPROJECT.replace('"kivy>=3.0,<4"', '"kivy>=3.0,<5"'))
            result = runner.invoke(lock, ["-p", "linux", "--json"])
        del real_resolve
        assert diagnostics.LOCK_SOURCE_UNAVAILABLE in result.stdout
        assert diagnostics.LOCK_PINS_CONFLICT not in result.stdout


class TestMobileBuildersPassThePolicy:
    def test_android(self, tmp_path):
        from kivyforge.platforms.android.lock.builder import build_lockfile
        from tests.platforms.android.lock.test_lock import (
            PYPROJECT as ANDROID,
        )
        from tests.platforms.android.lock.test_lock import (
            FakeProvider,
            FakeResolver,
            _config,
            _pkg,
        )

        (tmp_path / "wheels").mkdir()
        (
            tmp_path / "wheels" / "pyjnius-1.7.0-cp314-cp314-android_24_x86_64.whl"
        ).write_bytes(b"")
        text = ANDROID.replace(
            'package = "org.example.lockapp"',
            'package = "org.example.lockapp"\nfind_links = ["wheels"]',
        )
        resolver = FakeResolver([_pkg()])
        build_lockfile(
            _config(text),
            project_root=tmp_path,
            resolver=resolver,
            python_provider=FakeProvider(),
        )
        policy = resolver.calls[0][1]["sources"]
        assert policy.platform == "android"
        assert policy.local_names == frozenset({"pyjnius"})

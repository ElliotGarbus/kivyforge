"""Each backend carries the verb's version through its own internal calls.

``Config.version_required`` falls back to a *static* declaration when a config
was loaded without a version, so a path that forgot to forward an override
would silently build the declared version instead. Pyright catches a missing
``version`` at the ``Platform`` methods; these catch it one level down, where
``run`` and ``package`` call the backend's own ``build`` and load config again.
Android's equivalents are in ``tests/platforms/android/test_cli.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kivyforge.config.model import ResolvedVersion

OVERRIDE = ResolvedVersion("9.8.7+local", source="override")


class _Stop(Exception):
    pass


def _capture_build(monkeypatch, cli, name):
    seen: list[ResolvedVersion | None] = []

    def fake_build(project_root, **kwargs):
        seen.append(kwargs.get("version"))
        raise _Stop

    monkeypatch.setattr(cli, name, fake_build)
    return seen


def _capture_loads(monkeypatch, cli, name, result):
    seen: list[ResolvedVersion | None] = []

    def fake_load(root, *args):
        seen.append(args[-1] if args else None)
        return result

    monkeypatch.setattr(cli, name, fake_load)
    return seen


class TestRunForwards:
    @pytest.mark.parametrize(
        ("fixture", "build_name"),
        [
            ("macos", "macos_build"),
            ("linux", "linux_build"),
            ("windows", "windows_build"),
        ],
    )
    def test_run_passes_the_version_to_its_build(
        self, request, monkeypatch, desktop_project, fixture, build_name
    ):
        cli = request.getfixturevalue(fixture)
        if fixture == "windows":
            monkeypatch.setattr(cli, "_load_config", lambda root, version=None: None)
        seen = _capture_build(monkeypatch, cli, build_name)
        with pytest.raises(_Stop):
            getattr(cli, f"{fixture}_run")(
                desktop_project, version=OVERRIDE, arch=None, no_build=False
            )
        assert seen == [OVERRIDE]


class TestPackageForwards:
    def test_macos_package_and_its_inner_build_both_load_with_it(
        self, macos, monkeypatch, desktop_project
    ):
        config = SimpleNamespace(
            macos_required=SimpleNamespace(
                signing=SimpleNamespace(identity=None, notary_profile=None),
                entitlements={},
                include_files=(),
            )
        )
        seen = _capture_loads(monkeypatch, macos, "_load_config", config)
        macos.macos_package(
            desktop_project,
            version=OVERRIDE,
            arch=None,
            no_verify_lock=False,
            no_cache=False,
        )
        assert seen == [OVERRIDE, OVERRIDE]

    @pytest.mark.parametrize(
        ("fixture", "expected"),
        [
            ("linux", "dist/linux/demo-app-9.8.7_local-x86_64.AppImage"),
            ("windows", "dist/windows/My App-9.8.7_local-amd64"),
        ],
    )
    def test_package_loads_with_it_and_names_the_artifact(
        self, request, monkeypatch, desktop_project, fixture, expected
    ):
        cli = request.getfixturevalue(fixture)
        config = (
            SimpleNamespace(app_slug="demo-app", version_required=OVERRIDE)
            if fixture == "linux"
            else SimpleNamespace(
                display_name="My App",
                version_required=OVERRIDE,
                windows_required=SimpleNamespace(signing=None),
            )
        )
        arch = "x86_64" if fixture == "linux" else "amd64"
        if fixture == "windows":
            monkeypatch.setattr(cli, "_sign_launcher", lambda config, dest: False)
        seen = _capture_loads(
            monkeypatch,
            cli,
            "_load_and_verify",
            (config, SimpleNamespace(archs=(arch,))),
        )
        kwargs = {"fmt": "appimage"} if fixture == "linux" else {"fmt": "folder"}
        outcome = getattr(cli, f"{fixture}_package")(
            desktop_project,
            version=OVERRIDE,
            arch=None,
            no_verify_lock=False,
            no_cache=False,
            **kwargs,
        )
        assert seen == [OVERRIDE]
        assert [a.path.as_posix() for a in outcome.artifacts] == [expected]


class TestIos:
    @pytest.mark.parametrize("verb", ["ios_build", "ios_package"])
    def test_the_loaded_config_gets_the_version(
        self, ios, monkeypatch, desktop_project, verb
    ):
        seen: list[ResolvedVersion | None] = []

        def record(config, version):
            seen.append(version)
            return config

        monkeypatch.setattr(ios, "with_version", record)
        kwargs = dict(
            version=OVERRIDE,
            team_id=None,
            signing_identity=None,
            export_method="development",
            no_verify_lock=False,
            no_cache=False,
        )
        if verb == "ios_build":
            kwargs.update(target=None, arch=None)
        getattr(ios, verb)(desktop_project, **kwargs)
        assert seen == [OVERRIDE]

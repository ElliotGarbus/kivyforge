"""Per-backend stubs for driving ``build``/``package`` hermetically on any host.

Each fixture stubs one backend's toolchain collaborators (host gate, config and
lock loading, the bundler or xcodebuild/Gradle) and returns that backend's
``cli`` module, so a test can go through either the Click verb or the backend
function. Shared by the human-output and recorded-outcome tests, which must
exercise exactly the same runs.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.platforms.ios.xcodebuild_fake import fake_xcodebuild

_PYPROJECT = """\
[project]
name = "demo-app"
version = "1.2.3"

[tool.kivy]
app_dir = "src"

[tool.kivy.windows]
[tool.kivy.linux]
[tool.kivy.macos]
[tool.kivy.ios]
"""


@pytest.fixture
def desktop_project(tmp_path, monkeypatch):
    """A cwd whose pyproject declares every non-Android overlay; configs are stubbed."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def windows(desktop_project, monkeypatch):
    from kivyforge.platforms.windows import cli

    config = SimpleNamespace(
        display_name="My App",
        project=SimpleNamespace(version="1.2.3"),
        windows_required=SimpleNamespace(signing=None),
    )
    lock = SimpleNamespace(archs=("amd64",))

    def fake_build_onedir(config, lock, project_root, **kw):
        bundle = project_root / "build" / "windows" / "My App"
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "My App.exe").write_bytes(b"MZ")
        return bundle

    monkeypatch.setattr(cli, "_require_windows_host", lambda: None)
    monkeypatch.setattr(cli, "_load_and_verify", lambda root, nv: (config, lock))
    monkeypatch.setattr(cli, "build_onedir", fake_build_onedir)
    return cli


@pytest.fixture
def linux(desktop_project, monkeypatch):
    from kivyforge.platforms.linux import cli

    config = SimpleNamespace(
        app_slug="demo-app", project=SimpleNamespace(version="1.2.3")
    )
    lock = SimpleNamespace(archs=("x86_64",))

    def fake_build_appdir(config, lock, project_root, **kw):
        appdir = project_root / "build" / "linux" / "Demo App.AppDir"
        appdir.mkdir(parents=True, exist_ok=True)
        return appdir

    def fake_build_appimage(appdir, output, arch, *, echo=lambda *a: None, **kw):
        echo(f"Packaging {output.name} with appimagetool 1.9.0 ...")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"ELF")
        return output

    monkeypatch.setattr(cli, "_require_linux_host", lambda: None)
    monkeypatch.setattr(cli, "_load_and_verify", lambda root, nv: (config, lock))
    monkeypatch.setattr(cli, "build_appdir", fake_build_appdir)
    monkeypatch.setattr(cli, "build_appimage", fake_build_appimage)
    return cli


@pytest.fixture
def macos(desktop_project, monkeypatch):
    from kivyforge.platforms.macos import cli

    config = SimpleNamespace(
        macos_required=SimpleNamespace(
            signing=SimpleNamespace(identity=None, notary_profile=None),
            entitlements={},
        )
    )

    def fake_build_app_bundle(config, lock, project_root, **kw):
        app = project_root / "build" / "macos" / "Demo App.app"
        app.mkdir(parents=True, exist_ok=True)
        return app

    monkeypatch.setattr(cli, "_require_macos_host", lambda: None)
    monkeypatch.setattr(cli, "_load_config", lambda root: config)
    monkeypatch.setattr(cli, "_load_lock", lambda root: object())
    monkeypatch.setattr(cli, "is_in_sync", lambda lock, text: True)
    monkeypatch.setattr(cli, "build_app_bundle", fake_build_app_bundle)
    monkeypatch.setattr(cli, "sign_bundle_developer_id", lambda app, i, **kw: 12)
    monkeypatch.setattr(cli, "notarize_and_staple", lambda app, **kw: None)
    return cli


@pytest.fixture
def ios(desktop_project, monkeypatch):
    from kivyforge.platforms.ios import cli

    config = SimpleNamespace(
        app_slug="demo",
        ios=SimpleNamespace(
            deployment_target="13.0",
            python_build_settings=None,
            signing=SimpleNamespace(auto_signing=True, upload_symbols=False),
        ),
    )
    lock = SimpleNamespace(
        python_xcframework=SimpleNamespace(version="3.14.0"),
        swift_packages=(),
        xcframeworks=(),
    )

    def fake_create_staging(config, project_root, *, echo, **kw):
        echo("[stage] app sources")

    def fake_collect_artifacts(lock, layout, *, echo, **kw):
        echo("[collect] Python.xcframework")

    monkeypatch.setattr(cli, "_require_macos_host", lambda: None)
    monkeypatch.setattr(cli, "_load_config", lambda pyproject: config)
    monkeypatch.setattr(cli, "_load_lock", lambda root: lock)
    monkeypatch.setattr(cli, "is_in_sync", lambda lock, text: True)
    monkeypatch.setattr(cli, "preflight_signing", lambda *a, **k: "TEAM123456")
    monkeypatch.setattr(cli, "preflight_profile", lambda *a: None)
    monkeypatch.setattr(cli, "create_staging", fake_create_staging)
    monkeypatch.setattr(cli, "collect_artifacts", fake_collect_artifacts)
    monkeypatch.setattr(cli, "materialize_project", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_xcode_last_upgrade_check", lambda: None)
    monkeypatch.setattr(cli, "resolve_signing_identity", lambda *a, **k: None)
    monkeypatch.setattr(cli, "export_options_plist", lambda **kw: {})
    monkeypatch.setattr(cli, "run_command", fake_xcodebuild)
    monkeypatch.setattr(cli, "default_simulator_arch", lambda: "arm64")
    return cli


@pytest.fixture
def android(tmp_path, monkeypatch):
    """A real Android project and lock with the network/Gradle collaborators stubbed.

    Returns the project root (the cwd), not the module: Android's pipeline runs
    for real up to the stubs, so tests mostly want paths under it.
    """
    from kivyforge.platforms.android import cli
    from kivyforge.platforms.android import policy as policy_mod
    from kivyforge.platforms.android import signing as signing_mod
    from kivyforge.platforms.android.signing import ResolvedSigning
    from tests.platforms.android import test_cli as android_tests

    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text(android_tests.PYPROJECT, encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("# entry\n", encoding="utf-8")
    android_tests._write_lock(root)
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path / "fake-sdk"))
    android_tests._patch_collaborators(
        monkeypatch, downloads=tmp_path / "downloads", calls={}
    )
    # Pin the byte-compile decision: whether this host has a final CPython 3.14
    # must not decide what the test expects to see.
    monkeypatch.setattr(cli, "find_interpreter", lambda version: None)
    resolved = ResolvedSigning(
        keystore=Path("release.keystore"),
        key_alias="upload",
        store_password_env="KIVYFORGE_KEYSTORE_PASSWORD",
        key_password_env="KIVYFORGE_KEY_PASSWORD",
        v1_signing=True,
        v2_signing=True,
        v3_signing=True,
        v4_signing=True,
    )
    monkeypatch.setattr(signing_mod, "resolve_signing", lambda *a, **k: resolved)
    monkeypatch.setattr(
        policy_mod,
        "enforce_release_manifest",
        lambda xml, **kw: [SimpleNamespace(message="org.example.Receiver is exported")],
    )
    monkeypatch.chdir(root)
    return root

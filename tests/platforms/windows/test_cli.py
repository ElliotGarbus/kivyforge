"""Windows verb dispatch: build/run/package/status (hermetic)."""

from __future__ import annotations

import pytest

from kivyforge.cli._common import ToolchainError
from kivyforge.platforms.windows import cli

pytestmark = pytest.mark.requires_windows

_PYPROJECT = """\
[project]
name = "demo-app"
version = "1.2.3"

[tool.kivy]
app_dir = "src"
entry_point = "main"
display_name = "My App"

[tool.kivy.windows]
schema_version = 1
app_id = "Acme.MyApp"

[tool.kivy.windows.python]
version = "3.13"
"""


@pytest.fixture
def project(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# entry\n", encoding="utf-8")
    return tmp_path


class TestStatus:
    def test_reports_identity_and_state(self, project, capsys):
        cli.windows_status(project)
        out = capsys.readouterr().out
        assert "My App" in out
        assert "Acme.MyApp" in out
        assert "3.13" in out
        assert "missing" in out  # no lock yet
        assert "not built" in out


class TestBuild:
    def test_delegates_to_bundler(self, project, monkeypatch):
        seen = {}

        def _fake_build(config, lock, project_root, **kw):
            seen["kw"] = kw
            return project_root / "build" / "windows" / "My App"

        monkeypatch.setattr(cli, "build_onedir", _fake_build)
        monkeypatch.setattr(cli, "_load_and_verify", lambda root, nv: ("cfg", "lock"))
        monkeypatch.setattr(cli, "_require_windows_host", lambda: None)
        out = cli.windows_build(project, arch=None, no_verify_lock=True, no_cache=False)
        assert out.name == "My App"
        assert seen["kw"]["arch"] is None


class TestRun:
    def test_no_build_requires_existing_bundle(self, project, monkeypatch):
        monkeypatch.setattr(cli, "_require_windows_host", lambda: None)
        with pytest.raises(ToolchainError, match="no built bundle"):
            cli.windows_run(project, arch=None, no_build=True)

    def test_launches_built_exe(self, project, monkeypatch):
        monkeypatch.setattr(cli, "_require_windows_host", lambda: None)
        bundle = project / "build" / "windows" / "My App"
        bundle.mkdir(parents=True)
        (bundle / "My App.exe").write_bytes(b"MZ")

        launched = {}

        class _Proc:
            returncode = 0

        def _run(cmd, *a, **k):
            launched["cmd"] = cmd
            return _Proc()

        monkeypatch.setattr(cli.subprocess, "run", _run)
        cli.windows_run(project, arch=None, no_build=True)
        assert launched["cmd"][0].endswith("My App.exe")

    def test_nonzero_exit_raises(self, project, monkeypatch):
        monkeypatch.setattr(cli, "_require_windows_host", lambda: None)
        bundle = project / "build" / "windows" / "My App"
        bundle.mkdir(parents=True)
        (bundle / "My App.exe").write_bytes(b"MZ")

        class _Proc:
            returncode = 3

        monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: _Proc())
        with pytest.raises(ToolchainError, match="exited with status 3"):
            cli.windows_run(project, arch=None, no_build=True)


class TestPackage:
    class _Lock:
        archs = ("amd64",)

    def _package(self, project, built, monkeypatch):
        monkeypatch.setattr(cli, "_require_windows_host", lambda: None)
        monkeypatch.setattr(
            cli, "_load_and_verify", lambda root, nv: (_config(project), self._Lock())
        )
        monkeypatch.setattr(cli, "build_onedir", lambda *a, **k: built)
        return cli.windows_package(
            project, fmt="folder", arch=None, no_verify_lock=True, no_cache=False
        )

    def _canonical_bundle(self, project):
        built = project / "build" / "windows" / "My App"
        (built / "python").mkdir(parents=True)
        (built / "app").mkdir()
        (built / "bin").mkdir()
        (built / "My App.exe").write_bytes(b"MZ")
        (built / "_kivyforge_bootstrap.py").write_text("# boot\n")
        (built / "python" / "python.exe").write_bytes(b"MZ")
        (built / "app" / "main.py").write_text("# app\n")
        (built / "bin" / "sdk.dll").write_bytes(b"MZ")
        return built

    def test_folder_copies_to_dist(self, project, monkeypatch):
        built = self._canonical_bundle(project)
        dest = self._package(project, built, monkeypatch)
        # Folder name is the sanitized display_name ("My App"), not project.name.
        assert dest == project / "dist" / "windows" / "My App-1.2.3-amd64"
        assert (dest / "My App.exe").exists()
        assert (dest / "python" / "python.exe").exists()
        assert (dest / "app" / "main.py").exists()
        assert (dest / "bin" / "sdk.dll").exists()

    def test_preserves_build_tree(self, project, monkeypatch):
        built = self._canonical_bundle(project)
        self._package(project, built, monkeypatch)
        # The build tree stays put as the unsigned dev-run target.
        assert (built / "My App.exe").exists()
        assert (built / "python" / "python.exe").exists()

    def test_excludes_vcs_cache_and_editor_droppings(self, project, monkeypatch):
        built = self._canonical_bundle(project)
        # Junk that must never reach dist/.
        (built / ".git").mkdir()
        (built / ".git" / "config").write_text("[core]\n")
        (built / "app" / "__pycache__").mkdir()
        (built / "app" / "__pycache__" / "main.cpython-313.pyc").write_bytes(b"x")
        (built / "app" / "main.pyc").write_bytes(b"x")
        (built / ".DS_Store").write_bytes(b"x")
        (built / "Thumbs.db").write_bytes(b"x")
        (built / "app" / "notes.swp").write_bytes(b"x")

        dest = self._package(project, built, monkeypatch)

        # Allowlist: dist tree is exactly the canonical bundle content.
        got = {p.relative_to(dest).as_posix() for p in dest.rglob("*")}
        assert got == {
            "My App.exe",
            "_kivyforge_bootstrap.py",
            "python",
            "python/python.exe",
            "app",
            "app/main.py",
            "bin",
            "bin/sdk.dll",
        }

    def test_replaces_existing_dist_dir(self, project, monkeypatch):
        built = self._canonical_bundle(project)
        dest = project / "dist" / "windows" / "My App-1.2.3-amd64"
        dest.mkdir(parents=True)
        stale = dest / "STALE-from-old-build.txt"
        stale.write_text("old")

        self._package(project, built, monkeypatch)
        assert not stale.exists()  # old contents fully replaced
        assert (dest / "My App.exe").exists()

    def test_unconfigured_leaves_unsigned(self, project, monkeypatch, capsys):
        built = self._canonical_bundle(project)
        self._package(project, built, monkeypatch)
        assert "unsigned" in capsys.readouterr().out

    def test_signs_dist_launcher_when_configured(self, project, monkeypatch):
        built = self._canonical_bundle(project)
        signed: dict = {}

        class _Signer:
            configured = True

            def sign(self, paths):
                signed["paths"] = list(paths)

        monkeypatch.setattr(cli, "select_signer", lambda signing: _Signer())
        self._package(project, built, monkeypatch)
        dest = project / "dist" / "windows" / "My App-1.2.3-amd64"
        # Only the launcher in the dist copy is signed (build tree untouched).
        assert signed["paths"] == [dest / "My App.exe"]

    def test_signer_failure_rolls_back_to_previous(self, project, monkeypatch):
        from kivyforge.platforms.windows import WindowsBundleError

        # A previous, known-good package already sits at the dist destination.
        dest = project / "dist" / "windows" / "My App-1.2.3-amd64"
        dest.mkdir(parents=True)
        (dest / "GOOD-previous.txt").write_text("keep me")

        built = self._canonical_bundle(project)

        class _FailingSigner:
            configured = True

            def sign(self, paths):
                raise WindowsBundleError("no signing certificate found")

        monkeypatch.setattr(cli, "select_signer", lambda signing: _FailingSigner())
        with pytest.raises(ToolchainError, match="no signing certificate"):
            self._package(project, built, monkeypatch)

        # The signer failure rolls back: the previous package is restored and the
        # half-written new (unsigned) tree is gone.
        assert (dest / "GOOD-previous.txt").read_text() == "keep me"
        assert not (dest / "My App.exe").exists()


def _config(project):
    from kivyforge.config import load_config

    return load_config(
        project / "pyproject.toml", require_ios=False, require_windows=True
    )

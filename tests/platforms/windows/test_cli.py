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

    def test_builds_then_launches(self, project, monkeypatch):
        # Default (no --no-build): run builds first, then launches the result.
        monkeypatch.setattr(cli, "_require_windows_host", lambda: None)
        bundle = project / "build" / "windows" / "My App"
        bundle.mkdir(parents=True)
        (bundle / "My App.exe").write_bytes(b"MZ")
        monkeypatch.setattr(cli, "windows_build", lambda *a, **k: bundle)

        launched = {}

        class _Proc:
            returncode = 0

        def _run(cmd, *a, **k):
            launched["cmd"] = cmd
            return _Proc()

        monkeypatch.setattr(cli.subprocess, "run", _run)
        cli.windows_run(project, arch=None, no_build=False)
        assert launched["cmd"][0].endswith("My App.exe")


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


def _write_windows_lock(project, *, in_sync=True):
    from kivyforge.lock.reader import compute_pyproject_sha256
    from kivyforge.lock.wheelruntime.model import (
        PythonRuntime,
        RuntimeArtifact,
        WheelRuntimeLock,
    )
    from kivyforge.platforms.windows.lock import dumps

    text = (project / "pyproject.toml").read_text(encoding="utf-8")
    lock = WheelRuntimeLock(
        platform="windows",
        requires_python=">=3.13",
        packages=(),
        python_runtime=PythonRuntime(
            provider="python-build-standalone",
            version="3.13.14",
            artifacts=(
                RuntimeArtifact(arch="amd64", url="https://e/x.tar.gz", sha256="x"),
            ),
        ),
        archs=("amd64",),
        kivyforge_version="3.0.0",
        generated_at="2026-01-01T00:00:00Z",
        pyproject_sha256=(compute_pyproject_sha256(text) if in_sync else "0" * 64),
        tool_kivyforge_schema_version=1,
    )
    (project / "pylock.windows.toml").write_text(dumps(lock), encoding="utf-8")


class TestLockState:
    """status' lock-sync string covers each state (missing already in TestStatus)."""

    def test_in_sync(self, project):
        _write_windows_lock(project, in_sync=True)
        assert cli._lock_state(project) == "in sync"

    def test_out_of_date(self, project):
        _write_windows_lock(project, in_sync=False)
        assert "out of date" in cli._lock_state(project)

    def test_unreadable(self, project):
        (project / "pylock.windows.toml").write_text("{{ not toml", encoding="utf-8")
        assert "unreadable" in cli._lock_state(project)


class TestBuildStateAndHumanize:
    def test_not_built(self, tmp_path):
        assert cli._build_state(tmp_path / "nope") == "not built"

    def test_built_reports_age(self, tmp_path):
        d = tmp_path / "b"
        d.mkdir()
        assert "last built" in cli._build_state(d)

    def test_humanize_scales(self):
        assert cli._humanize(5) == "just now"
        assert cli._humanize(120) == "2 minutes ago"
        assert cli._humanize(3600) == "1 hour ago"
        assert cli._humanize(86400 * 2) == "2 days ago"


class TestHostAndLoaderErrors:
    """The thin translation wrappers turn domain errors into ToolchainError."""

    def test_require_host_translates_capability_error(self, monkeypatch):
        from kivyforge.platforms import HostCapabilityError

        class _Plat:
            def check_host_capability(self):
                raise HostCapabilityError("Windows onedir builds need a Windows host")

        monkeypatch.setattr(cli, "get_platform", lambda name: _Plat())
        with pytest.raises(ToolchainError, match="need a Windows host"):
            cli._require_windows_host()

    def test_load_config_translates_config_error(self, tmp_path):
        # A pyproject with no [tool.kivy.windows] table fails require_windows.
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname='x'\nversion='1'\n", encoding="utf-8"
        )
        with pytest.raises(ToolchainError):
            cli._load_config(tmp_path)

    def test_load_lock_missing_is_actionable(self, tmp_path):
        with pytest.raises(ToolchainError, match="lock -p windows"):
            cli._load_lock(tmp_path)

    def test_load_lock_unreadable(self, project):
        (project / "pylock.windows.toml").write_text("{{ not toml", encoding="utf-8")
        with pytest.raises(ToolchainError):
            cli._load_lock(project)


class TestLoadAndVerify:
    def test_in_sync_returns_config_and_lock(self, project):
        _write_windows_lock(project, in_sync=True)
        config, lock = cli._load_and_verify(project, False)
        assert lock.archs == ("amd64",)

    def test_stale_lock_raises(self, project):
        _write_windows_lock(project, in_sync=False)
        with pytest.raises(ToolchainError, match="out of date"):
            cli._load_and_verify(project, False)

    def test_no_verify_lock_allows_stale(self, project):
        _write_windows_lock(project, in_sync=False)
        _config_obj, lock = cli._load_and_verify(project, True)
        assert lock.archs == ("amd64",)


class TestAssembleAndArch:
    def test_assemble_translates_bundle_error(self, project, monkeypatch):
        from kivyforge.platforms.windows import WindowsBundleError

        def boom(*a, **k):
            raise WindowsBundleError("bundle assembly blew up")

        monkeypatch.setattr(cli, "build_onedir", boom)
        with pytest.raises(ToolchainError, match="bundle assembly blew up"):
            cli._assemble(
                _config(project), object(), project, arch=None, no_cache=False
            )

    def test_resolve_arch_translates_bundle_error(self):
        class _Lock:
            archs = ("amd64",)

        with pytest.raises(ToolchainError, match="not in the lock"):
            cli._resolve_arch(_Lock(), "arm64")


class TestStageDistCopy:
    def test_reserve_failure_translated(self, tmp_path, monkeypatch):
        from kivyforge.platforms.windows import WindowsBundleError

        def locked(target, *a, **k):
            raise WindowsBundleError("output is still open in another process")

        monkeypatch.setattr(cli, "reserve_previous", locked)
        with pytest.raises(ToolchainError, match="another process"):
            cli._stage_dist_copy(tmp_path / "src", tmp_path / "dist" / "App")

    def test_copy_failure_rolls_back(self, tmp_path, monkeypatch):
        src = tmp_path / "src"
        src.mkdir()
        (src / "f.txt").write_text("x")
        dest = tmp_path / "dist" / "App"

        def boom(*a, **k):
            raise RuntimeError("copytree died mid-copy")

        monkeypatch.setattr(cli.shutil, "copytree", boom)
        with pytest.raises(RuntimeError, match="copytree died"):
            cli._stage_dist_copy(src, dest)
        # The half-written destination is cleaned up (nothing was reserved).
        assert not dest.exists()

"""``create_staging``'s release-mode app copy + byte-compile (pyproject-ios)."""

from __future__ import annotations

import shutil

import pytest

from kivyforge.platforms.ios import staging as staging_mod
from kivyforge.platforms.ios.staging import StagingError, create_staging


class TestReleaseCopy:
    def test_release_materializes_a_real_copy_not_a_symlink(self, config, project_root):
        layout = create_staging(
            config, project_root, release=True, python_version="3.15.0"
        )
        assert layout.app.is_dir()
        assert not layout.app.is_symlink()
        assert (layout.app / "main.py").is_file()

    def test_dev_build_still_symlinks(self, config, project_root):
        layout = create_staging(config, project_root, release=False)
        assert layout.app.is_symlink()

    def test_release_replaces_a_prior_dev_symlink(self, config, project_root):
        create_staging(config, project_root, release=False)
        layout = create_staging(
            config, project_root, release=True, python_version="3.15.0"
        )
        assert layout.app.is_dir()
        assert not layout.app.is_symlink()

    def test_dev_build_after_release_replaces_the_copy_with_a_symlink(
        self, config, project_root
    ):
        create_staging(config, project_root, release=True, python_version="3.15.0")
        layout = create_staging(config, project_root, release=False)
        assert layout.app.is_symlink()

    def test_release_missing_app_dir_hard_fails(self, config, project_root):
        shutil.rmtree(project_root / "src")
        with pytest.raises(StagingError, match="app_dir"):
            create_staging(config, project_root, release=True, python_version="3.15.0")

    def test_release_without_python_version_is_a_programmer_error(
        self, config, project_root
    ):
        with pytest.raises(ValueError, match="python_version"):
            create_staging(config, project_root, release=True)

    def test_release_rebuild_starts_clean(self, config, project_root):
        # A byte-compiled copy is destructive (deletes .py once .pyc exists);
        # rerunning must never reuse a stale copy from a previous release build.
        layout = create_staging(
            config, project_root, release=True, python_version="3.15.0"
        )
        (layout.app / "STALE.txt").write_text("old")
        layout = create_staging(
            config, project_root, release=True, python_version="3.15.0"
        )
        assert not (layout.app / "STALE.txt").exists()
        assert (layout.app / "main.py").is_file()


class TestByteCompileResolution:
    """``byte_compile``/``strip_source`` (pyproject-ios §build_settings).

    ``select_compiler`` is stubbed here (it has its own tests in
    tests/bundle/test_pycompile.py); the interesting behavior at this layer is
    the tri-state resolution and the degrade-vs-error split.
    """

    def _select(self, monkeypatch, result):
        monkeypatch.setattr(staging_mod, "select_compiler", lambda **kw: result)

    def test_release_default_compiles_and_strips(
        self, make_config, project_root, monkeypatch
    ):
        self._select(monkeypatch, ("staged-python",))
        calls = []
        monkeypatch.setattr(
            staging_mod,
            "byte_compile",
            lambda trees, **kw: calls.append((trees, kw)),
        )
        create_staging(
            make_config(), project_root, release=True, python_version="3.15.0"
        )
        assert calls
        trees, kw = calls[0]
        assert trees[0].name == "app"
        assert kw["strip_source"] is True

    def test_false_never_compiles(self, make_config, project_root, monkeypatch):
        self._select(monkeypatch, ("staged-python",))
        calls = []
        monkeypatch.setattr(
            staging_mod,
            "byte_compile",
            lambda trees, **kw: calls.append((trees, kw)),
        )
        cfg = make_config(
            "[tool.kivy.ios.python.build_settings]\nbyte_compile = false\n"
        )
        create_staging(cfg, project_root, release=True, python_version="3.15.0")
        assert not calls

    def test_true_compiles_even_though_this_helper_is_release_only(
        self, make_config, project_root, monkeypatch
    ):
        # _compile_app_copy is unreachable outside release=True, so "release"
        # and explicit true behave identically here — this just documents that.
        self._select(monkeypatch, ())
        calls = []
        monkeypatch.setattr(
            staging_mod,
            "byte_compile",
            lambda trees, **kw: calls.append((trees, kw)),
        )
        cfg = make_config(
            "[tool.kivy.ios.python.build_settings]\nbyte_compile = true\n"
        )
        create_staging(cfg, project_root, release=True, python_version="3.15.0")
        assert calls

    def test_default_degrades_when_no_compiler_found(
        self, make_config, project_root, monkeypatch
    ):
        self._select(monkeypatch, None)
        messages = []
        layout = create_staging(
            make_config(),
            project_root,
            release=True,
            python_version="3.15.0",
            echo=messages.append,
        )
        assert any("not byte-compiling" in m for m in messages)
        # Degraded: the copy is untouched source, not partially compiled.
        assert (layout.app / "main.py").is_file()

    def test_explicit_true_fails_when_no_compiler_found(
        self, make_config, project_root, monkeypatch
    ):
        self._select(monkeypatch, None)
        cfg = make_config(
            "[tool.kivy.ios.python.build_settings]\nbyte_compile = true\n"
        )
        with pytest.raises(StagingError, match="byte_compile = true"):
            create_staging(cfg, project_root, release=True, python_version="3.15.0")

    def test_strip_source_removes_py_once_compiled(
        self, make_config, project_root, monkeypatch
    ):
        # Use the real in-process compiler (compiler=()) so this exercises the
        # actual byte_compile()/strip_sources() mechanics end to end, not a stub.
        self._select(monkeypatch, ())
        cfg = make_config(
            "[tool.kivy.ios.python.build_settings]\n"
            "byte_compile = true\nstrip_source = true\n"
        )
        layout = create_staging(
            cfg, project_root, release=True, python_version="3.15.0"
        )
        assert not (layout.app / "main.py").exists()
        assert (layout.app / "main.pyc").is_file()

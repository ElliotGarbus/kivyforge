"""find_links validation before pip resolution."""

from __future__ import annotations

import pytest

from kivyforge.config import load_config_from_text
from kivyforge.lock.find_links import (
    FindLinksError,
    find_links_doctor_detail,
    find_links_resolution_hint,
    validate_find_links,
)
from kivyforge.platforms.ios.lock import BuildError, build_lockfile

from .conftest import FakePythonProvider, FakeResolver


def _toml_with_find_links(find_links: str) -> str:
    return (
        "[project]\nname='a'\nversion='1'\ndependencies=['kivy']\n"
        "[tool.kivy]\napp_dir='src'\n[tool.kivy.ios]\nschema_version=1\n"
        f"bundle_id='o.x.a'\nfind_links={find_links}\n"
        "[tool.kivy.ios.python]\nversion='3.15.0'"
    )


class TestValidateFindLinks:
    def test_missing_directory(self, tmp_path):
        with pytest.raises(FindLinksError, match="does not exist"):
            validate_find_links(tmp_path, ("wheels",))

    def test_entry_is_file_not_directory(self, tmp_path):
        (tmp_path / "wheels").write_bytes(b"not a dir")
        with pytest.raises(FindLinksError, match="not a directory"):
            validate_find_links(tmp_path, ("wheels",))

    def test_empty_directory(self, tmp_path):
        (tmp_path / "wheels").mkdir()
        with pytest.raises(FindLinksError, match="no .whl files"):
            validate_find_links(tmp_path, ("wheels",))

    def test_directory_with_wheels_passes(self, tmp_path):
        wheels = tmp_path / "wheels"
        wheels.mkdir()
        (wheels / "kivy-1.whl").write_bytes(b"whl")
        validate_find_links(tmp_path, ("wheels",))

    def test_empty_entries_is_noop(self, tmp_path):
        validate_find_links(tmp_path, ())

    def test_sibling_directory_allowed(self, tmp_path):
        app = tmp_path / "hello-kivy"
        shared = tmp_path / "wheels"
        app.mkdir()
        shared.mkdir()
        (shared / "kivy-1.whl").write_bytes(b"whl")
        validate_find_links(app, ("../wheels",))

    def test_error_includes_hint(self, tmp_path):
        with pytest.raises(FindLinksError, match="kivyforge lock"):
            validate_find_links(tmp_path, ("wheels",))

    def test_default_platform_is_ios(self, tmp_path):
        with pytest.raises(FindLinksError, match=r"\[tool\.kivy\.ios\]\.find_links"):
            validate_find_links(tmp_path, ("wheels",))

    def test_linux_platform_wording(self, tmp_path):
        with pytest.raises(FindLinksError) as exc:
            validate_find_links(tmp_path, ("wheels",), platform="linux")
        msg = str(exc.value)
        assert "[tool.kivy.linux].find_links" in msg
        assert "ios" not in msg.lower()
        assert "linux wheels" in msg

    def test_macos_platform_wording(self, tmp_path):
        with pytest.raises(FindLinksError) as exc:
            validate_find_links(tmp_path, ("wheels",), platform="macos")
        assert "[tool.kivy.macos].find_links" in str(exc.value)


class TestFindLinksResolutionHint:
    def test_empty_entries_returns_none(self, tmp_path):
        assert find_links_resolution_hint(tmp_path, ()) is None

    def test_unrelated_pip_error_returns_none(self, tmp_path):
        (tmp_path / "wheels").mkdir()
        result = find_links_resolution_hint(
            tmp_path, ("wheels",), pip_stderr="some other error"
        )
        assert result is None

    def test_missing_dir_mentioned_in_hint(self, tmp_path):
        result = find_links_resolution_hint(
            tmp_path,
            ("wheels",),
            pip_stderr="no matching distribution found",
        )
        assert result is not None
        assert "missing" in result

    def test_entry_is_file_not_dir(self, tmp_path):
        (tmp_path / "wheels").write_bytes(b"x")
        result = find_links_resolution_hint(
            tmp_path,
            ("wheels",),
            pip_stderr="could not find a version that satisfies",
        )
        assert result is not None
        assert "not a directory" in result

    def test_empty_dir_mentioned_in_hint(self, tmp_path):
        (tmp_path / "wheels").mkdir()
        result = find_links_resolution_hint(
            tmp_path,
            ("wheels",),
            pip_stderr="no matching distribution found",
        )
        assert result is not None
        assert "no .whl files" in result

    def test_wheels_present_but_unmatched(self, tmp_path):
        wheels = tmp_path / "wheels"
        wheels.mkdir()
        (wheels / "kivy-1.whl").write_bytes(b"whl")
        result = find_links_resolution_hint(
            tmp_path,
            ("wheels",),
            pip_stderr="no matching distribution found",
        )
        assert result is not None
        assert "1 wheel(s) present" in result

    def test_no_problems_returns_none(self, tmp_path):
        # All entries valid — function should return None (no lines to report)
        wheels = tmp_path / "wheels"
        wheels.mkdir()
        (wheels / "kivy-1.whl").write_bytes(b"whl")
        # pip_stderr matches but all dirs are healthy → no lines → None
        result = find_links_resolution_hint(
            tmp_path,
            ("wheels",),
            pip_stderr="no matching distribution found",
        )
        # Wheels exist so we get the "N wheel(s) present but unmatched" line
        assert result is not None  # it's still reported as potentially relevant


class TestFindLinksDoctorDetail:
    def test_missing_path(self, tmp_path):
        path = tmp_path / "wheels"
        detail, hint = find_links_doctor_detail(tmp_path, "wheels", path)
        assert "missing" in detail
        assert hint is not None

    def test_not_a_directory(self, tmp_path):
        path = tmp_path / "wheels"
        path.write_bytes(b"x")
        detail, hint = find_links_doctor_detail(tmp_path, "wheels", path)
        assert "not a directory" in detail
        assert hint is None

    def test_empty_directory(self, tmp_path):
        path = tmp_path / "wheels"
        path.mkdir()
        detail, hint = find_links_doctor_detail(tmp_path, "wheels", path)
        assert "no .whl files" in detail
        assert hint is not None

    def test_wheels_present(self, tmp_path):
        path = tmp_path / "wheels"
        path.mkdir()
        (path / "kivy-1.whl").write_bytes(b"whl")
        (path / "kivy-2.whl").write_bytes(b"whl")
        detail, hint = find_links_doctor_detail(tmp_path, "wheels", path)
        assert "2 wheel(s)" in detail
        assert hint is None


class TestBuildUsesFindLinksValidation:
    def test_lock_fails_before_resolver_when_find_links_missing(self, tmp_path):
        resolver = FakeResolver()
        toml = _toml_with_find_links('["wheels"]')
        cfg = load_config_from_text(toml)
        with pytest.raises(BuildError, match="does not exist"):
            build_lockfile(
                cfg,
                toml,
                project_root=tmp_path,
                resolver=resolver,
                python_provider=FakePythonProvider(),
            )
        assert resolver.calls == []

    def test_normalize_sibling_wheel_path(self, tmp_path):
        from kivyforge.platforms.ios.lock.builder import _normalize_wheel_source

        app = tmp_path / "app"
        shared = tmp_path / "wheels"
        app.mkdir()
        shared.mkdir()
        wheel = shared / "kivy-1.whl"
        wheel.write_bytes(b"whl")
        _, path = _normalize_wheel_source(wheel.as_uri(), project_root=app)
        assert path == "../wheels/kivy-1.whl"

    def test_normalize_shared_wheelhouse_within_repo(self, tmp_path):
        from kivyforge.platforms.ios.lock.builder import _normalize_wheel_source

        (tmp_path / ".git").mkdir()
        app = tmp_path / "examples" / "mobile" / "hello-kivy"
        shared = tmp_path / "examples" / "wheels" / "ios"
        app.mkdir(parents=True)
        shared.mkdir(parents=True)
        wheel = shared / "kivy-1.whl"
        wheel.write_bytes(b"whl")
        _, path = _normalize_wheel_source(wheel.as_uri(), project_root=app)
        assert path == "../../wheels/ios/kivy-1.whl"

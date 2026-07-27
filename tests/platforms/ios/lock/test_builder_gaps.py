"""iOS lock builder edge cases not covered by ``test_builder.py``: the missing
``[tool.kivy.ios]`` guard, find_links validation/resolver-error hinting,
excluded-package dropping, wheel-source normalization (local path / file: URI
/ out-of-scope / missing SHA-256), slice-coverage parsing edge cases, and
``diff_summary``/``_req_name`` (spec 02).
"""

from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path

import pytest

from kivyforge.config import load_config_from_text
from kivyforge.platforms.ios.lock.builder import (
    BuildError,
    _req_name,
    build_lockfile,
    diff_summary,
)
from kivyforge.platforms.ios.lock.model import Lockfile, PythonXcframework
from kivyforge.platforms.ios.lock.resolver import (
    ResolvedPackage,
    ResolvedWheel,
    ResolverError,
)

_NO_IOS_TOML = (
    "[project]\nname='a'\nversion='1'\ndependencies=[]\n[tool.kivy]\napp_dir='src'\n"
)


def _toml(extra_ios: str = "") -> str:
    # ``extra_ios`` must land inside [tool.kivy.ios], i.e. *before* the
    # [tool.kivy.ios.python] sub-table header.
    return (
        "[project]\nname='a'\nversion='1'\ndependencies=['kivy']\n"
        "[tool.kivy]\napp_dir='src'\n[tool.kivy.ios]\nschema_version=1\n"
        f"bundle_id='o.x.a'\n{extra_ios}"
        "[tool.kivy.ios.python]\nversion='3.15.0'\n"
    )


_BASE = _toml()


def _build(toml, resolver, provider, **kw):
    cfg = load_config_from_text(toml)
    return build_lockfile(cfg, toml, resolver=resolver, python_provider=provider, **kw)


class TestMissingIosTable:
    def test_no_ios_table_rejected(self, fake_resolver, fake_python_provider):
        cfg = load_config_from_text(_NO_IOS_TOML, require_ios=False)
        with pytest.raises(BuildError, match="nothing to lock"):
            build_lockfile(
                cfg,
                _NO_IOS_TOML,
                resolver=fake_resolver,
                python_provider=fake_python_provider,
            )


class TestFindLinksValidation:
    def test_missing_find_links_dir_rejected(
        self, fake_resolver, fake_python_provider, tmp_path
    ):
        toml = _toml("find_links = ['missing-wheels']\n")
        cfg = load_config_from_text(toml)
        with pytest.raises(BuildError, match="does not exist"):
            build_lockfile(
                cfg,
                toml,
                resolver=fake_resolver,
                python_provider=fake_python_provider,
                project_root=tmp_path,
            )

    def test_resolver_error_without_hint(self, fake_python_provider, tmp_path):
        class Boom:
            def resolve(self, *a, **kw):
                raise ResolverError("pip exploded")

        cfg = load_config_from_text(_BASE)
        with pytest.raises(BuildError, match="pip exploded") as exc_info:
            build_lockfile(
                cfg,
                _BASE,
                resolver=Boom(),
                python_provider=fake_python_provider,
                project_root=tmp_path,
            )
        assert "find_links check" not in str(exc_info.value)

    def test_resolver_error_with_find_links_hint(self, fake_python_provider, tmp_path):
        wheels_dir = tmp_path / "wheels"
        wheels_dir.mkdir()
        (wheels_dir / "somepkg-1.0-py3-none-any.whl").write_bytes(b"x")
        toml = _toml("find_links = ['wheels']\n")

        class Boom:
            def resolve(self, *a, **kw):
                raise ResolverError("No matching distribution found for kivy")

        cfg = load_config_from_text(toml)
        with pytest.raises(BuildError, match="find_links check"):
            build_lockfile(
                cfg,
                toml,
                resolver=Boom(),
                python_provider=fake_python_provider,
                project_root=tmp_path,
            )


class TestExcludedPackagesDropped:
    def test_transitive_excluded_package_is_dropped(
        self, fake_resolver, fake_python_provider
    ):
        toml = _toml("exclude = ['more-itertools']\n")
        lock = _build(toml, fake_resolver, fake_python_provider)
        names = {p.name for p in lock.packages}
        assert "more-itertools" not in names
        assert "kivy" in names

    def test_excluding_a_direct_dependency_is_a_no_op(
        self, fake_resolver, fake_python_provider
    ):
        # Rule: you can't exclude what you explicitly depend on.
        toml = (
            "[project]\nname='a'\nversion='1'\ndependencies=['kivy']\n"
            "[tool.kivy]\napp_dir='src'\n[tool.kivy.ios]\nschema_version=1\n"
            "bundle_id='o.x.a'\nexclude=['kivy']\n"
            "[tool.kivy.ios.python]\nversion='3.15.0'"
        )
        lock = _build(toml, fake_resolver, fake_python_provider)
        assert "kivy" in {p.name for p in lock.packages}


class _LocalWheelResolver:
    def __init__(self, wheel_url: str, sha256: str = ""):
        self._url = wheel_url
        self._sha256 = sha256

    def resolve(self, requirements, **kwargs):
        if not requirements:
            return []
        return [
            ResolvedPackage(
                name="localpkg",
                version="1.0",
                wheels=[
                    ResolvedWheel(
                        filename="localpkg-1.0-py3-none-any.whl",
                        url=self._url,
                        sha256=self._sha256,
                    )
                ],
                requires_python=">=3.8",
            )
        ]


class TestWheelSourceNormalization:
    def test_local_plain_path_missing_sha256_is_hashed(
        self, fake_python_provider, tmp_path
    ):
        wheel = tmp_path / "localpkg-1.0-py3-none-any.whl"
        wheel.write_bytes(b"wheel contents")
        from kivyforge.artifacts.verify import sha256_file

        expected = sha256_file(wheel)

        toml = (
            "[project]\nname='a'\nversion='1'\ndependencies=['localpkg']\n"
            "[tool.kivy]\napp_dir='src'\n[tool.kivy.ios]\nschema_version=1\n"
            "bundle_id='o.x.a'\n[tool.kivy.ios.python]\nversion='3.15.0'"
        )
        cfg = load_config_from_text(toml)
        lock = build_lockfile(
            cfg,
            toml,
            resolver=_LocalWheelResolver(str(wheel)),
            python_provider=fake_python_provider,
            project_root=tmp_path,
        )
        (pkg,) = lock.packages
        (w,) = pkg.wheels
        assert w.path == "localpkg-1.0-py3-none-any.whl"
        assert w.url is None
        assert w.sha256 == expected

    def test_local_file_uri_resolved(self, fake_python_provider, tmp_path):
        wheel = tmp_path / "sub" / "localpkg-1.0-py3-none-any.whl"
        wheel.parent.mkdir()
        wheel.write_bytes(b"wheel contents")

        toml = (
            "[project]\nname='a'\nversion='1'\ndependencies=['localpkg']\n"
            "[tool.kivy]\napp_dir='src'\n[tool.kivy.ios]\nschema_version=1\n"
            "bundle_id='o.x.a'\n[tool.kivy.ios.python]\nversion='3.15.0'"
        )
        cfg = load_config_from_text(toml)
        lock = build_lockfile(
            cfg,
            toml,
            resolver=_LocalWheelResolver(wheel.as_uri()),
            python_provider=fake_python_provider,
            project_root=tmp_path,
        )
        (pkg,) = lock.packages
        (w,) = pkg.wheels
        assert w.path == "sub/localpkg-1.0-py3-none-any.whl"

    def test_remote_wheel_missing_sha256_rejected(self, fake_python_provider, tmp_path):
        toml = (
            "[project]\nname='a'\nversion='1'\ndependencies=['localpkg']\n"
            "[tool.kivy]\napp_dir='src'\n[tool.kivy.ios]\nschema_version=1\n"
            "bundle_id='o.x.a'\n[tool.kivy.ios.python]\nversion='3.15.0'"
        )
        cfg = load_config_from_text(toml)
        with pytest.raises(BuildError, match="could not determine SHA-256"):
            build_lockfile(
                cfg,
                toml,
                resolver=_LocalWheelResolver("https://example.com/localpkg.whl", ""),
                python_provider=fake_python_provider,
                project_root=tmp_path,
            )

    def test_wheel_outside_project_scope_rejected(self, fake_python_provider, tmp_path):
        project_root = tmp_path / "proj"
        project_root.mkdir()
        outside_dir = Path(tempfile.mkdtemp())
        try:
            wheel = outside_dir / "localpkg-1.0-py3-none-any.whl"
            wheel.write_bytes(b"x")
            toml = (
                "[project]\nname='a'\nversion='1'\ndependencies=['localpkg']\n"
                "[tool.kivy]\napp_dir='src'\n[tool.kivy.ios]\nschema_version=1\n"
                "bundle_id='o.x.a'\n[tool.kivy.ios.python]\nversion='3.15.0'"
            )
            cfg = load_config_from_text(toml)
            with pytest.raises(
                BuildError, match="outside the allowed find_links scope"
            ):
                build_lockfile(
                    cfg,
                    toml,
                    resolver=_LocalWheelResolver(str(wheel), "a" * 64),
                    python_provider=fake_python_provider,
                    project_root=project_root,
                )
        finally:
            import shutil

            shutil.rmtree(outside_dir, ignore_errors=True)


class _SliceEdgeCaseResolver:
    """One compiled package with wheels tuned to hit every branch of the
    slice-coverage scanner: a non-iOS tag, an unmatched-suffix tag, a
    malformed version segment, and an over-the-floor version."""

    def resolve(self, requirements, **kwargs):
        if not requirements:
            return []
        filenames = [
            "oddpkg-1.0-cp313-cp313-linux_x86_64.whl",
            "oddpkg-1.0-cp313-cp313-ios_13_0_watchos.whl",
            "oddpkg-1.0-cp313-cp313-ios_a_b_arm64_iphoneos.whl",
            "oddpkg-1.0-cp313-cp313-ios_99_0_x86_64_iphonesimulator.whl",
        ]
        wheels = [
            ResolvedWheel(filename=f, url=f"https://example/{f}", sha256="a" * 64)
            for f in filenames
        ]
        return [
            ResolvedPackage(
                name="oddpkg", version="1.0", wheels=wheels, requires_python=">=3.8"
            )
        ]


class TestSliceCoverageEdgeCases:
    def test_all_branches_still_report_missing_slices(self, fake_python_provider):
        toml = (
            "[project]\nname='a'\nversion='1'\ndependencies=['oddpkg']\n"
            "[tool.kivy]\napp_dir='src'\n[tool.kivy.ios]\nschema_version=1\n"
            "bundle_id='o.x.a'\n[tool.kivy.ios.python]\nversion='3.15.0'"
        )
        cfg = load_config_from_text(toml)
        with pytest.raises(BuildError, match="missing iOS wheel slice"):
            build_lockfile(
                cfg,
                toml,
                resolver=_SliceEdgeCaseResolver(),
                python_provider=fake_python_provider,
            )


class TestReqName:
    def test_invalid_requirement_string_returned_verbatim(self):
        assert _req_name("not! a valid !! requirement") == "not! a valid !! requirement"

    def test_valid_requirement_returns_name(self):
        assert _req_name("kivy>=3.0,<4") == "kivy"


class TestDiffSummary:
    def _lock(self, **overrides) -> Lockfile:
        base = Lockfile(
            requires_python=">=3.15",
            packages=(),
            python_xcframework=PythonXcframework(
                version="3.15.0", url="https://x/py.tar.gz", sha256="a" * 64
            ),
            kivyforge_version="0",
            generated_at="t",
            pyproject_sha256="b" * 64,
            tool_kivyforge_schema_version=1,
        )
        return dataclasses.replace(base, **overrides)

    def test_added_removed_unchanged_and_changed_packages(
        self, fake_resolver, fake_python_provider
    ):
        old_built = _build(_BASE, fake_resolver, fake_python_provider)
        (kivy,) = [p for p in old_built.packages if p.name == "kivy"]
        (mi,) = [p for p in old_built.packages if p.name == "more-itertools"]
        removed_pkg = dataclasses.replace(mi, name="removed-pkg")
        old = dataclasses.replace(old_built, packages=(kivy, mi, removed_pkg))
        extra = dataclasses.replace(mi, name="extra-pkg")
        new = dataclasses.replace(
            old,
            packages=(
                dataclasses.replace(kivy, version="99.0.0"),
                mi,  # unchanged version: hits the no-op branch
                extra,  # not in old: hits the "added" branch
                # removed_pkg dropped: hits the "removed" branch
            ),
        )
        lines = diff_summary(old, new)
        assert any("extra-pkg" in ln and "added" in ln for ln in lines)
        assert any("removed-pkg" in ln and "removed" in ln for ln in lines)
        assert any("kivy" in ln and "->" in ln for ln in lines)
        assert not any("more-itertools" in ln for ln in lines)

    def test_no_changes_yields_empty_summary(self):
        lock = self._lock()
        assert diff_summary(lock, lock) == []

    def test_python_xcframework_version_change_reported(self):
        old = self._lock()
        new = dataclasses.replace(
            old,
            python_xcframework=PythonXcframework(
                version="3.16.0", url="https://x/py.tar.gz", sha256="c" * 64
            ),
        )
        lines = diff_summary(old, new)
        assert any("Python.xcframework" in ln for ln in lines)

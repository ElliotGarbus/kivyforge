"""``[tool.kivy.macos.native.swift_packages]`` in ``pylock.macos.toml`` (#201).

The SPM resolver is faked: no ``swift`` toolchain and no network.
"""

from __future__ import annotations

import dataclasses

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.lock.inputs import lock_inputs_sha256
from kivyforge.platforms.ios.lock.spm import ResolvedSwiftPackage, SpmResolverError
from kivyforge.platforms.macos.lock import (
    MacosBuildError,
    build_macos_lockfile,
    diff_summary,
    dumps,
    loads,
    semantic_equal,
)

from .conftest import FakeMacosResolver, FakeRuntimeProvider

_SWIFT = (
    "\n[tool.kivy.macos.native.swift_packages]\n"
    'Promises = { url = "https://github.com/google/promises", '
    'requirement = { from = "2.4.0" }, products = ["Promises"] }\n'
    'Shim = { path = "swift-shims", products = ["Shim"] }\n'
)
_REV = "5d1d0d8836996aead64c0d76e2aaaa6c18a7d58c"


class FakeSpm:
    def __init__(self, *, fail: str | None = None) -> None:
        self.calls: list[dict] = []
        self._fail = fail

    def resolve(self, packages, *, project_root, offline=False):
        self.calls.append({"names": [p.name for p in packages], "offline": offline})
        if self._fail:
            raise SpmResolverError(self._fail)
        return [
            ResolvedSwiftPackage(name=p.name, revision=_REV, version="2.4.0")
            for p in packages
        ]


def _build(text, tmp_path, *, spm=None, **kw):
    cfg = load_config_from_text(
        text, require_ios=False, require_macos=True, project_root=tmp_path
    )
    return build_macos_lockfile(
        cfg,
        project_root=tmp_path,
        resolver=FakeMacosResolver(),
        runtime_provider=FakeRuntimeProvider(floor="11.0"),
        spm_resolver=spm,
        **kw,
    )


class TestLock:
    def test_remote_pinned_local_recorded(self, macos_pyproject, tmp_path):
        spm = FakeSpm()
        lock = _build(macos_pyproject + _SWIFT, tmp_path, spm=spm, offline=True)
        promises, shim = lock.swift_packages
        assert promises.name == "Promises"
        assert promises.revision == _REV and promises.version == "2.4.0"
        assert promises.requirement == {"from": "2.4.0"}
        assert shim.path == "swift-shims" and shim.revision is None
        # Only remote packages reach SPM, and --offline reaches it too.
        assert spm.calls == [{"names": ["Promises"], "offline": True}]

    def test_local_only_never_runs_swift(self, macos_pyproject, tmp_path):
        local = (
            "\n[tool.kivy.macos.native.swift_packages]\n"
            'Shim = { path = "swift-shims", products = ["Shim"] }\n'
        )
        spm = FakeSpm(fail="must not be called")
        (shim,) = _build(macos_pyproject + local, tmp_path, spm=spm).swift_packages
        assert shim.name == "Shim"
        assert spm.calls == []

    def test_resolver_failure_is_a_macos_build_error(self, macos_pyproject, tmp_path):
        with pytest.raises(MacosBuildError, match="could not resolve"):
            _build(
                macos_pyproject + _SWIFT,
                tmp_path,
                spm=FakeSpm(fail="swift could not resolve the packages"),
            )

    def test_none_declared(self, macos_pyproject, tmp_path):
        assert _build(macos_pyproject, tmp_path).swift_packages == ()

    def test_packages_are_a_lock_input(self, macos_pyproject, tmp_path):
        def sha(text):
            cfg = load_config_from_text(
                text, require_ios=False, require_macos=True, project_root=tmp_path
            )
            return lock_inputs_sha256(cfg, "macos")

        assert sha(macos_pyproject) != sha(macos_pyproject + _SWIFT)


class TestSerialize:
    def test_round_trips_without_link_or_embed(self, macos_pyproject, tmp_path):
        lock = _build(macos_pyproject + _SWIFT, tmp_path, spm=FakeSpm())
        text = dumps(lock)
        assert "[[tool.kivyforge.swift_packages]]" in text
        assert f'revision = "{_REV}"' in text
        assert 'requirement = { from = "2.4.0" }' in text
        # Xcode target settings are iOS's; a macOS lock does not carry them.
        assert "link =" not in text and "embed =" not in text
        again = loads(text)
        assert again.swift_packages == lock.swift_packages
        assert semantic_equal(again, lock)
        assert dumps(again) == text

    def test_no_table_without_packages(self, macos_pyproject, tmp_path):
        assert "swift_packages" not in dumps(_build(macos_pyproject, tmp_path))


class TestDiff:
    def test_reports_added_moved_and_removed(self, macos_pyproject, tmp_path):
        old = _build(macos_pyproject + _SWIFT, tmp_path, spm=FakeSpm())
        promises, shim = old.swift_packages
        moved = dataclasses.replace(promises, revision="f" * 40, version="2.4.1")
        new = dataclasses.replace(old, swift_packages=(moved,))
        lines = diff_summary(old, new)
        assert "  ~ swift package Promises: 2.4.0 -> 2.4.1" in lines
        assert "  - swift package Shim (local swift-shims) (removed)" in lines
        assert not semantic_equal(old, new)
        assert "  + swift package Shim (local swift-shims) (added)" in diff_summary(
            new, old
        )

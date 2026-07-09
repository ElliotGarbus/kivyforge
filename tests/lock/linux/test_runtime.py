"""Linux runtime provider selection (hermetic; fake metadata fetcher)."""

from __future__ import annotations

import pytest

from kivyforge.lock.linux.runtime import (
    LINUX_TRIPLES,
    PythonBuildStandaloneProvider,
    ReleaseAsset,
    RuntimeProviderError,
    get_runtime_provider,
    pbs_asset_name,
)


class FakeFetcher:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def fetch(self, version, arch_triple, *, offline=False):
        self.calls.append((version, arch_triple))
        return ReleaseAsset(
            url=f"https://example.com/{version}-{arch_triple}.tar.gz",
            sha256="d" * 64,
        )


class TestTriples:
    def test_x86_64_maps_to_gnu(self):
        assert LINUX_TRIPLES["x86_64"] == "x86_64-unknown-linux-gnu"


class TestPbsAssetName:
    def test_stem(self):
        assert (
            pbs_asset_name("3.15.0", "x86_64-unknown-linux-gnu")
            == "cpython-3.15.0+*-x86_64-unknown-linux-gnu-install_only.tar.gz"
        )


class TestProvider:
    def test_resolves_with_default_floor(self):
        fetcher = FakeFetcher()
        rt = PythonBuildStandaloneProvider(fetcher).resolve("3.15.0", ("x86_64",))
        assert rt.provider == "python-build-standalone"
        assert rt.version == "3.15.0"
        assert rt.floor == "2.17"
        assert {a.arch for a in rt.artifacts} == {"x86_64"}
        assert ("3.15.0", "x86_64-unknown-linux-gnu") in fetcher.calls

    def test_unknown_arch(self):
        with pytest.raises(RuntimeProviderError, match="no build for arch"):
            PythonBuildStandaloneProvider(FakeFetcher()).resolve("3.15.0", ("aarch64",))


class TestFactory:
    def test_get_default(self):
        assert isinstance(get_runtime_provider(), PythonBuildStandaloneProvider)

    def test_get_unknown(self):
        with pytest.raises(RuntimeProviderError, match="unknown runtime provider"):
            get_runtime_provider("bogus")

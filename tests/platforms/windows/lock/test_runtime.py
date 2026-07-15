"""Windows runtime provider selection (hermetic; fake metadata fetcher)."""

from __future__ import annotations

import pytest

from kivyforge.platforms.windows.lock.runtime import (
    WINDOWS_TRIPLES,
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
    def test_amd64_maps_to_msvc(self):
        assert WINDOWS_TRIPLES["amd64"] == "x86_64-pc-windows-msvc"


class TestPbsAssetName:
    def test_stem(self):
        assert (
            pbs_asset_name("3.13.14", "x86_64-pc-windows-msvc")
            == "cpython-3.13.14+*-x86_64-pc-windows-msvc-install_only.tar.gz"
        )


class TestProvider:
    def test_resolves(self):
        fetcher = FakeFetcher()
        rt = PythonBuildStandaloneProvider(fetcher).resolve("3.13.14", ("amd64",))
        assert rt.provider == "python-build-standalone"
        assert rt.version == "3.13.14"
        # Windows has no OS floor concept (unlike Linux glibc).
        assert rt.floor is None
        assert {a.arch for a in rt.artifacts} == {"amd64"}
        assert ("3.13.14", "x86_64-pc-windows-msvc") in fetcher.calls

    def test_unknown_arch(self):
        with pytest.raises(RuntimeProviderError, match="no build for arch"):
            PythonBuildStandaloneProvider(FakeFetcher()).resolve("3.13.14", ("arm64",))


class TestFactory:
    def test_get_default(self):
        assert isinstance(get_runtime_provider(), PythonBuildStandaloneProvider)

    def test_get_unknown(self):
        with pytest.raises(RuntimeProviderError, match="unknown runtime provider"):
            get_runtime_provider("bogus")

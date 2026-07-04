"""Runtime provider selection logic (hermetic; fake metadata fetcher)."""

from __future__ import annotations

import pytest

from kivyforge.lock.macos.runtime import (
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


class TestPbsAssetName:
    def test_stem(self):
        assert (
            pbs_asset_name("3.15.0", "aarch64-apple-darwin")
            == "cpython-3.15.0+*-aarch64-apple-darwin-install_only.tar.gz"
        )


class TestProvider:
    def test_resolves_per_arch(self):
        fetcher = FakeFetcher()
        provider = PythonBuildStandaloneProvider(fetcher, floor="11.0")
        rt = provider.resolve("3.15.0", ("arm64", "x86_64"))
        assert rt.provider == "python-build-standalone"
        assert rt.version == "3.15.0"
        assert rt.floor == "11.0"
        assert {a.arch for a in rt.artifacts} == {"arm64", "x86_64"}
        assert rt.artifact_for("arm64").sha256 == "d" * 64
        # Correct triples were requested.
        assert ("3.15.0", "aarch64-apple-darwin") in fetcher.calls
        assert ("3.15.0", "x86_64-apple-darwin") in fetcher.calls

    def test_thin_build(self):
        rt = PythonBuildStandaloneProvider(FakeFetcher()).resolve("3.15.0", ("arm64",))
        assert len(rt.artifacts) == 1
        assert rt.artifact_for("x86_64") is None

    def test_unknown_arch(self):
        with pytest.raises(RuntimeProviderError, match="no macOS build"):
            PythonBuildStandaloneProvider(FakeFetcher()).resolve("3.15.0", ("ppc64",))

    def test_no_archs(self):
        with pytest.raises(RuntimeProviderError, match="no architectures"):
            PythonBuildStandaloneProvider(FakeFetcher()).resolve("3.15.0", ())

    def test_fetcher_error_normalized(self):
        class Boom:
            def fetch(self, *a, **k):
                raise ValueError("kaboom")

        with pytest.raises(RuntimeProviderError, match="could not resolve"):
            PythonBuildStandaloneProvider(Boom()).resolve("3.15.0", ("arm64",))


class TestFactory:
    def test_get_default(self):
        assert isinstance(get_runtime_provider(), PythonBuildStandaloneProvider)

    def test_get_unknown(self):
        with pytest.raises(RuntimeProviderError, match="unknown runtime provider"):
            get_runtime_provider("bogus")

"""macOS runtime provider — python-build-standalone with darwin triples.

A one-line specialization of the generic :class:`PbsProvider`: it fixes the
arch→target-triple map to macOS's, and otherwise inherits the shared PBS
resolution + injectable metadata fetcher.
"""

from __future__ import annotations

from kivyforge.lock.wheelruntime.runtime import (
    MetadataFetcher,
    PbsProvider,
    ReleaseAsset,
    RuntimeProvider,
    RuntimeProviderError,
    pbs_asset_glob,
)

__all__ = [
    "DARWIN_TRIPLES",
    "PythonBuildStandaloneProvider",
    "ReleaseAsset",
    "RuntimeProvider",
    "RuntimeProviderError",
    "get_runtime_provider",
    "pbs_asset_name",
]

# kivyforge arch name -> PBS/LLVM darwin target triple.
DARWIN_TRIPLES = {
    "arm64": "aarch64-apple-darwin",
    "x86_64": "x86_64-apple-darwin",
}

# macOS-facing alias for the generic PBS asset glob helper.
pbs_asset_name = pbs_asset_glob


class PythonBuildStandaloneProvider(PbsProvider):
    """PBS provider fixed to macOS darwin triples."""

    def __init__(
        self,
        metadata_fetcher: MetadataFetcher | None = None,
        *,
        floor: str | None = None,
    ) -> None:
        super().__init__(DARWIN_TRIPLES, metadata_fetcher, floor=floor)


def get_runtime_provider(
    name: str = "python-build-standalone", **kwargs
) -> RuntimeProvider:
    if name in ("python-build-standalone", "pbs", "python_build_standalone"):
        return PythonBuildStandaloneProvider(**kwargs)
    raise RuntimeProviderError(
        f"unknown runtime provider {name!r} (expected python-build-standalone)"
    )

"""Windows runtime provider — python-build-standalone with the msvc triple.

A one-line specialization of the generic :class:`PbsProvider`: it fixes the
arch→target-triple map to Windows's ``x86_64-pc-windows-msvc`` build, and
otherwise inherits the shared PBS resolution + injectable metadata fetcher. The
Windows ``install_only`` archive normalizes under the same top-level ``python/``
tree as the darwin/linux ones (a normal relocatable prefix — ``python.exe`` at
the root, ``Lib/site-packages`` beneath it), which is load-bearing: staging must
**not** flatten, prune, or ``._pth``-isolate it (windows-spec).
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
    "PythonBuildStandaloneProvider",
    "ReleaseAsset",
    "RuntimeProvider",
    "RuntimeProviderError",
    "WINDOWS_TRIPLES",
    "get_runtime_provider",
    "pbs_asset_name",
]

# kivyforge arch name -> PBS/LLVM Windows target triple.
# arm64: add "arm64": "aarch64-pc-windows-msvc" (confirm PBS ships that
# install_only archive for the pinned CPython). The generic PbsProvider handles
# the rest — no other change here. See arm64-windows.md §3.
WINDOWS_TRIPLES = {
    "amd64": "x86_64-pc-windows-msvc",
}

# Windows-facing alias for the generic PBS asset glob helper.
pbs_asset_name = pbs_asset_glob


class PythonBuildStandaloneProvider(PbsProvider):
    """PBS provider fixed to the Windows msvc triple."""

    def __init__(
        self,
        metadata_fetcher: MetadataFetcher | None = None,
        *,
        floor: str | None = None,
    ) -> None:
        super().__init__(WINDOWS_TRIPLES, metadata_fetcher, floor=floor)


def get_runtime_provider(
    name: str = "python-build-standalone", **kwargs
) -> RuntimeProvider:
    if name in ("python-build-standalone", "pbs", "python_build_standalone"):
        return PythonBuildStandaloneProvider(**kwargs)
    raise RuntimeProviderError(
        f"unknown runtime provider {name!r} (expected python-build-standalone)"
    )

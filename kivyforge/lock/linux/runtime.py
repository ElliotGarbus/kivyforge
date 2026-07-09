"""Linux runtime provider — python-build-standalone with linux-gnu triples.

A one-line specialization of the generic :class:`PbsProvider`: it fixes the
arch→target-triple map to Linux's baseline ``*-unknown-linux-gnu`` builds (not
the ``_v2``/``_v3`` microarchitecture variants), and otherwise inherits the
shared PBS resolution + injectable metadata fetcher. The linux-gnu
``install_only`` archives share the same relocatable unix-prefix layout as the
darwin ones, so no patchelf pass is needed (linux-spec).
"""

from __future__ import annotations

from ..wheelruntime.runtime import (
    MetadataFetcher,
    PbsProvider,
    ReleaseAsset,
    RuntimeProvider,
    RuntimeProviderError,
    pbs_asset_glob,
)

__all__ = [
    "LINUX_TRIPLES",
    "PythonBuildStandaloneProvider",
    "ReleaseAsset",
    "RuntimeProvider",
    "RuntimeProviderError",
    "get_runtime_provider",
    "pbs_asset_name",
]

# The manylinux2014-class glibc floor PBS's linux-gnu builds inherit from their
# build host. Recorded on the runtime so the lock/doctor can state (and the
# builder can validate against) the artifact's host requirement.
DEFAULT_GLIBC_FLOOR = "2.17"

# kivyforge arch name -> PBS/LLVM linux target triple (baseline microarch).
LINUX_TRIPLES = {
    "x86_64": "x86_64-unknown-linux-gnu",
}

# Linux-facing alias for the generic PBS asset glob helper.
pbs_asset_name = pbs_asset_glob


class PythonBuildStandaloneProvider(PbsProvider):
    """PBS provider fixed to Linux gnu triples (glibc 2.17 floor by default)."""

    def __init__(
        self,
        metadata_fetcher: MetadataFetcher | None = None,
        *,
        floor: str | None = DEFAULT_GLIBC_FLOOR,
    ) -> None:
        super().__init__(LINUX_TRIPLES, metadata_fetcher, floor=floor)


def get_runtime_provider(
    name: str = "python-build-standalone", **kwargs
) -> RuntimeProvider:
    if name in ("python-build-standalone", "pbs", "python_build_standalone"):
        return PythonBuildStandaloneProvider(**kwargs)
    raise RuntimeProviderError(
        f"unknown runtime provider {name!r} (expected python-build-standalone)"
    )

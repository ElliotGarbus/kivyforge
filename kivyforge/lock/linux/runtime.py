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
#
# IMPORTANT — this is a *pinned assumption* about PBS's build baseline, not a
# value derived from inspecting the resolved artifact. PBS's ``install_only``
# archives carry no structured glibc metadata, and `kivyforge lock` records only
# the artifact URL + SHA-256 (it does not download the runtime), so there is
# nothing to derive from at lock time. This constant is versioned with kivyforge:
# if PBS ever raises its linux-gnu baseline above 2.17, THIS VALUE MUST BE
# BUMPED IN LOCKSTEP, otherwise the lock/doctor would advertise a floor the
# binary no longer meets. (A deeper, deferred safeguard would ELF-inspect the
# staged ``bin/python3`` version-needs at build time to prove the floor.)
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

"""Swappable macOS Python-runtime provider (macos-spec §"Python runtime").

The *source* of the bundled CPython is hidden behind ``RuntimeProvider`` so the
future switch from ``python-build-standalone`` (PBS) to python.org's official
relocatable framework is a re-lock, not a rewrite. The provider resolves a
CPython version + arch set to concrete, pinned per-arch archives; everything
downstream (the ``.app`` bundler, launcher, signing, doctor) depends only on the
canonical relocatable layout the archives normalize to, never on the provider.

PBS publishes per-architecture macOS ``install_only`` archives whose filenames
embed a dated release tag, so the concrete URL + SHA-256 cannot be constructed
from the version alone — they are discovered via a release-metadata lookup. That
network lookup is injectable (``MetadataFetcher``) so the selection logic here
stays hermetically testable; the real GitHub-backed fetcher is validated at the
phase stop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .model import MacosPythonRuntime, RuntimeArtifact

PROVIDER_NAME = "python-build-standalone"

# kivyforge arch name -> PBS/LLVM target triple prefix.
PBS_TRIPLE = {
    "arm64": "aarch64-apple-darwin",
    "x86_64": "x86_64-apple-darwin",
}


class RuntimeProviderError(Exception):
    """A runtime could not be resolved (unknown arch, missing asset, offline)."""


@dataclass(frozen=True)
class ReleaseAsset:
    """One resolved downloadable archive for a single arch."""

    url: str
    sha256: str
    archive_format: str = "tar.gz"


class MetadataFetcher(Protocol):
    """Resolves a (version, arch) to a concrete PBS asset (URL + SHA-256).

    Injectable so the provider's selection logic is testable without network.
    """

    def fetch(
        self, version: str, arch_triple: str, *, offline: bool = False
    ) -> ReleaseAsset: ...


class RuntimeProvider(Protocol):
    name: str

    def resolve(
        self, version: str, archs: tuple[str, ...], *, offline: bool = False
    ) -> MacosPythonRuntime: ...


class PythonBuildStandaloneProvider:
    """Resolves the bundled runtime from python-build-standalone (PBS)."""

    name = PROVIDER_NAME

    def __init__(
        self,
        metadata_fetcher: MetadataFetcher | None = None,
        *,
        floor: str | None = None,
    ) -> None:
        # A default GitHub-backed fetcher is created lazily so unit tests that
        # inject a fake never import the network layer.
        self._fetcher = metadata_fetcher
        self._floor = floor

    def resolve(
        self, version: str, archs: tuple[str, ...], *, offline: bool = False
    ) -> MacosPythonRuntime:
        if not archs:
            raise RuntimeProviderError("no architectures requested for the runtime")
        unknown = [a for a in archs if a not in PBS_TRIPLE]
        if unknown:
            valid = ", ".join(sorted(PBS_TRIPLE))
            raise RuntimeProviderError(
                f"python-build-standalone has no macOS build for arch(es) "
                f"{unknown}; valid values are: {valid}."
            )
        fetcher = self._fetcher or _default_fetcher()
        artifacts: list[RuntimeArtifact] = []
        for arch in archs:
            triple = PBS_TRIPLE[arch]
            try:
                asset = fetcher.fetch(version, triple, offline=offline)
            except RuntimeProviderError:
                raise
            except Exception as exc:  # noqa: BLE001 — normalize fetcher failures
                raise RuntimeProviderError(
                    f"could not resolve a python-build-standalone {version} build "
                    f"for {arch} ({triple}): {exc}"
                ) from exc
            artifacts.append(
                RuntimeArtifact(
                    arch=arch,
                    url=asset.url,
                    sha256=asset.sha256,
                    archive_format=asset.archive_format,
                )
            )
        return MacosPythonRuntime(
            provider=self.name,
            version=version,
            artifacts=tuple(artifacts),
            floor=self._floor,
        )


def pbs_asset_name(version: str, arch_triple: str) -> str:
    """The PBS ``install_only`` archive filename for a version + triple.

    PBS embeds a dated release tag in the filename (e.g.
    ``cpython-3.15.0+20250115-aarch64-apple-darwin-install_only.tar.gz``), so
    this returns the *tag-free* stem the metadata lookup matches against.
    """
    return f"cpython-{version}+*-{arch_triple}-install_only.tar.gz"


def _default_fetcher() -> MetadataFetcher:
    from .pbs_github import GithubPbsMetadataFetcher

    return GithubPbsMetadataFetcher()


def get_runtime_provider(name: str = PROVIDER_NAME, **kwargs) -> RuntimeProvider:
    if name in (PROVIDER_NAME, "pbs", "python_build_standalone"):
        return PythonBuildStandaloneProvider(**kwargs)
    raise RuntimeProviderError(
        f"unknown runtime provider {name!r} (expected {PROVIDER_NAME})"
    )

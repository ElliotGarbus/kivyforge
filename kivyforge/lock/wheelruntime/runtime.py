"""Swappable Python-runtime providers for the wheel+runtime family.

A ``RuntimeProvider`` resolves a CPython version + arch set to concrete, pinned
per-arch archives and normalizes them (downstream) to a canonical relocatable
layout the bundler consumes. Hiding the *source* behind this seam means switching
from ``python-build-standalone`` (PBS) to python.org's future relocatable builds
is a re-lock, not a rewrite.

``PbsProvider`` is the generic PBS implementation, parameterized by an
arch→target-triple map so each platform (macOS darwin triples now, Linux triples
later) is a one-line specialization. PBS embeds a dated release tag in every
asset filename, so the concrete URL + SHA-256 are discovered via an injectable
``MetadataFetcher`` (keeping the selection logic hermetically testable); the real
GitHub-backed fetcher is validated at the phase stop.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .model import PythonRuntime, RuntimeArtifact

PBS_PROVIDER_NAME = "python-build-standalone"

# Per-provider archive layout: the sub-directory an extracted runtime archive
# places its canonical relocatable CPython tree under. Staging (macOS/Linux)
# consults this by the runtime's recorded ``provider`` field instead of assuming
# a fixed layout, so the bundler depends only on the canonical contract and a
# new provider is registered here in one place (spec 07).
_PROVIDER_ARCHIVE_ROOTS = {
    PBS_PROVIDER_NAME: "python",
}


def normalized_runtime_root(provider: str, extracted: Path) -> Path:
    """Return the canonical relocatable CPython root within *extracted*.

    Encapsulates each provider's archive layout so bundlers never hard-code a
    specific provider's internals. Raises :class:`RuntimeProviderError` for an
    unregistered provider or an archive that does not match its expected layout.
    """
    try:
        root_name = _PROVIDER_ARCHIVE_ROOTS[provider]
    except KeyError:
        raise RuntimeProviderError(
            f"no runtime staging layout registered for provider {provider!r}; "
            f"known providers: {', '.join(sorted(_PROVIDER_ARCHIVE_ROOTS))}."
        ) from None
    root = extracted / root_name
    if not root.is_dir():
        raise RuntimeProviderError(
            f"the extracted runtime is missing the expected top-level "
            f"{root_name}/ directory required by the {provider!r} runtime provider."
        )
    return root


class RuntimeProviderError(Exception):
    """A runtime could not be resolved (unknown arch, missing asset, offline)."""


@dataclass(frozen=True)
class ReleaseAsset:
    """One resolved downloadable archive for a single arch."""

    url: str
    sha256: str
    archive_format: str = "tar.gz"


class MetadataFetcher(Protocol):
    """Resolves a (version, target triple) to a concrete asset (URL + SHA-256)."""

    def fetch(
        self, version: str, target_triple: str, *, offline: bool = False
    ) -> ReleaseAsset: ...


class RuntimeProvider(Protocol):
    name: str

    def resolve(
        self, version: str, archs: tuple[str, ...], *, offline: bool = False
    ) -> PythonRuntime: ...


class PbsProvider:
    """python-build-standalone provider, parameterized by an arch→triple map."""

    name = PBS_PROVIDER_NAME

    def __init__(
        self,
        triples: dict[str, str],
        metadata_fetcher: MetadataFetcher | None = None,
        *,
        floor: str | None = None,
    ) -> None:
        self._triples = triples
        # The default GitHub-backed fetcher is created lazily so tests that
        # inject a fake never import the network layer.
        self._fetcher = metadata_fetcher
        self._floor = floor

    def resolve(
        self, version: str, archs: tuple[str, ...], *, offline: bool = False
    ) -> PythonRuntime:
        if not archs:
            raise RuntimeProviderError("no architectures requested for the runtime")
        unknown = [a for a in archs if a not in self._triples]
        if unknown:
            valid = ", ".join(sorted(self._triples))
            raise RuntimeProviderError(
                f"python-build-standalone has no build for arch(es) {unknown}; "
                f"valid values are: {valid}."
            )
        fetcher = self._fetcher or _default_fetcher()
        artifacts: list[RuntimeArtifact] = []
        for arch in archs:
            triple = self._triples[arch]
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
        return PythonRuntime(
            provider=self.name,
            version=version,
            artifacts=tuple(artifacts),
            floor=self._floor,
        )


def pbs_asset_glob(version: str, target_triple: str) -> str:
    """The PBS ``install_only`` archive filename pattern for a version + triple.

    PBS embeds a dated release tag (e.g.
    ``cpython-3.15.0+20250115-aarch64-apple-darwin-install_only.tar.gz``); this
    returns the tag-globbed stem the metadata lookup matches.
    """
    return f"cpython-{version}+*-{target_triple}-install_only.tar.gz"


def _default_fetcher() -> MetadataFetcher:
    from .pbs_github import GithubPbsMetadataFetcher

    return GithubPbsMetadataFetcher()

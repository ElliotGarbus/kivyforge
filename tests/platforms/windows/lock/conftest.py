"""Hermetic fakes for Windows lock tests: no network, no pip subprocess."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from kivyforge.platforms.windows.lock import (
    ResolvedPackage,
    ResolvedWheel,
    RuntimeArtifact,
    WindowsPythonRuntime,
)


class FakeWindowsResolver:
    """Deterministic resolver: kivy + kivy_deps.sdl2 (compiled win_amd64) + pure dep.

    Implements the generic ``WheelResolver`` interface (resolves over
    ``variants``). ``drop_wheel`` omits kivy's win_amd64 wheel to exercise the
    coverage check. ``vendored`` sources kivy's wheel from the first
    ``find_links`` directory (a local path) instead of PyPI.
    """

    def __init__(self, *, drop_wheel: bool = False, vendored: bool = False):
        self.calls: list[dict] = []
        self._drop_wheel = drop_wheel
        self._vendored = vendored

    def resolve(
        self,
        requirements,
        *,
        python_version,
        variants,
        extra_index_urls,
        find_links=None,
        offline=False,
    ):
        self.calls.append(
            {
                "requirements": list(requirements),
                "python_version": python_version,
                "variants": tuple(variants),
                "archs": tuple(v.arch for v in variants),
                "request_tags": tuple(variants[0].request_tags) if variants else (),
                "extra_index_urls": list(extra_index_urls),
                "find_links": list(find_links or []),
                "offline": offline,
            }
        )
        if not requirements:
            return []
        abi = "cp" + "".join(python_version.split(".")[:2])
        kivy_wheels = []
        if not self._drop_wheel:
            fname = f"kivy-2.3.1-{abi}-{abi}-win_amd64.whl"
            if self._vendored and find_links:
                url = str(Path(find_links[0]) / fname)
            else:
                url = f"https://files.pythonhosted.org/packages/aa/{fname}"
            kivy_wheels.append(ResolvedWheel(filename=fname, url=url, sha256="a" * 64))
        kivy = ResolvedPackage(
            name="kivy",
            version="2.3.1",
            wheels=kivy_wheels,
            requires_python=">=3.8",
            dependencies=["kivy-deps-sdl2", "docutils"],
        )
        # kivy_deps.sdl2 is an ordinary compiled win_amd64 wheel (no special-case).
        sdl2 = ResolvedPackage(
            name="kivy-deps-sdl2",
            version="0.7.0",
            wheels=[
                ResolvedWheel(
                    filename=f"kivy_deps_sdl2-0.7.0-{abi}-{abi}-win_amd64.whl",
                    url="https://files.pythonhosted.org/packages/bb/kivy_deps_sdl2-0.7.0-win_amd64.whl",
                    sha256="b" * 64,
                )
            ],
            requires_python=">=3.8",
        )
        docutils = ResolvedPackage(
            name="docutils",
            version="0.21.2",
            wheels=[
                ResolvedWheel(
                    filename="docutils-0.21.2-py3-none-any.whl",
                    url="https://files.pythonhosted.org/packages/cc/docutils-0.21.2-py3-none-any.whl",
                    sha256="c" * 64,
                )
            ],
            requires_python=">=3.9",
        )
        return [kivy, sdl2, docutils]


class FakeRuntimeProvider:
    """Returns a pinned PBS-style runtime with one artifact per requested arch."""

    name = "python-build-standalone"

    def __init__(self, *, floor: str | None = None):
        self.calls: list[dict] = []
        self._floor = floor

    def resolve(self, version, archs, *, offline=False):
        self.calls.append(
            {"version": version, "archs": tuple(archs), "offline": offline}
        )
        artifacts = tuple(
            RuntimeArtifact(
                arch=arch,
                url=f"https://example.com/cpython-{version}-{arch}-windows.tar.gz",
                sha256="d" * 64,
            )
            for arch in archs
        )
        return WindowsPythonRuntime(
            provider=self.name,
            version=version,
            artifacts=artifacts,
            floor=self._floor,
        )


@pytest.fixture
def fake_windows_resolver():
    return FakeWindowsResolver()


@pytest.fixture
def fake_runtime_provider():
    return FakeRuntimeProvider()


@pytest.fixture
def windows_pyproject() -> str:
    return textwrap.dedent(
        """
        [project]
        name = "myapp"
        version = "1.0.0"
        requires-python = ">=3.13"
        dependencies = ["kivy>=2.3,<3", "docutils"]

        [tool.kivy]
        app_dir = "src"

        [tool.kivy.windows]
        schema_version = 1
        app_id = "Example.MyApp"

        [tool.kivy.windows.python]
        version = "3.13.14"
        """
    ).strip()

"""Hermetic fakes for macOS lock tests: no network, no pip subprocess."""

from __future__ import annotations

import textwrap

import pytest

from kivyforge.platforms.macos.lock import (
    MacosPythonRuntime,
    ResolvedPackage,
    ResolvedWheel,
    RuntimeArtifact,
)


class FakeMacosResolver:
    """Deterministic resolver: kivy (compiled, per-arch) + a pure-Python dep.

    Implements the generic ``WheelResolver`` interface (resolves over
    ``variants``). ``universal2=True`` returns a single universal2 wheel instead
    of per-arch wheels; ``drop_arch`` omits one arch to exercise the coverage
    check.
    """

    def __init__(self, *, universal2: bool = False, drop_arch: str | None = None):
        self.calls: list[dict] = []
        self._universal2 = universal2
        self._drop_arch = drop_arch

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
                "extra_index_urls": list(extra_index_urls),
                "find_links": list(find_links or []),
                "offline": offline,
            }
        )
        if not requirements:
            return []
        abi = "cp" + "".join(python_version.split(".")[:2])
        # Every variant's tag shares the same macosx_<floor> prefix.
        f = variants[0].platform_tag.split("_", 1)[1].rsplit("_", 1)[0]
        kivy_wheels = []
        if self._universal2:
            fname = f"kivy-3.0.0-{abi}-{abi}-macosx_{f}_universal2.whl"
            kivy_wheels.append(
                ResolvedWheel(
                    filename=fname,
                    url=f"https://files.pythonhosted.org/packages/aa/{fname}",
                    sha256="a" * 64,
                )
            )
        else:
            for variant in variants:
                if variant.arch == self._drop_arch:
                    continue
                fname = f"kivy-3.0.0-{abi}-{abi}-macosx_{f}_{variant.arch}.whl"
                kivy_wheels.append(
                    ResolvedWheel(
                        filename=fname,
                        url=f"https://files.pythonhosted.org/packages/aa/{fname}",
                        sha256="a" * 64,
                    )
                )
        kivy = ResolvedPackage(
            name="kivy",
            version="3.0.0",
            wheels=kivy_wheels,
            requires_python=">=3.10",
            dependencies=["more-itertools"],
        )
        mi = ResolvedPackage(
            name="more-itertools",
            version="10.5.0",
            wheels=[
                ResolvedWheel(
                    filename="more_itertools-10.5.0-py3-none-any.whl",
                    url="https://files.pythonhosted.org/packages/bb/more_itertools-10.5.0-py3-none-any.whl",
                    sha256="b" * 64,
                )
            ],
            requires_python=">=3.8",
        )
        return [kivy, mi]


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
                url=f"https://example.com/cpython-{version}-{arch}.tar.gz",
                sha256="c" * 64,
            )
            for arch in archs
        )
        return MacosPythonRuntime(
            provider=self.name,
            version=version,
            artifacts=artifacts,
            floor=self._floor,
        )


@pytest.fixture
def fake_macos_resolver():
    return FakeMacosResolver()


@pytest.fixture
def fake_runtime_provider():
    return FakeRuntimeProvider()


@pytest.fixture
def macos_pyproject() -> str:
    return textwrap.dedent(
        """
        [project]
        name = "myapp"
        version = "1.0.0"
        requires-python = ">=3.15"
        dependencies = ["kivy>=3.0,<4", "more-itertools>=10.5"]

        [tool.kivy]
        app_dir = "src"

        [tool.kivy.macos]
        schema_version = 1
        bundle_id = "org.example.myapp"

        [tool.kivy.macos.python]
        version = "3.15.0"
        """
    ).strip()

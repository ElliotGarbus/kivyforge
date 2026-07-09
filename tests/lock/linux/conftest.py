"""Hermetic fakes for Linux lock tests: no network, no pip subprocess."""

from __future__ import annotations

import textwrap

import pytest

from kivyforge.lock.linux import (
    LinuxPythonRuntime,
    ResolvedPackage,
    ResolvedWheel,
    RuntimeArtifact,
)


class FakeLinuxResolver:
    """Deterministic resolver: kivy (compiled manylinux) + a pure-Python dep.

    Implements the generic ``WheelResolver`` interface (resolves over
    ``variants``). ``drop_wheel`` omits kivy's manylinux wheel to exercise the
    coverage check. ``plain_linux`` returns a bare ``linux_x86_64`` tag.
    """

    def __init__(self, *, drop_wheel: bool = False, plain_linux: bool = False):
        self.calls: list[dict] = []
        self._drop_wheel = drop_wheel
        self._plain_linux = plain_linux

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
            if self._plain_linux:
                tag = "linux_x86_64"
            else:
                tag = "manylinux_2_17_x86_64.manylinux2014_x86_64"
            fname = f"kivy-3.0.0-{abi}-{abi}-{tag}.whl"
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

    def __init__(self, *, floor: str | None = "2.17"):
        self.calls: list[dict] = []
        self._floor = floor

    def resolve(self, version, archs, *, offline=False):
        self.calls.append(
            {"version": version, "archs": tuple(archs), "offline": offline}
        )
        artifacts = tuple(
            RuntimeArtifact(
                arch=arch,
                url=f"https://example.com/cpython-{version}-{arch}-linux.tar.gz",
                sha256="c" * 64,
            )
            for arch in archs
        )
        return LinuxPythonRuntime(
            provider=self.name,
            version=version,
            artifacts=artifacts,
            floor=self._floor,
        )


@pytest.fixture
def fake_linux_resolver():
    return FakeLinuxResolver()


@pytest.fixture
def fake_runtime_provider():
    return FakeRuntimeProvider()


@pytest.fixture
def linux_pyproject() -> str:
    return textwrap.dedent(
        """
        [project]
        name = "myapp"
        version = "1.0.0"
        requires-python = ">=3.15"
        dependencies = ["kivy>=3.0,<4", "more-itertools>=10.5"]

        [tool.kivy]
        app_dir = "src"

        [tool.kivy.linux]
        schema_version = 1
        app_id = "org.example.myapp"

        [tool.kivy.linux.python]
        version = "3.15.0"
        """
    ).strip()

"""Linux lock profile — the platform-specific inputs to the wheel+runtime core.

Linux variants are CPU architectures (``x86_64`` only this phase). Wheels use
manylinux platform tags; because pip does not expand the manylinux hierarchy
from a single explicit ``--platform`` (linux-spec spike), each variant requests
the full ladder of compatible tags at or below the glibc floor in one pip
invocation. The bundled runtime comes from python-build-standalone (linux-gnu).
Everything else — resolve/serialize/build orchestration — is the shared core.
"""

from __future__ import annotations

import re

from kivyforge.config.errors import ConfigError
from kivyforge.config.model import Config
from kivyforge.lock.wheelruntime.model import WheelRuntimeLock
from kivyforge.lock.wheelruntime.profile import PlatformLockProfile
from kivyforge.lock.wheelruntime.resolver import Variant
from kivyforge.lock.wheelruntime.runtime import RuntimeProvider

from .runtime import DEFAULT_GLIBC_FLOOR, PythonBuildStandaloneProvider

VALID_WHEEL_ARCHS = frozenset({"x86_64"})

# Legacy manylinux aliases and the perennial (PEP 600) glibc minor they map to.
_LEGACY_ALIASES = {5: "manylinux1", 12: "manylinux2010", 17: "manylinux2014"}
# manylinux1 (glibc 2.5) is the oldest tag; nothing predates it.
_MIN_MANYLINUX_MINOR = 5

_PERENNIAL_RE = re.compile(r"^manylinux_(\d+)_(\d+)_(?P<arch>.+)$")
_LINUX_TAG_RE = re.compile(
    r"^(?:linux|manylinux1|manylinux2010|manylinux2014|manylinux_\d+_\d+)"
    r"_(?P<arch>.+)$"
)


def _floor_parts(floor: str) -> tuple[int, int]:
    """``"2.17"`` -> ``(2, 17)``; tolerant of extra/absent components."""
    nums = [int(p) for p in re.findall(r"\d+", floor)]
    major = nums[0] if nums else 2
    minor = nums[1] if len(nums) > 1 else 0
    return major, minor


def manylinux_platform_tags(floor: str, arch: str) -> tuple[str, ...]:
    """The pip ``--platform`` tags to request for a glibc *floor* + *arch*.

    Returns the perennial ladder from the floor down to manylinux1 (glibc 2.5),
    plus the legacy aliases (``manylinux1``/``manylinux2010``/``manylinux2014``)
    at or below the floor. The floor tag is first (the variant's identity tag).
    A wheel matching *any* of these runs on a host meeting the floor, so pip —
    given all tags in one invocation — locks the newest compatible version.
    """
    major, minor = _floor_parts(floor)
    tags: list[str] = []
    if major == 2:
        for m in range(minor, _MIN_MANYLINUX_MINOR - 1, -1):
            tags.append(f"manylinux_{major}_{m}_{arch}")
        for m, alias in sorted(_LEGACY_ALIASES.items()):
            if m <= minor:
                tags.append(f"{alias}_{arch}")
    else:  # pragma: no cover - no manylinux_3_x exists yet
        tags.append(f"manylinux_{major}_{minor}_{arch}")
    return tuple(tags)


def linux_wheel_arch(tag: str) -> str | None:
    """The architecture a single Linux wheel platform (sub)tag targets.

    ``manylinux2014_x86_64`` / ``manylinux_2_17_x86_64`` / ``linux_x86_64`` ->
    ``x86_64``. ``musllinux_*`` never covers (returns ``None``). A tag that is
    not a linux tag at all also returns ``None``.
    """
    if tag.startswith("musllinux"):
        return None
    match = _LINUX_TAG_RE.match(tag)
    return match.group("arch") if match else None


def is_plain_linux_tag(sub_tag: str) -> bool:
    """A bare ``linux_<arch>`` platform tag (no manylinux/musllinux prefix).

    Plain ``linux_*`` wheels carry **no glibc promise** — the tag says nothing
    about which glibc the wheel was built against — so a distro-built one tied
    to a newer glibc would abort the AppImage on older hosts.
    """
    return sub_tag.startswith("linux_")


def plain_linux_wheel_warning(wheel_name: str, sub_tag: str) -> str:
    """The mandated warning for accepting a vendored plain ``linux_*`` wheel."""
    return (
        f"warning: accepting vendored wheel {wheel_name} on its {sub_tag} tag; "
        f"plain linux_* wheels make no glibc promise, so the AppImage may fail "
        f"on hosts with an older glibc than this wheel's build host. Portability "
        f"is your call (prefer a manylinux-tagged wheel where available)."
    )


def linux_wheel_coverage(wheel, archs: tuple[str, ...]) -> tuple[set[str], str | None]:
    """Archs a locked *wheel* covers on Linux, plus an optional warning.

    A manylinux/legacy tag covers its arch unconditionally. A plain
    ``linux_<arch>`` tag covers **only when the wheel is vendored via
    find_links** (``wheel.path`` is set) — a plain wheel pulled from
    PyPI/an extra index makes no glibc promise and does *not* count toward
    coverage — and yields the mandated warning when it does.
    """
    from_find_links = wheel.path is not None
    covered: set[str] = set()
    warning: str | None = None
    for sub in wheel.platform_tag.split("."):
        arch = linux_wheel_arch(sub)
        if arch not in archs:
            continue
        if is_plain_linux_tag(sub):
            if from_find_links:
                covered.add(arch)
                warning = plain_linux_wheel_warning(wheel.name, sub)
        else:
            covered.add(arch)
    return covered, warning


def _subtag_glibc_level(tag: str) -> tuple[int, int] | None:
    """The (major, minor) glibc a single manylinux sub-tag requires, or None."""
    if tag.startswith("musllinux"):
        return None
    match = _PERENNIAL_RE.match(tag)
    if match:
        return int(match.group(1)), int(match.group(2))
    if tag.startswith("manylinux1_"):
        return 2, 5
    if tag.startswith("manylinux2010_"):
        return 2, 12
    if tag.startswith("manylinux2014_"):
        return 2, 17
    return None  # plain linux_* makes no glibc promise


def wheel_glibc_level(platform_tag: str) -> tuple[int, int] | None:
    """The glibc a wheel requires = the *lowest* level among its sub-tags.

    A compound (dot-joined) tag declares the wheel valid under any of its
    platforms, so its real requirement is the least demanding one.
    """
    levels = [
        lvl
        for sub in platform_tag.split(".")
        if (lvl := _subtag_glibc_level(sub)) is not None
    ]
    return min(levels) if levels else None


def effective_glibc_floor(lock: WheelRuntimeLock) -> str:
    """The artifact's true host glibc requirement (derived, linux-spec).

    ``max(runtime floor, highest locked wheel manylinux level)``. Computed on
    demand from the locked wheels for ``doctor``/docs rather than stored as a
    distinct lock field, keeping the shared lock model platform-agnostic.
    """
    floor = _floor_parts(lock.python_runtime.floor or DEFAULT_GLIBC_FLOOR)
    for pkg in lock.packages:
        for wheel in pkg.wheels:
            level = wheel_glibc_level(wheel.platform_tag)
            if level is not None and level > floor:
                floor = level
    return f"{floor[0]}.{floor[1]}"


class LinuxProfile(PlatformLockProfile):
    platform = "linux"

    def overlay(self, config: Config):
        return config.linux

    def missing_overlay_error(self) -> str:
        return "pyproject.toml has no [tool.kivy.linux] table; nothing to lock."

    def python_version(self, config: Config) -> str:
        # [tool.kivy.linux.python].version is required (the loader raises a
        # ConfigError when it is missing), so it is always set here. Never
        # silently substitute a hidden default — that would pin an unexpected
        # (and possibly unreleased) Python instead of surfacing the misconfig.
        version = config.linux_required.python_version
        if not version:
            raise ConfigError(
                "missing required [tool.kivy.linux.python].version",
                key_path="tool.kivy.linux.python.version",
            )
        return version

    def _floor(self, config: Config) -> str:
        return config.linux_required.glibc_floor or DEFAULT_GLIBC_FLOOR

    def variants(self, config: Config) -> tuple[Variant, ...]:
        floor = self._floor(config)
        variants: list[Variant] = []
        for arch in config.linux_required.archs:
            tags = manylinux_platform_tags(floor, arch)
            variants.append(
                Variant(
                    arch=arch,
                    platform_tag=tags[0],
                    extra_platform_tags=tags[1:],
                )
            )
        return tuple(variants)

    def wheel_covers(self, platform_tag: str, archs: tuple[str, ...]) -> set[str]:
        covered: set[str] = set()
        for sub in platform_tag.split("."):
            arch = linux_wheel_arch(sub)
            if arch in archs:
                covered.add(arch)
        return covered

    def wheel_coverage(
        self, wheel, archs: tuple[str, ...]
    ) -> tuple[set[str], str | None]:
        # Source-gate plain linux_* wheels (accepted only from find_links) and
        # emit the mandated no-glibc-promise warning (linux-spec coverage rule).
        return linux_wheel_coverage(wheel, archs)

    def runtime_provider(self, config: Config) -> RuntimeProvider:
        return PythonBuildStandaloneProvider()

    def declared_floor(self, config: Config) -> str | None:
        return config.linux_required.glibc_floor

    def coverage_error(self, name: str, missing: list[str]) -> str:
        return (
            f"{name} has no manylinux wheel for arch(es): {', '.join(missing)} at "
            f"the configured glibc floor.\n"
            f"  A compiled package must publish a manylinux wheel that runs on the "
            f"floor to be locked reproducibly.\n"
            f"  Raise [tool.kivy.linux].glibc_floor to admit a newer-manylinux "
            f"wheel, or supply the wheel via extra_index_urls/find_links."
        )

    def floor_error(self, declared: str, runtime_floor: str, version: str) -> str:
        return (
            f"glibc_floor {declared} is below the glibc {runtime_floor} floor "
            f"required by the python-build-standalone {version} runtime.\n"
            f"  Raise [tool.kivy.linux].glibc_floor to at least {runtime_floor}."
        )

    def wheel_scope_hint(self) -> str:
        return (
            "Vendored wheels must live under the project directory, a sibling "
            "directory, or the enclosing repository (e.g. a wheels/ directory "
            "beside pyproject.toml)."
        )

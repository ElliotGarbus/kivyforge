"""Re-resolve with an existing lock's versions as the preference (#126).

pip has no "prefer these versions" option, so each locked package becomes a
``name==version`` constraint. A constraint only applies to a package pip would
install anyway, so a pin for a dependency that went away is harmless.

A direct requirement whose specifier now excludes its locked version loses its
pin first: that is the package the user asked to move. If the constrained
resolve still fails, it is retried without pins. A retry that succeeds means
the old pins were the conflict (``PinsConflict``, fixed by ``lock --update``);
a retry that fails is reported as pip's own failure, as it was before pins.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

from ..report import diagnostics
from ..report.failures import ClassifiedError
from .model import LockedPackage, canonical_name

#: ``name`` (canonical) to the version to keep.
Pins = Mapping[str, str]


class PinsConflict(ClassifiedError):
    """The changed inputs cannot be resolved with the locked versions kept."""

    code = diagnostics.LOCK_PINS_CONFLICT


def preferred_pins(
    locked: Iterable[LockedPackage], requirements: Sequence[str]
) -> dict[str, str]:
    """The locked versions to keep for a resolve of ``requirements``."""
    specifiers: dict[str, list] = {}
    for requirement in requirements:
        try:
            parsed = Requirement(requirement)
        except InvalidRequirement:
            continue
        specifiers.setdefault(canonical_name(parsed.name), []).append(parsed.specifier)
    pins: dict[str, str] = {}
    for package in locked:
        key = canonical_name(package.name)
        wanted = specifiers.get(key, ())
        if all(spec.contains(package.version, prereleases=True) for spec in wanted):
            pins[key] = package.version
    return pins


def constraint_args(directory: Path, pins: Pins) -> list[str]:
    """pip arguments applying ``pins``, written as a constraints file."""
    if not pins:
        return []
    path = directory / "kivyforge-constraints.txt"
    path.write_text(
        "".join(f"{name}=={version}\n" for name, version in sorted(pins.items())),
        encoding="utf-8",
    )
    return ["-c", str(path)]


def resolve_preferring[T](
    resolve: Callable[[Pins], T],
    pins: Pins,
    *,
    errors: tuple[type[Exception], ...],
    platform: str,
) -> T:
    """``resolve(pins)``; if that fails only because of the pins, ``PinsConflict``."""
    if not pins:
        return resolve({})
    try:
        return resolve(pins)
    except errors as constrained:
        resolve({})  # a real failure raises here, unchanged
        raise PinsConflict(
            "the changed lock inputs cannot be resolved while keeping the versions "
            f"already in pylock.{platform}.toml.\n"
            f"  Fix: run `kivyforge lock -p {platform} --update` to re-resolve "
            "every package to the newest version its specifier allows, or pin "
            "the package that has to move in [project].dependencies.\n"
            f"  With the locked versions kept, pip said:\n{constrained}",
            context={"platform": platform},
        ) from constrained

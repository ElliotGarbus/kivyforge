"""What this kivyforge can do, as data (roadmap item 3, agent point 6).

Everything here is **derived**, never restated. The platform list is the
registry, the host matrix comes from asking each backend's own
``check_host_capability`` — the function the verbs actually gate on — the verb
list is the click group, and the code vocabularies are the modules that define
them. A second copy of any of these would be a copy that drifts, and the first
symptom would be an agent trusting it.

The host matrix is the payload that earns the verb: it is the fact that stops an
agent trying to build iOS on Windows, and nothing in ``--help`` states it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .platforms import HostCapabilityError, Platform, available_platform_names
from .platforms import get_platform as _get_platform
from .report import diagnostics, exit_codes

#: The ``platform.system()`` values kivyforge runs on. Not every host builds
#: every target, which is what :attr:`PlatformCapability.hosts` answers.
HOSTS = ("Darwin", "Linux", "Windows")

#: Friendlier spellings for the human report; the JSON keeps ``platform.system()``
#: values, since that is what a consumer can compare against its own host.
_HOST_LABELS = {"Darwin": "macOS", "Linux": "Linux", "Windows": "Windows"}


@dataclass(frozen=True)
class PlatformCapability:
    name: str
    aliases: tuple[str, ...]
    archs: tuple[str, ...]
    package_formats: tuple[str, ...]
    default_package_format: str | None
    #: The host this platform is the default target for, or ``None`` for a
    #: cross-compiled target that always needs explicit selection.
    host_default_for: str | None
    #: Per host: can this host build this target at all?
    hosts: dict[str, bool]

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "archs": list(self.archs),
            "package_formats": list(self.package_formats),
            "default_package_format": self.default_package_format,
            "host_default_for": self.host_default_for,
            "hosts": dict(self.hosts),
        }

    @property
    def buildable_on(self) -> tuple[str, ...]:
        return tuple(host for host in HOSTS if self.hosts.get(host))


@dataclass(frozen=True)
class Capabilities:
    platforms: tuple[PlatformCapability, ...]
    #: Verb name -> whether it accepts ``--json``.
    verbs: dict[str, bool]
    exit_codes: dict[int, str]
    diagnostic_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "hosts": list(HOSTS),
            "platforms": [p.as_dict() for p in self.platforms],
            # String keys: JSON object keys are strings anyway, and spelling it
            # here keeps round-tripping honest.
            "verbs": [
                {"name": name, "json": supported}
                for name, supported in self.verbs.items()
            ],
            "exit_codes": {
                str(code): meaning for code, meaning in self.exit_codes.items()
            },
            "diagnostic_codes": list(self.diagnostic_codes),
        }


def _can_build(backend: Platform, host: str) -> bool:
    """Whether *host* can build *backend*'s target, asked of the backend itself."""
    try:
        backend.check_host_capability(host_system=host)
    except HostCapabilityError:
        return False
    return True


def _platform_capability(backend: Platform) -> PlatformCapability:
    return PlatformCapability(
        name=backend.name,
        aliases=backend.aliases,
        archs=backend.archs,
        package_formats=backend.package_formats,
        default_package_format=backend.default_package_format,
        host_default_for=backend.host_system,
        hosts={host: _can_build(backend, host) for host in HOSTS},
    )


def _verbs() -> dict[str, bool]:
    """Every registered verb, and whether it accepts ``--json``.

    Read off the click group rather than listed, so a verb that gains or loses
    the flag cannot leave this behind.
    """
    from .cli import main

    return {
        name: any(param.name == "json_out" for param in command.params)
        for name, command in sorted(main.commands.items())
    }


def _diagnostic_codes() -> tuple[str, ...]:
    """The published code vocabulary, read out of ``report/diagnostics.py``."""
    return tuple(
        sorted(
            value
            for name, value in vars(diagnostics).items()
            if not name.startswith("_")
            and isinstance(value, str)
            and value.startswith("KF-")
        )
    )


def collect() -> Capabilities:
    """Everything this kivyforge can do, derived from the code that does it."""
    return Capabilities(
        platforms=tuple(
            _platform_capability(_get_platform(name))
            for name in available_platform_names()
        ),
        verbs=_verbs(),
        exit_codes=dict(sorted(exit_codes.RESERVED.items())),
        diagnostic_codes=_diagnostic_codes(),
    )


def host_label(host: str) -> str:
    return _HOST_LABELS.get(host, host)

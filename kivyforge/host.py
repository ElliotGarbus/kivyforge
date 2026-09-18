"""Whether this host can run a target-arch binary without emulation.

Doctor and every desktop bundler used to open-code the same test
(``platform.machine().lower() == target_arch``). aarch64 as a Linux *target*
is what makes a disagreement between those copies expensive, so there is one
definition. The spelling of ``platform.machine()`` already matches each
backend's arch vocabulary (``x86_64`` on Linux, ``arm64`` on Apple Silicon,
``amd64`` on Windows), so the comparison is equality after ``.lower()``.
"""

from __future__ import annotations

import platform


def host_machine() -> str:
    """Lower-cased ``platform.machine()``, matching :meth:`Probe.host_machine`."""
    return platform.machine().lower()


def host_runs_natively(target_arch: str, *, host_machine: str | None = None) -> bool:
    """True when this host can execute a binary of *target_arch* natively.

    *host_machine* defaults to :func:`host_machine`. Pass an explicit value
    from a :class:`~kivyforge.doctor.probe.Probe` so tests can fake the host
    without patching ``platform``.
    """
    host = host_machine if host_machine is not None else platform.machine().lower()
    return host == target_arch.lower()

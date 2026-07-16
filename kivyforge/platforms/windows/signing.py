r"""Authenticode signing hook for the Windows launcher (signing-windows).

v1 ships kivyforge's own binaries and the default artifact **unsigned**, but the
hook is first-class and optional from day one. Identity is always a
certificate-store **thumbprint** in the configured ``store_scope`` — never a
``.pfx`` path/password — so the same store ``signtool`` uses is the one the
doctor certificate check inspects.

Two backends behind a single :class:`Signer` protocol:

* :class:`NullSigner` — the unconfigured default; leaves the artifact unsigned.
* :class:`SigntoolSigner` — ``signtool sign /sha1 <thumbprint> /fd SHA256
  /tr <timestamp_url> /td SHA256`` (adding ``/sm`` for ``store_scope=machine``),
  always RFC-3161 timestamped.

Signing runs on the ``dist/windows`` copy only, **after** the resource patch
(a resource edit invalidates any signature) and **before** any external
installer. Only the launcher ``.exe`` is signed; payload DLLs/``.pyd``s are
**not** signed (not planned — onedir keeps it possible if ever needed).
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from packaging.version import InvalidVersion, Version

from . import WindowsBundleError

# Windows version resources are four unsigned 16-bit integers.
_U16_MAX = 0xFFFF

# The fourth numeric field folds PEP 440 pre/post/dev into a single monotonic
# 16-bit value so ordering is preserved: dev < alpha < beta < rc < final < post.
# The string ProductVersion field always carries the full, human PEP 440 string.
_PRE_TIER = {"a": 10000, "b": 20000, "rc": 30000}
_FINAL_TIER = 40000
_POST_TIER = 50000


def _clamp(value: int, hi: int = _U16_MAX) -> int:
    return max(0, min(value, hi))


def pep440_to_file_version(version: str) -> str:
    """Map a PEP 440 *version* to a deterministic ``a.b.c.d`` of four 16-bit ints.

    ``a.b.c`` are ``release[0:3]`` (missing parts are 0). ``d`` folds the
    pre/post/dev segment so that, for the same ``a.b.c``:
    ``devN`` (``0+N``) < ``aN`` (``10000+N``) < ``bN`` (``20000+N``) <
    ``rcN`` (``30000+N``) < final (``40000``) < ``postN`` (``50000+N``).
    The result is therefore monotonic **within a single epoch** only. Epoch is
    not representable in the four-field resource (``major`` already holds
    ``release[0]``) and is carried only by the string ProductVersion, so a
    cross-epoch numeric comparison may not order; an unparseable version degrades
    to ``0.0.0.0``.
    """
    try:
        v = Version(version)
    except InvalidVersion:
        return "0.0.0.0"
    release = v.release
    a = _clamp(release[0] if len(release) > 0 else 0)
    b = _clamp(release[1] if len(release) > 1 else 0)
    c = _clamp(release[2] if len(release) > 2 else 0)
    if v.pre is not None:
        letter, n = v.pre
        d = _PRE_TIER.get(letter, _PRE_TIER["rc"]) + _clamp(n, 9999)
    elif v.post is not None:
        d = _POST_TIER + _clamp(v.post, 9999)
    elif v.dev is not None:
        d = _clamp(v.dev, 9999)
    else:
        d = _FINAL_TIER
    return f"{a}.{b}.{c}.{_clamp(d)}"


@runtime_checkable
class Signer(Protocol):
    """Signs a set of PE files in place (Windows-only, new to the codebase)."""

    def sign(self, paths: Sequence[Path]) -> None: ...

    @property
    def configured(self) -> bool: ...


@dataclass(frozen=True)
class NullSigner:
    """The unconfigured default: signing is a no-op, artifact stays unsigned."""

    configured: bool = False

    def sign(self, paths: Sequence[Path]) -> None:
        return


@dataclass(frozen=True)
class SigntoolSigner:
    """Authenticode signing via ``signtool`` against a cert-store thumbprint."""

    thumbprint: str
    timestamp_url: str
    store_scope: str
    signtool: str = "signtool"
    configured: bool = True

    def command(self, paths: Sequence[Path]) -> list[str]:
        """The exact ``signtool`` argv for *paths* (pure; unit-tested directly)."""
        argv = [
            self.signtool,
            "sign",
            "/sha1",
            self.thumbprint,
            "/fd",
            "SHA256",
            "/tr",
            self.timestamp_url,
            "/td",
            "SHA256",
        ]
        # /sm selects the LocalMachine store; without it signtool uses CurrentUser.
        if self.store_scope == "machine":
            argv.append("/sm")
        argv += [str(p) for p in paths]
        return argv

    def sign(self, paths: Sequence[Path]) -> None:
        if not paths:
            return
        argv = self.command(paths)
        exe = shutil.which(self.signtool) or self.signtool
        argv[0] = exe
        try:
            proc = subprocess.run(argv, capture_output=True, text=True)
        except OSError as exc:
            raise WindowsBundleError(
                f"failed to run signtool ({self.signtool}): {exc}. signtool ships "
                "with the Windows SDK and is Windows-only."
            ) from exc
        if proc.returncode != 0:
            raise WindowsBundleError(
                f"signtool failed (exit {proc.returncode}):\n"
                f"{(proc.stderr or proc.stdout).strip()}\n"
                "  Check the thumbprint, that the cert is in the configured "
                "store_scope, and that the timestamp server is reachable."
            )


def select_signer(signing, *, signtool: str = "signtool") -> Signer:
    """Pick the signer for a ``[tool.kivy.windows.signing]`` config.

    Returns a :class:`SigntoolSigner` when a thumbprint is configured, else a
    :class:`NullSigner` (unsigned artifact — the v1 default).
    """
    if not signing.configured:
        return NullSigner()
    return SigntoolSigner(
        thumbprint=signing.thumbprint.replace(" ", "").upper(),
        timestamp_url=signing.timestamp_url,
        store_scope=signing.store_scope,
        signtool=signtool,
    )

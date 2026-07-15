"""Per-app launcher resource patching via the vendored ``rcedit`` (windows-spec).

The single vendored launcher is parameterized per app only by its *resources*
(no recompilation): the icon (from ``[tool.kivy.windows.icons]``) and the
version resource (product/file version, names, copyright — from ``[project]`` /
``[tool.kivy]``). ``rcedit`` performs the edit without any toolchain.

Command construction (:func:`build_rcedit_args`) is pure and host-agnostic so it
is unit-tested directly; execution (:func:`patch_resources`) is Windows-only.
Patching happens **before** signing — a resource edit invalidates any existing
Authenticode signature (the signing pipeline guarantees the order).

The numeric ``FILEVERSION``/``PRODUCTVERSION`` are four 16-bit integers; the
PEP 440 → four-part mapping lives in signing (Phase 9) and is passed in here as
an already-formatted ``a.b.c.d`` string.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import WindowsBundleError


@dataclass(frozen=True)
class ResourcePatch:
    """The per-app resources to write into a launcher copy.

    Every field is optional: only the ones set emit an ``rcedit`` flag, so a
    minimal project (no icon, no metadata) still produces a valid launcher.
    ``file_version``/``product_version`` are the numeric ``a.b.c.d`` forms;
    ``product_version_string`` carries the human PEP 440 string.
    """

    icon: Path | None = None
    product_name: str | None = None
    file_description: str | None = None
    product_version_string: str | None = None
    legal_copyright: str | None = None
    company_name: str | None = None
    file_version: str | None = None  # numeric "a.b.c.d"
    product_version: str | None = None  # numeric "a.b.c.d"

    @property
    def is_empty(self) -> bool:
        return all(
            getattr(self, f) is None
            for f in (
                "icon",
                "product_name",
                "file_description",
                "product_version_string",
                "legal_copyright",
                "company_name",
                "file_version",
                "product_version",
            )
        )


def build_rcedit_args(rcedit: Path, exe: Path, patch: ResourcePatch) -> list[str]:
    """The full ``rcedit`` argv to patch *exe* in place (one invocation).

    ``rcedit`` applies every ``--set-*`` operation given in a single call, so
    the whole patch is one command. Returns ``[rcedit, exe]`` (no-op) when the
    patch is empty — callers may skip execution in that case.
    """
    args: list[str] = [str(rcedit), str(exe)]
    if patch.icon is not None:
        args += ["--set-icon", str(patch.icon)]
    # Numeric version fields first (dedicated flags), then string fields.
    if patch.file_version is not None:
        args += ["--set-file-version", patch.file_version]
    if patch.product_version is not None:
        args += ["--set-product-version", patch.product_version]
    string_fields = [
        ("ProductName", patch.product_name),
        ("FileDescription", patch.file_description),
        ("ProductVersion", patch.product_version_string),
        ("LegalCopyright", patch.legal_copyright),
        ("CompanyName", patch.company_name),
    ]
    for key, value in string_fields:
        if value is not None:
            args += ["--set-version-string", key, value]
    return args


def patch_resources(
    exe: Path, patch: ResourcePatch, *, rcedit: Path | None = None
) -> None:
    """Patch *exe*'s icon/version resources in place with ``rcedit`` (Windows).

    A no-op when *patch* is empty. Raises :class:`WindowsBundleError` on any
    ``rcedit`` failure.
    """
    if patch.is_empty:
        return
    if rcedit is None:
        from .assets import vendored_rcedit

        rcedit = vendored_rcedit()
    args = build_rcedit_args(rcedit, exe, patch)
    try:
        proc = subprocess.run(args, capture_output=True, text=True)
    except OSError as exc:
        raise WindowsBundleError(
            f"failed to run rcedit ({rcedit}): {exc}. rcedit is Windows-only."
        ) from exc
    if proc.returncode != 0:
        raise WindowsBundleError(
            f"rcedit failed to patch {exe.name} (exit {proc.returncode}):\n"
            f"{(proc.stderr or proc.stdout).strip()}"
        )

"""Failure classification that survives the trip to the CLI boundary.

Backends raise their own exception types (``AppDirError``, ``AndroidBuildError``,
...) and the CLI translates them into ``ToolchainError``. That translation used to
be ``ToolchainError(str(exc))``, which kept the message and threw away everything
a consumer could branch on. A backend error that derives from
:class:`ClassifiedError` carries its code, exit status and context across instead
(``ToolchainError.wrap``); one that does not stays ``KF-ERROR`` / exit ``1``,
exactly as before.
"""

from __future__ import annotations

import errno as errno_mod
import shutil
from collections.abc import Mapping
from typing import TypedDict

from . import diagnostics, exit_codes


class ClassifiedError(Exception):
    """An expected failure that knows its diagnostic code and exit status.

    Subclasses may fix ``code``/``exit_code`` as class attributes (a failure
    family); a raise site may also pass them per instance.
    """

    code: str = diagnostics.UNSPECIFIED
    exit_code: int = exit_codes.CONFIG_ERROR

    def __init__(
        self,
        message: str = "",
        *,
        code: str | None = None,
        exit_code: int | None = None,
        context: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        if exit_code is not None:
            self.exit_code = exit_code
        self.context: dict[str, str] = dict(context or {})


class Classification(TypedDict, total=False):
    """Keyword arguments that classify a failure, for ``**`` at a raise site."""

    code: str
    exit_code: int
    context: dict[str, str]


def reclassify(exc: ClassifiedError) -> Classification:
    """Carry *exc*'s classification into the family re-raising it.

    A lower layer's failure is often re-raised as the surrounding backend's own
    type with advice appended -- ``PycompileError`` becomes ``AppDirError`` plus
    "or set byte_compile = false". Without this the re-raise keeps the message and
    drops the code, which is the same loss ``ToolchainError.wrap`` exists to
    prevent, one layer down.
    """
    return {"code": exc.code, "exit_code": exc.exit_code, "context": dict(exc.context)}


def spawn_failure(tool: str, exc: OSError) -> Classification:
    """``code``/``exit_code``/``context`` for a tool that could not be started.

    Only ``FileNotFoundError`` means "missing". Anything else -- a wrapper
    without its executable bit, the wrong binary format -- is a different fix,
    and folding it into "missing" would send someone to install a tool that is
    already there. Both are the machine's problem, hence one exit status.
    """
    if isinstance(exc, FileNotFoundError):
        return {
            "code": diagnostics.TOOLCHAIN_MISSING,
            "exit_code": exit_codes.ENVIRONMENT_ERROR,
            "context": {"tool": tool},
        }
    number = exc.errno
    return {
        "code": diagnostics.TOOLCHAIN_UNUSABLE,
        "exit_code": exit_codes.ENVIRONMENT_ERROR,
        "context": {
            "tool": tool,
            "errno": errno_mod.errorcode.get(number, str(number))
            if number is not None
            else "unknown",
        },
    }


def os_failure(doing: str, exc: OSError) -> str:
    """``could not <doing>: <why>``, in one line however many paths failed.

    For a filesystem operation of kivyforge's own that the OS refused. Left
    bare, the ``OSError`` escapes the CLI as a traceback with no ``--json``
    envelope; raised as ``ToolchainError(os_failure(...))`` it is an ordinary
    unclassified failure. Unclassified on purpose: a full disk, a read-only
    folder and a file where a folder belongs have nothing in common to name.

    ``shutil.copytree`` raises a bare ``OSError`` when it cannot even start, and
    otherwise one ``shutil.Error`` at the end carrying ``(src, dst, reason)`` for
    every path that failed. A refused or too-long target fails every file below
    it, which is thousands of entries, so name the first and count the rest.
    """
    failed = _copy_failures(exc)
    if not failed:
        return f"could not {doing}: {exc}"
    _src, path, reason = failed[0]
    # The reason usually ends by repeating the path; it is named once.
    reason = reason.removesuffix(f": {path!r}")
    count = "1 path" if len(failed) == 1 else f"{len(failed)} paths"
    return f"could not {doing}: {count} failed, the first {path} ({reason})"


def failed_path(exc: OSError) -> str:
    """The path :func:`os_failure` names for *exc*, or ``""`` when it names none."""
    failed = _copy_failures(exc)
    if failed:
        return failed[0][1]
    return exc.filename if isinstance(exc.filename, str) else ""


def _copy_failures(exc: OSError) -> list[tuple[str, str, str]]:
    """The ``(src, dst, reason)`` entries of a ``shutil.Error``, or ``[]``."""
    failed = exc.args[0] if isinstance(exc, shutil.Error) and exc.args else None
    if isinstance(failed, list) and failed and len(failed[0]) == 3:
        return failed
    return []


def build_tool_failed(tool: str, task: str) -> Classification:
    """``code``/``exit_code``/``context`` for a build tool that exited non-zero."""
    return {
        "code": diagnostics.BUILD_TOOL_FAILED,
        "exit_code": exit_codes.BUILD_FAILURE,
        "context": {"tool": tool, "task": task},
    }


#: The three lock conditions, all fixed the same way: re-run ``kivyforge lock``.
LOCK_MISSING: Classification = {
    "code": diagnostics.LOCK_MISSING,
    "exit_code": exit_codes.LOCK_DRIFT,
}
LOCK_UNREADABLE: Classification = {
    "code": diagnostics.LOCK_UNREADABLE,
    "exit_code": exit_codes.LOCK_DRIFT,
}
LOCK_DRIFT: Classification = {
    "code": diagnostics.LOCK_DRIFT,
    "exit_code": exit_codes.LOCK_DRIFT,
}
HOST_INCAPABLE: Classification = {
    "code": diagnostics.HOST_INCAPABLE,
    "exit_code": exit_codes.ENVIRONMENT_ERROR,
}
ARTIFACT_MISSING: Classification = {
    "code": diagnostics.ARTIFACT_MISSING,
    "exit_code": exit_codes.BUILD_FAILURE,
}

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

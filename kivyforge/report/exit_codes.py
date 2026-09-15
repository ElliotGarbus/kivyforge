"""Exit-code taxonomy (roadmap item 3, agent-friendliness point 4).

``ToolchainError.exit_code`` was ``1`` for everything, which means a caller --
human or agent -- cannot tell "you configured this wrong" from "this toolchain
is missing" from "the build failed". Those want three different reactions: fix
the file, install something, or read the log. One code cannot express that.

The numbers are a contract as soon as anything branches on them, so they are
reserved here rather than chosen at each raise site:

===== ===================== =============================================
Code  Meaning               Typical reaction
===== ===================== =============================================
0     success               continue
1     config / user error   edit ``pyproject.toml`` and retry
2     environment missing   install a toolchain, then retry unchanged
3     lock drift            run ``kivyforge lock -p <platform>``
4     build failure         read the build log; the toolchain ran and said no
===== ===================== =============================================

``1`` keeps its historical meaning so nothing that already treats non-zero as
failure changes behaviour, and so the narrowing is additive: a raise site that
has not been triaged yet still exits ``1`` and is merely *unspecific*, never
wrong.
"""

from __future__ import annotations

SUCCESS = 0
CONFIG_ERROR = 1
ENVIRONMENT_ERROR = 2
LOCK_DRIFT = 3
BUILD_FAILURE = 4

#: Every reserved code, for tests and for ``capabilities --json`` to publish.
RESERVED = {
    SUCCESS: "success",
    CONFIG_ERROR: "config or user error",
    ENVIRONMENT_ERROR: "environment or toolchain missing",
    LOCK_DRIFT: "lock file out of date",
    BUILD_FAILURE: "build failed",
}

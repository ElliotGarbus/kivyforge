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
2     *usage error*         click's, not ours -- fix the command line
3     environment missing   install a toolchain, then retry unchanged
4     lock drift            run ``kivyforge lock -p <platform>``
5     build failure         read the build log; the toolchain ran and said no
===== ===================== =============================================

**``2`` is reserved for click and we never assign it.** This is a correction to
the numbering first drafted for roadmap item 3, which was written from memory
and gave ``2`` to "environment missing". Measured instead:
``kivyforge doctor --bogus-flag`` already exits ``2``, because ``2`` is
``click.UsageError.exit_code`` and the same convention ``argparse`` follows. Had
we kept ``2``, "you typed the command wrong" and "this machine lacks a toolchain"
would have been indistinguishable -- which is precisely the confusion the
taxonomy exists to remove, so the convention wins and the rest shift up.

``1`` keeps its historical meaning so nothing that already treats non-zero as
failure changes behaviour, and so the narrowing is additive: a raise site that
has not been triaged yet still exits ``1`` and is merely *unspecific*, never
wrong.
"""

from __future__ import annotations

SUCCESS = 0
CONFIG_ERROR = 1
#: ``click.UsageError.exit_code``. Listed so it cannot be handed out twice;
#: kivyforge never raises it deliberately.
USAGE_ERROR = 2
ENVIRONMENT_ERROR = 3
LOCK_DRIFT = 4
BUILD_FAILURE = 5

#: Every reserved code, for tests and for ``capabilities --json`` to publish.
RESERVED = {
    SUCCESS: "success",
    CONFIG_ERROR: "config or user error",
    USAGE_ERROR: "usage error (click)",
    ENVIRONMENT_ERROR: "environment or toolchain missing",
    LOCK_DRIFT: "lock file out of date",
    BUILD_FAILURE: "build failed",
}

"""The versioned ``--json`` envelope (roadmap item 3, agent-friendliness point 1).

Every ``--json`` response has the same outer shape regardless of verb, because
an agent should be able to find ``ok`` and ``diagnostics`` without knowing which
command produced the document:

.. code-block:: json

    {
      "schema": 1,
      "kivyforge": "3.0.0.dev0",
      "command": "doctor",
      "platform": "linux",
      "ok": true,
      "data": {},
      "diagnostics": []
    }

``schema`` is first and it is an integer on purpose. An unversioned payload is
one that breaks silently: a consumer written against today's shape has no way to
notice it is now parsing something else. Bump it only for changes that are not
additive -- adding a key inside ``data`` is not a bump.

``data`` and ``diagnostics`` are **always present**, even when empty. Optional
containers force every consumer to write the same defensive ``get(..., [])``,
and the ones who forget get an ``AttributeError`` on the unusual path rather
than the common one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .diagnostics import Diagnostic

#: Bump only on a non-additive change. See the module docstring.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Envelope:
    command: str
    kivyforge: str
    ok: bool
    platform: str | None = None
    data: dict[str, object] = field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA_VERSION,
            "kivyforge": self.kivyforge,
            "command": self.command,
            "platform": self.platform,
            "ok": self.ok,
            "data": dict(self.data),
            "diagnostics": [d.as_dict() for d in self.diagnostics],
        }

    def to_json(self) -> str:
        """Serialise deterministically, with a trailing newline.

        ``sort_keys`` stays off so the documented key order above is the order
        on the wire -- ``schema`` first is worth more to a human reading a dump
        than alphabetical order is. Key order within ``data`` is likewise the
        producing verb's choice, which keeps related fields adjacent.

        ``ensure_ascii`` stays **on**, which is a deliberate difference from the
        human path. It escapes every non-ASCII character to ``\\uXXXX``, so the
        machine output cannot raise ``UnicodeEncodeError`` on any stream
        encoding whatsoever -- including a redirected cp1252 Windows stdout,
        which is exactly where the human path has to be careful
        (``tests/test_message_encoding.py``). JSON consumers decode the escapes
        transparently, so nothing is lost. The alternative would make
        ``--json > out.json`` depend on a message-content guard holding
        forever, and machine output is the last thing that should crash.
        """
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=True) + "\n"

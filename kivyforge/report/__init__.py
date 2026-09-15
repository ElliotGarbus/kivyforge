"""Output layer: one seam, two renderers (roadmap item 3).

Verbs emit structured results and progress through :class:`Report` rather than
calling ``click.echo``. A human renderer (``rich``) and a JSON renderer consume
the same calls, so colour and ``--json`` did not each require editing the ~119
output sites.

Start at :mod:`kivyforge.report.console` for the stream-routing rule, which is
the decision the rest of the item rests on.
"""

from __future__ import annotations

from . import diagnostics, exit_codes
from .console import STYLES, Report, want_color
from .diagnostics import ERROR, INFO, WARNING, Diagnostic
from .envelope import SCHEMA_VERSION, Envelope

__all__ = [
    "ERROR",
    "INFO",
    "SCHEMA_VERSION",
    "STYLES",
    "WARNING",
    "Diagnostic",
    "Envelope",
    "Report",
    "diagnostics",
    "exit_codes",
    "want_color",
]

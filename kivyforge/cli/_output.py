"""Shared output options for every verb (roadmap item 3).

``--json`` and ``--no-color`` belong to all verbs, so they are one decorator
rather than nine copies. They sit on the *verbs* rather than the top-level group
on purpose: a group option has to precede the subcommand (``kivyforge --no-color
doctor``), and everyone types ``kivyforge doctor --no-color``.
"""

from __future__ import annotations

from collections.abc import Callable

import click


def output_options[F: Callable[..., object]](fn: F) -> F:
    """Add ``--json`` and ``--no-color``, passed as ``json_out`` / ``no_color``.

    ``--json`` is named ``json_out`` in Python because ``json`` would shadow the
    stdlib module inside the verb, which is exactly the sort of thing that works
    until someone adds an ``import json`` and gets a confusing error.
    """
    fn = click.option(
        "--json",
        "json_out",
        is_flag=True,
        help="Emit a machine-readable JSON envelope on stdout.",
    )(fn)
    fn = click.option(
        "--no-color",
        is_flag=True,
        help="Disable coloured output. NO_COLOR is honoured too.",
    )(fn)
    return fn

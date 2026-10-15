"""Deadline-aware matching and multiline end detection.

Mirrors ``command/PSystemCommandFactory.java:268-286`` (``isMultilineCommandOk``): lines
are appended one unit at a time (``:288-307`` glues ``{{ ... }}`` embedded diagrams into
one unit), the command is re-validated after each unit, and ``NOT_OK`` / running out of
lines drops the candidate so the next command is tried.

* ``multiline``: ``command/CommandMultilines2.java:79-110`` (and
  ``CommandMultilines.java:58-74``): one line is always ``OK_PARTIAL``; with more lines,
  ``OK`` iff the *last* line, trimmed, fully matches the ``end`` pattern. Only the last
  line is tested, so cost is one regex per appended line.
* ``multiline-bracket``: ``command/CommandMultilinesBracket.java:64-96``: bracket depth
  starts at 1; each later trimmed line ending in ``{`` adds one, ending in ``}`` removes
  one; below 0 is ``NOT_OK``; ``OK`` when depth returns to 0. Depth is maintained
  incrementally here instead of recomputed (same result, linear time).

Known gaps (not representable in the model): ``isLineConsistent`` (abstract, per
command), ``CommandDecoratorMultine.getNbMaxLines`` line cap (``:281``),
``finalVerification`` hooks, and the ``MultilinesStrategy.REMOVE_STARTING_QUOTE`` line
filter (``MultilinesStrategy.java``; ``'`` lines are already gone, see ``source``).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from tools.interp.source import Line, embedded_type, is_embedded_end

BRACKET_OPEN = "{"
BRACKET_CLOSE = "}"


class BlockTimeout(Exception):  # noqa: N818 - control-flow signal, not an error
    """The per-block time budget is spent."""


class Deadline:
    """A per-block budget; every regex call receives the remaining time."""

    def __init__(self, timeout_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._limit = clock() + timeout_s

    def fullmatch(self, pattern: Any, text: str) -> bool:
        """Whole-string match; raises ``BlockTimeout`` when the budget runs out."""
        remaining = self._limit - self._clock()
        if remaining <= 0:
            raise BlockTimeout
        try:
            return pattern.fullmatch(text, timeout=remaining) is not None
        except TimeoutError as exc:
            raise BlockTimeout from exc


def unit_end(body: list[Line], j: int) -> int:
    """End (exclusive) of the unit starting at ``j`` (``PSystemCommandFactory.java:288``)."""
    if embedded_type(body[j].text) is None:
        return j + 1
    nested = 1
    for k in range(j + 1, len(body)):
        if embedded_type(body[k].text) is not None:
            nested += 1
        elif is_embedded_end(body[k].text):
            nested -= 1
            if nested == 0:
                return k + 1
    return len(body)


def scan_multiline(end: Any, body: list[Line], i: int, deadline: Deadline) -> int | None:
    """Index after a ``multiline`` command starting at ``i``, or ``None`` (dropped)."""
    j = i
    while j < len(body):
        j = unit_end(body, j)
        if j - i > 1 and deadline.fullmatch(end, body[j - 1].trimmed):
            return j
    return None


def scan_bracket(body: list[Line], i: int) -> int | None:
    """Index after a ``multiline-bracket`` command starting at ``i``, or ``None``."""
    level = 1
    j = i
    while j < len(body):
        nxt = unit_end(body, j)
        for k in range(max(j, i + 1), nxt):
            text = body[k].trimmed
            level += text.endswith(BRACKET_OPEN) - text.endswith(BRACKET_CLOSE)
            if level < 0:
                return None
        j = nxt
        if j - i > 1 and level == 0:
            return j
    return None

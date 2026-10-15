"""Compile model Parts to whole-line regexes.

Upstream compiles every command regex through ``Pattern2.compileInternal`` with
``Pattern.CASE_INSENSITIVE`` (``regex/Pattern2.java:114`` at 97a5992) and matches the
whole trimmed line (``Matcher.matches()``; ``command/SingleLineCommand2.java:102``,
``command/CommandMultilines2.java:98``). The same is done here: ``{regex}`` leaves are
case-insensitive only when the model says so: ``{regex, ci: true}`` and ``{literal, ci}``
leaves are wrapped in ``(?i:...)`` / ``(?-i:...)`` according to ``ci`` (absent = case
sensitive). The translator sets ``ci: true`` on Pattern2-compiled regexes.
Patterns such as ``\\p{L}`` need the ``regex`` module, never ``re``.

Known gap: Python's default Unicode ``\\w``/``\\s``/``\\b`` and case folding are broader
than Java's ASCII defaults. The ``regex.ASCII`` flag would fix that but also disables
``\\p{L}`` on non-ASCII text, which upstream's ``%pLN`` relies on, so it is not used.
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

import regex

from tools.model import Part

FLAGS = 0
LIST_JOINERS = {"seq": "", "alt": "|"}
QUANTIFIERS = {"opt": "?", "star": "*", "plus": "+"}


class PartError(ValueError):
    """A Part that is neither a known form nor free of unresolved ``ref``."""


def part_to_regex(part: Part) -> str:
    """Translate a resolved Part to a regex source string (no anchors added)."""
    for key, joiner in LIST_JOINERS.items():
        if key in part:
            return "(?:" + joiner.join(part_to_regex(p) for p in part[key]) + ")"
    for key, quantifier in QUANTIFIERS.items():
        if key in part:
            return "(?:" + part_to_regex(part[key]) + ")" + quantifier
    if "regex" in part:
        return _case_mode(part) + str(part["regex"]) + ")"
    if "literal" in part:
        return _case_mode(part) + str(regex.escape(part["literal"])) + ")"
    raise PartError(f"unresolved or unknown Part: {sorted(part)}")


def _case_mode(part: Part) -> str:
    return "(?i:" if part.get("ci") else "(?-i:"


def part_key(part: Part) -> str:
    """A stable cache key for a Part."""
    return json.dumps(part, sort_keys=True, separators=(",", ":"))


@cache
def _compile_source(source: str) -> Any:
    return regex.compile(source, FLAGS)


@cache
def _compile_key(key: str) -> Any:
    return _compile_source(part_to_regex(json.loads(key)))


def compile_part(part: Part) -> Any:
    """Compile (memoized per distinct Part) a pattern for ``fullmatch`` on a line."""
    return _compile_key(part_key(part))

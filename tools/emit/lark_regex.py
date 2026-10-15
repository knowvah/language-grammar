"""Regex to Lark terminal translation helpers (see ``tools.emit.lark`` for the shape).

Lark's dynamic lexer takes ONE ``regex.match`` at a position and ``dynamic_complete`` only
retries *shorter* prefixes of it, so everything upstream's backtracking would do must be
reachable by shortening a maximal first match: lazy quantifiers become greedy, alternatives
that extend earlier ones move first, and no terminal may cross a line end.
"""

from __future__ import annotations

import re

from lark.utils import get_regexp_width

from tools.emit.linebound import line_bounded
from tools.model import Part

EOL_LOOKAHEAD = r"(?=[ \t]*(?:\r?\n|\Z))"
NULLABLE_PREFIX = r"(?V0)(?=[\s\S])(?:"
_PLAIN = r"(?:[^()\[\]{}|*+?.^$\\\r\n]|\\[^\w\s])+"
_WORD_ALTERNATION = re.compile(rf"(?P<open>\((?:\?:)?)(?P<alts>{_PLAIN}(?:\|{_PLAIN})+)\)")
LAZY_AFTER = "*+?}"
GROUP_HEAD_END = ":=!>)"
ESCAPE = "\\"


def strip_anchors(pattern: str) -> str:
    """Drop a leading ``^`` and a trailing unescaped ``$`` (lines are delimited by ``_NL``)."""
    if pattern.startswith("^"):
        pattern = pattern[1:]
    body = pattern[:-1]
    escapes = len(body) - len(body.rstrip("\\"))
    if pattern.endswith("$") and escapes % 2 == 0:
        return body
    return pattern


def prefer_longest(pattern: str) -> str:
    r"""Reorder plain-word alternations ``(par|partition)`` longest first.

    Upstream's backtracking regex tries every alternative; Lark's terminal match takes the
    first alternative that matches and ``dynamic_complete`` only shortens it afterwards, so
    a shorter alternative that is a prefix of a longer one (``par`` / ``partition``) would
    otherwise shadow it. Groups made solely of plain alternatives (words, spaces, escaped
    punctuation) are sorted longest first; in every other alternation (``lift_prefixed``) an
    alternative that starts with the full text of an earlier one is moved before it, so
    ``A|A\[H\]`` becomes ``A\[H\]|A``. The set of strings the pattern matches does not
    change, only which alternative a first (non-backtracking) match prefers.
    """
    return lift_prefixed(_WORD_ALTERNATION.sub(_longest_first, pattern))


def greedy(pattern: str) -> str:
    """Make every lazy quantifier greedy (``.+?`` -> ``.+``), outside character classes.

    The lexer takes one match at a position and ``dynamic_complete`` only tries *shorter*
    prefixes of it, never longer ones. A lazy quantifier would therefore pin the match to
    its minimum (``(.*?)`` -> empty, ``<<.+?>>`` -> the first stereotype only); greedy
    plus shortening reaches every length the backtracking upstream regex could produce.
    """
    out: list[str] = []
    in_class = escaped = after_quantifier = False
    for char in pattern:
        if escaped:
            escaped = after_quantifier = False
        elif char == "\\":
            escaped = True
        elif in_class:
            in_class = char != "]"
            after_quantifier = False
        elif char == "[":
            in_class = True
            after_quantifier = False
        elif char == "?" and after_quantifier:
            after_quantifier = False
            continue
        else:
            after_quantifier = char in LAZY_AFTER
        out.append(char)
    return "".join(out)


def _longest_first(found: re.Match[str]) -> str:
    alternatives = sorted(found["alts"].split("|"), key=len, reverse=True)
    return found["open"] + "|".join(alternatives) + ")"


def _escape_slashes(pattern: str) -> str:
    out: list[str] = []
    chars = iter(pattern)
    for char in chars:
        if char == "\\":
            out.append(char + next(chars, ""))
        elif char == "/":
            out.append("\\/")
        else:
            out.append(char.replace("\n", "\\n"))
    return "".join(out)


def regex_terminal(pattern: str, ci: bool = False, eol: bool = False) -> tuple[str, bool]:
    """Lark ``/.../`` literal for ``pattern`` (flag ``i`` when ``ci``) and whether it
    needed the nullable guard. With ``eol`` the match must end at the line end (the
    stripped ``$``), so lazy and greedy quantifiers both reach it."""
    pattern = greedy(prefer_longest(line_bounded(strip_anchors(pattern))))
    nullable = get_regexp_width(pattern)[0] == 0
    if eol:
        pattern = f"(?:{pattern}){EOL_LOOKAHEAD}"
    if nullable:
        pattern = NULLABLE_PREFIX + pattern + ")"
    return "/" + _escape_slashes(pattern) + "/" + ("i" if ci else ""), nullable


def nullable_part(part: Part) -> bool:
    """Whether ``part`` can match the empty string."""
    if "seq" in part:
        return all(nullable_part(p) for p in part["seq"])
    if "alt" in part:
        return any(nullable_part(p) for p in part["alt"])
    if "opt" in part or "star" in part:
        return True
    if "plus" in part:
        return nullable_part(part["plus"])
    if "regex" in part:
        return get_regexp_width(strip_anchors(part["regex"]))[0] == 0
    return False


def _class_end(pattern: str, start: int) -> int:
    """Index just after the character class opening at start ([)."""
    i = start + 1
    if pattern[i : i + 1] == "^":
        i += 1
    if pattern[i : i + 1] == "]":
        i += 1
    while i < len(pattern) and pattern[i] != "]":
        i += 2 if pattern[i] == ESCAPE else 1
    return i + 1


def _group_head(pattern: str, start: int) -> int:
    """Index just after the opening of the group at start ((, (?:, (?<=...)."""
    if pattern[start + 1 : start + 2] != "?":
        return start + 1
    i = start + 2
    while i < len(pattern) and pattern[i] not in GROUP_HEAD_END:
        i += 1
    return i if pattern[i : i + 1] == ")" else i + 1


def _lift(alternatives: list[str]) -> list[str]:
    ordered: list[str] = []
    for alt in alternatives:
        at = next(
            (
                k
                for k, prior in enumerate(ordered)
                if prior and alt != prior and alt.startswith(prior)
            ),
            len(ordered),
        )
        ordered.insert(at, alt)
    return ordered


def _alternation(pattern: str, start: int) -> tuple[str, int]:
    """Reorder the alternation beginning at start; returns (text, index of its ")")."""
    alternatives: list[str] = []
    current: list[str] = []
    i = start
    while i < len(pattern) and pattern[i] != ")":
        char = pattern[i]
        step = i + 1
        if char == ESCAPE:
            current.append(pattern[i : i + 2])
            step = i + 2
        elif char == "[":
            step = _class_end(pattern, i)
            current.append(pattern[i:step])
        elif char == "(":
            body = _group_head(pattern, i)
            inner, close = _alternation(pattern, body)
            current.append(pattern[i:body] + inner + pattern[close : close + 1])
            step = close + 1
        elif char == "|":
            alternatives.append("".join(current))
            current = []
        else:
            current.append(char)
        i = step
    alternatives.append("".join(current))
    return "|".join(_lift(alternatives)), i


def lift_prefixed(pattern: str) -> str:
    r"""Move every alternative that starts with the text of an earlier alternative before it.

    Applies to each alternation, top level included: ``A|A\[H\*?\]`` becomes
    ``A\[H\*?\]|A``. Escapes and character classes are opaque; group openers
    (``(?:``, ``(?=``, ``(?<name>``) are kept as written.
    """
    return _alternation(pattern, 0)[0]

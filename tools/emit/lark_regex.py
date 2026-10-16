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
from tools.model.java_regex import literal_to_python, to_python

EOL_LOOKAHEAD = r"(?=[ \t]*(?:\r?\n|\Z))"
LINE_END = r"(?=\r|\n|\Z)"  # `$` / `\Z` inside a terminal: the end of its line
# `$` inside a fused guard: no `\Z`, because dynamic_complete re-matches a guarded terminal
# against its own truncated text, where `\Z` would be a false line end. A body line is
# always followed by a newline (the block's end line comes after it).
GUARD_LINE_END = r"(?=\r|\n)"
# Emitter-internal Part keys set by ``tools.emit.guards`` (never in a model file).
PRE_KEY = "_pre"  # guards, as (model regex, ci) pairs, checked before the terminal
POST_KEY = "_post"  # guards checked after it
NONEMPTY_KEY = "_nonempty"  # the non-empty form of a nullable regex
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


QUOTE_ESCAPE = r"\x22"


def render_literal_body(pattern: str) -> str:
    r"""``pattern`` escaped for the body of a Lark ``/.../`` regex literal.

    Lark runs ``eval_escaping`` on the body (lark/load_grammar.py): it doubles every ``\\``
    and then replaces ``\"`` by ``"`` anywhere, so the regex ``\\"`` (escaped backslash,
    quote) reached the lexer as ``\"`` (an escaped quote) and never matched a backslash.
    A quote written as ``\x22`` is untouched by that replacement (``literal_eval`` turns it
    into the character afterwards), so every ``"`` -- bare or escaped -- is emitted that way,
    and ``/`` as ``\/``. A newline is written ``\n``.
    """
    out: list[str] = []
    chars = iter(pattern)
    for char in chars:
        if char == "\\":
            following = next(chars, "")
            out.append(QUOTE_ESCAPE if following == '"' else char + following)
        elif char == "/":
            out.append("\\/")
        elif char == '"':
            out.append(QUOTE_ESCAPE)
        else:
            out.append(char.replace("\n", "\\n"))
    return "".join(out)


def lark_pattern(pattern: str, ci: bool = False) -> str:
    """THE model-regex -> Lark-terminal-regex translation (one place for every rewrite).

    Every regex that reaches a Lark terminal, and every static width check on one
    (``regex_terminal``, ``nullable_part``), goes through this function. Stages, in order:
    drop the ``^`` / ``$`` anchors; give the Java text Python-``regex`` meaning
    (``tools.model.java_regex.to_python``: ASCII classes, line-bounded ``.``, ASCII case
    folding as explicit ``[aA]`` classes for ``ci``, any remaining ``$`` / ``\\Z`` as a line
    end, never the end of the whole text); bound the pattern to one line; put alternatives
    that extend an earlier one first; make lazy quantifiers greedy. Terminals carry no Lark
    ``i`` flag: that flag folds Unicode, Java's ``CASE_INSENSITIVE`` folds ASCII only.
    """
    java = to_python(strip_anchors(pattern), ci=ci, end_anchor=LINE_END)
    return greedy(prefer_longest(line_bounded(java)))


def guard_pattern(pattern: str, ci: bool = False) -> str:
    """``lark_pattern`` for a fused guard: anchors kept, ``$`` is ``GUARD_LINE_END``."""
    java = to_python(pattern, ci=ci, end_anchor=GUARD_LINE_END)
    return greedy(prefer_longest(line_bounded(java)))


def regex_terminal(pattern: str, ci: bool = False, eol: bool = False) -> tuple[str, bool]:
    """Lark ``/.../`` literal for ``pattern`` (``ci`` folds ASCII case inside the pattern)
    and whether it needed the nullable guard. With ``eol`` the match must end at the line
    end (the stripped ``$``), so lazy and greedy quantifiers both reach it."""
    return python_terminal(lark_pattern(pattern, ci), eol)


def part_terminal(part: Part, eol: bool = False) -> tuple[str, bool]:
    """``regex_terminal`` for a regex or literal Part with the guards fused into it."""
    ci = bool(part.get("ci"))
    if "regex" in part:
        core = lark_pattern(part["regex"], ci)
    else:
        core = literal_to_python(part["literal"], ci=ci)
    pre = "".join(f"(?:{guard_pattern(g, gci)})" for g, gci in part.get(PRE_KEY, ()))
    post = "".join(f"(?:{guard_pattern(g, gci)})" for g, gci in part.get(POST_KEY, ()))
    if pre or post:
        core = f"{pre}(?:{core}){post}"
    return python_terminal(core, eol)


def python_terminal(pattern: str, eol: bool) -> tuple[str, bool]:
    """Lark literal for a translated pattern (see ``regex_terminal``)."""
    nullable = get_regexp_width(pattern)[0] == 0
    if eol:
        pattern = f"(?:{pattern}){EOL_LOOKAHEAD}"
    if nullable:
        pattern = NULLABLE_PREFIX + pattern + ")"
    return "/" + render_literal_body(pattern) + "/", nullable


def nullable_part(part: Part) -> bool:
    """Whether ``part`` can match the empty string."""
    if part.get(NONEMPTY_KEY):
        return False
    if "seq" in part:
        return all(nullable_part(p) for p in part["seq"])
    if "alt" in part:
        return any(nullable_part(p) for p in part["alt"])
    if "opt" in part or "star" in part:
        return True
    if "plus" in part:
        return nullable_part(part["plus"])
    if "regex" in part:
        return get_regexp_width(lark_pattern(part["regex"], bool(part.get("ci"))))[0] == 0
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

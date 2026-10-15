"""Rewrite a regex so it can never match a line end (``\\r`` or ``\\n``).

Upstream matches every command regex against one trimmed line. Lark's dynamic lexer matches
a terminal against the whole text, so ``\\s``, ``[^#]`` or ``\\W`` would run across ``\\n``
and swallow following lines. ``line_bounded`` rewrites each construct that can match a line
end so the terminal stays inside its line:

* ``\\s`` -> ``[^\\S\\r\\n]``; inside a class the explicit whitespace set without ``\\r\\n``.
* every negated class gains ``\\r\\n`` (``[^#]`` -> ``[^\\r\\n#]``).
* ``.`` -> ``[^\\r\\n]`` (``.`` already excludes ``\\n`` but not ``\\r``).
* ``\\W``, ``\\D`` and negated properties (``\\P{L}``, ``\\p{^L}``), alone or inside a positive
  class, are guarded with ``(?![\\r\\n])``.

``\\S`` needs no rewrite: it never matches whitespace. Constructs that name a line end
literally (``\\n``) are left alone.
"""

from __future__ import annotations

LINE_END = r"\r\n"
SPACE_CLASS = r"[^\S\r\n]"
# \s without \r and \n: ASCII space, tab, VT, FF and the Unicode spaces ``regex`` accepts.
SPACE_CHARS = " \\t\x0b\x0c\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000"
ANY_BUT_LINE_END = f"[^{LINE_END}]"
GUARD = f"(?![{LINE_END}])"
NEGATED_SHORTHANDS = frozenset("WD")
PROPERTY = "pP"
NEGATION = "^"
CLASS_CLOSE = "]"
POSIX_OPEN = "[:"
POSIX_CLOSE = ":]"


def _property_end(pattern: str, index: int) -> int:
    """Index after the ``\\p`` / ``\\P`` escape starting at ``index``."""
    if pattern.startswith("{", index + 2):
        close = pattern.find("}", index + 2)
        return len(pattern) if close < 0 else close + 1
    return min(index + 3, len(pattern))


def _property_negated(escape: str) -> bool:
    """Whether ``\\P{L}`` / ``\\p{^L}`` (a complement, so it matches ``\\n``)."""
    negated = escape[1] == "P"
    name = escape[3:] if escape[2:3] == "{" else ""
    return negated != name.startswith(NEGATION)


def _escape(pattern: str, index: int) -> tuple[str, int, bool]:
    """``(text, next index, can match a line end)`` of the escape at ``index``."""
    kind = pattern[index + 1 : index + 2]
    if kind in PROPERTY and kind:
        end = _property_end(pattern, index)
        text = pattern[index:end]
        return text, end, _property_negated(text)
    return pattern[index : index + 2], index + 2, kind in NEGATED_SHORTHANDS


def _class(pattern: str, start: int) -> tuple[str, int]:
    """Rewrite the character class opening at ``start``; returns it and the next index."""
    index = start + 1
    negated = pattern.startswith(NEGATION, index)
    index += negated
    parts: list[str] = []
    unsafe = False
    first = True
    while index < len(pattern) and (pattern[index] != CLASS_CLOSE or first):
        char = pattern[index]
        if char == "\\" and pattern[index + 1 : index + 2] == "s":
            parts.append(SPACE_CHARS)
            index += 2
        elif char == "\\":
            text, index, matches_newline = _escape(pattern, index)
            parts.append(text)
            unsafe = unsafe or matches_newline
        elif pattern.startswith(POSIX_OPEN, index):
            end = pattern.find(POSIX_CLOSE, index)
            end = len(pattern) if end < 0 else end + len(POSIX_CLOSE)
            parts.append(pattern[index:end])
            index = end
        else:
            parts.append("\\]" if char == CLASS_CLOSE else char)
            index += 1
        first = False
    body = "".join(parts)
    index += 1
    if negated:
        return f"[^{LINE_END}{body}]", index
    if unsafe:
        return f"(?:{GUARD}[{body}])", index
    return f"[{body}]", index


def line_bounded(pattern: str) -> str:
    """``pattern`` rewritten so it cannot match ``\\r`` or ``\\n`` (see module doc)."""
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "[":
            text, index = _class(pattern, index)
        elif char == "\\" and pattern[index + 1 : index + 2] == "s":
            text, index = SPACE_CLASS, index + 2
        elif char == "\\":
            text, index, matches_newline = _escape(pattern, index)
            text = f"(?:{GUARD}{text})" if matches_newline else text
        elif char == ".":
            text, index = ANY_BUT_LINE_END, index + 1
        else:
            text, index = char, index + 1
        out.append(text)
    return "".join(out)

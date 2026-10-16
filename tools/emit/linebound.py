"""Rewrite a regex so it can never match a line end (``\\r`` or ``\\n``).

Upstream matches every command regex against one trimmed line. Lark's dynamic lexer matches
a terminal against the whole text, so ``\\s``, ``[^#]`` or ``\\W`` would run across ``\\n``
and swallow following lines. ``line_bounded`` rewrites each construct that can match a line
end so the terminal stays inside its line:

* ``\\s`` -> ``[^\\S\\r\\n]``; inside a class the explicit whitespace set without ``\\r\\n``.
* every negated class gains ``\\r\\n`` (``[^#]`` -> ``[^\\r\\n#]``).
* ``.`` -> ``[^\\r\\n]`` (``.`` already excludes ``\\n`` but not ``\\r``).
* a positive class loses ``\\n`` and ``\\r`` wherever it names them -- escapes, raw characters,
  ``\\x0a`` / ``\\u000d`` and ranges such as ``\\t-\\r`` (split around them); a class left empty
  becomes ``[^\\x00-\\U0010ffff]`` (never matches,
  one character wide; ``[^\\s\\S]`` would match anything in ``regex``).
  Ranges are rewritten only when both ends are single code points.
* ``\\W``, ``\\D`` and negated properties (``\\P{L}``, ``\\p{^L}``), alone or inside a positive
  class, are guarded with ``(?![\\r\\n])``.

``\\S`` needs no rewrite: it never matches whitespace. Constructs that name a line end
literally (``\\n``) are left alone.
"""

from __future__ import annotations

import re

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
NEWLINE, CARRIAGE_RETURN = 10, 13
NEVER = r"[^\x00-\U0010ffff]"
CODE_ESCAPES = {"n": 10, "r": 13, "t": 9, "f": 12, "v": 11, "0": 0}
HEX_ESCAPE = re.compile(r"\\(?:x([0-9A-Fa-f]{2})|u([0-9A-Fa-f]{4})|x\{([0-9A-Fa-f]+)\})")


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


def _code_point(pattern: str, index: int) -> tuple[int, int] | None:
    """``(code point, next index)`` of the one-character class member at ``index``, if it is one."""
    char = pattern[index]
    if char != "\\":
        return ord(char), index + 1
    hexed = HEX_ESCAPE.match(pattern, index)
    if hexed:
        return int(next(g for g in hexed.groups() if g), 16), hexed.end()
    kind = pattern[index + 1 : index + 2]
    if kind in CODE_ESCAPES:
        return CODE_ESCAPES[kind], index + 2
    if kind and not kind.isalnum():
        return ord(kind), index + 2
    return None


def _code_text(code: int) -> str:
    return (
        f"\\x{code:02x}"
        if code <= 0xFF
        else f"\\u{code:04x}"
        if code <= 0xFFFF
        else f"\\U{code:08x}"
    )


def _pieces(low: int, high: int) -> str:
    """The range ``low``-``high`` without ``\\n`` and ``\\r``, as class text."""
    text: list[str] = []
    start = low
    for line_end in (NEWLINE, CARRIAGE_RETURN):
        if start <= line_end <= high:
            text.append(_range_text(start, line_end - 1))
            start = line_end + 1
    text.append(_range_text(start, high))
    return "".join(text)


def _range_text(low: int, high: int) -> str:
    if low > high:
        return ""
    if low == high:
        return _code_text(low)
    return f"{_code_text(low)}-{_code_text(high)}"


def _member(pattern: str, index: int) -> tuple[str, int] | None:
    """Rewrite a literal member or range of a *positive* class so it excludes ``\\r\\n``.

    Returns ``(text, next index)``; ``None`` when the member is not a plain code point (a
    shorthand such as ``\\w`` or a property), which ``_class`` handles itself.
    """
    first = _code_point(pattern, index)
    if first is None:
        return None
    low, end = first
    high = low
    if pattern.startswith("-", end) and pattern[end + 1 : end + 2] not in ("", CLASS_CLOSE):
        second = _code_point(pattern, end + 1)
        if second is not None and second[0] >= low:
            high, end = second
    if not any(low <= line_end <= high for line_end in (NEWLINE, CARRIAGE_RETURN)):
        text = pattern[index:end]
        return ("\\]" if text == CLASS_CLOSE else text), end
    return _pieces(low, high), end


def _opaque_member(pattern: str, index: int) -> tuple[str, int, bool]:
    """``(text, next index, can match a line end)`` of a member ``_member`` does not rewrite."""
    if pattern[index : index + 2] == "\\s":
        return SPACE_CHARS, index + 2, False
    if pattern[index] == "\\":
        return _escape(pattern, index)
    if pattern.startswith(POSIX_OPEN, index):
        end = pattern.find(POSIX_CLOSE, index)
        end = len(pattern) if end < 0 else end + len(POSIX_CLOSE)
        return pattern[index:end], end, False
    char = pattern[index]
    return ("\\]" if char == CLASS_CLOSE else char), index + 1, False


def _next_member(pattern: str, index: int, negated: bool) -> tuple[str, int, bool]:
    """``(text, next index, can match a line end)`` of the class member at ``index``."""
    if not negated and not pattern.startswith(POSIX_OPEN, index):
        member = _member(pattern, index)
        if member is not None:
            return member[0], member[1], False
    return _opaque_member(pattern, index)


def _class(pattern: str, start: int) -> tuple[str, int]:
    """Rewrite the character class opening at ``start``; returns it and the next index."""
    index = start + 1
    negated = pattern.startswith(NEGATION, index)
    index += negated
    body_start = index
    parts: list[str] = []
    unsafe = False
    while index < len(pattern) and (pattern[index] != CLASS_CLOSE or index == body_start):
        text, index, matches_newline = _next_member(pattern, index, negated)
        parts.append(text)
        unsafe = unsafe or matches_newline
    body = "".join(parts)
    if negated:
        return f"[^{LINE_END}{body}]", index + 1
    if not body:
        return NEVER, index + 1
    return (f"(?:{GUARD}[{body}])" if unsafe else f"[{body}]"), index + 1


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

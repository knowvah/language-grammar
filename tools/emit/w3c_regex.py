"""Regex to W3C EBNF translation (see ``tools.emit.w3c`` for the conventions)."""

from __future__ import annotations

import re

from tools.emit.w3c_text import (
    ANY_CHAR,
    ATOM,
    BACKREFERENCE,
    DROPPED_ESCAPES,
    EMPTY_TEXT,
    INLINE_FLAGS,
    LARGE_REPEAT,
    LOOKAROUND,
    MAX_REPEAT,
    QUANTS,
    SEQ,
    SHORTHANDS,
    SIMPLE_ESCAPES,
    UNICODE_PROPERTY,
    UNSUPPORTED,
    WORD_BOUNDARY,
    Node,
    Ranges,
    Sink,
    ci_char,
    comment,
    complement,
    fold_ascii,
    format_class,
    is_cased,
    join_alt,
    join_seq,
    quote,
    repeat,
)

_BOUND = re.compile(r"\{(\d+)(?:(,)(\d*))?\}")
_GROUP_PREFIX = re.compile(
    r"\(\?(?:(?P<plain>[:>])|P?<[A-Za-z_]\w*>|'\w+'|(?P<look><?[=!])|(?P<flags>[a-zA-Z-]*)(?P<end>[:)]))"
)


class _RegexParser:
    """Recursive-descent translation of one regex to a W3C expression."""

    def __init__(self, src: str, sink: Sink, rule: str, ci: bool) -> None:
        self.src, self.sink, self.rule, self.ci = src, sink, rule, ci
        self.pos = 0
        self.class_property = False

    def parse(self) -> Node:
        node = self._alt()
        if self.pos != len(self.src):
            raise IndexError(self.pos)
        return node

    def _peek(self) -> str:
        return self.src[self.pos] if self.pos < len(self.src) else ""

    def _alt(self) -> Node:
        branches = [self._seq()]
        while self._peek() == "|":
            self.pos += 1
            branches.append(self._seq())
        return join_alt(branches)

    def _seq(self) -> Node:
        items: list[Node] = []
        while self._peek() not in ("", "|", ")"):
            node = self._quantified()
            if node is not None:
                items.append(node)
        return join_seq(items)

    def _quantified(self) -> Node | None:
        start = self.pos
        atom = self._atom()
        bounds = self._quantifier()
        if atom is None or bounds is None:
            return atom
        lo, hi = bounds
        if max(lo, hi or 0) <= MAX_REPEAT:
            return repeat(atom, lo, hi)
        original = self.src[start : self.pos]
        self.sink.note(self.rule, LARGE_REPEAT, original)
        approx = repeat(atom, min(lo, 1), None)
        return Node(f"{approx.text} {comment(original)}", SEQ)

    def _quantifier(self) -> tuple[int, int | None] | None:
        char = self._peek()
        if char in QUANTS and char:
            self.pos += 1
            bounds = QUANTS[char]
        else:
            match = _BOUND.match(self.src, self.pos) if char == "{" else None
            if match is None:
                return None
            self.pos = match.end()
            lo = int(match[1])
            bounds = (lo, lo if match[2] is None else (int(match[3]) if match[3] else None))
        if self._peek() in ("?", "+") and self._peek():
            self.pos += 1
        return bounds

    def _literal(self, char: str) -> Node:
        if self.ci and is_cased(char):
            return Node(ci_char(char))
        return Node(quote(char).text, ATOM, lit=char)

    def _atom(self) -> Node | None:
        char = self._peek()
        if char == "(":
            return self._group()
        if char == "[":
            return self._class()
        if char == ".":
            self.pos += 1
            return Node(ANY_CHAR)
        if char in ("^", "$"):
            self.pos += 1
            return None
        if char == "\\":
            return self._escape()
        self.pos += 1
        return self._literal(char)

    def _lossy(self, construct: str, start: int, body: str) -> Node:
        return self.sink.placeholder(self.rule, construct, self.src[start : self.pos], body)

    # groups

    def _skip_group(self) -> None:
        """Advance past the balanced group starting at ``pos``."""
        depth = 0
        while self.pos < len(self.src):
            char = self.src[self.pos]
            self.pos += 1
            if char == "\\":
                self.pos += 1
            elif char == "[":
                self._skip_class_body()
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return

    def _skip_class_body(self) -> None:
        if self._peek() == "^":
            self.pos += 1
        if self._peek() == "]":
            self.pos += 1
        while self.pos < len(self.src) and self.src[self.pos] != "]":
            self.pos += 2 if self.src[self.pos] == "\\" else 1
        self.pos += 1

    def _group(self) -> Node | None:
        start = self.pos
        match = _GROUP_PREFIX.match(self.src, start) if self.src.startswith("(?", start) else None
        if self.src.startswith("(?", start) and match is None:
            self._skip_group()
            return self._lossy(UNSUPPORTED, start, ANY_CHAR + "*")
        if match is not None and match["look"]:
            self._skip_group()
            return self._lossy(LOOKAROUND, start, EMPTY_TEXT)
        if match is not None and match["end"]:
            return self._flags(match)
        self.pos = match.end() if match else start + 1
        return self._group_body()

    def _group_body(self) -> Node:
        saved = self.ci
        node = self._alt()
        self.pos += 1  # ')'
        self.ci = saved
        return node

    def _flags(self, match: re.Match[str]) -> Node | None:
        on, _, off = match["flags"].partition("-")
        extra = set(on + off) - {"i"}
        if extra:
            self.sink.note(self.rule, INLINE_FLAGS, match[0])
        self.pos = match.end()
        if match["end"] == ":":
            saved = self.ci
            self.ci = self._flag_value(on, off)
            node = self._group_body()
            self.ci = saved
            return node
        self.ci = self._flag_value(on, off)
        return None

    def _flag_value(self, on: str, off: str) -> bool:
        return "i" in on or (self.ci and "i" not in off)

    # escapes and classes

    def _property(self) -> None:
        """Consume ``\\p{..}`` / ``\\pL`` (pos is at the backslash)."""
        self.pos += 2
        if self._peek() == "{":
            end = self.src.find("}", self.pos)
            self.pos = len(self.src) if end < 0 else end + 1
        else:
            self.pos += 1

    def _hex_escape(self) -> int:
        kind = self.src[self.pos + 1]
        self.pos += 2
        if self._peek() == "{":
            end = self.src.index("}", self.pos)
            digits, self.pos = self.src[self.pos + 1 : end], end + 1
        else:
            width = 2 if kind == "x" else 4
            digits, self.pos = self.src[self.pos : self.pos + width], self.pos + width
        return int(digits, 16)

    def _escape(self) -> Node | None:
        start, char = self.pos, self.src[self.pos + 1]
        if char in "pP":
            self._property()
            return self._lossy(UNICODE_PROPERTY, start, ANY_CHAR)
        if char in "xu":
            return self._literal(chr(self._hex_escape()))
        self.pos += 2
        if char in "bB":
            return self._lossy(WORD_BOUNDARY, start, EMPTY_TEXT)
        if char in DROPPED_ESCAPES:
            return None
        if char.isdigit() and char != "0" or char == "k":
            return self._backreference(start, char)
        if char.lower() in SHORTHANDS:
            return Node(self._shorthand(char))
        return self._literal(chr(SIMPLE_ESCAPES[char]) if char in SIMPLE_ESCAPES else char)

    def _backreference(self, start: int, char: str) -> Node:
        if char == "k":
            end = self.src.find(">", self.pos)
            self.pos = len(self.src) if end < 0 else end + 1
        else:
            while self._peek().isdigit() and self._peek():
                self.pos += 1
        return self._lossy(BACKREFERENCE, start, ANY_CHAR + "*")

    def _shorthand(self, char: str) -> str:
        ranges = SHORTHANDS[char.lower()]
        return format_class(fold_ascii(ranges) if self.ci else ranges, char.isupper())

    def _class(self) -> Node:
        start = self.pos
        self.pos += 1
        negated = self._peek() == "^"
        self.pos += negated
        ranges: Ranges = []
        self.class_property = False
        first = True
        while self._peek() != "]" or first:
            first = False
            ranges.extend(self._class_members())
        self.pos += 1
        if self.class_property:
            return self._lossy(UNICODE_PROPERTY, start, ANY_CHAR)
        return Node(format_class(fold_ascii(ranges) if self.ci else ranges, negated))

    def _class_members(self) -> Ranges:
        """Ranges contributed by the next class item (and a following ``-hi``)."""
        item = self._class_item()
        if item is None:
            self.class_property = True
            return []
        if isinstance(item, list):
            return item
        if self._peek() != "-" or self.src[self.pos + 1 : self.pos + 2] in ("]", ""):
            return [(item, item)]
        self.pos += 1
        hi = self._class_item()
        if isinstance(hi, int):
            return [(item, hi)]
        if hi is None:
            self.class_property = True
            return [(item, item)]
        return [(item, item), (ord("-"), ord("-")), *hi]

    def _class_item(self) -> int | Ranges | None:
        char = self.src[self.pos]
        if char != "\\":
            self.pos += 1
            return ord(char)
        esc = self.src[self.pos + 1]
        if esc in "pP":
            self._property()
            return None
        if esc in "xu":
            return self._hex_escape()
        self.pos += 2
        if esc.lower() in SHORTHANDS:
            ranges = SHORTHANDS[esc.lower()]
            return complement(ranges) if esc.isupper() else list(ranges)
        if esc == "b":
            return 8
        return SIMPLE_ESCAPES.get(esc, ord(esc))


def translate_regex(pattern: str, sink: Sink, rule: str) -> Node:
    """W3C expression for ``pattern``; unparseable patterns become one placeholder."""
    try:
        return _RegexParser(pattern, sink, rule, ci=False).parse()
    except (IndexError, ValueError):
        return sink.placeholder(rule, UNSUPPORTED, pattern, ANY_CHAR + "*")

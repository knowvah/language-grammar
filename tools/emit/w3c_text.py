"""Text-level helpers for the W3C EBNF emitter: nodes, literals, classes, lossiness sink."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tools.emit.lark import _Names

MAX_CODEPOINT = 0x10FFFF
MAX_REPEAT = 16
LOSSY_SUFFIX = "_lossy"
ATOM, SEQ, ALT = "atom", "seq", "alt"
LOOKAROUND = "lookaround"
BACKREFERENCE = "backreference"
UNICODE_PROPERTY = "unicode-property"
WORD_BOUNDARY = "word-boundary"
INLINE_FLAGS = "inline-flags"
LARGE_REPEAT = "large-repeat"
UNSUPPORTED = "unsupported-construct"
ANY_CHAR = "[^#xA#xD]"
EMPTY_TEXT = '""'
NOT_EOL = "[^#xD#xA]"
INLINE_WS = "[#x20#x9]"
PRELUDE = (
    "NL ::= #xD? #xA",
    f"WS ::= {INLINE_WS}+",
    f"BODY_LINE ::= {NOT_EOL}+",
    f'BRACKET_CLOSE ::= {INLINE_WS}* "}}"',
)
BRACKET_CLOSE = "BRACKET_CLOSE"

Ranges = list[tuple[int, int]]
SHORTHANDS: dict[str, Ranges] = {
    "s": [(9, 13), (32, 32)],
    "d": [(48, 57)],
    "w": [(48, 57), (65, 90), (95, 95), (97, 122)],
}
SIMPLE_ESCAPES = {"t": 9, "n": 10, "r": 13, "f": 12, "v": 11, "e": 27, "a": 7, "0": 0}
DROPPED_ESCAPES = frozenset("AzZG")
CLASS_SAFE = re.compile(r"[A-Za-z0-9_]")
QUANTS = {"?": (0, 1), "*": (0, None), "+": (1, None)}


@dataclass(frozen=True)
class Lossy:
    """One construct the W3C notation cannot express exactly."""

    rule: str
    construct: str
    regex: str


@dataclass(frozen=True)
class Node:
    """A translated expression and how tightly it binds (``ATOM``/``SEQ``/``ALT``)."""

    text: str
    kind: str = ATOM
    lit: str | None = None


EMPTY = Node(EMPTY_TEXT)


@dataclass
class Sink:
    """Collects lossiness entries and the placeholder productions they create."""

    names: _Names
    lossy: list[Lossy] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    def note(self, rule: str, construct: str, original: str) -> None:
        self.lossy.append(Lossy(rule, construct, original))

    def placeholder(self, rule: str, construct: str, original: str, body: str) -> Node:
        self.note(rule, construct, original)
        name = self.names.unique(f"{rule}{LOSSY_SUFFIX}")
        self.lines.append(f"{name} ::= {body} {comment(original)}")
        return Node(name)

    def drain(self) -> list[str]:
        lines, self.lines = self.lines, []
        return lines


def comment(original: str) -> str:
    """A ``/* regex: ... */`` comment that cannot terminate early."""
    safe = original.replace("*/", "* /").replace("\n", "\\n").replace("\r", "\\r")
    return f"/* regex: {safe} */"


# --- literals and classes ---------------------------------------------------------------


def _hex(code: int) -> str:
    return f"#x{code:X}"


def _class_char(code: int) -> str:
    char = chr(code)
    return char if CLASS_SAFE.fullmatch(char) else _hex(code)


def _normalize(ranges: Ranges) -> Ranges:
    merged: Ranges = []
    for lo, hi in sorted(ranges):
        if merged and lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
        else:
            merged.append((lo, hi))
    return merged


def complement(ranges: Ranges) -> Ranges:
    """Code points in ``0..MAX_CODEPOINT`` not covered by ``ranges``."""
    out: Ranges = []
    nxt = 0
    for lo, hi in _normalize(ranges):
        if lo > nxt:
            out.append((nxt, lo - 1))
        nxt = hi + 1
    if nxt <= MAX_CODEPOINT:
        out.append((nxt, MAX_CODEPOINT))
    return out


def fold_ascii(ranges: Ranges) -> Ranges:
    """Add the other ASCII case for every letter in ``ranges``."""
    extra: Ranges = []
    for lo, hi in ranges:
        for code in range(max(lo, 65), min(hi, 122) + 1):
            if chr(code).isalpha() and code < 128:
                extra.append((ord(chr(code).swapcase()),) * 2)
    return _normalize(ranges + extra) if extra else ranges


def format_class(ranges: Ranges, negated: bool = False) -> str:
    """W3C character class; ranges keep their given order (no sorting or merging)."""
    if not ranges:
        return f"[{'' if negated else '^'}#x0-{_hex(MAX_CODEPOINT)}]"
    body = "".join(
        _class_char(lo) if lo == hi else f"{_class_char(lo)}-{_class_char(hi)}" for lo, hi in ranges
    )
    return f"[{'^' if negated else ''}{body}]"


def quote(text: str) -> Node:
    """A W3C string expression for ``text`` (quotes and control chars use other forms)."""
    tokens: list[str] = []
    run = ""
    for char in text:
        if char == '"' or ord(char) < 0x20 or ord(char) == 0x7F:
            if run:
                tokens.append(f'"{run}"')
                run = ""
            tokens.append("'\"'" if char == '"' else _hex(ord(char)))
        else:
            run += char
    if run:
        tokens.append(f'"{run}"')
    if not tokens:
        return EMPTY
    return Node(" ".join(tokens), ATOM if len(tokens) == 1 else SEQ)


def is_cased(char: str) -> bool:
    """True when ``char`` has a distinct single-character other case."""
    lower, upper = char.lower(), char.upper()
    return len(lower) == 1 and len(upper) == 1 and lower != upper


def ci_char(char: str) -> str:
    """Two-character class for a cased letter, upper case first: ``c`` -> ``[Cc]``."""
    upper, lower = ord(char.upper()), ord(char.lower())
    return format_class([(upper, upper), (lower, lower)])


def ci_literal(text: str) -> Node:
    """Case-insensitive literal: ``[Cc][Ll][Aa][Ss][Ss]`` style."""
    items: list[Node] = []
    run = ""
    for char in text:
        if is_cased(char):
            if run:
                items.append(quote(run))
                run = ""
            items.append(Node(ci_char(char)))
        else:
            run += char
    if run:
        items.append(quote(run))
    return join_seq(items)


def paren(node: Node) -> Node:
    """``node`` as an atom (parenthesised unless already one)."""
    return node if node.kind == ATOM else Node(f"({node.text})")


def join_seq(nodes: list[Node]) -> Node:
    """Sequence; adjacent plain literal characters are merged into one string."""
    items: list[Node] = []
    run = ""
    for node in nodes:
        if node.lit is not None:
            run += node.lit
            continue
        if run:
            items.append(quote(run))
            run = ""
        items.append(node)
    if run:
        items.append(quote(run))
    if not items:
        return EMPTY
    if len(items) == 1:
        return items[0]
    return Node(" ".join(paren(i).text if i.kind == ALT else i.text for i in items), SEQ)


def join_alt(nodes: list[Node]) -> Node:
    """Alternation of ``nodes``."""
    if len(nodes) == 1:
        return nodes[0]
    return Node(" | ".join(n.text for n in nodes), ALT)


def repeat(node: Node, lo: int, hi: int | None) -> Node:
    """Apply a ``{lo,hi}`` bound (``hi=None`` is unbounded) to ``node``."""
    atom = paren(Node(node.text, node.kind))
    if (lo, hi) in QUANTS.values():
        return Node(atom.text + {v: k for k, v in QUANTS.items()}[(lo, hi)], SEQ)
    copies = [atom] * lo
    if hi is None:
        tail = Node(atom.text + "*")
        if lo:
            copies, tail = copies[:-1], Node(atom.text + "+")
        copies.append(tail)
    else:
        copies.extend([Node(atom.text + "?")] * (hi - lo))
    return join_seq(copies) if copies else EMPTY

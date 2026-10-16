"""Emit the command model as W3C EBNF (XML 1.0 section 6 notation), ``dist/plantuml.ebnf``.

The output renders as railroad diagrams on https://rr.red-dove.com/ui. It documents the
grammar; it is not executable. W3C notation has no case-insensitive literals, no
lookaround and no Unicode property classes, so the translation is lossy by design.

Conventions (repeated in the generated header):

* Case-insensitive literals: each cased letter becomes a two-character class, so ``class``
  is ``[Cc][Ll][Aa][Ss][Ss]``; uncased runs stay quoted literals.
* Regexes are translated construct by construct: classes, ``.``, ``\\s \\d \\w`` (ASCII
  semantics), groups, alternation and ``? * + {n,m}`` quantifiers (bounded ``{n,m}`` is
  expanded). Anchors ``^ $ \\A \\z \\Z`` are dropped (lines are delimited by ``NL``).
* Lossy constructs -- lookaround, word boundaries, backreferences, ``\\p{..}`` classes, and
  inline flags other than ``i`` -- become a placeholder production
  ``<rule>_lossy ::= <approximation> /* regex: <original> */`` and one ``Lossy`` entry.
* A regex Part with ``ci: true`` is case-folded with the same convention (each cased
  letter and class range gains its other case); absent ``ci`` is case-sensitive.
* ``multiline`` with ``join`` is approximated as a single line (only ``parts``), and
  skipped when ``parts`` require U+E100 on every path (``tools.emit.skip.needs_joiner``: no
  single line contains it); ``reject: true`` entries are dropped;
  ``multiline-bracket`` as a body closed by a line ``WS* "}"`` (bracket depth is not
  modelled).
* Structure mirrors the Lark emitter (``tools.emit.flow``, ``tools.emit.flow_rules``):
  ``push``/``set`` become newline-led block rules (``(NL line?)* (NL exit)``). A ``set``
  line in a pushed context embeds the target's block, so it replaces the frame instead of
  needing a second closing line; a block that is still open at the end of the body is a
  ``*_tail`` rule that can only be the last line of its parent (a push without
  ``require_pop``); in ``main`` ``pop`` entries are dropped and a ``set`` embeds
  the target's ``*_root`` block. Trailing blanks are
  allowed after a first line (``WS?``) and before an ``end`` part. Ordered alternatives
  become unordered ``|``. ``require_pop`` backtracking (the interpreter retries the pushing
  line when a body never closes) is not expressible.

Regex dialect: model regexes carry Java semantics (``docs/grammar-guide.md``, "Regex
semantics"). Only the Lark emitter converts them with ``tools.model.java_regex.to_python``,
because Lark runs on Python's ``regex`` module. This emitter targets a notation and keeps
the model text, applying its own ASCII conventions above; TextMate targets Oniguruma
(``(?i)`` there is Unicode-folding, a known approximation). Neither is routed through
``to_python``.

Framing: blocks follow ``tools.emit.keywords`` (a model sits under every start keyword whose
``start_map`` factory list names its factory) and end at one shared ``END_BLOCK`` that accepts
any ``@end...`` / ``\\end...`` line. ``block_other`` stands for a start word no keyword covers
(``PSystemUnsupported``, accepted upstream); its keyword exclusion is a lookahead, so the
production overlaps the keyword starts and the header says so.

``emit_w3c`` returns the text (the ``tools.emit.build`` contract); ``emit_w3c_with_lossiness``
also returns the lossiness entries. The header states the total and a per-construct tally.

Contract keys ignored by this emitter: ``gives``/``needs`` (diagram flags, final-state
checks) are ignored; ``trim: false`` is ignored (the emitted pattern is matched against
the trimmed line); ``emit: false`` entries are dropped like ``reject`` (see ``skip.py``).
"""

from __future__ import annotations

from collections import Counter

from tools.emit import flow
from tools.emit.flow_rules import FlowBuilder
from tools.emit.keywords import (
    UML_KEYWORD,
    document_start_map,
    start_keywords,
)
from tools.emit.lark import (
    KIND_BRACKET,
    KIND_MULTILINE,
    _Names,
)
from tools.emit.tops import emitted_diagrams
from tools.emit.w3c_regex import translate_regex
from tools.emit.w3c_text import (
    BRACKET_CLOSE,
    INLINE_WS,
    NOT_EOL,
    PRELUDE,
    SEQ,
    Lossy,
    Node,
    Sink,
    ci_literal,
    join_alt,
    join_seq,
    paren,
    quote,
)
from tools.model import Entry, Part, ResolvedModel, ResolvedModels


class _Diagram(FlowBuilder):
    """Builds the productions of one diagram-layer model."""

    def __init__(self, model: ResolvedModel, names: _Names, sink: Sink) -> None:
        super().__init__(model, names)
        self.sink = sink
        self.rules: list[str] = []

    def render(self) -> list[str]:
        """Productions for this model."""
        self.render_flow()
        return self.rules

    def add(self, name: str, text: str) -> None:
        self.rules.append(f"{name} ::= {text}")
        self.rules.extend(self.sink.drain())

    def choice(self, options: list[str]) -> str:
        return "(" + " | ".join(options) + ")"

    def entry_expr(self, entry: Entry, role: str) -> str:
        expr = self.part(entry["parts"])
        moved = flow.transition(entry)
        body = [Node("WS?"), Node("NL"), Node("(BODY_LINE? NL)*")]
        if entry["kind"] == KIND_BRACKET:
            return join_seq([expr, *body, Node(BRACKET_CLOSE)]).text
        if entry["kind"] == KIND_MULTILINE and "end" in entry:
            return join_seq([expr, *body, Node("WS?"), self.part(entry["end"])]).text
        if moved:
            block = self.form(moved[1], flow.target_form(entry, role))
            return join_seq([expr, Node("WS?"), Node(block)]).text
        return expr.text

    def part(self, part: Part) -> Node:
        """W3C expression for a Part."""
        if "seq" in part:
            return join_seq([self.part(p) for p in part["seq"]])
        if "alt" in part:
            return join_alt([self.part(p) for p in part["alt"]])
        for key, op in (("opt", "?"), ("star", "*"), ("plus", "+")):
            if key in part:
                return Node(paren(self.part(part[key])).text + op, SEQ)
        if "literal" in part:
            literal = str(part["literal"])
            return ci_literal(literal) if part.get("ci") else quote(literal)
        return translate_regex(part["regex"], self.sink, self.rule, bool(part.get("ci")))


END_RULE = "END_BLOCK"
DIRECTIVE_CHARS = '("@" | "\\")'
OTHER_WORD = f'"start" {NOT_EOL}+'  # any start word; the keyword exclusion is not expressible


def _blocks(groups: dict[str, list[str]]) -> list[str]:
    """Block productions: one START per keyword and one END shared by all (any ``@end...``)."""
    lines: list[str] = []
    for keyword, bodies in groups.items():
        upper = keyword.upper()
        joined = " | ".join(bodies)
        body = f" ({joined})" if len(bodies) > 1 else f" {joined}" if bodies else ""
        lines.append(f"block_{keyword} ::= START_{upper} NL{body} {END_RULE}")
    for keyword in groups:
        start = ci_literal(f"start{keyword}").text
        lines.append(
            f"START_{keyword.upper()} ::= {INLINE_WS}* {DIRECTIVE_CHARS} {start} {NOT_EOL}*"
        )
    lines.append(f"block_other ::= START_OTHER NL (BODY_LINE? NL)* {END_RULE}")
    lines.append(f"START_OTHER ::= {INLINE_WS}* {DIRECTIVE_CHARS} {OTHER_WORD}")
    lines.append(f'{END_RULE} ::= {INLINE_WS}* {DIRECTIVE_CHARS} "end" {NOT_EOL}*')
    return lines


def _header(lossy: list[Lossy]) -> str:
    tally = Counter(item.construct for item in lossy)
    detail = ", ".join(f"{name}: {count}" for name, count in sorted(tally.items())) or "none"
    lines = [
        "Generated by tools.emit.w3c from model/ -- do not edit.",
        "Notation: W3C XML 1.0 section 6 (renders at https://rr.red-dove.com/ui).",
        "Case-insensitive literals: each cased letter is a class, class = [Cc][Ll][Aa][Ss][Ss].",
        "Character shorthands use ASCII semantics; ^ and $ anchors are dropped.",
        "Start lines allow trailing text after the keyword (lookahead not expressible).",
        "block_other (an unsupported @start word, PSystemUnsupported) overlaps the keyword",
        "starts: the exclusion of keyword prefixes is a lookahead, so it is only stated here.",
        "A block ends at ANY end directive (@end..., \\end...), like StartUtils.isEndDirective.",
        f"Lossiness: {len(lossy)} constructs approximated ({detail}).",
        "Each is a *_lossy production carrying its original regex in a comment.",
    ]
    return "/*\n" + "\n".join(f"   {line}" for line in lines) + "\n*/"


def emit_w3c_with_lossiness(resolved: ResolvedModels) -> tuple[str, list[Lossy]]:
    """Render the EBNF text and the list of lossy constructs."""
    names = _Names()
    sink = Sink(names)
    rules: list[str] = []
    groups: dict[str, list[str]] = {}
    start_map = document_start_map(resolved)
    for model in emitted_diagrams(resolved):
        diagram = _Diagram(model, names, sink)
        rules.extend(diagram.render())
        for keyword in start_keywords(model, start_map):
            groups.setdefault(keyword, []).append(diagram.body)
    if not groups:
        groups[UML_KEYWORD] = []
    top = [
        "plantuml ::= NL* block (NL+ block)* NL*",
        "block ::= " + " | ".join([*(f"block_{k}" for k in groups), "block_other"]),
    ]
    text = "\n".join([_header(sink.lossy), *top, *_blocks(groups), *rules, *PRELUDE]) + "\n"
    return text, sink.lossy


def emit_w3c(resolved: ResolvedModels) -> str:
    """Render the W3C EBNF text (the ``tools.emit.build`` emitter contract)."""
    return emit_w3c_with_lossiness(resolved)[0]

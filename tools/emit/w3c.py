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
* ``multiline`` with ``join`` is approximated as a single line (only ``parts``);
  ``multiline-bracket`` as a body closed by a line ``WS* "}"`` (bracket depth is not
  modelled).
* Structure mirrors the Lark emitter: ``push``/``set`` become nested context rules, ordered
  alternatives become unordered ``|``.

``emit_w3c`` returns the text (the ``tools.emit.build`` contract); ``emit_w3c_with_lossiness``
also returns the lossiness entries. The header states the total and a per-construct tally.
"""

from __future__ import annotations

from collections import Counter

from tools.emit.lark import (
    DIAGRAM_LAYER,
    KIND_BRACKET,
    KIND_MULTILINE,
    MAIN_CONTEXT,
    UML_KEYWORD,
    _Names,
    snake,
    start_keyword,
)
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


class _Diagram:
    """Builds the productions of one diagram-layer model."""

    def __init__(self, model: ResolvedModel, names: _Names, sink: Sink) -> None:
        assert model.diagram is not None
        self.model, self.names, self.sink = model, names, sink
        self.prefix = model.diagram.lower()
        self.rules: list[str] = []
        self.context_rules: dict[str, str] = {}
        self.pending: list[str] = []
        self.rule = self.prefix
        self.body = names.unique(f"{self.prefix}_body")

    def render(self) -> list[str]:
        """Productions for this model."""
        line = self._lines(self.prefix, self.model.contexts.get(MAIN_CONTEXT, []), pop=False)
        self._add(f"{self.body} ::= ({line}? NL)*")
        while self.pending:
            self._context(self.pending.pop(0))
        return self.rules

    def _add(self, line: str) -> None:
        self.rules.append(line)
        self.rules.extend(self.sink.drain())

    def _context(self, ctx: str) -> None:
        rule = self.context_rules[ctx]
        entries = self.model.contexts[ctx]
        line = self._lines(rule, entries, pop=False)
        pop_line = self._lines(f"{rule}_pop", entries, pop=True)
        self._add(f"{rule} ::= ({line}? NL)* {pop_line or line + '?'}")

    def _lines(self, base: str, entries: list[Entry], pop: bool) -> str:
        chosen = [e for e in entries if bool(e.get("pop")) == pop]
        name = self.names.unique(f"{base}_line")
        if not chosen:
            if not pop:
                self._add(f"{name} ::= WS")
            return "" if pop else name
        commands = f"{name}_command"
        self.names.used.add(commands)
        alternatives = [self._entry(e) for e in chosen]
        self._add(f"{name} ::= WS? {commands} WS?{'' if pop else ' | WS'}")
        self._add(f"{commands} ::= " + "\n    | ".join(alternatives))
        return name

    def _entry(self, entry: Entry) -> str:
        rule = self.names.unique(f"{self.prefix}_{snake(entry['command'])}")
        self.rule = rule
        self._add(f"{rule} ::= {self._entry_expr(entry).text}")
        return rule

    def _entry_expr(self, entry: Entry) -> Node:
        expr = self.part(entry["parts"])
        if entry["kind"] == KIND_BRACKET:
            return join_seq([expr, Node("NL"), Node("(BODY_LINE? NL)*"), Node(BRACKET_CLOSE)])
        if entry["kind"] == KIND_MULTILINE and "end" in entry:
            tail = [Node("NL"), Node("(BODY_LINE? NL)*"), self.part(entry["end"])]
            return join_seq([expr, *tail])
        target = entry.get("push") or entry.get("set")
        if target:
            return join_seq([expr, Node("NL"), Node(self._context_rule(target))])
        return expr

    def _context_rule(self, ctx: str) -> str:
        if ctx not in self.context_rules:
            self.context_rules[ctx] = self.names.unique(f"{self.prefix}_{snake(ctx)}_block")
            self.pending.append(ctx)
        return self.context_rules[ctx]

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


def _blocks(groups: dict[str, list[str]]) -> list[str]:
    lines: list[str] = []
    for keyword, bodies in groups.items():
        upper = keyword.upper()
        joined = " | ".join(bodies)
        body = f" ({joined})" if len(bodies) > 1 else f" {joined}" if bodies else ""
        lines.append(f"block_{keyword} ::= START_{upper} NL{body} END_{upper}")
    for keyword in groups:
        upper = keyword.upper()
        start = ci_literal(f"@start{keyword}").text
        end = ci_literal(f"@end{keyword}").text
        lines.append(f"START_{upper} ::= {INLINE_WS}* {start} {NOT_EOL}*")
        lines.append(f"END_{upper} ::= {INLINE_WS}* {end} {NOT_EOL}*")
    return lines


def _header(lossy: list[Lossy]) -> str:
    tally = Counter(item.construct for item in lossy)
    detail = ", ".join(f"{name}: {count}" for name, count in sorted(tally.items())) or "none"
    lines = [
        "Generated by tools.emit.w3c from model/ -- do not edit.",
        "Notation: W3C XML 1.0 section 6 (renders at https://rr.red-dove.com/ui).",
        "Case-insensitive literals: each cased letter is a class, class = [Cc][Ll][Aa][Ss][Ss].",
        "Character shorthands use ASCII semantics; ^ and $ anchors are dropped.",
        "Start/end lines allow trailing text after the keyword (lookahead not expressible).",
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
    for _, model in sorted(resolved.items()):
        if model.layer != DIAGRAM_LAYER or not model.diagram:
            continue
        diagram = _Diagram(model, names, sink)
        rules.extend(diagram.render())
        groups.setdefault(start_keyword(str(model.diagram)), []).append(diagram.body)
    if not groups:
        groups[UML_KEYWORD] = []
    top = [
        "plantuml ::= NL* block (NL+ block)* NL*",
        "block ::= " + " | ".join(f"block_{k}" for k in groups),
    ]
    text = "\n".join([_header(sink.lossy), *top, *_blocks(groups), *rules, *PRELUDE]) + "\n"
    return text, sink.lossy


def emit_w3c(resolved: ResolvedModels) -> str:
    """Render the W3C EBNF text (the ``tools.emit.build`` emitter contract)."""
    return emit_w3c_with_lossiness(resolved)[0]

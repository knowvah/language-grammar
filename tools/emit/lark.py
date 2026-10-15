"""Emit the command model as a Lark (Earley) grammar, ``dist/plantuml.lark``.

Output shape (line based, whitespace significant; newlines are never ``%ignore``d)::

    start: _NL* block (_NL+ block)* _NL*
    block: block_uml | block_salt          # one alternative per @start keyword
    block_uml: START_UML _NL (class_body | sequence_body) END_UML
    class_body: (class_line? _NL)*         # one body per diagram-layer model
    class_line: _WS? class_command _WS? | _WS
    class_command: class_command_a | class_command_b
    class_command_a: <parts>               # one rule per command: <diagram>_<command>

Only ``layer: diagram`` models contribute, and of those only the top model of each
``factory`` (``tools.emit.tops``; document and preproc layers are future work);
rules and terminals are emitted in model-id / context / entry order, so output is
deterministic. UML sub-types all sit under ``@startuml``; other diagram types use
``@start<lowercase diagram>`` (see ``start_keyword``).

Every ``opt``, ``alt`` and compound ``star``/``plus`` body (and every nullable regex) is
hoisted into a shared ``_``-prefixed rule (``_o_N: x |``, ``_a_N: a | b``, ``_g_N: ...``)
because Lark distributes inline ``(a|b)`` groups and ``x?`` into a cartesian product of
flat expansions (``SimplifyRule_Visitor.expansion``): ~1e8 expansions for one command
otherwise. ``_`` rules are inlined in the parse tree, so ``<diagram>_body`` detection is
unaffected. Identical bodies share one rule.

Approximations (Earley accepts if *any* derivation exists; upstream is ordered
first-match and stateful), so interpreter/Lark disagreements are expected:

* ``push``/``pop``/``set``/``require_pop`` -- one rendering of the interpreter's context
  stack (``tools.emit.flow``): a transition command is ``<parts> _WS? <block>`` and every
  block rule is newline-led (``(_NL line?)* ...``), so a transition on the last body line
  needs no empty line after it. ``CLOSED`` blocks end with a ``pop`` line, or with a ``set``
  line that embeds the target's ``CLOSED`` block (the frame is replaced, so an if/else needs
  one ``endif``). A block still open at the end of the body is a ``TAIL``: it may only be
  the last line (the "spine") of its parent, and only for a push without ``require_pop``;
  a context that no ``pop`` can reach is therefore always a spine. In ``main`` (the bottom
  frame) a ``set`` line continues with the target's ``ROOT`` form and ``pop`` entries are
  dropped: the interpreter treats them as no-ops but upstream reports a closer without an
  opener as an error, which family models express with ``reject`` entries that emitters
  cannot. Remaining approximations: a
  ``require_pop`` body that never closes makes the interpreter retry the pushing line with
  the later rules (``docs/grammar-guide.md``); Earley has no such retry and just rejects.
  Transitions on ``multiline`` entries with ``end`` or on brackets are not rendered.
* Whitespace -- a line is ``_WS? <command> _WS?`` (the interpreter matches trimmed lines);
  the first line of a bracket, ``multiline``/``end`` or transition command takes ``_WS?``
  before its ``_NL``, and an ``end`` part takes ``_WS?`` before it (trailing blanks come
  from the line wrapper).
* ``multiline`` with ``end`` -- start line, any number of arbitrary body lines, then the
  end line. A body line may itself match the end part, so ordered "stop at first end" is
  lost.
* ``multiline`` with ``join`` -- approximated as a single line: only ``parts`` is matched
  against one line (upstream joins up to ``max_lines`` + 1 lines with U+E100). A join
  entry whose ``parts`` require U+E100 on every path (``tools.emit.skip.needs_joiner``,
  e.g. a mandatory ``\\ue100`` in a ``seq``) can never match one line and is skipped.
* ``reject: true`` entries only make the interpreter fail an attempt; they have no
  accepted text and are dropped (no alternative is emitted).
* ``multiline-bracket`` -- approximated as start line, arbitrary body lines, then a line
  ``\\s*\\}`` (the ``_BRACKET_CLOSE`` terminal). Bracket depth is not modelled, so nested
  ``{ ... }`` bodies close at the first ``}`` line.
* A body needs at least one non-blank, non-comment line unless the model declares an
  ``empty`` context (upstream factories reject empty bodies).
* Comment lines (``'...`` and ``/' ... '/``, dropped upstream by ReadFilterQuoteComment
  before any factory sees them) are accepted wherever a blank line is.
* ``ci: true`` regex terminals carry the Lark ``i`` flag; absent means case-sensitive.
* Ordered alternatives become unordered ``|``; ``opaque`` is treated as ``single``.
* Regexes: the lexer is Lark's ``dynamic`` Earley lexer with ``regex=True`` (the
  third-party ``regex`` module), because expanded patterns contain ``\\p{L}``-style
  classes that ``re`` rejects. Terminals match greedily at one position (no
  backtracking into shorter matches), and an alternative that extends an earlier one
  (``A|A\\[H\\]``) is moved before it (``tools.emit.lark_regex``), so every pattern goes through
  ``tools.emit.linebound.line_bounded`` and cannot cross a line end. Leading ``^`` and
  trailing ``$`` anchors are dropped (lines are delimited by ``_NL``). Dynamic Earley
  rejects terminals whose static minimum width is zero, so a
  nullable regex is emitted as ``(/(?V0)(?=[\\s\\S])(?:PATTERN)/)?``: ``(?V0)`` makes
  Lark fall back to ``regex.match('')`` for the width check, the lookahead makes that
  check report non-empty, and the rule-level ``?`` restores nullability.

Contract keys ignored by this emitter: ``gives``/``needs`` (diagram flags, final-state
checks) are ignored; ``trim: false`` is ignored (the emitted pattern is matched against
the trimmed line); ``emit: false`` entries are dropped like ``reject`` (see ``skip.py``).
"""

from __future__ import annotations

import json

from tools.emit import flow
from tools.emit.flow_rules import EMPTY_CONTEXT as EMPTY_CONTEXT
from tools.emit.flow_rules import MAIN_CONTEXT as MAIN_CONTEXT
from tools.emit.flow_rules import FlowBuilder
from tools.emit.flow_rules import Names as _Names
from tools.emit.flow_rules import snake as snake
from tools.emit.lark_regex import (
    EOL_LOOKAHEAD as EOL_LOOKAHEAD,
)
from tools.emit.lark_regex import (
    NULLABLE_PREFIX as NULLABLE_PREFIX,
)
from tools.emit.lark_regex import (
    greedy as greedy,
)
from tools.emit.lark_regex import (
    nullable_part,
    regex_terminal,
)
from tools.emit.lark_regex import (
    prefer_longest as prefer_longest,
)
from tools.emit.tops import emitted_diagrams
from tools.model import Entry, Part, ResolvedModel, ResolvedModels

UML_KEYWORD = "uml"
UML_TYPES = frozenset(
    {
        "SEQUENCE",
        "STATE",
        "CLASS",
        "OBJECT",
        "ACTIVITY",
        "DESCRIPTION",
        "COMPOSITE",
        "TIMING",
        "HELP",
        "SPRITES",
    }
)
KEYWORD_OVERRIDES = {"CHEN_EER": "chen", "DEFINITION": "def", "PACKET": "packetdiag"}
KIND_MULTILINE = "multiline"
KIND_BRACKET = "multiline-bracket"
HOIST_OPT = "_o"
HOIST_ALT = "_a"
HOIST_GROUP = "_g"
COMPOUND_KEYS = frozenset({"seq", "star", "plus"})
BLANK_LINE = "_WS | _COMMENT | _LONG_COMMENT"
HEADER = "// Generated by tools.emit.lark from model/ -- do not edit."
PRELUDE = (
    r"_NL: /\r?\n/",
    r"_WS: /[ \t]+/",
    r"_BODY_LINE: /[^\r\n]+/",
    r"_BRACKET_CLOSE: /[ \t]*\}/",
    r"_COMMENT: /[ \t]*'[^\r\n]*/",
    r"_LONG_COMMENT: /[ \t]*\/'[\s\S]*?'\/[ \t]*(?=\r?\n|\Z)/",
)


def start_keyword(diagram: str) -> str:
    """The lowercase ``@start<kw>`` keyword used by a diagram type."""
    if diagram in UML_TYPES:
        return UML_KEYWORD
    return KEYWORD_OVERRIDES.get(diagram, diagram.lower())


def lark_string(text: str, ci: bool) -> str:
    """A Lark string literal (``"..."`` or ``"..."i``)."""
    body = json.dumps(text, ensure_ascii=False)
    return body + ("i" if ci else "")


class _Diagram(FlowBuilder):
    """Builds the rules of one diagram-layer model."""

    NL = "_NL"
    WS = "_WS"
    BLANK = BLANK_LINE

    def __init__(self, model: ResolvedModel, names: _Names) -> None:
        super().__init__(model, names)
        self.rules: list[str] = []
        self.terminals: dict[tuple[str, str], str] = {}
        self.terminal_defs: list[str] = []

    def render(self) -> tuple[list[str], list[str]]:
        """Return ``(rule lines, terminal lines)``."""
        self.render_flow()
        return self.rules, self.terminal_defs

    def add(self, name: str, text: str) -> None:
        self.rules.append(f"{name}: {text}")

    def choice(self, options: list[str]) -> str:
        return self._hoist(HOIST_ALT, " | ".join(options))

    def entry_expr(self, entry: Entry, role: str) -> str:
        expr = self.tail(entry["parts"])
        moved = flow.transition(entry)
        if entry["kind"] == KIND_BRACKET:
            return f"{expr} _WS? _NL (_BODY_LINE? _NL)* _BRACKET_CLOSE"
        if entry["kind"] == KIND_MULTILINE and "end" in entry:
            return f"{expr} _WS? _NL (_BODY_LINE? _NL)* _WS? {self.tail(entry['end'])}"
        if moved:
            return f"{expr} _WS? {self.form(moved[1], flow.target_form(entry, role))}"
        return expr

    def part(self, part: Part) -> str:
        """Lark expression for a Part; always an atom or parenthesised group.

        ``opt``, ``alt`` and ``star``/``plus`` over a compound body become hoisted
        ``_``-prefixed rules (see ``_hoist``), keeping every rule's expansion linear.
        """
        if "seq" in part:
            return "(" + " ".join(self.part(p) for p in part["seq"]) + ")"
        if "alt" in part:
            return self._hoist(HOIST_ALT, " | ".join(self.part(p) for p in part["alt"]))
        if "opt" in part:
            return self._hoist(HOIST_OPT, self.part(part["opt"]) + " |")
        for key, op in (("star", "*"), ("plus", "+")):
            if key in part:
                return self._repeat(part[key], op)
        if "literal" in part:
            return lark_string(part["literal"], bool(part.get("ci")))
        return self._regex(part)

    def _repeat(self, inner: Part, op: str) -> str:
        body = self.part(inner)
        if COMPOUND_KEYS.intersection(inner):
            body = self._hoist(HOIST_GROUP, body)
        return body + op

    def _hoist(self, kind: str, body: str) -> str:
        """Name of the shared ``_<kind>`` rule defined as ``body`` (created on demand).

        Lark distributes inline ``(a|b)`` groups and ``x?`` into a cartesian product of
        flat expansions; a separate rule is compiled on its own, so the cost stays linear.
        """
        key = f"{kind}\0{body}"
        if key not in self.names.hoisted:
            name = self.names.unique(kind)
            self.names.hoisted[key] = name
            self.rules.append(f"{name}: {body}")
        return self.names.hoisted[key]

    def tail(self, part: Part) -> str:
        """Like ``part`` for a Part that ends its line: every regex that can be the last
        consumer carries the end-of-line lookahead (``EOL_LOOKAHEAD``).

        A sequence ending in skippable parts gets one variant per possible last element
        (``a b? c?`` -> ``a | a b | a b c``), so a regex in the middle of the line
        never needs the lookahead and the lookahead is never wrong for its branch.
        """
        if "seq" in part:
            return self._tail_seq(part["seq"])
        if "alt" in part:
            return self._hoist(HOIST_ALT, " | ".join(self.tail(p) for p in part["alt"]))
        if "opt" in part:
            return self._hoist(HOIST_OPT, self.tail(part["opt"]) + " |")
        if "star" in part:
            return self._hoist(HOIST_OPT, self._tail_plus(part["star"]) + " |")
        if "plus" in part:
            return self._tail_plus(part["plus"])
        if "regex" in part:
            return self._regex(part, eol=True)
        return self.part(part)

    def _tail_plus(self, inner: Part) -> str:
        return f"{self._repeat(inner, '*')} {self.tail(inner)}"

    def _tail_seq(self, elems: list[Part]) -> str:
        variants: list[str] = []
        for index in range(len(elems) - 1, -1, -1):
            skippable = nullable_part(elems[index])
            last = self._required_tail(elems[index]) if skippable else self.tail(elems[index])
            head = [self.part(e) for e in elems[:index]]
            variants.append("(" + " ".join([*head, last]) + ")")
            if not skippable:
                break
        if len(variants) == 1:
            return variants[0]
        return self._hoist(HOIST_ALT, " | ".join(variants))

    def _required_tail(self, part: Part) -> str:
        """The non-empty form of a skippable last element."""
        if "opt" in part:
            return self.tail(part["opt"])
        if "star" in part:
            return self._tail_plus(part["star"])
        if "regex" in part:
            return self._regex(part, eol=True, required=True)
        return self.tail(part)

    def _regex(self, part: Part, eol: bool = False, required: bool = False) -> str:
        literal, nullable = regex_terminal(part["regex"], bool(part.get("ci")), eol)
        name = part.get("name")
        if name:
            literal = self._named_terminal(str(name), literal)
        if nullable and not required:
            return self._hoist(HOIST_OPT, literal + " |")
        return literal

    def _named_terminal(self, name: str, literal: str) -> str:
        key = (name, literal)
        if key not in self.terminals:
            base = f"{self.prefix}_{snake(name)}".upper()
            terminal = self.names.unique(base)
            self.terminals[key] = terminal
            self.terminal_defs.append(f"{terminal}: {literal}")
        return self.terminals[key]


def _blocks(groups: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """Block rules and START/END terminals, one per @start keyword."""
    rules: list[str] = []
    terminals: list[str] = []
    for keyword, bodies in groups.items():
        upper = keyword.upper()
        body = f" ({' | '.join(bodies)})" if bodies else ""
        rules.append(f"block_{keyword}: START_{upper} _NL{body} END_{upper}")
        terminals.append(f"START_{upper}: /[ \\t]*@start{keyword}(?![A-Za-z0-9])[^\\r\\n]*/i")
        terminals.append(f"END_{upper}: /[ \\t]*@end{keyword}[^\\r\\n]*/i")
    return rules, terminals


def emit_lark(resolved: ResolvedModels) -> str:
    """Render the Lark grammar text for the diagram-layer models in ``resolved``."""
    names = _Names()
    diagrams = [_Diagram(m, names) for m in emitted_diagrams(resolved)]
    rules: list[str] = []
    terminals: list[str] = []
    groups: dict[str, list[str]] = {}
    for diagram in diagrams:
        diagram_rules, diagram_terminals = diagram.render()
        rules.extend(diagram_rules)
        terminals.extend(diagram_terminals)
        keyword = start_keyword(str(diagram.model.diagram))
        groups.setdefault(keyword, []).append(diagram.body)
    if not groups:
        groups[UML_KEYWORD] = []
    block_rules, block_terminals = _blocks(groups)
    head = [
        HEADER,
        "start: _NL* block (_NL+ block)* _NL*",
        "block: " + " | ".join(f"block_{k}" for k in groups),
    ]
    return "\n".join([*head, *block_rules, *rules, *PRELUDE, *block_terminals, *terminals]) + "\n"

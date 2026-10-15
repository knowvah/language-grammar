"""Emit the command model as a Lark (Earley) grammar, ``dist/plantuml.lark``.

Output shape (line based, whitespace significant; newlines are never ``%ignore``d)::

    start: _NL* block (_NL+ block)* _NL*
    block: block_uml | block_salt          # one alternative per @start keyword
    block_uml: START_UML _NL (class_body | sequence_body) END_UML
    class_body: (class_line? _NL)*         # one body per diagram-layer model
    class_line: _WS? class_command _WS? | _WS
    class_command: class_command_a | class_command_b
    class_command_a: <parts>               # one rule per command: <diagram>_<command>

Only ``layer: diagram`` models contribute (document and preproc layers are future work);
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

* ``push``/``set`` -- the command becomes ``<parts> _NL <ctx>_block`` where the nested
  context rule is ``(line? _NL)* <pop line>``: a pushed context is a nested rule ended
  by a command whose entry says ``pop: true``. A context without any popping command
  ends at its last line. ``set`` is treated exactly like ``push``. ``pop`` entries
  outside a pushed context are ordinary lines. Transitions on multiline entries are
  ignored.
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
  backtracking into shorter matches), and a regex such as ``\\s`` can cross a line
  break. Leading ``^`` and trailing ``$`` anchors are dropped (lines are delimited by
  ``_NL``). Dynamic Earley rejects terminals whose static minimum width is zero, so a
  nullable regex is emitted as ``(/(?V0)(?=[\\s\\S])(?:PATTERN)/)?``: ``(?V0)`` makes
  Lark fall back to ``regex.match('')`` for the width check, the lookahead makes that
  check report non-empty, and the rule-level ``?`` restores nullability.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from lark.utils import get_regexp_width

from tools.emit.skip import skipped
from tools.model import Entry, Part, ResolvedModel, ResolvedModels

DIAGRAM_LAYER = "diagram"
MAIN_CONTEXT = "main"
EMPTY_CONTEXT = "empty"
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
EOL_LOOKAHEAD = r"(?=[ \t]*(?:\r?\n|\Z))"
NULLABLE_PREFIX = r"(?V0)(?=[\s\S])(?:"
HEADER = "// Generated by tools.emit.lark from model/ -- do not edit."
PRELUDE = (
    r"_NL: /\r?\n/",
    r"_WS: /[ \t]+/",
    r"_BODY_LINE: /[^\r\n]+/",
    r"_BRACKET_CLOSE: /[ \t]*\}/",
    r"_COMMENT: /[ \t]*'[^\r\n]*/",
    r"_LONG_COMMENT: /[ \t]*\/'[\s\S]*?'\/[ \t]*(?=\r?\n|\Z)/",
)
_PLAIN = r"(?:[^()\[\]{}|*+?.^$\\\r\n]|\\[^\w\s])+"
_WORD_ALTERNATION = re.compile(rf"(?P<open>\((?:\?:)?)(?P<alts>{_PLAIN}(?:\|{_PLAIN})+)\)")
LAZY_AFTER = "*+?}"
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ID = re.compile(r"[^a-z0-9]+")


def start_keyword(diagram: str) -> str:
    """The lowercase ``@start<kw>`` keyword used by a diagram type."""
    if diagram in UML_TYPES:
        return UML_KEYWORD
    return KEYWORD_OVERRIDES.get(diagram, diagram.lower())


def snake(name: str) -> str:
    """``CommandCreateClass`` -> ``command_create_class`` (rule-name safe)."""
    return _NON_ID.sub("_", _CAMEL.sub("_", name).lower()).strip("_") or "x"


def lark_string(text: str, ci: bool) -> str:
    """A Lark string literal (``"..."`` or ``"..."i``)."""
    body = json.dumps(text, ensure_ascii=False)
    return body + ("i" if ci else "")


def _strip_anchors(pattern: str) -> str:
    if pattern.startswith("^"):
        pattern = pattern[1:]
    body = pattern[:-1]
    escapes = len(body) - len(body.rstrip("\\"))
    if pattern.endswith("$") and escapes % 2 == 0:
        return body
    return pattern


def prefer_longest(pattern: str) -> str:
    """Reorder plain-word alternations ``(par|partition)`` longest first.

    Upstream's backtracking regex tries every alternative; Lark's terminal match takes the
    first alternative that matches and ``dynamic_complete`` only shortens it afterwards, so
    a shorter alternative that is a prefix of a longer one (``par`` / ``partition``) would
    otherwise shadow it. Only groups made solely of plain alternatives (words, spaces,
    escaped punctuation) are touched.
    """
    return _WORD_ALTERNATION.sub(_longest_first, pattern)


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
        elif char == "[":
            in_class = True
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
    pattern = greedy(prefer_longest(_strip_anchors(pattern)))
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
        return get_regexp_width(_strip_anchors(part["regex"]))[0] == 0
    return False


@dataclass
class _Names:
    """Allocates unique lower-case rule names and upper-case terminal names."""

    used: set[str] = field(default_factory=set)
    hoisted: dict[str, str] = field(default_factory=dict)

    def unique(self, base: str) -> str:
        name, index = base, 1
        while name in self.used:
            index += 1
            name = f"{base}_{index}"
        self.used.add(name)
        return name


class _Diagram:
    """Builds the rules of one diagram-layer model."""

    def __init__(self, model: ResolvedModel, names: _Names) -> None:
        assert model.diagram is not None
        self.model = model
        self.prefix = model.diagram.lower()
        self.names = names
        self.rules: list[str] = []
        self.terminals: dict[tuple[str, str], str] = {}
        self.terminal_defs: list[str] = []
        self.context_rules: dict[str, str] = {}
        self.pending: list[str] = []
        self.body = names.unique(f"{self.prefix}_body")

    def render(self) -> tuple[list[str], list[str]]:
        """Return ``(rule lines, terminal lines)``."""
        main = self.model.contexts.get(MAIN_CONTEXT, [])
        line = self._lines(self.prefix, main, pop=False)
        self.rules.append(f"{self.body}: {self._body_expr(line)}")
        while self.pending:
            self._context(self.pending.pop(0))
        return self.rules, self.terminal_defs

    def _context(self, ctx: str) -> None:
        rule = self.context_rules[ctx]
        entries = self.model.contexts[ctx]
        line = self._lines(rule, entries, pop=False)
        pop_line = self._lines(f"{rule}_pop", entries, pop=True)
        tail = pop_line if pop_line else f"{line}?"
        self.rules.append(f"{rule}: ({line}? _NL)* {tail}")

    def _body_expr(self, line: str) -> str:
        """Body expression: lines, at least one real command unless ``empty`` is declared.

        Upstream command factories reject a body without a non-blank line; a model that
        accepts one declares an ``empty`` context (``docs/grammar-guide.md``).
        """
        command = f"{line}_command"
        if EMPTY_CONTEXT in self.model.contexts or command not in self.names.used:
            return f"({line}? _NL)*"
        return f"(({BLANK_LINE})? _NL)* _WS? {command} _WS? _NL ({line}? _NL)*"

    def _lines(self, base: str, entries: list[Entry], pop: bool) -> str:
        """Define ``<base>_line`` for the entries with/without ``pop``; '' when none."""
        chosen = [e for e in entries if bool(e.get("pop")) == pop and not skipped(e)]
        name = self.names.unique(f"{base}_line")
        commands = [self._entry(e) for e in chosen]
        if not commands:
            if pop:
                return ""
            self.rules.append(f"{name}: {BLANK_LINE}")
            return name
        alternatives = f"{name}_command"
        self.names.used.add(alternatives)
        blank = "" if pop else f" | {BLANK_LINE}"
        self.rules.append(f"{name}: _WS? {alternatives} _WS?{blank}")
        self.rules.append(f"{alternatives}: " + " | ".join(commands))
        return name

    def _entry(self, entry: Entry) -> str:
        rule = self.names.unique(f"{self.prefix}_{snake(entry['command'])}")
        self.rules.append(f"{rule}: {self._entry_expr(entry)}")
        return rule

    def _entry_expr(self, entry: Entry) -> str:
        expr = self.tail(entry["parts"])
        if entry["kind"] == KIND_BRACKET:
            return f"{expr} _NL (_BODY_LINE? _NL)* _BRACKET_CLOSE"
        if entry["kind"] == KIND_MULTILINE and "end" in entry:
            return f"{expr} _NL (_BODY_LINE? _NL)* {self.tail(entry['end'])}"
        target = entry.get("push") or entry.get("set")
        if target:
            return f"{expr} _NL {self._context_rule(target)}"
        return expr

    def _context_rule(self, ctx: str) -> str:
        if ctx not in self.context_rules:
            self.context_rules[ctx] = self.names.unique(f"{self.prefix}_{snake(ctx)}_block")
            self.pending.append(ctx)
        return self.context_rules[ctx]

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
    diagrams = [
        _Diagram(m, names)
        for _, m in sorted(resolved.items())
        if m.layer == DIAGRAM_LAYER and m.diagram
    ]
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

"""Rule structure of one diagram model, shared by the Lark and W3C emitters.

``FlowBuilder`` turns contexts into line rules and newline-led block rules following
``tools.emit.flow``; a subclass supplies the notation through ``NL``, ``WS``, ``BLANK``,
``ASSIGN`` and three hooks: ``add`` (store a rule), ``choice`` (alternation of expressions)
and ``entry_expr`` (the expression of one command, which asks ``form`` for its block).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import NamedTuple

from tools.emit import flow
from tools.emit.skip import skipped
from tools.model import Entry, ResolvedModel

MAIN_CONTEXT = "main"
EMPTY_CONTEXT = "empty"
KIND_LINE = "line"
KIND_EXIT = "exit"
KIND_SPINE = "spine"
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ID = re.compile(r"[^a-z0-9]+")


def snake(name: str) -> str:
    """``CommandCreateClass`` -> ``command_create_class`` (rule-name safe)."""
    return _NON_ID.sub("_", _CAMEL.sub("_", name).lower()).strip("_") or "x"


@dataclass
class Names:
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


class Line(NamedTuple):
    """A line rule: ``name`` (maybe also blank lines) and ``real`` (commands only)."""

    name: str
    real: str


NO_LINE = Line("", "")


class FlowBuilder:
    """Builds the line, body and block rules of one diagram-layer model."""

    NL = "NL"
    WS = "WS"
    BLANK = "WS"
    ASSIGN = " ::= "

    def __init__(self, model: ResolvedModel, names: Names) -> None:
        assert model.diagram is not None
        self.model = model
        self.prefix = model.diagram.lower()
        self.names = names
        self.closing = flow.closable(model.contexts)
        self.forms: dict[tuple[str, str], str] = {}
        self.lines: dict[tuple[str, str, bool], Line] = {}
        self.entry_rules: dict[tuple[int, str], str] = {}
        self.pending: list[tuple[str, str]] = []
        self.rule = self.prefix  # name of the entry rule being built (lossy placeholders)
        self.body = names.unique(f"{self.prefix}_body")

    # --- hooks ---------------------------------------------------------------------------

    def add(self, name: str, text: str) -> None:
        """Store the rule ``name`` defined as ``text``."""
        raise NotImplementedError

    def choice(self, options: list[str]) -> str:
        """Expression matching any of ``options`` (an atom or a rule name)."""
        raise NotImplementedError

    def entry_expr(self, entry: Entry, role: str) -> str:
        """Expression of one command entry rendered in ``role``."""
        raise NotImplementedError

    # --- structure -----------------------------------------------------------------------

    def render_flow(self) -> None:
        """Define the body rule and, on demand, every block rule it reaches."""
        line = self._line(MAIN_CONTEXT, KIND_LINE, root=True)
        spine = self._line(MAIN_CONTEXT, KIND_SPINE, root=True)
        self.add(self.body, self._body_expr(line, spine))
        while self.pending:
            self._form_rule(*self.pending.pop(0))

    def _body_expr(self, line: Line, spine: Line) -> str:
        """Body expression: lines, at least one real command unless ``empty`` is declared.

        Upstream command factories reject a body without a non-blank line; a model that
        accepts one declares an ``empty`` context (``docs/grammar-guide.md``). The spine
        line (``set`` of the bottom frame, open ``push``) ends the lines of ``main``: the
        rest of the block belongs to the target's form, which the line itself embeds.
        """
        nl = self.NL
        end = f" ({spine.name} {nl})?" if spine.name else ""
        rest = f"({line.name}? {nl})*{end}"
        if EMPTY_CONTEXT in self.model.contexts or not (line.real or spine.name):
            return rest
        first = [f"{line.real} {nl} {rest}"] if line.real else []
        if spine.name:
            first.append(f"{spine.name} {nl}")
        return f"(({self.BLANK})? {nl})* {self.choice(first)}"

    def _form_rule(self, ctx: str, form: str) -> None:
        """Newline-led rule of a block (``CLOSED``, ``TAIL`` or ``ROOT``; ``tools.emit.flow``)."""
        root = form == flow.ROOT
        nl = self.NL
        text = f"({nl} {self._line(ctx, KIND_LINE, root=root).name}?)*"
        if form == flow.CLOSED:
            text += f" ({nl} {self._line(ctx, KIND_EXIT, root=False).name})"
        else:
            spine = self._line(ctx, KIND_SPINE, root=root)
            text += f" ({nl} {spine.name})?" if spine.name else ""
        self.add(self.forms[(ctx, form)], text)

    def form(self, ctx: str, form: str) -> str:
        """Name of the block rule for ``ctx`` in ``form``, queued for rendering on demand."""
        if (ctx, form) not in self.forms:
            base = f"{self.prefix}_{snake(ctx)}_{flow.FORM_SUFFIX[form]}"
            self.forms[(ctx, form)] = self.names.unique(base)
            self.pending.append((ctx, form))
        return self.forms[(ctx, form)]

    def _line(self, ctx: str, kind: str, root: bool) -> Line:
        """Line rules of ``ctx``: ``line`` (ordinary plus blanks), ``exit`` or ``spine``.

        Only the spine depends on ``root`` (a ``set`` of the bottom frame embeds a ``ROOT``
        form, any other spine a ``TAIL`` form).
        """
        root = root and kind == KIND_SPINE
        key = (ctx, kind, root)
        if key not in self.lines:
            chosen, role = self._select(self.model.contexts[ctx], kind, root)
            base = self.prefix if ctx == MAIN_CONTEXT else f"{self.prefix}_{snake(ctx)}"
            self.lines[key] = self._define_line(base, chosen, role, kind)
        return self.lines[key]

    def _select(self, entries: list[Entry], kind: str, root: bool) -> tuple[list[Entry], str]:
        if kind == KIND_LINE:
            return flow.ordinary(entries, self.closing), flow.ROLE_ORD
        if kind == KIND_EXIT:
            return flow.exits(entries, self.closing), flow.ROLE_EXIT
        return flow.tails(entries), flow.ROLE_ROOT_TAIL if root else flow.ROLE_TAIL

    def _define_line(self, base: str, entries: list[Entry], role: str, kind: str) -> Line:
        """Define ``<base>_line`` / ``<base>_exit`` / ``<base>_spine`` for ``entries``."""
        usable = [e for e in entries if not skipped(e)]
        blank = kind == KIND_LINE
        if not usable and not blank:
            return NO_LINE
        name = self.names.unique(f"{base}_{kind}")
        if not usable:
            self.add(name, self.BLANK)
            return Line(name, "")
        real = f"{name}_real" if blank else name
        self.add(real, " | ".join(self._alternatives(name, usable, role)))
        if blank:
            self.add(name, f"{real} | {self.BLANK}")
        return Line(name, real)

    def _alternatives(self, name: str, usable: list[Entry], role: str) -> list[str]:
        """Line alternatives: plain commands (padded by blanks) and transition commands."""
        plain = [self._entry(e, role) for e in usable if flow.transition(e) is None]
        moving = [self._entry(e, role) for e in usable if flow.transition(e) is not None]
        self.names.used.add(f"{name}_command")
        out = []
        if plain:
            self.add(f"{name}_command", " | ".join(plain))
            out.append(f"{self.WS}? {name}_command {self.WS}?")
        if moving:
            self.add(f"{name}_flow", " | ".join(moving))
            out.append(f"{self.WS}? {name}_flow")
        return out

    def _entry(self, entry: Entry, role: str) -> str:
        """Rule name for ``entry``; entries with a transition differ per role."""
        key = (id(entry), role if flow.transition(entry) else "")
        if key not in self.entry_rules:
            rule = self.names.unique(f"{self.prefix}_{snake(entry['command'])}")
            self.entry_rules[key] = self.rule = rule
            self.add(rule, self.entry_expr(entry, role))
        return self.entry_rules[key]

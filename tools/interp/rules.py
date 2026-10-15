"""Compiled rules of a resolved model, built lazily per context and cached."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.interp.compile import compile_part
from tools.interp.scan import Deadline, scan_bracket, scan_multiline
from tools.interp.source import Line
from tools.model import Entry, ResolvedModel

KIND_SINGLE = "single"
KIND_MULTILINE = "multiline"
KIND_BRACKET = "multiline-bracket"
KIND_OPAQUE = "opaque"
ACTION_PUSH = "push"
ACTION_POP = "pop"
ACTION_SET = "set"
ACTION_NONE = ""


@dataclass(frozen=True)
class Rule:
    """One command with its compiled patterns and context transition."""

    name: str
    kind: str
    start: Any
    end: Any
    action: str
    target: str

    def advance(self, body: list[Line], i: int, deadline: Deadline) -> int | None:
        """Index after this command given its first line matched; ``None`` = dropped."""
        if self.kind == KIND_OPAQUE:
            return len(body)
        if self.kind == KIND_MULTILINE:
            return scan_multiline(self.end, body, i, deadline)
        if self.kind == KIND_BRACKET:
            return scan_bracket(body, i)
        return i + 1


def build_rule(entry: Entry) -> Rule:
    """Compile a resolved command entry."""
    action, target = ACTION_NONE, ""
    if entry.get("pop"):
        action = ACTION_POP
    for key in (ACTION_PUSH, ACTION_SET):
        if key in entry:
            action, target = key, entry[key]
    end = compile_part(entry["end"]) if "end" in entry else None
    return Rule(entry["command"], entry["kind"], compile_part(entry["parts"]), end, action, target)


class RuleBook:
    """Lazily compiled ``context -> [Rule]`` for the given models (read-only)."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], list[Rule]] = {}

    def rules(self, model: ResolvedModel, context: str) -> list[Rule]:
        """Rules of ``context``; ``KeyError`` if the context does not exist."""
        key = (model.id, context)
        if key not in self._cache:
            self._cache[key] = [build_rule(e) for e in model.contexts[context]]
        return self._cache[key]

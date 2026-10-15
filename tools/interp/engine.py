"""The interpreter: run a block through the model the way upstream runs commands.

Upstream semantics mirrored (all at 97a5992):

* Factory loop, ``PSystemBuilder.java:257-287``: factories whose type matches the start
  line are tried in order; the first whose ``createSystem`` returns a non-error diagram
  wins (``isOk``, ``:298-303``). If all fail, ``PSystemErrorUtils.merge``
  (``error/PSystemErrorUtils.java:112-147``) keeps the error with the highest
  ``score()`` (``error/PSystemError.java:382``: ``trace.size() * 10 + ...``, strict ``<``
  so the first factory wins ties). ``trace.size()`` is the number of lines consumed when
  the error arose, so the reported failure is the one that got furthest; ties go to the
  earliest candidate. No candidate at all is ``PSystemUnsupported`` (``:283-284``).
* Command loop, ``command/PSystemCommandFactory.java:107-150``: skip the start line,
  stop at the first ``@end`` line, an empty body (only blank lines / comments) is an
  error at the start line (``:117-122``; ``core/UmlSource.java:255-270``).
* ``getCandidate``, ``PSystemCommandFactory.java:223-247``: commands in list order for
  the current line. ``OK`` consumes one line; ``OK_PARTIAL`` consumes lines until the
  command's end condition (see ``tools.interp.scan``); a multiline command that never
  completes is skipped and the next command is tried. No command matches: syntax error
  at that line (``:193-201``).
* Blank lines: upstream relies on ``CommandNope`` (``command/CommandNope.java:46-58``,
  registered by ``CommonCommands.java:63``). Here a blank line is skipped only when no
  command of the current context matched it, so models that include ``CommandNope``
  behave identically and toy models still accept blank lines. ``'`` and ``/' '/``
  comments are removed before the command loop (``tools.interp.source``).
* Contexts: sublime-syntax stack semantics (``docs/grammar-guide.md``). Only the context
  on top of the stack is searched; ``push`` / ``pop`` / ``set`` apply after the command
  completes. ``pop`` on the bottom ``main`` context is a no-op.
* ``kind: opaque``: after its ``parts`` match the line, the rest of the block (up to
  ``@end``) is swallowed as an unparsed body and accepted.

Known semantic gaps (upstream behavior the model cannot represent, so the interpreter
may accept what the jar rejects): ``executeArg``/``execute`` results (e.g. unknown
colors, duplicate entities, ``CommandExecutionResult.error``), ``finalVerification``,
``isCommandForbidden``, ``checkFinalError`` / ``isIncomplete``
(``PSystemCommandFactory.java:157-170``), multi-pass diagrams (``getRequiredPass``),
``syntaxWithFinalBracket`` handling, ``CommandDecoratorMultine`` line caps, abstract
``isLineConsistent`` of bracket commands, error *scores* beyond line progress, and
``Throwable`` crashes inside a factory (``:275-281``). See also ``tools.interp.compile``
for regex-dialect gaps.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence

import regex

from tools.interp import STATUS_ERROR, STATUS_OK, STATUS_REJECT, STATUS_TIMEOUT, Verdict
from tools.interp.compile import PartError
from tools.interp.dispatch import candidates
from tools.interp.rules import ACTION_POP, ACTION_PUSH, ACTION_SET, Rule, RuleBook
from tools.interp.scan import BlockTimeout, Deadline
from tools.interp.source import Block, Line, split_block
from tools.model import ResolvedModel, ResolvedModels

MAIN_CONTEXT = "main"
DEFAULT_TIMEOUT_S = 10.0
MODEL_ERRORS = (regex.error, KeyError, PartError)


def _verdict(status: str, diagram: str | None = None, failed: Line | None = None) -> Verdict:
    failure = {"line": failed.number, "text": failed.text} if failed else None
    return {
        "accepted": status == STATUS_OK,
        "diagram": diagram,
        "first_failure": failure,  # type: ignore[typeddict-item]
        "status": status,  # type: ignore[typeddict-item]
    }


def _apply(stack: list[str], rule: Rule) -> None:
    if rule.action == ACTION_PUSH:
        stack.append(rule.target)
    elif rule.action == ACTION_SET:
        stack[-1] = rule.target
    elif rule.action == ACTION_POP and len(stack) > 1:
        stack.pop()


class Interpreter:
    """Runs blocks against resolved models; compiled rules are reused across blocks."""

    def __init__(
        self,
        models: ResolvedModels,
        start_map: Mapping[str, Sequence[str]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._models = models
        self._start_map = start_map
        self._clock = clock
        self._book = RuleBook()

    def accepts(self, block_text: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> Verdict:
        """Contract I3. Line numbers are 1-based within ``block_text``."""
        block = split_block(block_text)
        deadline = Deadline(timeout_s, self._clock)
        try:
            return self._decide(block, deadline)
        except BlockTimeout:
            return _verdict(STATUS_TIMEOUT)
        except MODEL_ERRORS:
            return _verdict(STATUS_ERROR)

    def _decide(self, block: Block, deadline: Deadline) -> Verdict:
        anchor = block.start or Line(1, "", "")
        if not any(line.trimmed for line in block.body):
            return _verdict(STATUS_REJECT, failed=anchor)
        cands = candidates(self._models, block.keyword, self._start_map)
        best: tuple[int, Line] | None = None
        for model in cands:
            failed = self._run(model, block.body, deadline)
            if failed is None:
                return _verdict(STATUS_OK, model.id)
            if best is None or failed > best[0]:
                best = (failed, block.body[failed])
        return _verdict(STATUS_REJECT, failed=best[1] if best else anchor)

    def _run(self, model: ResolvedModel, body: list[Line], deadline: Deadline) -> int | None:
        """Body index of the first line no command accepts, or ``None`` if all pass."""
        stack = [MAIN_CONTEXT]
        i = 0
        while i < len(body):
            step = self._candidate(model, stack[-1], body, i, deadline)
            if step is not None:
                _apply(stack, step[0])
                i = step[1]
            elif body[i].trimmed:
                return i
            else:
                i += 1
        return None

    def _candidate(
        self, model: ResolvedModel, context: str, body: list[Line], i: int, deadline: Deadline
    ) -> tuple[Rule, int] | None:
        """``PSystemCommandFactory.getCandidate`` (:223-247)."""
        first = body[i].trimmed
        for rule in self._book.rules(model, context):
            if not deadline.fullmatch(rule.start, first):
                continue
            nxt = rule.advance(body, i, deadline)
            if nxt is not None:
                return rule, nxt
        return None


_LAST: list[tuple[ResolvedModels, Mapping[str, Sequence[str]] | None, Interpreter]] = []


def _interpreter_for(
    models: ResolvedModels, start_map: Mapping[str, Sequence[str]] | None
) -> Interpreter:
    """Single-slot cache keyed by object identity, so compiled rules persist across calls.

    ``models`` must not be mutated between calls; pass a new mapping instead.
    """
    if _LAST and _LAST[0][0] is models and _LAST[0][1] is start_map:
        return _LAST[0][2]
    interpreter = Interpreter(models, start_map)
    _LAST[:] = [(models, start_map, interpreter)]
    return interpreter


def accepts(
    models: ResolvedModels,
    block_text: str,
    *,
    start_map: Mapping[str, Sequence[str]] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> Verdict:
    """Would upstream accept ``block_text`` (``@startX`` ... ``@endX`` included)?

    ``start_map`` maps a start keyword (``"uml"`` or ``"@startuml"``) to the ordered ids
    of the diagram models to try; without it the keyword is resolved like
    ``DiagramType.findStartTypes`` (see ``tools.interp.dispatch``). A block with no
    ``@start`` line is treated as a bare body tried against every diagram model.
    """
    return _interpreter_for(models, start_map).accepts(block_text, timeout_s)

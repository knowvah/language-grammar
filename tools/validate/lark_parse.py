"""Parse a ``@start...@end`` block with the generated Lark grammar (contract I4).

``parse_with_lark(block_text, timeout_s)`` returns an I3-shaped verdict dict
``{accepted, diagram, first_failure ({line, text} | None), status}``. Earley cannot be
interrupted in-thread, so each grammar gets a long-lived *spawned* worker process that
builds the parser once and then answers parse requests over a pipe. When a parse exceeds
``timeout_s`` the worker is terminated and a fresh one is started on the next call.
Parser construction is not charged against ``timeout_s`` (a separate startup budget).

Line numbers are 1-based within ``block_text`` (line 1 is the ``@start`` line).
"""

from __future__ import annotations

import atexit
import multiprocessing as mp
import re
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any

from lark import Lark, Tree
from lark.exceptions import LarkError, UnexpectedInput

DEFAULT_GRAMMAR = Path(__file__).resolve().parents[2] / "dist" / "plantuml.lark"
DEFAULT_TIMEOUT_S = 10.0
STARTUP_TIMEOUT_S = 60.0
LEXER = "dynamic_complete"
BODY_NAME = re.compile(r"^(?P<diagram>.+)_body(?:_\d+)?$")
READY = "ready"
Verdict = dict[str, Any]


def make_verdict(
    status: str,
    accepted: bool = False,
    diagram: str | None = None,
    failure: tuple[int, str] | None = None,
) -> Verdict:
    """Build the I3/I4 verdict dict."""
    first = {"line": failure[0], "text": failure[1]} if failure else None
    return {"accepted": accepted, "diagram": diagram, "first_failure": first, "status": status}


def build_parser(grammar_path: Path) -> Lark:
    """The Earley parser for a grammar file (``dynamic_complete`` lexer, ``regex`` module)."""
    text = grammar_path.read_text(encoding="utf-8")
    return Lark(text, start="start", parser="earley", lexer=LEXER, regex=True)


def diagram_of(tree: Tree[Any]) -> str | None:
    """Diagram type of the first ``<diagram>_body[_N]`` subtree, or None.

    The emitter suffixes ``_N`` when several models share one diagram type.
    """
    for sub in tree.iter_subtrees_topdown():
        found = BODY_NAME.match(str(sub.data))
        if found:
            return found["diagram"].upper()
    return None


def failure_line(text: str, pos: int | None) -> tuple[int, str]:
    """1-based line number and text containing offset ``pos`` (end of text if unknown)."""
    lines = text.split("\n")
    if pos is None or pos < 0:
        number = len(lines)
    else:
        number = text.count("\n", 0, min(pos, len(text))) + 1
    return number, lines[number - 1].rstrip("\r")


def parse_text(parser: Lark, text: str) -> Verdict:
    """Pure parse of ``text`` with ``parser`` into a verdict (never raises LarkError)."""
    try:
        tree = parser.parse(text)
    except UnexpectedInput as exc:
        pos = getattr(exc, "pos_in_stream", None)
        return make_verdict("reject", failure=failure_line(text, pos))
    except LarkError:
        return make_verdict("error")
    return make_verdict("ok", accepted=True, diagram=diagram_of(tree))


def _worker_main(conn: Connection, grammar_path: str) -> None:  # pragma: no cover
    """Worker loop (runs in the spawned process)."""
    try:
        parser = build_parser(Path(grammar_path))
    except Exception as exc:  # noqa: BLE001 - reported to the parent as an error verdict
        conn.send((READY, str(exc)))
        return
    conn.send((READY, None))
    while True:
        text = conn.recv()
        if text is None:
            return
        try:
            conn.send(parse_text(parser, text))
        except Exception:  # noqa: BLE001 - never kill the worker on one bad input
            conn.send(make_verdict("error"))


class _Worker:
    def __init__(self, process: BaseProcess, conn: Connection) -> None:
        self.process = process
        self.conn = conn

    def stop(self) -> None:
        if self.process.is_alive():
            self.process.terminate()
        self.process.join()
        self.conn.close()


class LarkRunner:
    """Parses blocks for one grammar file in a reusable, killable worker process."""

    def __init__(self, grammar_path: Path = DEFAULT_GRAMMAR) -> None:
        self.grammar_path = grammar_path
        self.worker: _Worker | None = None
        self.last_process: BaseProcess | None = None

    def parse(self, text: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> Verdict:
        """Verdict for ``text``; ``status: timeout`` kills the worker."""
        worker = self.worker or self._start()
        if worker is None:
            return make_verdict("error")
        self.last_process = worker.process
        try:
            worker.conn.send(text)
            if not worker.conn.poll(timeout_s):
                self.close()
                return make_verdict("timeout")
            verdict: Verdict = worker.conn.recv()
        except (EOFError, OSError):
            self.close()
            return make_verdict("error")
        return verdict

    def _start(self) -> _Worker | None:
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        process = ctx.Process(target=_worker_main, args=(child, str(self.grammar_path)))
        process.daemon = True
        process.start()
        child.close()
        worker = _Worker(process, parent)
        self.last_process = process
        if parent.poll(STARTUP_TIMEOUT_S):
            try:
                message = parent.recv()
            except EOFError:
                message = (READY, "worker died")
            if message[1] is None:
                self.worker = worker
                return worker
        worker.stop()
        return None

    def close(self) -> None:
        """Terminate the worker, if any."""
        if self.worker is not None:
            self.worker.stop()
            self.worker = None


_runners: dict[Path, LarkRunner] = {}


def _runner(grammar_path: Path) -> LarkRunner:
    if grammar_path not in _runners:
        _runners[grammar_path] = LarkRunner(grammar_path)
    return _runners[grammar_path]


@atexit.register
def close_all() -> None:
    """Terminate every cached worker."""
    for runner in _runners.values():
        runner.close()


def parse_with_lark(
    block_text: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    grammar_path: Path = DEFAULT_GRAMMAR,
) -> Verdict:
    """Parse one source block with ``dist/plantuml.lark`` (I4).

    Args:
        block_text: The block including its ``@start...`` and ``@end...`` lines.
        timeout_s: Seconds allowed for the parse itself.
        grammar_path: Grammar file; defaults to ``dist/plantuml.lark``.

    Returns:
        ``{accepted, diagram, first_failure, status}`` with status ok, reject, timeout
        or error (error also covers a missing or invalid grammar file).
    """
    return _runner(grammar_path).parse(block_text, timeout_s)

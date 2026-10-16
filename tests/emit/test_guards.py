"""Zero-width guards (pure lookaround parts) are kept by the Lark emitter.

A guard cannot be its own Lark terminal (the dynamic lexer drops zero-length matches), and
an optional rule around it lets Earley skip it. ``tools.emit.guards`` folds every guard into
the terminal(s) that follow it, or into the one before it at the end of a line. Lark
acceptance is compared with the interpreter, which runs the model regexes directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.emit import guards
from tools.emit import lark as emitter
from tools.emit.lark_regex import NONEMPTY_KEY, PRE_KEY
from tools.interp import accepts
from tools.model.load import load_dir
from tools.model.resolve import resolve
from tools.validate.lark_parse import LarkRunner

GUARDS = Path(__file__).parent / "fixtures" / "guards"
START = "@startuml"
END = "@enduml"
ACCEPT = True
REJECT = False
WORD = {"regex": "[a-z]+", "ci": False}
NOT_FOO = {"regex": "(?!foo)", "ci": False}

CASES: list[tuple[str, bool]] = [
    ("bar", ACCEPT),
    ("fob", ACCEPT),
    ("foo", REJECT),
    ("foobar", REJECT),
    ("p y", ACCEPT),
    ("p xy", ACCEPT),
    ("p yz", ACCEPT),
    ("p z", REJECT),
    ("p xz", REJECT),
    ("a q", ACCEPT),
    ("a qs", ACCEPT),
    ("a r", ACCEPT),
    ("a rt", ACCEPT),
    ("a rs", REJECT),
    ("e ab", ACCEPT),
    ("e az", REJECT),
    ("t", ACCEPT),
    ("s;", ACCEPT),
    ("s  ;", ACCEPT),
    ("s ;", REJECT),
]


def block(line: str) -> str:
    return f"{START}\n{line}\n{END}\n"


@pytest.fixture(scope="module")
def models():
    return resolve(load_dir(GUARDS))


@pytest.fixture(scope="module")
def runner(tmp_path_factory: pytest.TempPathFactory, models):
    path = tmp_path_factory.mktemp("guards") / "plantuml.lark"
    path.write_text(emitter.emit_lark(models), encoding="utf-8")
    r = LarkRunner(path)
    yield r
    r.close()


@pytest.mark.parametrize(("line", "expected"), CASES, ids=[c[0] for c in CASES])
def test_interpreter_agrees_with_expectation(models, line: str, expected: bool) -> None:
    assert accepts(models, block(line))["accepted"] is expected


@pytest.mark.parametrize(("line", "expected"), CASES, ids=[c[0] for c in CASES])
def test_lark_matches_interpreter(runner: LarkRunner, line: str, expected: bool) -> None:
    assert runner.parse(block(line))["accepted"] is expected


# --- the transform ---------------------------------------------------------------------


def test_parts_without_guards_are_returned_unchanged() -> None:
    part = {"seq": [{"literal": "x", "ci": False}, {"opt": WORD}]}
    assert guards.fuse_line(part) is part


def test_guard_becomes_a_prefix_of_the_next_terminal() -> None:
    fused = guards.fuse_line({"seq": [NOT_FOO, WORD]})
    assert fused == {**WORD, PRE_KEY: [("(?!foo)", False)]}


def test_guard_before_a_nullable_part_splits_into_taken_and_skipped() -> None:
    star = {"regex": "[ ]*", "ci": False}
    semi = {"literal": ";", "ci": False}
    fused = guards.fuse_line({"seq": [NOT_FOO, star, semi]})
    taken = {"seq": [{**star, PRE_KEY: [("(?!foo)", False)], NONEMPTY_KEY: True}, semi]}
    skipped = {**semi, PRE_KEY: [("(?!foo)", False)]}
    assert fused == {"alt": [taken, skipped]}


def test_lookahead_at_line_end_is_decided_statically() -> None:
    assert guards.fuse_line({"seq": [WORD, {"regex": "(?![a-z])", "ci": False}]}) == WORD


def test_guard_kept_for_an_impossible_line_end_rejects_the_entry(models) -> None:
    # `(?=x)` can never hold at the end of a line: the entry matches nothing
    assert guards.fuse_line({"seq": [WORD, {"regex": "(?=x)", "ci": False}]}) is None

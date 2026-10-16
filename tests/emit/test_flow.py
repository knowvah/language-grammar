"""Context transitions (push/set/pop/require_pop) rendered consistently by every emitter.

Lark acceptance is compared with the interpreter (the reference semantics) and with an
explicit expectation on a toy model that covers each transition shape the family models use.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.emit import flow, w3c
from tools.emit import lark as emitter
from tools.interp import accepts
from tools.model.load import load_dir
from tools.model.resolve import resolve
from tools.validate.lark_parse import LarkRunner

FLOW = Path(__file__).parent / "fixtures" / "flow"
START = "@startuml"
END = "@enduml"
ACCEPT = True
REJECT = False

CASES: list[tuple[str, tuple[str, ...], bool]] = [
    # set inside a pushed context ends the block (activity3 if/else)
    ("if-else", ("if", "cmd", "else", "cmd", "endif"), ACCEPT),
    ("if-else-then-main", ("if", "else", "endif", "cmd"), ACCEPT),
    ("if-only", ("if", "cmd", "endif"), ACCEPT),
    ("if-else-extra-endif", ("if", "else", "endif", "endif"), REJECT),
    ("if-else-needs-no-second-endif", ("if", "else", "cmd", "endif", "cmd"), ACCEPT),
    # open (no require_pop) push may end with the block; require_pop must close
    ("grp-unclosed", ("grp {", "cmd"), ACCEPT),
    ("grp-last-line", ("cmd", "grp {"), ACCEPT),
    ("grp-closed", ("grp {", "cmd", "}", "cmd"), ACCEPT),
    ("grp-nested-inner-closed", ("grp {", "grp {", "}"), ACCEPT),
    ("grp-extra-close", ("grp {", "}", "}"), REJECT),
    ("strict-unclosed", ("strict {", "cmd"), REJECT),
    ("strict-closed", ("strict {", "cmd", "}"), ACCEPT),
    ("strict-inner-closed-outer-open", ("strict {", "grp {", "}"), REJECT),
    ("strict-last-line", ("strict {",), REJECT),
    # set from main replaces the root frame: the rest of the block is the target's lines
    ("mode-last-line", ("cmd", "mode"), ACCEPT),
    ("mode-then-target-lines", ("mode", "mcmd", "mcmd"), ACCEPT),
    ("mode-then-main-line", ("mode", "cmd"), REJECT),
    ("mode-back", ("mode", "mcmd", "back", "cmd"), ACCEPT),
    # a context without any pop line ends with the block
    ("orphan-set-last-line", ("jump",), ACCEPT),
    ("orphan-set-lines", ("jump", "o", "o"), ACCEPT),
    ("orphan-set-foreign-line", ("jump", "cmd"), REJECT),
    ("orphan-push-last-line", ("orph",), ACCEPT),
    ("orphan-push-lines", ("orph", "o", "", "o"), ACCEPT),
    # whitespace around first, end and pop lines
    ("trailing-space-first-line", ("grp { ", "cmd", "}"), ACCEPT),
    ("trailing-space-multiline-first", ("note ", "x", "end note"), ACCEPT),
    ("indented-multiline-end", ("note", "x", "  end note"), ACCEPT),
    ("trailing-space-multiline-end", ("note", "x", "end note  "), ACCEPT),
    ("indented-pop-line", ("grp {", "cmd", "  }  "), ACCEPT),
    ("indented-set-line", ("if", "  else  ", "  endif"), ACCEPT),
    ("trailing-space-set-line", ("mode  ", "mcmd"), ACCEPT),
    ("trailing-space-push-last-line", ("grp {  ",), ACCEPT),
    ("trailing-space-bracket-first-line", ("br { ", "x", "}"), ACCEPT),
    ("indented-bracket-close", ("br {", "x", "  }  "), ACCEPT),
    ("bracket-unclosed", ("br {", "x"), REJECT),
    ("multiline-missing-end", ("note", "x"), REJECT),
]
IDS = [case[0] for case in CASES]


def block(lines: tuple[str, ...]) -> str:
    return "\n".join([START, *lines, END]) + "\n"


@pytest.fixture(scope="module")
def models():
    return resolve(load_dir(FLOW))


@pytest.fixture(scope="module")
def runner(tmp_path_factory: pytest.TempPathFactory, models) -> LarkRunner:
    path = tmp_path_factory.mktemp("flow") / "plantuml.lark"
    path.write_text(emitter.emit_lark(models), encoding="utf-8")
    r = LarkRunner(path)
    yield r
    r.close()


@pytest.mark.parametrize(("name", "lines", "expected"), CASES, ids=IDS)
def test_interpreter_agrees_with_expectation(models, name, lines, expected) -> None:
    assert accepts(models, block(lines))["accepted"] is expected, name


@pytest.mark.parametrize(("name", "lines", "expected"), CASES, ids=IDS)
def test_lark_matches_interpreter(runner: LarkRunner, name, lines, expected) -> None:
    assert runner.parse(block(lines))["accepted"] is expected, name


# --- rendering ------------------------------------------------------------------------


def rules_of(text: str) -> dict[str, str]:
    return dict(line.split(": ", 1) for line in text.splitlines() if ": " in line)


def test_set_in_closed_block_embeds_the_target_closed_block(models) -> None:
    rules = rules_of(emitter.emit_lark(models))
    # `else` ends the ifthen block and continues with ifelse; no second `endif` is needed
    assert rules["class_t_else"] == '"else" _WS? class_ifelse_block'
    assert rules["class_ifelse_block"] == "(_NL class_ifelse_line?)* (_NL class_ifelse_exit)"
    assert rules["class_ifelse_exit"] == "_WS? class_ifelse_exit_command _WS?"


def test_open_push_is_only_the_spine_of_a_tail_form(models) -> None:
    rules = rules_of(emitter.emit_lark(models))
    assert rules["class_grp_tail"] == "(_NL class_grp_line?)* (_NL class_grp_spine)?"
    # a require_pop push has a closed alternative only
    assert "class_strict_tail" not in rules
    assert rules["class_strict_block"] == "(_NL class_strict_line?)* (_NL class_strict_exit)"


def test_context_that_cannot_close_is_tail_only(models) -> None:
    rules = rules_of(emitter.emit_lark(models))
    assert rules["class_orphan_tail"] == "(_NL class_orphan_line?)*"
    assert "class_orphan_block" not in rules


def test_root_form_drops_pop_entries_unlike_the_interpreter(models, runner) -> None:
    """A closer in the bottom frame is a no-op for the interpreter but an error upstream
    (family models shadow it with ``reject``, which emitters cannot express): Lark rejects."""
    rules = rules_of(emitter.emit_lark(models))
    assert rules["class_modeb_line_command"] == "class_m_cmd"
    for lines in (("done", "cmd"), ("mode", "pp", "mcmd")):
        assert accepts(models, block(lines))["accepted"] is True
        assert runner.parse(block(lines))["accepted"] is False


def test_w3c_forms_mirror_lark(models) -> None:
    prods = dict(
        line.split(" ::= ", 1) for line in w3c.emit_w3c(models).splitlines() if " ::= " in line
    )
    assert prods["class_orphan_tail"] == "(NL class_orphan_line?)*"
    assert prods["class_strict_block"] == "(NL class_strict_line?)* (NL class_strict_exit)"
    assert prods["class_grp_tail"] == "(NL class_grp_line?)* (NL class_grp_spine)?"
    assert prods["class_mode"].endswith("WS? class_modeb_root")


def test_w3c_set_continues_with_target(models) -> None:
    lines = w3c.emit_w3c(models).splitlines()
    line = next(ln for ln in lines if ln.startswith("class_t_else ::="))
    assert line.endswith("class_ifelse_block")


# --- flow classification (pure) ---------------------------------------------------------


def entry(**keys):
    base = {"command": "C", "kind": "single", "parts": {"literal": "x"}}
    return {**base, **keys}


def test_transition_ignores_multiline_with_end() -> None:
    assert flow.transition(entry(push="a")) == (flow.PUSH, "a")
    assert flow.transition(entry(set="b")) == (flow.SET, "b")
    assert flow.transition(entry(kind="multiline", end={"literal": "e"}, set="b")) is None
    assert flow.transition(entry(kind="multiline-bracket", push="a")) is None
    assert flow.transition(entry(kind="multiline", join={"max_lines": 1}, set="b")) == (
        flow.SET,
        "b",
    )
    assert flow.transition(entry()) is None


def test_closable_follows_set_chains_and_skips_rejected_pops() -> None:
    contexts = {
        "main": [entry()],
        "a": [entry(set="b")],
        "b": [entry(set="c")],
        "c": [entry(pop=True)],
        "d": [entry(pop=True, reject=True)],
        "e": [entry(set="e")],
    }
    assert flow.closable(contexts) == {"a", "b", "c"}


def test_ordinary_exit_and_tail_selection() -> None:
    plain, pop, setter = entry(), entry(pop=True), entry(set="t")
    open_push, strict, dead = entry(push="t"), entry(push="t", require_pop=True), entry(push="x")
    entries = [plain, pop, setter, open_push, strict, dead]
    closing = frozenset({"t"})
    assert flow.ordinary(entries, closing) == [plain, open_push, strict]
    assert flow.exits(entries, closing) == [pop, setter]
    assert flow.tails(entries) == [setter, open_push, dead]


def test_target_form_per_role() -> None:
    push, setter = entry(push="t"), entry(set="t")
    assert flow.target_form(push, flow.ROLE_ORD) == flow.CLOSED
    assert flow.target_form(setter, flow.ROLE_EXIT) == flow.CLOSED
    assert flow.target_form(push, flow.ROLE_TAIL) == flow.TAIL
    assert flow.target_form(setter, flow.ROLE_TAIL) == flow.TAIL
    assert flow.target_form(push, flow.ROLE_ROOT_TAIL) == flow.TAIL
    assert flow.target_form(setter, flow.ROLE_ROOT_TAIL) == flow.ROOT

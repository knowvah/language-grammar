"""Emitters honour regex ``ci``, ``join`` and ``end``-less ``multiline-bracket`` entries."""

from __future__ import annotations

from pathlib import Path

import pcre2
import pytest

from tools.emit import lark as lark_emit
from tools.emit import textmate, w3c
from tools.model import ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve
from tools.validate.lark_parse import LarkRunner

CONTRACT = Path(__file__).parent / "fixtures" / "contract"


@pytest.fixture(scope="module")
def models() -> ResolvedModels:
    return resolve(load_dir(CONTRACT))


@pytest.fixture(scope="module")
def runner(models: ResolvedModels, tmp_path_factory: pytest.TempPathFactory):
    path = tmp_path_factory.mktemp("contract") / "plantuml.lark"
    path.write_text(lark_emit.emit_lark(models), encoding="utf-8")
    r = LarkRunner(path)
    yield r
    r.close()


def uml(*lines: str) -> str:
    return "\n".join(["@startuml", *lines, "@enduml"]) + "\n"


# --- lark ---------------------------------------------------------------------------------


def test_lark_ci_regex_terminal_has_i_flag_and_absent_does_not(models: ResolvedModels) -> None:
    lines = lark_emit.emit_lark(models).splitlines()
    assert "class_command_ci_regex: /abc/i" in lines
    assert "class_command_cs_regex: /xyz/" in lines


def test_lark_regex_ci_controls_case(runner: LarkRunner) -> None:
    assert runner.parse(uml("ABC"))["accepted"] is True
    assert runner.parse(uml("xyz"))["accepted"] is True
    verdict = runner.parse(uml("XYZ"))
    assert verdict["accepted"] is False
    assert verdict["first_failure"] == {"line": 2, "text": "XYZ"}


def test_lark_join_entry_is_a_single_line(models: ResolvedModels, runner: LarkRunner) -> None:
    line = next(
        x for x in lark_emit.emit_lark(models).splitlines() if x.startswith("class_command_join:")
    )
    assert "_NL" not in line
    assert runner.parse(uml("wrap a"))["accepted"] is True


def test_lark_bracket_without_end_closes_on_a_brace_line(
    models: ResolvedModels, runner: LarkRunner
) -> None:
    text = lark_emit.emit_lark(models)
    assert "class_command_bracket: (" in text
    assert " _NL (_BODY_LINE? _NL)* _BRACKET_CLOSE" in text
    assert runner.parse(uml("pkg a {", "x", "  }"))["accepted"] is True
    assert runner.parse(uml("pkg a {", "x"))["accepted"] is False


# --- w3c ----------------------------------------------------------------------------------


def test_w3c_regex_ci_folds_and_absent_stays_case_sensitive(models: ResolvedModels) -> None:
    lines = w3c.emit_w3c(models).splitlines()
    assert "class_command_ci_regex ::= [Aa] [Bb] [Cc]" in lines
    assert 'class_command_cs_regex ::= "xyz"' in lines


def test_w3c_join_is_single_line_and_bracket_closes_on_brace_line(
    models: ResolvedModels,
) -> None:
    lines = w3c.emit_w3c(models).splitlines()
    join = next(x for x in lines if x.startswith("class_command_join ::="))
    assert "NL" not in join
    bracket = next(x for x in lines if x.startswith("class_command_bracket ::="))
    assert bracket.endswith("NL (BODY_LINE? NL)* BRACKET_CLOSE")
    assert 'BRACKET_CLOSE ::= [#x20#x9]* "}"' in lines


# --- textmate -----------------------------------------------------------------------------


def _rules(models: ResolvedModels) -> list[dict[str, object]]:
    grammar = textmate.emit_textmate(models)
    return grammar["repository"]["diagram_uml"]["patterns"]


def test_textmate_regex_ci_wraps_and_absent_does_not(models: ResolvedModels) -> None:
    matches = [r.get("match") for r in _rules(models)]
    assert matches[0] == "(?i:abc)"
    assert matches[1] == "xyz"
    assert pcre2.compile("(?i:abc)").match("ABC") is not None


def test_textmate_join_is_a_single_line_match(models: ResolvedModels) -> None:
    rule = _rules(models)[2]
    assert "begin" not in rule
    assert rule["match"] == "(?i:wrap)\\s+\\w+(?:\\ue100\\w+)?"


def test_textmate_bracket_without_end_keeps_the_default_end(models: ResolvedModels) -> None:
    rule = _rules(models)[3]
    assert rule["end"] == "^\\s*\\}"
    assert rule["begin"] == "(?i:pkg)\\s+\\w+\\s*\\{"

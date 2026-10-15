"""Tests for the Lark emitter, the dist build CLI and the Earley parse wrapper."""

from __future__ import annotations

from pathlib import Path

import pytest
from lark import Lark
from lark.exceptions import LarkError

from tools.emit import build as build_cli
from tools.emit import lark as emitter
from tools.model.load import load_dir
from tools.model.resolve import resolve
from tools.validate import lark_parse
from tools.validate.lark_parse import LarkRunner

FIXTURES = Path(__file__).parent / "fixtures"
TOY = FIXTURES / "toy"
EMPTY = FIXTURES / "empty"
AMBIGUOUS = FIXTURES / "ambiguous.lark"
SHORT_TIMEOUT_S = 0.1
OK = "ok"
REJECT = "reject"
CLASS_SRC = "@startuml\n{body}\n@enduml\n"


def uml(*lines: str) -> str:
    return CLASS_SRC.format(body="\n".join(lines))


@pytest.fixture(scope="module")
def grammar_text() -> str:
    return emitter.emit_lark(resolve(load_dir(TOY)))


@pytest.fixture(scope="module")
def runner(tmp_path_factory: pytest.TempPathFactory, grammar_text: str):
    path = tmp_path_factory.mktemp("dist") / "plantuml.lark"
    path.write_text(grammar_text, encoding="utf-8")
    r = LarkRunner(path)
    yield r
    r.close()


# --- emitter units -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("diagram", "keyword"),
    [("CLASS", "uml"), ("SEQUENCE", "uml"), ("SALT", "salt"), ("CHEN_EER", "chen")],
)
def test_start_keyword(diagram: str, keyword: str) -> None:
    assert emitter.start_keyword(diagram) == keyword


@pytest.mark.parametrize(
    ("name", "expected"),
    [("CommandCreateClass", "command_create_class"), ("HTTPServer", "http_server"), ("a-b", "a_b")],
)
def test_snake(name: str, expected: str) -> None:
    assert emitter.snake(name) == expected


def test_snake_never_empty() -> None:
    assert emitter.snake("--") == "x"


def test_lark_string_ci_and_escapes() -> None:
    assert emitter.lark_string('a"b\\', ci=True) == '"a\\"b\\\\"i'
    assert emitter.lark_string("é", ci=False) == '"é"'


@pytest.mark.parametrize(
    ("pattern", "literal", "nullable"),
    [
        ("^\\w+$", "/\\w+/", False),
        ("a\\$", "/a\\$/", False),
        ("a\\\\$", "/a\\\\/", False),
        ("a/b", "/a\\/b/", False),
        ("a\\/b", "/a\\/b/", False),
        ("a\nb", "/a\\nb/", False),
        ("\\s*", "/(?V0)(?=[\\s\\S])(?:\\s*)/", True),
    ],
)
def test_regex_terminal(pattern: str, literal: str, nullable: bool) -> None:
    assert emitter.regex_terminal(pattern) == (literal, nullable)


def test_emit_is_deterministic(grammar_text: str) -> None:
    assert emitter.emit_lark(resolve(load_dir(TOY))) == grammar_text


def test_emit_structure(grammar_text: str) -> None:
    lines = grammar_text.splitlines()
    assert "block: block_uml | block_salt" in lines
    assert 'class_command_create_class: ("class"i /\\s+/ CLASS_IDENT)' in lines
    assert "CLASS_IDENT: /[\\p{L}_][\\p{L}\\p{N}_]*/" in lines
    assert not any(line.startswith("%ignore") for line in lines)


def test_emit_empty_model_is_trivial_but_valid() -> None:
    text = emitter.emit_lark({})
    parser = Lark(text, parser="earley", lexer="dynamic", regex=True)
    assert parser.parse("@startuml\n@enduml").data == "start"
    with pytest.raises(LarkError):
        parser.parse("@startuml\nclass A\n@enduml")


def test_named_terminal_reused_and_disambiguated() -> None:
    models = load_dir(TOY)
    diagram = emitter._Diagram(resolve(models)["toy_class"], emitter._Names())
    first = diagram.part({"regex": "a+", "name": "n"})
    again = diagram.part({"regex": "a+", "name": "n"})
    other = diagram.part({"regex": "b+", "name": "n"})
    assert (first, again, other) == ("CLASS_N", "CLASS_N", "CLASS_N_2")


# --- acceptance: grammar behaviour ------------------------------------------------------


@pytest.mark.parametrize("line", ["CLASS Foo", "class Foo", "  class Foo  ", "class Ünï"])
def test_ci_literal_and_named_regex_parse(runner: LarkRunner, line: str) -> None:
    verdict = runner.parse(uml(line))
    assert verdict == {
        "accepted": True,
        "diagram": "CLASS",
        "first_failure": None,
        "status": OK,
    }


def test_unknown_keyword_rejected_at_its_line(runner: LarkRunner) -> None:
    verdict = runner.parse(uml("class A", "klass Foo"))
    assert verdict["status"] == REJECT
    assert verdict["accepted"] is False
    assert verdict["first_failure"] == {"line": 3, "text": "klass Foo"}


def test_multiline_three_line_body_parses(runner: LarkRunner) -> None:
    src = uml("note left", "one", "two", "", "three", "end note")
    assert runner.parse(src)["accepted"] is True


def test_multiline_missing_end_line_fails(runner: LarkRunner) -> None:
    verdict = runner.parse(uml("note left", "one", "two", "three"))
    assert verdict["status"] == REJECT
    assert verdict["first_failure"]["line"] >= 6


def test_push_pop_nested_context(runner: LarkRunner) -> None:
    assert runner.parse(uml("package p {", "item x", "", "}", "class A"))["accepted"] is True


def test_pushed_context_requires_pop(runner: LarkRunner) -> None:
    verdict = runner.parse(uml("package p {", "item x"))
    assert verdict["status"] == REJECT


def test_pushed_context_rejects_foreign_command(runner: LarkRunner) -> None:
    verdict = runner.parse(uml("package p {", "class A", "}"))
    assert verdict["first_failure"] == {"line": 3, "text": "class A"}


@pytest.mark.parametrize("line", ["hide", "hide   foo", "path /abc/def"])
def test_nullable_anchor_and_slash_regexes(runner: LarkRunner, line: str) -> None:
    assert runner.parse(uml(line))["accepted"] is True


def test_second_diagram_type_selected(runner: LarkRunner) -> None:
    verdict = runner.parse("@startsalt\n[ok]\n@endsalt")
    assert verdict["diagram"] == "SALT"
    assert verdict["status"] == OK


def test_start_keyword_must_match_diagram(runner: LarkRunner) -> None:
    assert runner.parse("@startsalt\nclass A\n@endsalt")["status"] == REJECT


def test_crlf_and_empty_block(runner: LarkRunner) -> None:
    assert runner.parse("@startuml\r\nclass A\r\n@enduml\r\n")["accepted"] is True
    assert runner.parse("@startuml\n@enduml")["accepted"] is True


def test_empty_input_rejected(runner: LarkRunner) -> None:
    verdict = runner.parse("")
    assert verdict["status"] == REJECT
    assert verdict["first_failure"] == {"line": 1, "text": ""}


def test_worker_is_reused_between_calls(runner: LarkRunner) -> None:
    runner.parse(uml("class A"))
    first = runner.last_process
    runner.parse(uml("class B"))
    assert runner.last_process is first


# --- timeout / worker failure ----------------------------------------------------------


def test_timeout_kills_worker_and_recovers() -> None:
    r = LarkRunner(AMBIGUOUS)
    try:
        verdict = r.parse("x" * 400, SHORT_TIMEOUT_S)
        assert verdict == {
            "accepted": False,
            "diagram": None,
            "first_failure": None,
            "status": "timeout",
        }
        dead = r.last_process
        assert dead is not None and dead.exitcode is not None
        assert r.worker is None
        assert r.parse("xx")["status"] == OK
        assert r.last_process is not dead
    finally:
        r.close()


def test_missing_grammar_is_error_verdict(tmp_path: Path) -> None:
    r = LarkRunner(tmp_path / "nope.lark")
    assert r.parse("x") == {
        "accepted": False,
        "diagram": None,
        "first_failure": None,
        "status": "error",
    }


def test_worker_death_is_error_and_restarts(tmp_path: Path) -> None:
    path = tmp_path / "g.lark"
    path.write_text('start: "x"\n', encoding="utf-8")
    r = LarkRunner(path)
    try:
        assert r.parse("x")["status"] == OK
        assert r.worker is not None
        r.worker.process.kill()
        r.worker.process.join()
        assert r.parse("x")["status"] == "error"
        assert r.parse("x")["status"] == OK
    finally:
        r.close()


def test_parse_with_lark_uses_cached_runner_per_grammar(tmp_path: Path) -> None:
    path = tmp_path / "g.lark"
    path.write_text('start: "x"\n', encoding="utf-8")
    try:
        assert lark_parse.parse_with_lark("x", grammar_path=path)["status"] == OK
        assert lark_parse.parse_with_lark("y", grammar_path=path)["first_failure"] == {
            "line": 1,
            "text": "y",
        }
        assert list(lark_parse._runners) == [path]
    finally:
        lark_parse.close_all()
        lark_parse._runners.clear()


# --- pure helpers ------------------------------------------------------------------------


def test_failure_line_positions() -> None:
    text = "a\nbb\nccc"
    assert lark_parse.failure_line(text, 0) == (1, "a")
    assert lark_parse.failure_line(text, 3) == (2, "bb")
    assert lark_parse.failure_line(text, 99) == (3, "ccc")
    assert lark_parse.failure_line(text, None) == (3, "ccc")
    assert lark_parse.failure_line("a\r\nb", 0) == (1, "a")


def test_parse_text_lark_error_is_error_status() -> None:
    class Boom:
        def parse(self, text: str) -> None:
            raise LarkError("boom")

    assert lark_parse.parse_text(Boom(), "x")["status"] == "error"  # type: ignore[arg-type]


def test_diagram_of_without_body_is_none() -> None:
    parser = Lark('start: "x"', parser="earley")
    assert lark_parse.diagram_of(parser.parse("x")) is None


# --- build CLI -------------------------------------------------------------------------


def test_build_only_lark_writes_deterministic_file(tmp_path: Path) -> None:
    args = ["--only", "lark", "--model-dir", str(TOY), "--out-dir", str(tmp_path)]
    assert build_cli.main(args) == 0
    first = (tmp_path / "plantuml.lark").read_bytes()
    assert build_cli.main(args) == 0
    assert (tmp_path / "plantuml.lark").read_bytes() == first
    assert first.decode().startswith(emitter.HEADER + "\n")


def test_build_empty_model_dir_writes_valid_grammar(tmp_path: Path) -> None:
    assert build_cli.main(["--model-dir", str(EMPTY), "--out-dir", str(tmp_path)]) == 0
    text = (tmp_path / "plantuml.lark").read_text(encoding="utf-8")
    assert Lark(text, parser="earley", lexer="dynamic", regex=True).parse("@startuml\n@enduml")


def test_build_default_model_dir_succeeds(tmp_path: Path) -> None:
    assert build_cli.main(["--out-dir", str(tmp_path)]) == 0
    assert (tmp_path / "plantuml.lark").is_file()


def test_build_unknown_emitter_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert build_cli.main(["--only", "lark,nope"]) == build_cli.EXIT_USAGE
    assert "unknown emitter: nope" in capsys.readouterr().err


def test_build_bad_model_dir_reports_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = build_cli.main(["--model-dir", str(tmp_path / "missing"), "--out-dir", str(tmp_path)])
    assert code == build_cli.EXIT_ERROR
    assert "not a directory" in capsys.readouterr().err


def test_select_default_and_registry_shape() -> None:
    assert build_cli.select(None) == list(build_cli.EMITTERS)
    assert build_cli.select(" lark ,") == ["lark"]
    assert build_cli.EMITTERS["lark"].filename == "plantuml.lark"

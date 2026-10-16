"""Lark grammar emitted from the real ``model/``: framing and terminal-rendering regressions."""

from __future__ import annotations

import pytest
from lark import Lark

from tools.emit.build import MODEL_DIR, ROOT
from tools.emit.lark import emit_lark
from tools.model.load import load_dir
from tools.model.resolve import resolve
from tools.validate.lark_parse import build_parser, parse_text

FIXTURES = ROOT / "tests" / "fixtures"
ACCEPT = "ok"
REJECT = "reject"
SPRITE_FIXTURES = [
    "meta-diagrams/pos/sprites-listsprites.puml",
    "meta-diagrams/pos/sprites-listsprite-upper.puml",
    "meta-diagrams/pos/sprites-common-commands.puml",
]
DOT_ESCAPED_QUOTE = "single-line/pos/dot-escaped-quote.puml"
NAME_SUFFIX = "document/forms/name-suffix.puml"  # `@startumlfoo`, jar-accepted as CLASS
START = "@start"


@pytest.fixture(scope="module")
def parser(tmp_path_factory: pytest.TempPathFactory) -> Lark:
    path = tmp_path_factory.mktemp("real-model") / "plantuml.lark"
    path.write_text(emit_lark(resolve(load_dir(MODEL_DIR))), encoding="utf-8")
    return build_parser(path)


def block_of(relative: str) -> str:
    fixture = FIXTURES / relative
    if not fixture.exists():
        pytest.skip(f"{relative} not present")
    text = fixture.read_text(encoding="utf-8")
    return text[text.index(START) :]


@pytest.mark.parametrize("relative", SPRITE_FIXTURES)
def test_startsprites_block_is_accepted(parser: Lark, relative: str) -> None:
    assert parse_text(parser, block_of(relative))["status"] == ACCEPT


def test_escaped_quote_in_dot_header_reaches_the_lexer_intact(parser: Lark) -> None:
    assert parse_text(parser, block_of(DOT_ESCAPED_QUOTE))["status"] == ACCEPT
    assert parse_text(parser, '@startdot\ndigraph "a\\b" {\n@enddot\n')["status"] == REJECT


@pytest.mark.parametrize("end", ["@enderegex", "@enduml", r"\endregex"])
def test_a_regex_block_closes_at_any_end_directive(parser: Lark, end: str) -> None:
    assert parse_text(parser, f"@startregex\nab\n{end}\n")["status"] == ACCEPT


def test_a_start_keyword_without_end_directive_stays_rejected(parser: Lark) -> None:
    assert parse_text(parser, "@startregex\nab\n")["status"] == REJECT


def test_a_start_keyword_followed_by_letters_is_that_keyword(parser: Lark) -> None:
    assert parse_text(parser, block_of(NAME_SUFFIX))["status"] == ACCEPT
    assert parse_text(parser, "@startumlx\nclass Foo\n@enduml\n")["status"] == ACCEPT

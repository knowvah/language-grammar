"""Block framing shared by the three emitters: start keywords from ``start_map`` and any-``@end``.

Upstream closes a block at the first ``StartUtils.isEndDirective`` line (``[@\\\\]end`` plus any
suffix; utils/StartUtils.java:119-121), and offers a factory under every keyword that lists it
(``DiagramType.findStartTypes``, core/DiagramType.java:94-218).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tools.emit import keywords, textmate, w3c
from tools.emit.build import MODEL_DIR
from tools.emit.lark import emit_lark
from tools.interp.source import is_end_directive
from tools.model.load import load_dir
from tools.model.resolve import resolve
from tools.validate.lark_parse import build_parser, parse_text

FRAMING = Path(__file__).parent / "fixtures" / "framing"
TOY = Path(__file__).parent / "fixtures" / "toy"
ACCEPT, REJECT = "ok", "reject"
LIST_LINE = "listsprite"
END_LINES = ["@enduml", "@endsprites", "@endmindmap", "  @end", r"\enduml", "@endfoo bar"]


@pytest.fixture(scope="module")
def toy_resolved():
    return resolve(load_dir(FRAMING))


@pytest.fixture(scope="module")
def real_resolved():
    return resolve(load_dir(MODEL_DIR))


@pytest.fixture(scope="module")
def toy_parser(tmp_path_factory: pytest.TempPathFactory, toy_resolved):
    path = tmp_path_factory.mktemp("framing") / "plantuml.lark"
    path.write_text(emit_lark(toy_resolved), encoding="utf-8")
    return build_parser(path)


def status(parser: Any, text: str) -> str:
    return str(parse_text(parser, text)["status"]).lower()


# --- keywords ------------------------------------------------------------------------


def test_document_start_map_comes_from_the_document_layer(toy_resolved) -> None:
    assert list(keywords.document_start_map(toy_resolved)) == [
        "uml",
        "sprites",
        "gantt",
        "project",
        "nomodel",
    ]


def test_document_start_map_is_empty_without_a_document_layer() -> None:
    assert keywords.document_start_map(resolve(load_dir(TOY))) == {}


def test_model_is_offered_under_every_keyword_naming_its_factory(toy_resolved) -> None:
    groups = keywords.group_by_keyword(toy_resolved)
    assert {k: [m.id for m in v] for k, v in groups.items()} == {
        "gantt": ["fr_gantt"],
        "project": ["fr_gantt"],
        "uml": ["fr_list"],
        "sprites": ["fr_list"],
    }


def test_models_without_factory_fall_back_to_the_diagram_type_keyword() -> None:
    groups = keywords.group_by_keyword(resolve(load_dir(TOY)))
    assert list(groups) == ["uml", "salt"]


@pytest.mark.parametrize(
    ("diagram", "keyword"),
    [("CLASS", "uml"), ("SPRITES", "uml"), ("SALT", "salt"), ("PACKET", "packetdiag")],
)
def test_start_keyword_by_diagram_type(diagram: str, keyword: str) -> None:
    assert keywords.start_keyword(diagram) == keyword


def test_every_real_start_keyword_has_a_block_in_all_three_emitters(real_resolved) -> None:
    expected = set(keywords.document_start_map(real_resolved))
    assert len(expected) == 29
    assert {"sprites", "project", "uml", "gantt"} <= expected
    lark_text = emit_lark(real_resolved)
    w3c_text = w3c.emit_w3c(real_resolved)
    grammar = textmate.emit_textmate(real_resolved)
    blocks = [p["begin"] for p in grammar["patterns"] if "begin" in p]
    for keyword in sorted(expected):
        upper = keyword.upper()
        assert f"\nblock_{keyword}: START_{upper} " in lark_text, keyword
        assert f"\nblock_{keyword} ::= START_{upper} " in w3c_text, keyword
        assert f"START_{upper} ::=" in w3c_text, keyword
        assert f"START_{upper}: /" in lark_text, keyword
        assert f"diagram_{keyword}" in grammar["repository"], keyword
        assert any(b.endswith(f"{keyword})(?![A-Za-z0-9])") for b in blocks), keyword
    assert len(blocks) == len(expected)


# --- Lark framing ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "start", ["@startuml", "@startsprites", "@startsprites name", r"\startuml"]
)
def test_lark_sprites_block_and_uml_block_accept_the_sprite_model(toy_parser, start: str) -> None:
    assert status(toy_parser, f"{start}\n{LIST_LINE}\n@enduml\n") == ACCEPT


def test_lark_project_block_uses_the_gantt_model(toy_parser) -> None:
    assert status(toy_parser, "@startproject\ntask abc\n@endproject\n") == ACCEPT
    assert status(toy_parser, "@startproject\nlistsprite\n@endproject\n") == REJECT


@pytest.mark.parametrize("end", END_LINES)
def test_lark_any_end_directive_closes_any_block(toy_parser, end: str) -> None:
    assert is_end_directive(end)
    assert status(toy_parser, f"@startsprites\n{LIST_LINE}\n{end}\n") == ACCEPT


@pytest.mark.parametrize("line", ["end", "@ end", "@begin", "@star", "enduml"])
def test_lark_non_end_line_does_not_close_a_block(toy_parser, line: str) -> None:
    assert not is_end_directive(line)
    assert status(toy_parser, f"@startsprites\n{LIST_LINE}\n{line}\n") == REJECT


def test_lark_end_is_case_sensitive_like_upstream(toy_parser) -> None:
    assert status(toy_parser, f"@startsprites\n{LIST_LINE}\n@ENDSPRITES\n") == REJECT


# --- W3C and TextMate framing -----------------------------------------------------------


def test_w3c_has_one_shared_end_production_accepting_any_end_directive(toy_resolved) -> None:
    text = w3c.emit_w3c(toy_resolved)
    ends = [line for line in text.splitlines() if line.startswith("END_")]
    assert ends == ['END_BLOCK ::= [#x20#x9]* ("@" | "\\") "end" [^#xD#xA]*']
    assert "block_sprites ::= START_SPRITES NL " in text
    assert text.count("END_BLOCK") == 1 + 4  # definition + four blocks


def test_textmate_block_ends_at_any_end_directive(toy_resolved) -> None:
    grammar = textmate.emit_textmate(toy_resolved)
    blocks = [p for p in grammar["patterns"] if "begin" in p]
    assert {b["end"] for b in blocks} == {r"^\s*([@\\]end[A-Za-z0-9]*)"}
    assert [b["begin"] for b in blocks][3] == r"(?i)^\s*([@\\]startsprites)(?![A-Za-z0-9])"
    assert "diagram_project" in grammar["repository"]

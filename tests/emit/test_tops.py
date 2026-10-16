"""Emitters render only the top model of each factory (a family replaces its base)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.emit import tops
from tools.emit.lark import emit_lark
from tools.emit.textmate import emit_textmate_json
from tools.emit.w3c import emit_w3c
from tools.model import ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve
from tools.validate.lark_parse import build_parser, parse_text

FAMILY = Path(__file__).parent / "fixtures" / "family"
BASE_ID = "gen-seq"
TOP_ID = "seq"
LOOSE_ID = "loose"
REMOVED = "gone"
ACCEPT = "ok"
REJECT = "reject"


@pytest.fixture(scope="module")
def models() -> ResolvedModels:
    return resolve(load_dir(FAMILY))


def uml_text(*lines: str) -> str:
    return "\n".join(["@startuml", *lines, "@enduml"]) + "\n"


def test_emitted_diagrams_are_tops_and_factoryless_models(models: ResolvedModels) -> None:
    assert [m.id for m in tops.emitted_diagrams(models)] == [LOOSE_ID, TOP_ID]


def test_without_the_family_the_base_is_the_top(models: ResolvedModels) -> None:
    stripped = {k: v for k, v in models.items() if k != TOP_ID}
    assert [m.id for m in tops.emitted_diagrams(stripped)] == [BASE_ID, LOOSE_ID]
    assert tops.emitted_diagrams({}) == []


@pytest.fixture(scope="module")
def lark_parser(models: ResolvedModels, tmp_path_factory: pytest.TempPathFactory):
    path = tmp_path_factory.mktemp("family") / "plantuml.lark"
    path.write_text(emit_lark(models), encoding="utf-8")
    return build_parser(path)


@pytest.mark.parametrize(
    ("line", "status"),
    [
        ("wide alpha", ACCEPT),
        ("wide beta", ACCEPT),
        ("wide gamma", REJECT),
        (REMOVED, REJECT),
        ("kept", ACCEPT),
    ],
)
def test_lark_honours_family_narrowing_and_remove(lark_parser, line: str, status: str) -> None:
    assert parse_text(lark_parser, uml_text(line))["status"] == status


def test_lark_keeps_factoryless_model(lark_parser) -> None:
    assert parse_text(lark_parser, "@startuml\ntick\n@enduml\n")["status"] == ACCEPT


def test_lark_has_one_sequence_body(models: ResolvedModels) -> None:
    bodies = [x for x in emit_lark(models).splitlines() if x.startswith("sequence_body")]
    assert len(bodies) == 1


def test_textmate_omits_base_entries(models: ResolvedModels) -> None:
    text = json.dumps(json.loads(emit_textmate_json(models))).lower()
    assert "alpha" in text
    assert "gamma" not in text
    assert REMOVED not in text
    assert "kept" in text
    assert "tick" in text


def test_w3c_omits_base_entries(models: ResolvedModels) -> None:
    text = emit_w3c(models)
    assert "sequence_command_wide" in text
    assert '("alpha" | "beta")' in text
    assert "sequence_command_gone" not in text
    assert text.count("sequence_command_kept ::=") == 1

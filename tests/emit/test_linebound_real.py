"""Line-bounded terminals, checked on a Lark grammar built from the real ``model/``."""

from __future__ import annotations

import re

import pytest
import regex
from lark import Lark

from tools.emit.build import MODEL_DIR, ROOT
from tools.emit.lark import emit_lark
from tools.model.load import load_dir
from tools.model.resolve import resolve
from tools.validate.lark_parse import build_parser, parse_text

NEG = ROOT / "tests" / "fixtures" / "sequence" / "neg"
SEQUENCE_MODEL = MODEL_DIR / "diagrams" / "sequence.yaml"
START = "@start"
REJECT = "reject"
FIXTURES = [
    "group-extra-end",
    "box-extra-end",
    "note-accross",
    "autonumber-start-overflow",
    "group-stray-else",
]


@pytest.fixture(scope="module")
def parser(tmp_path_factory: pytest.TempPathFactory) -> Lark:
    if not SEQUENCE_MODEL.exists():
        pytest.skip("sequence family model not present")
    path = tmp_path_factory.mktemp("real") / "plantuml.lark"
    path.write_text(emit_lark(resolve(load_dir(MODEL_DIR))), encoding="utf-8")
    return build_parser(path)


@pytest.mark.parametrize("name", FIXTURES)
def test_lark_rejects_sequence_negative(parser: Lark, name: str) -> None:
    fixture = NEG / f"{name}.puml"
    if not fixture.exists():
        pytest.skip(f"{fixture.name} not present")
    text = fixture.read_text(encoding="utf-8")
    block = text[text.index(START) :]
    assert parse_text(parser, block)["status"] == REJECT


PROBE = 'a b_1 \r\n  #x;"q" [r]\n\t.,:<>\u00e9 \n'
MULTILINE_TERMINALS = frozenset({"_LONG_COMMENT", "_NL"})


def test_no_emitted_terminal_matches_across_a_line_end(parser: Lark) -> None:
    crossing = []
    for terminal in parser.terminals:
        if terminal.name in MULTILINE_TERMINALS:
            continue
        flags = regex.I if "i" in terminal.pattern.flags else 0
        compiled = regex.compile(terminal.pattern.to_regexp(), flags)
        for start in range(len(PROBE)):
            found = compiled.match(PROBE, start)
            if found and re.search(r"[\r\n]", found.group(0)):
                crossing.append(terminal.name)
                break
    assert crossing == []

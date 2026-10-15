"""Tests for the W3C EBNF emitter (regex translation, structure, lossiness, build path)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools.emit import build as build_cli
from tools.emit import w3c
from tools.emit.lark import _Names
from tools.emit.w3c_regex import translate_regex
from tools.emit.w3c_text import (
    Node,
    Sink,
    ci_literal,
    comment,
    complement,
    fold_ascii,
    format_class,
    join_alt,
    join_seq,
    quote,
    repeat,
)
from tools.model import ModelLoadError
from tools.model.load import load_dir
from tools.model.resolve import resolve

FIXTURES = Path(__file__).parent / "fixtures"
LOSSY = FIXTURES / "w3c" / "lossy"
TOY = FIXTURES / "toy"
RULE = "r"
DOUBLE_QUOTE = '"'


def tr(pattern: str) -> tuple[str, Sink]:
    sink = Sink(_Names())
    return translate_regex(pattern, sink, RULE).text, sink


# --- regex translation ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("[A-Za-z_][A-Za-z0-9_]*", "[A-Za-z_] [A-Za-z0-9_]*"),
        ("abc", '"abc"'),
        ("ab*", '"a" "b"*'),
        ("(a|b)c", '("a" | "b") "c"'),
        ("a|b", '"a" | "b"'),
        ("a{2,3}b", '"a" "a" "a"? "b"'),
        ("a{2}", '"a" "a"'),
        ("x{3,}", '"x" "x" "x"+'),
        ("x{0,2}", '"x"? "x"?'),
        ("x{0,}", '"x"*'),
        ("a+?", '"a"+'),
        ("a*+", '"a"*'),
        ("(?:ab)+", '"ab"+'),
        ("(?:a|b)*", '("a" | "b")*'),
        ("(?<n>x)(?P<m>y)(z)", '"x" "y" "z"'),
        (r"\s+", "[#x9-#xD#x20]+"),
        (r"\w\d", "[0-9A-Z_a-z] [0-9]"),
        (r"\S", "[^#x9-#xD#x20]"),
        (r"[^\s\]]+", "[^#x9-#xD#x20#x5D]+"),
        (r"[\S]", "[#x0-#x8#xE-#x1F#x21-#x10FFFF]"),
        (r"[a\-z\t\x41B\b]", "[a#x2Dz#x9AB#x8]"),
        ("[]a]", "[#x5Da]"),
        ("[a-]", "[a#x2D]"),
        ("[a-\\d]", "[a#x2D0-9]"),
        (".", "[^#xA#xD]"),
        ("^abc$", '"abc"'),
        (r"\Aab\z\Z\G", '"ab"'),
        (r"a\.b\/", '"a.b/"'),
        (r"\x41\x{42}C\n", '"ABC" #xA'),
        ('say "hi"', '"say " \'"\' "hi" \'"\''),
        ("", '""'),
        ("(a|)", '"a" | ""'),
        ("x{", '"x{"'),
        ("a{40}", '"a"+ /* regex: a{40} */'),
        ("a{0,99}", '"a"* /* regex: a{0,99} */'),
        ("(?i)ab[c-e]", "[Aa] [Bb] [C-Ec-e]"),
        ("(?i:ab)c", '[Aa] [Bb] "c"'),
        ("(?i:a)(?-i:b)c", '[Aa] "b" "c"'),
        ("(?i)(?-i)a", '"a"'),
        (r"(?i)\w", "[0-9A-Z_a-z]"),
        ("(?i)(a)b", "[Aa] [Bb]"),
        ("(?>a)", '"a"'),
    ],
)
def test_translate_regex(pattern: str, expected: str) -> None:
    text, sink = tr(pattern)
    assert text == expected
    assert [(item.construct) for item in sink.lossy] == (
        ["large-repeat"] if "regex: a{" in expected else []
    )


@pytest.mark.parametrize(
    ("pattern", "construct", "body", "original"),
    [
        ("foo(?=bar)", "lookaround", '""', "(?=bar)"),
        ("(?!x)a", "lookaround", '""', "(?!x)"),
        ("(?<=a(b))c", "lookaround", '""', "(?<=a(b))"),
        ("(?<!a)c", "lookaround", '""', "(?<!a)"),
        (r"(?=\)[)\]]x)y", "lookaround", '""', r"(?=\)[)\]]x)"),
        (r"(?![^]x]a)", "lookaround", '""', "(?![^]x]a)"),
        (r"(a)\12", "backreference", "[^#xA#xD]*", r"\12"),
        (r"\k<n", "backreference", "[^#xA#xD]*", r"\k<n"),
        (r"[a-\p{L}]", "unicode-property", "[^#xA#xD]", r"[a-\p{L}]"),
        (r"a\bb", "word-boundary", '""', r"\b"),
        (r"a\Bb", "word-boundary", '""', r"\B"),
        (r"\p{L}", "unicode-property", "[^#xA#xD]", r"\p{L}"),
        (r"\pL", "unicode-property", "[^#xA#xD]", r"\pL"),
        (r"\P{Lu}", "unicode-property", "[^#xA#xD]", r"\P{Lu}"),
        (r"[\p{L}\d]", "unicode-property", "[^#xA#xD]", r"[\p{L}\d]"),
        (r"(a)\1", "backreference", "[^#xA#xD]*", r"\1"),
        (r"(?<n>a)\k<n>", "backreference", "[^#xA#xD]*", r"\k<n>"),
        (r"(?(1)a|b)", "unsupported-construct", "[^#xA#xD]*", "(?(1)a|b)"),
        (r"(?(1)a|b)\)[(]", "unsupported-construct", "[^#xA#xD]*", "(?(1)a|b)"),
    ],
)
def test_lossy_constructs_become_placeholders(
    pattern: str, construct: str, body: str, original: str
) -> None:
    text, sink = tr(pattern)
    assert [(i.rule, i.construct, i.regex) for i in sink.lossy] == [(RULE, construct, original)]
    assert f"{RULE}_lossy" in text
    assert sink.lines == [f"{RULE}_lossy ::= {body} /* regex: {original} */"]


def test_inline_flags_other_than_i_are_noted() -> None:
    text, sink = tr("(?s)a")
    assert text == '"a"'
    assert [(i.construct, i.regex) for i in sink.lossy] == [("inline-flags", "(?s)")]


def test_two_lossy_constructs_get_distinct_names() -> None:
    text, sink = tr(r"\bw\b")
    assert text == 'r_lossy "w" r_lossy_2'
    assert len(sink.lines) == 2


def test_unparseable_regex_becomes_one_placeholder() -> None:
    text, sink = tr("a)b")
    assert text == "r_lossy"
    assert [(i.construct, i.regex) for i in sink.lossy] == [("unsupported-construct", "a)b")]


def test_unterminated_class_becomes_placeholder() -> None:
    _, sink = tr("[abc")
    assert [i.construct for i in sink.lossy] == ["unsupported-construct"]


# --- text helpers --------------------------------------------------------------------------


def test_ci_literal_convention() -> None:
    assert ci_literal("class").text == "[Cc] [Ll] [Aa] [Ss] [Ss]"
    assert ci_literal("end note").text == '[Ee] [Nn] [Dd] " " [Nn] [Oo] [Tt] [Ee]'
    assert ci_literal("@1").text == '"@1"'
    assert ci_literal("").text == '""'
    assert ci_literal("é").text == "[#xC9#xE9]"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("abc", '"abc"'),
        ('a"b', '"a" \'"\' "b"'),
        ("\t", "#x9"),
        ("a\nb", '"a" #xA "b"'),
        ('"', "'\"'"),
        ("", '""'),
    ],
)
def test_quote(text: str, expected: str) -> None:
    assert quote(text).text == expected


def test_format_class_keeps_order_and_escapes() -> None:
    assert format_class([(97, 122), (65, 90), (95, 95)]) == "[a-zA-Z_]"
    assert format_class([(32, 32), (45, 45)], negated=True) == "[^#x20#x2D]"
    assert format_class([]) == "[^#x0-#x10FFFF]"
    assert format_class([], negated=True) == "[#x0-#x10FFFF]"


def test_complement_and_fold() -> None:
    assert complement([(0, 9), (11, 0x10FFFF)]) == [(10, 10)]
    assert complement([(5, 6), (1, 2)]) == [(0, 0), (3, 4), (7, 0x10FFFF)]
    assert fold_ascii([(97, 98)]) == [(65, 66), (97, 98)]
    assert fold_ascii([(48, 57)]) == [(48, 57)]


def test_join_helpers_and_repeat() -> None:
    assert join_seq([]).text == '""'
    alt = join_alt([Node('"a"'), Node('"b"')])
    assert join_alt([Node("x")]).text == "x"
    assert join_seq([alt, Node("y")]).text == '("a" | "b") y'
    assert repeat(Node("x y", "seq"), 0, 1).text == "(x y)?"
    assert repeat(Node("x"), 0, 0).text == '""'
    assert comment("a*/b\n") == "/* regex: a* /b\\n */"


# --- model walk ----------------------------------------------------------------------------

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NOISE = re.compile(r"/\*.*?\*/|\"[^\"]*\"|'[^']*'|\[[^\]]*\]|#x[0-9A-Fa-f]+", re.S)


def productions(text: str) -> dict[str, str]:
    """Parse ``name ::= body`` productions (continuation lines start with ``|``)."""
    out: dict[str, str] = {}
    current = ""
    for line in text.splitlines():
        match = re.match(r"([A-Za-z_]\w*) ::= (.*)$", line)
        if match:
            current = match[1]
            assert current not in out, f"duplicate production {current}"
            out[current] = match[2]
        elif line.startswith("    |"):
            out[current] += " " + line.strip()
    return out


def check_w3c_syntax(text: str) -> dict[str, str]:
    """Assert balanced parens and defined references; return the productions."""
    body = re.sub(r"\A/\*.*?\*/", "", text, count=1, flags=re.S)
    prods = productions(body)
    for name, expr in prods.items():
        plain = _NOISE.sub(" ", expr)
        assert plain.count("(") == plain.count(")"), name
        for ref in _NAME.findall(plain):
            assert ref in prods, f"{name} references undefined {ref}"
    return prods


@pytest.fixture(scope="module")
def lossy_result() -> tuple[str, list[w3c.Lossy]]:
    return w3c.emit_w3c_with_lossiness(resolve(load_dir(LOSSY)))


def test_output_is_valid_w3c_with_every_name_defined(
    lossy_result: tuple[str, list[w3c.Lossy]],
) -> None:
    prods = check_w3c_syntax(lossy_result[0])
    assert prods["plantuml"] == "NL* block (NL+ block)* NL*"
    assert prods["block"] == "block_uml | block_salt"
    assert prods["block_uml"] == "START_UML NL class_body END_UML"
    assert prods["NL"] == "#xD? #xA"


def test_ci_literal_and_regex_in_rule(lossy_result: tuple[str, list[w3c.Lossy]]) -> None:
    prods = productions(lossy_result[0])
    assert (
        prods["class_command_ident"]
        == "[Cc] [Ll] [Aa] [Ss] [Ss] [#x9-#xD#x20]+ [A-Za-z_] [A-Za-z0-9_]*"
    )
    assert prods["class_command_look"].startswith('"say " \'"\' "hi" \'"\' "foo" ')


def test_lookahead_gives_placeholder_and_lossiness_entry(
    lossy_result: tuple[str, list[w3c.Lossy]],
) -> None:
    text, lossy = lossy_result
    prods = productions(text)
    assert prods["class_command_look_lossy"] == '"" /* regex: (?=bar) */'
    assert [(i.rule, i.construct) for i in lossy if i.construct == "lookaround"] == [
        ("class_command_look", "lookaround")
    ]
    assert [(i.rule, i.construct) for i in lossy] == [
        ("class_command_look", "lookaround"),
        ("class_command_look", "unicode-property"),
        ("salt_command_back", "backreference"),
    ]


def test_header_states_lossiness_count_and_convention(
    lossy_result: tuple[str, list[w3c.Lossy]],
) -> None:
    header = lossy_result[0].split("*/", 1)[0]
    assert "Lossiness: 3 constructs approximated (backreference: 1, lookaround: 1" in header
    assert "[Cc][Ll][Aa][Ss][Ss]" in header
    assert header.count("/*") == 1


def test_structure_push_pop_and_multiline(lossy_result: tuple[str, list[w3c.Lossy]]) -> None:
    prods = productions(lossy_result[0])
    assert prods["class_command_open"] == '"{" NL class_inner_block'
    assert prods["class_inner_block"] == "(class_inner_block_line? NL)* class_inner_block_pop_line"
    assert prods["class_command_item"] == '("a" | "b")*'
    assert prods["class_command_block"].endswith(
        '(BODY_LINE? NL)* [Ee] [Nn] [Dd] " " [Nn] [Oo] [Tt] [Ee]'
    )
    assert prods["class_line_command"].count("\n") == 0
    assert prods["class_line_command"].split(" | ")[0] == "class_command_ident"
    assert prods["START_SALT"].startswith('[#x20#x9]* "@" [Ss] [Tt] [Aa] [Rr] [Tt] [Ss]')


def test_emit_w3c_returns_text_only(lossy_result: tuple[str, list[w3c.Lossy]]) -> None:
    assert w3c.emit_w3c(resolve(load_dir(LOSSY))) == lossy_result[0]


def test_deterministic() -> None:
    first = w3c.emit_w3c(resolve(load_dir(TOY)))
    assert w3c.emit_w3c(resolve(load_dir(TOY))) == first
    check_w3c_syntax(first)


def test_no_diagram_models_yields_default_uml_block(tmp_path: Path) -> None:
    text, lossy = w3c.emit_w3c_with_lossiness(resolve(load_dir(tmp_path)))
    prods = check_w3c_syntax(text)
    assert prods["block_uml"] == "START_UML NL END_UML"
    assert lossy == []
    assert "Lossiness: 0 constructs approximated (none)." in text


def test_context_without_commands_or_pop(tmp_path: Path) -> None:
    (tmp_path / "m.yaml").write_text(
        """schema_version: 1
id: m
layer: diagram
diagram: CLASS
contexts:
  main:
    - command: CommandGo
      provenance: {class: t.CommandGo}
      kind: single
      parts: {literal: go, ci: false}
      push: empty
  empty: []
""",
        encoding="utf-8",
    )
    prods = check_w3c_syntax(w3c.emit_w3c(resolve(load_dir(tmp_path))))
    assert prods["class_empty_block"] == "(class_empty_block_line? NL)* class_empty_block_line?"
    assert prods["class_empty_block_line"] == "WS"


# --- build path ------------------------------------------------------------------------------


def test_build_writes_deterministic_ebnf_with_lossiness_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        build_cli.EMITTERS, "w3c", build_cli.EmitterSpec("tools.emit.w3c:emit_w3c", "plantuml.ebnf")
    )
    paths = build_cli.build(["w3c"], LOSSY, tmp_path)
    assert paths == [tmp_path / "plantuml.ebnf"]
    first = paths[0].read_text(encoding="utf-8")
    build_cli.build(["w3c"], LOSSY, tmp_path)
    assert paths[0].read_text(encoding="utf-8") == first
    assert "Lossiness: 3 constructs approximated" in first


def test_build_cli_only_w3c(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        build_cli.EMITTERS, "w3c", build_cli.EmitterSpec("tools.emit.w3c:emit_w3c", "plantuml.ebnf")
    )
    argv = ["--only", "w3c", "--model-dir", str(LOSSY), "--out-dir", str(tmp_path)]
    assert build_cli.main(argv) == build_cli.EXIT_OK
    assert (tmp_path / "plantuml.ebnf").read_text(encoding="utf-8").startswith("/*\n")


def test_bad_model_dir_still_reports_load_error(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text("id: bad\n", encoding="utf-8")
    with pytest.raises(ModelLoadError):
        w3c.emit_w3c(resolve(load_dir(tmp_path)))

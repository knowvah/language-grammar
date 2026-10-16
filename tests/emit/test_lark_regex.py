"""Alternation reordering for Lark terminals (``tools.emit.lark_regex``)."""

from __future__ import annotations

import pytest
import regex
from lark import Lark

from tools.emit import lark_regex as lr

ENT = r"([\p{L}\p{N}_.:]+|[\p{L}\p{N}_.:]+\[H\*?\]|\[\*\])"


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        (r"A|A\[H\*?\]", r"A\[H\*?\]|A"),
        (r"(A|A\[H\])x", r"(A\[H\]|A)x"),
        (r"(?:a|a+b)", r"(?:a+b|a)"),
        (r"(?:a|b|ab)", r"(?:ab|a|b)"),
        (r"(x|(y|y\d))", r"(x|(y\d|y))"),
        (r"[a|b]|[a|b]c", r"[a|b]c|[a|b]"),
        (r"\||\|x", r"\|x|\|"),
        (r"(?i:a|ab)", r"(?i:ab|a)"),
        (r"(?i)a|ab", r"(?i)a|ab"),
        (r"(?<=a|ab)c", r"(?<=ab|a)c"),
        (r"(?P<n>a|ab)", r"(?P<n>ab|a)"),
        (r"(|a)", r"(|a)"),
        (r"a|a", r"a|a"),
        (r"abc", r"abc"),
        (r"[]|]x|[]|]", r"[]|]x|[]|]"),
    ],
)
def test_lift_prefixed(pattern: str, expected: str) -> None:
    assert lr.lift_prefixed(pattern) == expected


def test_lift_prefixed_is_stable_when_nothing_extends() -> None:
    assert lr.lift_prefixed(r"(foo|bar|baz)") == "(foo|bar|baz)"


def test_prefer_longest_applies_both_word_and_prefix_rules() -> None:
    assert lr.prefer_longest("(par|partition)") == "(partition|par)"
    assert lr.prefer_longest(ENT).startswith(r"([\p{L}\p{N}_.:]+\[H\*?\]|[\p{L}\p{N}_.:]+|")


def terminal_parser(pattern: str) -> Lark:
    literal, _ = lr.regex_terminal(pattern)
    grammar = f"start: ENT _TAIL\nENT: {literal}\n_TAIL: / --> B/\n"
    return Lark(grammar, parser="earley", lexer="dynamic_complete", regex=True)


@pytest.mark.parametrize("text", ["Stopwatch[H] --> B", "Stopwatch[H*] --> B", "Stopwatch --> B"])
def test_history_suffix_is_reachable_when_more_text_follows(text: str) -> None:
    tree = terminal_parser(ENT).parse(text)
    assert str(tree.children[0]) == text.removesuffix(" --> B")


def test_regex_terminal_keeps_unrelated_alternation_order() -> None:
    literal, _ = lr.regex_terminal("(foo|bar)")
    assert literal == "/(foo|bar)/"


QUOTE_CASES = [
    (r'"(?:[^"\\]|\\")*"', ['"ab"', '"a\\"b"'], ['"a\\b"', '"ab', '"a\\\\"']),
    (r'\\"', ['\\"'], ['"', '\\\\"']),
    (r"a\"b", ['a"b'], ['a\\"b']),
    (r'[\\"]x', ["\\x", '"x'], ["ax"]),
    (r'\\\\"', ['\\\\"'], ['\\"']),
    (r"a/b", ["a/b"], ["ab"]),
]


@pytest.mark.parametrize(("pattern", "matching", "rejected"), QUOTE_CASES)
def test_terminal_keeps_backslash_and_quote_through_lark_escape_evaluation(
    pattern: str, matching: list[str], rejected: list[str]
) -> None:
    """Lark's ``eval_escaping`` turned ``\\\\"`` into ``\\"``; the lexer must see the original."""
    literal, _ = lr.regex_terminal(pattern)
    parser = Lark(f"start: {literal}\n", lexer="dynamic_complete", regex=True)
    compiled = regex.compile(parser.terminals[0].pattern.to_regexp())
    assert [bool(compiled.fullmatch(t)) for t in matching] == [True] * len(matching)
    assert [bool(compiled.fullmatch(t)) for t in rejected] == [False] * len(rejected)
    original = regex.compile(pattern)
    assert [bool(original.fullmatch(t)) for t in matching + rejected] == [True] * len(matching) + [
        False
    ] * len(rejected)


def test_render_literal_body_quotes_become_hex_escapes() -> None:
    assert lr.render_literal_body(r'\\"') == r"\\\x22"
    assert lr.render_literal_body(r"\"") == r"\x22"
    assert lr.render_literal_body('a"/\n\\') == "a\\x22\\/\\n\\"


# --- Java semantics inside terminals ------------------------------------------------------


def terminal_regex(pattern: str, ci: bool = False) -> regex.Pattern[str]:
    """The pattern the lexer compiles for a terminal (after Lark's escape evaluation)."""
    literal, _ = lr.regex_terminal(pattern, ci)
    parser = Lark(f"start: {literal}\n", lexer="dynamic_complete", regex=True)
    return regex.compile(parser.terminals[0].pattern.to_regexp())


@pytest.mark.parametrize(
    ("pattern", "ci", "accepted", "rejected"),
    [
        (r"\d+", False, ["09"], ["٣"]),
        (r"\w+", False, ["a_9"], ["\xe9", "a b"]),
        (r"[\w-]+", False, ["a-b"], ["\xe9"]),
        (r"a.b", False, ["axb", "a\x0bb"], ["a b", "a\x85b", "a b"]),
        (r"class", True, ["CLaSS"], ["claſs", "clas"]),
        (r"k", True, ["K"], ["K"]),
        (r"[a-c]+", True, ["aBc"], ["K", "d"]),
        (r"\p{Lu}", True, ["a", "\xe9"], ["1"]),
        (r"\s\S", False, [" x"], ["\xa0x", " x"]),
        (r"[^\]\\-]", False, ["a", "^"], ["]", "\\", "-"]),
        (r"[\]\\^-]+", False, ["]\\^-"], ["a"]),
        (r"a\b.", False, ["a-"], ["ab"]),
        (r"[\W]+", False, ["\xe9 -"], ["a"]),
    ],
)
def test_terminal_has_java_meaning(
    pattern: str, ci: bool, accepted: list[str], rejected: list[str]
) -> None:
    compiled = terminal_regex(pattern, ci)
    assert [bool(compiled.fullmatch(t)) for t in accepted] == [True] * len(accepted)
    assert [bool(compiled.fullmatch(t)) for t in rejected] == [False] * len(rejected)


def test_terminal_carries_no_lark_case_flag() -> None:
    literal, _ = lr.regex_terminal("abc", ci=True)
    assert literal == "/[aA][bB][cC]/"


def test_dollar_and_z_inside_a_terminal_end_at_the_line_not_the_text() -> None:
    assert lr.lark_pattern(r"a(?=b|$)") == r"a(?=b|(?=\r|\n|\Z))"
    compiled = regex.compile(lr.lark_pattern(r"a\Z"))
    assert compiled.match("a\nb") is not None
    assert compiled.match("ab") is None
    assert lr.lark_pattern(r"^a$") == "a"  # outer anchors are still dropped


def test_explicit_classes_stay_inside_the_line() -> None:
    for pattern in (r"\D+", r"\W+", r"[^\w]+", r"[\W]+", r".+", r"\S+", r"[\D]+"):
        match = regex.compile(lr.lark_pattern(pattern)).match("-!\r\n+\n")
        assert match is not None and not regex.search(r"[\r\n]", match.group()), pattern


def test_word_boundary_lookbehinds_survive_the_terminal_stages() -> None:
    java = lr.to_python(r"if\b", end_anchor=lr.LINE_END)
    for text in ["if x", "iffy", "if́", "if_"]:
        assert bool(regex.match(java, text)) == bool(regex.match(lr.lark_pattern(r"if\b"), text))


def test_ci_regex_inside_prefer_longest_still_lifts_prefixed_alternatives() -> None:
    compiled = regex.compile(lr.lark_pattern("(par|partition)", ci=True))
    assert compiled.match("PARTITION").group() == "PARTITION"

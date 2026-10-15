"""Alternation reordering for Lark terminals (``tools.emit.lark_regex``)."""

from __future__ import annotations

import pytest
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

"""No emitted Lark terminal may cross a line end."""

from __future__ import annotations

from pathlib import Path

import pytest
import regex
from lark import Lark

from tools.emit.lark import emit_lark, greedy, regex_terminal
from tools.emit.linebound import SPACE_CHARS, line_bounded
from tools.model.load import load_dir
from tools.model.resolve import resolve
from tools.validate.lark_parse import build_parser, parse_text

LINEBOUND = Path(__file__).parent / "fixtures" / "linebound"
SAMPLE = "ab \r\n x#_1\n\t;Z9é \n"
NEWLINES = "\r\n"
ACCEPT = "ok"
REJECT = "reject"


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        (r"\s", r"[^\S\r\n]"),
        (r"a\s+b", r"a[^\S\r\n]+b"),
        (r"\\s", r"\\s"),
        (r"\S+", r"\S+"),
        (r"[^#]+", r"[^\r\n#]+"),
        (r"[^]x]", r"[^\r\n\]x]"),
        (r"[]x]", r"[\]x]"),
        (r"[abc]", r"[abc]"),
        (r".*", r"[^\r\n]*"),
        (r"\.", r"\."),
        (r"[.]", r"[.]"),
        (r"\W+", r"(?:(?![\r\n])\W)+"),
        (r"\D", r"(?:(?![\r\n])\D)"),
        (r"[\W_]", r"(?:(?![\r\n])[\W_])"),
        (r"[^\W]", r"[^\r\n\W]"),
        (r"[^\S]", r"[^\r\n\S]"),
        (r"\p{L}", r"\p{L}"),
        (r"\P{L}", r"(?:(?![\r\n])\P{L})"),
        (r"\p{^L}", r"(?:(?![\r\n])\p{^L})"),
        (r"\P{^L}", r"\P{^L}"),
        (r"[\P{L}]", r"(?:(?![\r\n])[\P{L}])"),
        (r"\pL", r"\pL"),
        (r"\PL", r"(?:(?![\r\n])\PL)"),
        (r"[[:alpha:]_]", r"[[:alpha:]_]"),
        (r"[\]x]", r"[\]x]"),
        (r"x\\", r"x\\"),
    ],
)
def test_line_bounded_rewrites(pattern: str, expected: str) -> None:
    assert line_bounded(pattern) == expected


def test_class_with_whitespace_shorthand_lists_spaces_without_line_ends() -> None:
    assert line_bounded(r"[\s_]") == f"[{SPACE_CHARS}_]"
    assert not set(NEWLINES) & set(SPACE_CHARS)


def test_unterminated_escape_and_class_do_not_hang() -> None:
    assert line_bounded("a\\") == "a\\"
    assert line_bounded("\\p") == "\\p"
    assert line_bounded("\\p{L") == "\\p{L"
    assert line_bounded("[ab") == "[ab]"
    assert line_bounded("[[:ab") == "[[:ab]"


@pytest.mark.parametrize(
    "pattern",
    [
        r"\s+",
        r"[\s_]+",
        r"[^#]+",
        r".+",
        r"\W+",
        r"\D+",
        r"[\W]+",
        r"\P{L}+",
        r"[^\S]+",
        r"[\s\S]+",
        r"[^\p{L}]+",
        r"[^\s,]+",
        r"(?:\s|;)+",
    ],
)
def test_rewritten_pattern_never_matches_a_line_end(pattern: str) -> None:
    compiled = regex.compile(line_bounded(pattern))
    hits = [m.group(0) for m in compiled.finditer(SAMPLE)]
    assert hits
    assert not any(c in hit for hit in hits for c in NEWLINES)


def test_original_patterns_do_cross_lines() -> None:
    assert "\n" in regex.search(r"\s+", SAMPLE).group(0)  # type: ignore[union-attr]
    assert "\n" in regex.search(r"[^#]+", SAMPLE).group(0)  # type: ignore[union-attr]
    assert "\r" in regex.search(r".+", "a\rb").group(0)  # type: ignore[union-attr]


def test_single_line_behaviour_is_unchanged() -> None:
    for pattern, text in [(r"[\s_]+(\w+)", "  _ab"), (r"[^#]+", "x y"), (r".*?", "abc")]:
        old = regex.match(pattern, text)
        new = regex.match(line_bounded(pattern), text)
        assert old is not None and new is not None
        assert new.group(0) == old.group(0)


def test_regex_terminal_rewrites_before_wrapping() -> None:
    literal, nullable = regex_terminal(r"^\s*$")
    assert literal == r"/(?V0)(?=[\s\S])(?:[^\S\r\n]*)/"
    assert nullable


def test_greedy_resets_quantifier_state_after_a_class() -> None:
    assert greedy(r"x*[a]?") == r"x*[a]?"
    assert greedy(r"x*[^\r\n]*?") == r"x*[^\r\n]*"


@pytest.fixture(scope="module")
def parser(tmp_path_factory: pytest.TempPathFactory) -> Lark:
    path = tmp_path_factory.mktemp("linebound") / "plantuml.lark"
    path.write_text(emit_lark(resolve(load_dir(LINEBOUND))), encoding="utf-8")
    return build_parser(path)


def verdict(parser: Lark, *lines: str) -> str:
    text = "\n".join(["@startuml", *lines, "@enduml"]) + "\n"
    return str(parse_text(parser, text)["status"])


@pytest.mark.parametrize(
    ("lines", "status"),
    [
        (("alt x", "Alice -> Bob", "end"), ACCEPT),
        (("alt x", "Alice -> Bob", "end", "end"), REJECT),
        (("alt x", "Alice -> Bob", "end  trailing words"), ACCEPT),
        (("alt\tx", "A -> B", "end", "note n"), ACCEPT),
        (("box x", "participant Alice", "end box"), ACCEPT),
        (("box x", "participant Alice", "end box", "end box"), REJECT),
        (("note a", "participant Alice"), REJECT),
    ],
)
def test_toy_terminals_stay_inside_their_line(
    parser: Lark, lines: tuple[str, ...], status: str
) -> None:
    assert verdict(parser, *lines) == status

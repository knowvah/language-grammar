"""Tests for tools.interp.compile."""

from __future__ import annotations

import pytest

from tools.interp.compile import PartError, compile_part, part_key, part_to_regex
from tools.model import Part


def matches(part: Part, text: str) -> bool:
    return compile_part(part).fullmatch(text) is not None


def test_part_to_regex_forms() -> None:
    assert part_to_regex({"seq": [{"regex": "a"}, {"regex": "b"}]}) == "(?:(?:a)(?:b))"
    assert part_to_regex({"alt": [{"regex": "a"}, {"regex": "b"}]}) == "(?:(?:a)|(?:b))"
    assert part_to_regex({"opt": {"regex": "a"}}) == "(?:(?:a))?"
    assert part_to_regex({"star": {"regex": "a"}}) == "(?:(?:a))*"
    assert part_to_regex({"plus": {"regex": "a"}}) == "(?:(?:a))+"
    assert part_to_regex({"literal": "a.b", "ci": True}) == "(?i:a\\.b)"
    assert part_to_regex({"literal": "a", "ci": False}) == "(?-i:a)"


def test_literal_ci_flag_controls_case_sensitivity() -> None:
    assert matches({"literal": "Class", "ci": True}, "cLASS")
    assert not matches({"literal": "Class", "ci": False}, "class")
    assert matches({"literal": "Class", "ci": False}, "Class")


def test_literal_is_escaped() -> None:
    assert matches({"literal": "a.b", "ci": True}, "a.b")
    assert not matches({"literal": "a.b", "ci": True}, "axb")


def test_regex_leaf_is_case_insensitive_like_upstream() -> None:
    assert matches({"regex": "abc"}, "ABC")


def test_unicode_property_classes_need_regex_module() -> None:
    assert matches({"plus": {"regex": "[\\p{L}\\p{N}_]"}}, "héllo1")


def test_match_is_whole_line_not_prefix() -> None:
    assert not matches({"regex": "ab"}, "abc")
    assert not matches({"regex": "bc"}, "abc")


def test_quantifiers_and_alternation() -> None:
    part: Part = {"seq": [{"alt": [{"regex": "x"}, {"regex": "y"}]}, {"star": {"regex": "z"}}]}
    assert matches(part, "yzzz")
    assert matches(part, "x")
    assert not matches(part, "xy")


def test_compile_is_memoized_per_distinct_part() -> None:
    a = compile_part({"regex": "memo\\d"})
    b = compile_part({"regex": "memo\\d"})
    assert a is b
    assert part_key({"b": 1, "a": 2}) == part_key({"a": 2, "b": 1})


@pytest.mark.parametrize("bad", [{"ref": "X"}, {}])
def test_unresolved_part_raises(bad: Part) -> None:
    with pytest.raises(PartError):
        part_to_regex(bad)

"""Tests for tools.model.resolve."""

from __future__ import annotations

from typing import Any

import pytest

from tools.model import Model, ModelError
from tools.model.load import load_dir
from tools.model.resolve import resolve

from .test_load import FIXTURES


def entry(parts: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"command": "C", "provenance": {"class": "X"}, "kind": "single", "parts": parts, **extra}


def model(mid: str, **kw: Any) -> Model:
    return Model(id=mid, layer="shared", **kw)


def contains_key(obj: Any, keys: set[str]) -> bool:
    if isinstance(obj, dict):
        return any(k in keys or contains_key(v, keys) for k, v in obj.items())
    if isinstance(obj, list):
        return any(contains_key(v, keys) for v in obj)
    return False


def test_a_includes_b_refs_var_in_c_fully_inlined() -> None:
    resolved = resolve(load_dir(FIXTURES))
    a = resolved["a"]
    assert not contains_key(a.contexts, {"include", "ref"})
    assert not contains_key(a.variables, {"include", "ref"})
    commands = [e["command"] for e in a.contexts["main"]]
    assert commands == ["CommandPaint", "CommandCreateClass"]
    paint = a.contexts["main"][0]["parts"]
    assert paint == {"seq": [{"literal": "color", "ci": True}, {"regex": "#\\w+"}]}
    create = a.contexts["main"][1]
    assert create["parts"]["seq"][2] == {"alt": [{"regex": "#\\w+"}, {"literal": "{", "ci": False}]}
    assert create["push"] == "body"
    assert create["end"] == {"literal": "}", "ci": False}


def test_resolved_merges_included_contexts_and_variables() -> None:
    a = resolve(load_dir(FIXTURES))["a"]
    assert sorted(a.contexts) == ["body", "common", "main"]
    assert sorted(a.variables) == ["COLOR", "PAINTED", "SPACE"]
    assert a.diagram == "CLASS"


def test_own_definitions_override_included() -> None:
    c = model("c", variables={"V": {"regex": "c"}})
    a = model("a", include=["c"], variables={"V": {"regex": "a"}})
    assert resolve({"a": a, "c": c})["a"].variables["V"] == {"regex": "a"}


def test_model_include_cycle_names_path() -> None:
    models = {"A": model("A", include=["B"]), "B": model("B", include=["A"])}
    with pytest.raises(ModelError, match="include cycle: A → B → A"):
        resolve(models)


def test_self_include_cycle() -> None:
    with pytest.raises(ModelError, match="include cycle: A → A"):
        resolve({"A": model("A", include=["A"])})


def test_context_include_cycle_across_models() -> None:
    a = model("A", contexts={"main": [{"include": "B"}]})
    b = model("B", contexts={"main": [{"include": "A"}]})
    with pytest.raises(ModelError, match=r"include cycle: A\.main → B\.main → A\.main"):
        resolve({"A": a, "B": b})


def test_variable_cycle() -> None:
    a = model("A", variables={"X": {"ref": "Y"}, "Y": {"ref": "X"}})
    with pytest.raises(ModelError, match=r"variable cycle: A\.X → A\.Y → A\.X"):
        resolve({"A": a})


def test_local_context_wins_over_model_id_and_hash_form() -> None:
    other = model("other", contexts={"main": [entry({"regex": "o"})]})
    a = model(
        "a",
        contexts={
            "other": [entry({"regex": "local"})],
            "main": [{"include": "other"}, {"include": "other#main"}],
        },
    )
    parts = [e["parts"] for e in resolve({"a": a, "other": other})["a"].contexts["main"]]
    assert parts == [{"regex": "local"}, {"regex": "o"}]


def test_unknown_include_and_push_targets() -> None:
    bad_inc = model("a", contexts={"main": [{"include": "nope"}]})
    with pytest.raises(ModelError, match="include target 'nope' not found") as info:
        resolve({"a": bad_inc})
    assert info.value.pointer == "/contexts/main/0/include"
    bad_push = model("a", contexts={"main": [entry({"regex": "x"}, push="ghost")]})
    with pytest.raises(ModelError, match="unknown context 'ghost'"):
        resolve({"a": bad_push})
    bad_hash = model("a", contexts={"main": [{"include": "zzz#main"}]})
    with pytest.raises(ModelError, match="not found"):
        resolve({"a": bad_hash})


def test_diamond_include_is_not_a_cycle() -> None:
    d = model("d", variables={"V": {"regex": "d"}})
    b = model("b", include=["d"])
    c = model("c", include=["d"])
    a = model("a", include=["b", "c"], contexts={"main": [entry({"ref": "V"})]})
    out = resolve({"a": a, "b": b, "c": c, "d": d})
    assert out["a"].contexts["main"][0]["parts"] == {"regex": "d"}

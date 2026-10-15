"""Gantt diagrams, non-sentence commands (T24, ``model/diagrams/gantt*.yaml``).

``gantt`` extends ``gen-gantt-diagram``, ``common`` and ``gantt-errors`` (which includes
``gantt-dates``). Its body contexts track two pieces of diagram state with head entries
placed before the spliced generated list:

* ``main``: no task-like entry yet (no separator, group or task); ``gantt_tasks``: some
  exist. Separators and ``[A] -> [B]`` move ``main`` to ``gantt_tasks``; the lookups
  ``A -> B``, ``[A] #color`` and ``note bottom`` fail in ``main``.
* group depth: ``gantt_group_1`` (the first group opened from ``main``, a flat state) and
  ``gantt_group`` (pushed); ``end group`` fails at depth 0.

The 9 NaturalGanttCommand sentences are T25 (``gantt-sentences``, one include line).

Fixtures (``tests/fixtures/gantt``), each with a header before ``@start``::

    ' gantt: CommandA, CommandB          rule ids the fixture exercises
    ' gap: <reason>                      gap/ only: why the model cannot reject it
"""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any

import pytest

from tools.interp import accepts
from tools.interp.compile import compile_part
from tools.interp.source import split_blocks
from tools.model import Model, ResolvedModel, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
FIXTURES = REPO / "tests" / "fixtures" / "gantt"
POS, NEG, GAP = "pos", "neg", "gap"
GANTT_ID, ERRORS_ID, DATES_ID = "gantt", "gantt-errors", "gantt-dates"
GENERATED_ID, COMMON_ID = "gen-gantt-diagram", "common"
FACTORY, DIAGRAM = "GanttDiagramFactory", "GANTT"
MAIN, TASKS, GROUP_1, GROUP = "main", "gantt_tasks", "gantt_group_1", "gantt_group"
BODY_CONTEXTS = (MAIN, TASKS, GROUP_1, GROUP)
NOTE_FIRST, NOTE_BODY = "gantt_note_first", "gantt_note_body"
START_MAP = {"gantt": [FACTORY]}
UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
# GanttDiagramFactory.java:89-91: the sentences, then the first gantt command.
FIRST_GANTT_COMMAND = "CommandGanttArrow"
REMOVED = ("CommandGroupStart", "CommandGroupEnd")
HEADER = re.compile(r"^' (?P<key>gantt|gap): (?P<value>.+)$")
JAVA_INT_MAX = 2**31 - 1

# head id -> (generated counterpart, action key, action value, sample line)
HEADS: dict[str, dict[str, tuple[str, str, Any, str]]] = {
    MAIN: {
        "GanttArrowWithoutTask": ("CommandGanttArrow", "reject", True, "A -> B"),
        "GanttFirstTaskByArrow": ("CommandGanttArrow2", "set", TASKS, "[A] -> [B]"),
        "GanttColorWithoutTask": ("CommandColorTask", "reject", True, "[A] #red"),
        "GanttFirstTaskBySeparator": ("CommandSeparator", "set", TASKS, "-- x --"),
        "GanttFirstGroup": ("CommandGroupStart", "set", GROUP_1, "group [G]"),
        "GanttGroupEndWithoutGroup": ("CommandGroupEnd", "reject", True, "end group"),
        "GanttNoteWithoutTask": ("CommandNoteBottom", "reject", True, "note bottom"),
    },
    TASKS: {
        "GanttGroupAtRoot": ("CommandGroupStart", "push", GROUP, "group [G]"),
        "GanttGroupEndAtRoot": ("CommandGroupEnd", "reject", True, "end group"),
    },
    GROUP_1: {
        "GanttGroupInFirstGroup": ("CommandGroupStart", "push", GROUP, "group [G]"),
        "GanttFirstGroupEnd": ("CommandGroupEnd", "set", TASKS, "end group"),
    },
    GROUP: {
        "GanttGroupInGroup": ("CommandGroupStart", "push", GROUP, "group [G]"),
        "GanttGroupEnd": ("CommandGroupEnd", "pop", True, "end group"),
    },
}


@pytest.fixture(scope="module")
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@pytest.fixture(scope="module")
def models(raw_models: dict[str, Model]) -> ResolvedModels:
    return resolve(raw_models)


@pytest.fixture(scope="module")
def gantt(models: ResolvedModels) -> ResolvedModel:
    return models[GANTT_ID]


def commands(entries: list[dict[str, Any]]) -> list[str]:
    return [e["command"] for e in entries]


def generated(models: ResolvedModels) -> list[dict[str, Any]]:
    return models[GENERATED_ID].contexts[MAIN]


def gantt_commands(models: ResolvedModels) -> list[str]:
    """Generated rule ids of the gantt commands (after the common block)."""
    ids = commands(generated(models))
    return ids[ids.index(FIRST_GANTT_COMMAND) :]


def generated_entry(models: ResolvedModels, command: str) -> dict[str, Any]:
    (found,) = [e for e in generated(models) if e["command"] == command]
    return found


def entry(model: ResolvedModel, context: str, command: str) -> dict[str, Any]:
    (found,) = [e for e in model.contexts[context] if e["command"] == command]
    return found


def spliced(gantt: ResolvedModel, context: str) -> list[dict[str, Any]]:
    return gantt.contexts[context][len(HEADS[context]) :]


# --- the model ------------------------------------------------------------------------


def test_gantt_is_the_top_model_of_its_factory(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    raw = raw_models[GANTT_ID]
    assert (raw.layer, raw.diagram, raw.factory) == ("diagram", DIAGRAM, FACTORY)
    assert raw.include[:3] == [GENERATED_ID, COMMON_ID, ERRORS_ID]
    assert top_models(models)[FACTORY] == GANTT_ID
    for mid in (ERRORS_ID, DATES_ID):
        assert (raw_models[mid].layer, raw_models[mid].diagram) == ("shared", None)


@pytest.mark.parametrize("context", BODY_CONTEXTS)
def test_body_context_is_heads_then_the_generated_order(
    gantt: ResolvedModel, models: ResolvedModels, context: str
) -> None:
    got = gantt.contexts[context]
    assert commands(got[: len(HEADS[context])]) == list(HEADS[context])
    wanted = [c for c in commands(generated(models)) if c not in REMOVED]
    rest = commands(spliced(gantt, context))
    assert [c for c in rest if c in set(wanted)] == wanted


@pytest.mark.parametrize("context", BODY_CONTEXTS)
def test_heads_carry_their_state_transition(gantt: ResolvedModel, context: str) -> None:
    for head, (_, key, value, _) in HEADS[context].items():
        assert entry(gantt, context, head)[key] == value, (context, head)


@pytest.mark.parametrize("context", BODY_CONTEXTS)
def test_heads_have_the_generated_shape(
    gantt: ResolvedModel, models: ResolvedModels, context: str
) -> None:
    for head, (counterpart, _, _, sample) in HEADS[context].items():
        got = entry(gantt, context, head)["parts"]
        assert got == generated_entry(models, counterpart)["parts"], head
        assert compile_part(got).fullmatch(sample), head


@pytest.mark.parametrize("context", BODY_CONTEXTS)
def test_no_earlier_command_takes_a_head_line(
    gantt: ResolvedModel, models: ResolvedModels, context: str
) -> None:
    """A head runs before the whole list, so no upstream-earlier rule may match it."""
    order = commands(generated(models))
    rest = spliced(gantt, context)
    earlier = rest[: commands(rest).index(FIRST_GANTT_COMMAND)]
    for head, (counterpart, _, _, sample) in HEADS[context].items():
        assert not [e["command"] for e in earlier if compile_part(e["parts"]).fullmatch(sample)]
        between = order[order.index(FIRST_GANTT_COMMAND) : order.index(counterpart)]
        hits = [
            c
            for c in between
            if compile_part(generated_entry(models, c)["parts"]).fullmatch(sample)
        ]
        assert hits == [], (head, hits)


def test_group_commands_are_replaced_by_heads(gantt: ResolvedModel) -> None:
    for context in BODY_CONTEXTS:
        assert not set(REMOVED) & set(commands(gantt.contexts[context]))


@pytest.mark.parametrize("context", (TASKS, GROUP_1, GROUP))
def test_note_enters_its_body(gantt: ResolvedModel, context: str) -> None:
    note = entry(gantt, context, "CommandNoteBottom")
    assert (note["kind"], note["push"], note["require_pop"]) == ("single", NOTE_FIRST, True)
    assert "end" not in note


def test_empty_note_rejects_before_its_emitter_twin(gantt: ResolvedModel) -> None:
    first = gantt.contexts[NOTE_FIRST]
    assert commands(first) == ["GanttNoteEmpty", "GanttNoteEmptyClose", "GanttNoteFirstLine"]
    assert first[0]["reject"] is True and first[1]["pop"] is True
    assert first[0]["parts"] == first[1]["parts"]
    assert first[2]["set"] == NOTE_BODY
    assert commands(gantt.contexts[NOTE_BODY]) == ["GanttNoteEnd", "GanttNoteLine"]


@pytest.mark.parametrize(
    ("text", "is_end"),
    [
        ("end note", True),
        ("END  NOTE", True),
        ("end note", True),
        ("endnote", True),
        ("end", False),
        ("end notes", False),
        ("x end note", False),
        ("", False),
    ],
)
def test_note_lines(gantt: ResolvedModel, text: str, is_end: bool) -> None:
    end = entry(gantt, NOTE_BODY, "GanttNoteEnd")["parts"]
    line = entry(gantt, NOTE_BODY, "GanttNoteLine")["parts"]
    assert (compile_part(end).fullmatch(text) is not None) is is_end
    assert (compile_part(line).fullmatch(text) is not None) is not is_end


# --- execution errors (gantt-errors) ----------------------------------------------------


@pytest.mark.parametrize("context", (TASKS, GROUP_1, GROUP))
def test_each_reject_sits_right_after_its_narrowed_rule(
    raw_models: dict[str, Model], gantt: ResolvedModel, context: str
) -> None:
    errors = raw_models[ERRORS_ID]
    assert set(errors.insert_after) == set(errors.overrides) - {"CommandLanguage"}
    got = commands(gantt.contexts[context])
    for key, (inserted,) in errors.insert_after.items():
        assert inserted["reject"] is True
        assert got[got.index(key) + 1] == inserted["command"], (context, key)


def test_every_patch_key_matches_a_gantt_rule(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    wanted = set(gantt_commands(models))
    for mid in (GANTT_ID, ERRORS_ID):
        raw = raw_models[mid]
        keys = set(raw.overrides) | set(raw.insert_before) | set(raw.insert_after)
        assert keys and keys <= wanted, mid


# reject id -> (generated rule, samples the generated rule matches)
REJECT_SAMPLES = {
    "CommandColorTaskError": ("CommandColorTask", ["[A] #zzz", "[A] #red/#ab", "[A] #redé"]),
    "CommandWeekNumberStrategyError": (
        "CommandWeekNumberStrategy",
        ["week start on mon 9999999999"],
    ),
    "CommandPrintScaleError": (
        "CommandPrintScale",
        ["printscale daily zoom 1.2.3", "printscale daily with week numbering from 2147483648"],
    ),
    "CommandPrintBetweenError": (
        "CommandPrintBetween",
        [
            "print between 2020-02-30 and D+_",
            "print between 31 apr 2020 and 2147483648 days after start",
            "print between feb 29 1900 and 1 jan 1_",
        ],
    ),
    "CommandFootboxGanttError": ("CommandFootboxGantt", ["footbox", "  footbox"]),
    "CommandTaskCompleteDefaultError": (
        "CommandTaskCompleteDefault",
        ["task default completion to 101", "task completion default to 99999999999 %"],
    ),
}


@pytest.mark.parametrize("reject", sorted(REJECT_SAMPLES))
def test_reject_shape_is_the_generated_shape(
    gantt: ResolvedModel, models: ResolvedModels, reject: str
) -> None:
    rule, samples = REJECT_SAMPLES[reject]
    shape = compile_part(entry(gantt, TASKS, reject)["parts"])
    narrowed = compile_part(entry(gantt, TASKS, rule)["parts"])
    original = compile_part(generated_entry(models, rule)["parts"])
    for sample in samples:
        assert original.fullmatch(sample) and shape.fullmatch(sample), sample
        assert not narrowed.fullmatch(sample), sample


# --- fragments ------------------------------------------------------------------------


def fragment(models: ResolvedModels, name: str) -> Any:
    return compile_part(models[DATES_ID].variables[name])


def is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def month_length(year: int, month: int) -> int:
    lengths = [31, 29 if is_leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return lengths[month - 1]


def is_valid(year: int, month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= month_length(year, month)


MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def date_samples(seed: int) -> list[tuple[int, int, int]]:
    rng = random.Random(seed)
    years = [0, 4, 100, 400, 1900, 2000, 2019, 2020, 2024, 9999] + [
        rng.randint(0, 9999) for _ in range(40)
    ]
    return [(y, m, d) for y in years for m in range(0, 14) for d in (0, 1, 28, 29, 30, 31, 32)]


def test_numeric_dates_agree_with_local_date(models: ResolvedModels) -> None:
    ok = fragment(models, "GD_DATE_ABSOLUTE_OK")
    for y, m, d in date_samples(24):
        for text in (f"{y}-{m:02}-{d:02}", f"{y:04}/{m}/{d}"):
            assert (ok.fullmatch(text) is not None) is is_valid(y, m, d), text


def test_named_dates_agree_with_local_date(models: ResolvedModels) -> None:
    ok = fragment(models, "GD_DATE_ABSOLUTE_OK")
    for y, m, d in date_samples(25):
        if not 1 <= m <= 12:
            continue
        name = MONTHS[m - 1]
        for text in (f"{d} {name.upper()}uary {y}", f"{d}th of {name} {y}", f"{name}. {d}, {y}"):
            assert (ok.fullmatch(text) is not None) is is_valid(y, m, d), text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2020-01-1_", False),
        ("2_20-01-01", False),
        ("D+0002147483647", True),
        ("d+2147483648", False),
        ("D+_", False),
        ("12 days after start", True),
        ("1 day after start", True),
        ("2147483648 days after start", False),
        ("2020-01-01", True),
        ("D+5", True),
    ],
)
def test_any_date_fragment(models: ResolvedModels, text: str, expected: bool) -> None:
    assert (fragment(models, "GD_DATE_ANY_OK").fullmatch(text) is not None) is expected


def test_counts_agree_with_java_int_bounds(models: ResolvedModels) -> None:
    rng = random.Random(26)
    numbers = [JAVA_INT_MAX, JAVA_INT_MAX + 1, 0, 10**10] + [
        rng.randint(0, 10**12) for _ in range(2000)
    ]
    ok = fragment(models, "GD_DATE_ANY_OK")
    for n in numbers:
        assert (ok.fullmatch(f"D+{n}") is not None) is (n <= JAVA_INT_MAX), n


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[A] #red", True),
        ("[A] #RED/#00f", True),
        ("[A] #a/automatic", True),
        ("[A] #ff00ff80", True),
        ("[A] #transparent", True),
        ("[A] #ab", False),
        ("[A] #zzz", False),
        ("[A] #red/#ffff", False),
        ("[A] #redé", False),
    ],
)
def test_color_task_narrowing(gantt: ResolvedModel, text: str, expected: bool) -> None:
    rule = compile_part(entry(gantt, TASKS, "CommandColorTask")["parts"])
    assert (rule.fullmatch(text) is not None) is expected


# --- fixtures -------------------------------------------------------------------------


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def fixture_commands(path: Path) -> list[str]:
    return [c.strip() for c in header(path)["gantt"].split(",")]


def rel(path: Path) -> str:
    return path.relative_to(FIXTURES).as_posix()


def restricted(models: ResolvedModels, path: Path) -> Any:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return accepts(models, block, raw=True, start_map=START_MAP)


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(models: ResolvedModels, path: Path) -> None:
    verdict = restricted(models, path)
    assert verdict["accepted"], verdict["first_failure"]
    assert (verdict["diagram"], verdict["model"]) == (DIAGRAM, GANTT_ID)


@pytest.mark.parametrize("path", fixtures(NEG), ids=rel)
def test_neg_fixture_is_rejected(models: ResolvedModels, path: Path) -> None:
    assert restricted(models, path)["accepted"] is False


def gap_params() -> list[Any]:
    return [
        pytest.param(p, id=rel(p), marks=pytest.mark.xfail(strict=True, reason=header(p)["gap"]))
        for p in fixtures(GAP)
    ]


@pytest.mark.parametrize("path", gap_params())
def test_gap_fixture_is_rejected(models: ResolvedModels, path: Path) -> None:
    assert restricted(models, path)["accepted"] is False


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_gantt_with_full_dispatch(models: ResolvedModels, path: Path) -> None:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    verdict = accepts(models, block, raw=True)
    assert (verdict["accepted"], verdict["diagram"]) == (True, DIAGRAM)


def test_every_fixture_names_known_commands(models: ResolvedModels) -> None:
    known = set(commands(generated(models)))
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        assert set(fixture_commands(path)) <= known, rel(path)


@pytest.mark.parametrize("group", [POS, NEG])
def test_every_gantt_command_has_a_fixture(models: ResolvedModels, group: str) -> None:
    covered = {c for path in fixtures(group) for c in fixture_commands(path)}
    assert set(gantt_commands(models)) <= covered


@pytest.mark.corpus
def test_fixture_verdicts_equal_the_oracle() -> None:
    from tools.validate.oracle import oracle_verdicts

    paths = fixtures(POS) + fixtures(NEG) + fixtures(GAP)
    verdicts = oracle_verdicts(paths)
    for path in paths:
        (block,) = verdicts[str(path)]
        assert block["accepted"] is (path.parent.name == POS), rel(path)
        if block["accepted"]:
            assert block["diagram_type"] == DIAGRAM, rel(path)

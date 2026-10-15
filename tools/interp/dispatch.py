"""Choosing and ordering candidate diagram models for a block.

Upstream (``PSystemBuilder.java:258-282``) walks its factory list in order and skips
factories whose ``DiagramType`` is not among ``DiagramType.findStartTypes(first line)``
(``core/DiagramType.java:69-92``, table ``:94-218``). The factory list is
``PSystemBuilder.java:133-200``. Models carry only the ``DiagramType`` (not the
factory), so candidates are the ``layer: diagram`` models whose ``diagram`` is in the
start types, stably ordered by the first factory registered for that type; ties keep
the order of the ``models`` mapping. An explicit ``start_map`` overrides all of this.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from tools.model import ResolvedModel, ResolvedModels

DIAGRAM_LAYER = "diagram"
START_PREFIX = "@start"
UML_TYPES = frozenset(
    "SEQUENCE STATE CLASS OBJECT ACTIVITY DESCRIPTION COMPOSITE TIMING HELP SPRITES".split()
)
START_TYPES: dict[str, frozenset[str]] = {
    "bpm": frozenset({"BPM"}),
    "board": frozenset({"BOARD"}),
    "chart": frozenset({"CHART"}),
    "creole": frozenset({"CREOLE"}),
    "chronology": frozenset({"CHRONOLOGY"}),
    "chen": frozenset({"CHEN_EER"}),
    "crash": frozenset({"CRASH"}),
    "dot": frozenset({"DOT"}),
    "ditaa": frozenset({"DITAA"}),
    "def": frozenset({"DEFINITION"}),
    "ebnf": frozenset({"EBNF"}),
    "flow": frozenset({"FLOW"}),
    "files": frozenset({"FILES"}),
    "gantt": frozenset({"GANTT"}),
    "project": frozenset({"GANTT"}),
    "git": frozenset({"GIT"}),
    "hcl": frozenset({"HCL"}),
    "jcckit": frozenset({"JCCKIT"}),
    "json": frozenset({"JSON"}),
    "latex": frozenset({"LATEX"}),
    "math": frozenset({"MATH"}),
    "mindmap": frozenset({"MINDMAP"}),
    "nwdiag": frozenset({"NWDIAG"}),
    "packetdiag": frozenset({"PACKET"}),
    "regex": frozenset({"REGEX"}),
    "salt": frozenset({"SALT"}),
    "sprites": frozenset({"SPRITES"}),
    "uml": UML_TYPES,
    "wire": frozenset({"WIRE"}),
    "wbs": frozenset({"WBS"}),
    "yaml": frozenset({"YAML"}),
}
# DiagramType of each factory in PSystemBuilder.java:133-200, first occurrence only.
FACTORY_TYPE_ORDER = (
    "SEQUENCE CLASS ACTIVITY DESCRIPTION STATE BPM SALT DOT NWDIAG MINDMAP WBS CHART "
    "PACKET DITAA DEFINITION SPRITES MATH LATEX CREOLE GANTT FLOW TIMING HELP WIRE JSON "
    "GIT FILES BOARD YAML HCL EBNF REGEX CHEN_EER CRASH"
).split()
ORDER_INDEX = {name: n for n, name in enumerate(FACTORY_TYPE_ORDER)}


def start_types(keyword: str) -> frozenset[str]:
    """``DiagramType.findStartTypes`` as a prefix lookup; empty when unknown."""
    for prefix, types in START_TYPES.items():
        if keyword.startswith(prefix):
            return types
    return frozenset()


def _diagram_models(models: ResolvedModels) -> list[ResolvedModel]:
    return [m for m in models.values() if m.layer == DIAGRAM_LAYER]


def candidates(
    models: ResolvedModels,
    keyword: str | None,
    start_map: Mapping[str, Sequence[str]] | None,
) -> list[ResolvedModel]:
    """Diagram models to try, in order. ``keyword`` is ``None`` for a bare body."""
    if keyword is None:
        return _diagram_models(models)
    if start_map is not None:
        ids = start_map.get(keyword) or start_map.get(START_PREFIX + keyword) or ()
        return [models[i] for i in ids if i in models]
    types = start_types(keyword)
    chosen = [m for m in _diagram_models(models) if m.diagram in types]
    return sorted(chosen, key=lambda m: ORDER_INDEX.get(m.diagram or "", len(ORDER_INDEX)))

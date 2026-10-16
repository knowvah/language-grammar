"""``@start<keyword>`` / ``@end...`` framing shared by the Lark, W3C and TextMate emitters.

Which keywords offer a diagram model
------------------------------------
The document model's ``start_map`` (``model/document.yaml``; upstream
``DiagramType.findStartTypes``, core/DiagramType.java:94-218) lists, per start keyword, the
factories tried. A diagram model is offered under every keyword whose list names its
``factory``: ``ListSpriteDiagramFactory`` under ``@startuml`` *and* ``@startsprites``,
``GanttDiagramFactory`` under ``@startgantt`` *and* ``@startproject``. A model without a
``factory`` (or one no keyword names), or a model set with no document layer, falls back to
the diagram-type keyword (``start_keyword``), which is the only mapping toy models have.

How a block ends
----------------
Upstream closes a block at the first line for which ``StartUtils.isEndDirective`` holds: an
optional run of whitespace, ``@`` or ``\\``, then the case-sensitive word ``end`` and any
suffix (utils/StartUtils.java:119-121, BlockUmlBuilder.java:126-135), so ``@startuml`` ...
``@endmindmap`` is one block. The interpreter mirrors it (``tools.interp.source``,
``is_end_directive``) and so do all three emitters: one shared end terminal instead of an
``@end<keyword>`` per block. Approximation: a *body* line that itself begins with
``@end`` is not excluded from the body rules, so a grammar could read past a first end
line that upstream would have cut at; block extraction (the oracle, the parity harness)
never hands a grammar such text.

Start words no keyword covers
-----------------------------
``DiagramType.findStartTypes`` matches a start word against the ``start_map`` keys by key prefix
(``DiagramType.check``, core/DiagramType.java:220-232): ``@startumlfoo`` is ``uml``, so each
``START_<KW>`` terminal is the keyword followed by anything. No key is a prefix of another, so
at most one keyword terminal matches a start line. A word no key covers (``@startjcckit``,
``@startchronology``) opens a block all the same and upstream answers ``PSystemUnsupported``
(PSystemBuilder.java:283-284, PSystemErrorUtils.java:58-59), which is accepted. Lark gets one
more block, ``block_other``, whose start terminal excludes every keyword prefix
(``other_start_pattern``) and whose body is any lines. W3C cannot express the exclusion (no
lookahead) and says so in its comments.
"""

from __future__ import annotations

from collections.abc import Iterable

from tools.emit.tops import emitted_diagrams
from tools.model import ResolvedModel, ResolvedModels

DOCUMENT_LAYER = "document"
UML_KEYWORD = "uml"
UML_TYPES = frozenset(
    {
        "SEQUENCE",
        "STATE",
        "CLASS",
        "OBJECT",
        "ACTIVITY",
        "DESCRIPTION",
        "COMPOSITE",
        "TIMING",
        "HELP",
        "SPRITES",
    }
)
KEYWORD_OVERRIDES = {"CHEN_EER": "chen", "DEFINITION": "def", "PACKET": "packetdiag"}
# Directive prefixes as regex text (``@`` or ``\``; StartUtils.java:51-63, 119-121).
START_DIRECTIVE = r"[@\\]start"
END_DIRECTIVE = r"[@\\]end"


def other_start_pattern(keywords: Iterable[str]) -> str:
    """Regex body of the start line of a word that no keyword is a prefix of.

    At least one character must follow ``start`` (``StartUtils.isStartDirective``).
    """
    covered = "|".join(sorted(set(keywords), key=lambda k: (-len(k), k)))
    return rf"[ \t]*{START_DIRECTIVE}(?!(?:{covered}))[^\r\n]+"


def start_keyword(diagram: str) -> str:
    """The lowercase ``@start<kw>`` keyword used by a diagram type."""
    if diagram in UML_TYPES:
        return UML_KEYWORD
    return KEYWORD_OVERRIDES.get(diagram, diagram.lower())


def document_start_map(resolved: ResolvedModels) -> dict[str, list[str]]:
    """The ``start_map`` of the document layer (empty when no document model is present)."""
    merged: dict[str, list[str]] = {}
    for _, model in sorted(resolved.items()):
        if model.layer == DOCUMENT_LAYER:
            merged.update(model.start_map)
    return merged


def start_keywords(model: ResolvedModel, start_map: dict[str, list[str]]) -> tuple[str, ...]:
    """Every start keyword that offers ``model`` (see the module doc), in ``start_map`` order."""
    found = tuple(k for k, factories in start_map.items() if model.factory in factories)
    if model.factory is None or not found:
        return (start_keyword(str(model.diagram)),)
    return found


def group_by_keyword(resolved: ResolvedModels) -> dict[str, list[ResolvedModel]]:
    """Emitted diagram models per start keyword, keywords in first-use order."""
    start_map = document_start_map(resolved)
    groups: dict[str, list[ResolvedModel]] = {}
    for model in emitted_diagrams(resolved):
        for keyword in start_keywords(model, start_map):
            groups.setdefault(keyword, []).append(model)
    return groups

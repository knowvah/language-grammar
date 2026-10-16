"""Context-transition planning shared by the Lark and W3C emitters (pure functions).

The interpreter keeps a stack of contexts (``tools.interp.engine``): ``push`` adds a frame,
``pop`` removes the top frame (a no-op on the bottom frame), ``set`` replaces the top frame
(the bottom one too), ``require_pop`` marks a push whose body must close before the block
ends, and a body that is still open at the end of the block is otherwise accepted. A
context-free grammar can state all of that with *forms*, newline-led rules (a transition
line supplies no trailing newline, so a transition on the last body line needs no phantom
empty line and a form may be empty):

* ``CLOSED`` -- a pushed frame that is popped: ``(_NL line?)* _NL exit``. The exit is a
  ``pop`` line, or a ``set`` line that embeds the *target's* ``CLOSED`` form (the frame is
  replaced, so the target's own ``pop`` returns to the parent and no second closing line
  is needed). Lines inside use ``CLOSED`` pushes for nested bodies.
* ``TAIL`` -- a frame still open at the end of the block: ``(_NL line?)* (_NL tail)?``.
  The optional last line is the *spine*: a ``set`` line (embedding the target's ``TAIL``) or
  an open ``push`` line (a push without ``require_pop``, embedding the target's ``TAIL``).
  An unclosed body therefore must be the last thing in the block, as in the interpreter.
  A ``require_pop`` push has no ``TAIL`` alternative: its body must close.
* ``ROOT`` -- the bottom frame (``main``, or a ``set`` target reached from it): the same as
  ``TAIL`` except that a ``set`` embeds the target's ``ROOT`` form. A ``pop`` entry in the
  bottom frame is dropped: the interpreter treats it as a no-op line, but upstream reports
  a closer without an opener as an error (family models shadow such entries with
  ``reject``, which emitters cannot express), so the grammar rejects the line.

A push whose target can never close (no ``pop`` entry on any ``set`` chain) has no
``CLOSED`` alternative, so it can only be the spine. Transitions on ``multiline`` entries
with an ``end`` or on brackets are not rendered (the transition would fire after a body the
grammar treats as one line): such entries are ordinary lines (or exits, for ``pop``).
"""

from __future__ import annotations

from collections.abc import Collection

from tools.emit.skip import skipped
from tools.model import Entry

PUSH = "push"
SET = "set"
POP = "pop"
CLOSED = "closed"
TAIL = "tail"
ROOT = "root"
ROLE_ORD = "ord"
ROLE_EXIT = "exit"
ROLE_TAIL = "tail"
ROLE_ROOT_TAIL = "root-tail"
BODYLESS = frozenset({"multiline", "multiline-bracket"})
FORM_SUFFIX = {CLOSED: "block", TAIL: "tail", ROOT: "root"}
Contexts = dict[str, list[Entry]]


def transition(entry: Entry) -> tuple[str, str] | None:
    """``(PUSH|SET, target)`` when the emitters render the entry's transition, else None."""
    if entry["kind"] == "multiline-bracket":
        return None
    if entry["kind"] == "multiline" and "end" in entry:
        return None
    if entry.get(PUSH):
        return PUSH, str(entry[PUSH])
    if entry.get(SET):
        return SET, str(entry[SET])
    return None


def kind_of(entry: Entry) -> str:
    """``PUSH``, ``SET`` or ``""`` (no rendered transition)."""
    return (transition(entry) or ("",))[0]


def closable(contexts: Contexts) -> frozenset[str]:
    """Contexts whose frame can be popped: a ``pop`` entry, or a ``set`` to a closable one."""
    found = {c for c, es in contexts.items() if any(e.get(POP) and not skipped(e) for e in es)}
    grown = True
    while grown:
        grown = False
        for ctx, entries in contexts.items():
            if ctx not in found and any(_sets_into(e, found) for e in entries):
                found.add(ctx)
                grown = True
    return frozenset(found)


def _sets_into(entry: Entry, found: Collection[str]) -> bool:
    moved = transition(entry)
    return bool(moved and moved[0] == SET and moved[1] in found and not skipped(entry))


def _enters_open_body(entry: Entry, closing: frozenset[str]) -> bool:
    moved = transition(entry)
    return bool(moved and moved[0] == PUSH and moved[1] not in closing)


def ordinary(entries: list[Entry], closing: frozenset[str]) -> list[Entry]:
    """Entries that are plain lines of a form. ``pop`` and ``set`` entries are exits; a push
    whose body can never close is left to the spine."""
    return [
        e
        for e in entries
        if kind_of(e) != SET and not e.get(POP) and not _enters_open_body(e, closing)
    ]


def exits(entries: list[Entry], closing: frozenset[str]) -> list[Entry]:
    """Entries that end a ``CLOSED`` form: ``pop`` entries and ``set`` into a closable one."""
    return [e for e in entries if e.get(POP) or _sets_into(e, closing)]


def tails(entries: list[Entry]) -> list[Entry]:
    """Entries that may be the spine of a ``TAIL``/``ROOT`` form: ``set`` and open pushes."""
    return [e for e in entries if kind_of(e) == SET or _opens(e)]


def _opens(entry: Entry) -> bool:
    return kind_of(entry) == PUSH and not entry.get("require_pop")


def target_form(entry: Entry, role: str) -> str:
    """Form an entry's transition enters when the entry is rendered in ``role``."""
    if role in (ROLE_ORD, ROLE_EXIT):
        return CLOSED
    if role == ROLE_ROOT_TAIL and kind_of(entry) == SET:
        return ROOT
    return TAIL

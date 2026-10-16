"""Fold zero-width guards into the Lark terminals around them.

A *guard* is a regex Part that can only match the empty string: a lookahead or lookbehind
such as ``D_NOT_FORBIDDEN`` (``(?![\\p{L}0-9_.]+(?:[\\r\\n]|$))``). Lark cannot keep one as a
terminal: dynamic Earley refuses zero-width terminals, and a zero-length match is filed under
the position already being scanned, so it is lost. Wrapping it as ``(T |)`` (the encoding for
nullable regexes) lets Earley take the empty alternative and skip the check.

``fuse_line`` rewrites a command line's Parts so that every guard becomes a prefix
(``PRE_KEY``) of each terminal that can come next, which is where the guard is evaluated:

* before a Part that cannot be empty, the guard goes into that Part's first terminals;
* before a Part that can be empty, the line splits into "the Part is taken" (its non-empty
  form, ``NONEMPTY_KEY``, carries the guard) and "the Part is skipped" (the guard moves on);
* at the end of an ``alt`` branch or ``opt`` body, the rest of the line is copied into it;
* at the end of the line, a lookahead is decided once (does it hold before a line end?) and a
  lookbehind becomes a suffix (``POST_KEY``) of the terminal before it.

A guard left at the end of a ``star``/``plus`` body (its continuation is unbounded) or with
no terminal before it keeps the old encoding. Parts without a guard are returned as is, so
their terminals do not change.
"""

from __future__ import annotations

import re
from functools import cache

import regex
from lark.utils import get_regexp_width

from tools.emit.lark_regex import (
    NONEMPTY_KEY,
    POST_KEY,
    PRE_KEY,
    guard_pattern,
    lark_pattern,
    nullable_part,
)
from tools.model import Part

Guard = tuple[str, bool]
EOL_KEY = "_eol"  # end-of-line sentinel, removed before the Parts reach the emitter
EMPTY: Part = {"regex": "", "ci": False}
LOOKBEHIND = re.compile(r"\(\?<[=!]")
LINE_END_TEXT = "\n"  # what follows the last Part of a line (see GUARD_LINE_END)
REPEATS = ("star", "plus")


def fuse_line(part: Part) -> Part | None:
    """``part`` with its guards folded into terminals; ``part`` itself when it has none;
    ``None`` when a guard can never hold, so the line matches nothing."""
    if not _has_guard(part):
        return part
    items = _norm([*_items(part), {EOL_KEY: True}])
    return None if items is None else _seq(_finish(items))


@cache
def _zero_width(pattern: str, ci: bool) -> bool:
    return pattern != "" and get_regexp_width(lark_pattern(pattern, ci))[1] == 0


def is_guard(part: Part) -> bool:
    """A regex Part that only ever matches the empty string (and is not the empty regex)."""
    if "regex" not in part or PRE_KEY in part or POST_KEY in part or NONEMPTY_KEY in part:
        return False
    return _zero_width(part["regex"], bool(part.get("ci")))


def _has_guard(part: Part) -> bool:
    if is_guard(part):
        return True
    children = part.get("seq") or part.get("alt") or []
    for key in ("opt", *REPEATS):
        if key in part:
            children = [part[key]]
    return any(_has_guard(child) for child in children)


def _items(part: Part) -> list[Part]:
    return _flatten(part["seq"]) if "seq" in part else [part]


def _flatten(parts: list[Part]) -> list[Part]:
    out: list[Part] = []
    for part in parts:
        out.extend(_flatten(part["seq"]) if "seq" in part else [part])
    return out


def _seq(items: list[Part]) -> Part:
    if not items:
        return EMPTY
    return items[0] if len(items) == 1 else {"seq": items}


def _alt(branches: list[list[Part]]) -> Part:
    """An ``alt`` of the branches; an empty branch makes the rest optional."""
    full = [_seq(b) for b in branches if b]
    choice = full[0] if len(full) == 1 else {"alt": full}
    return {"opt": choice} if len(full) < len(branches) else choice


def _is_noop(part: Part) -> bool:
    return part == EMPTY or part == {"seq": []}


# --- normal form: no guard is followed by anything in its own list -----------------------


def _norm(parts: list[Part]) -> list[Part] | None:
    """The list with every guard pushed into what follows it, right to left.

    A guard can remain only as the last element (it needs the caller's continuation).
    ``None``: no way through the list satisfies its guards.
    """
    out: list[Part] = []
    for raw in reversed(_flatten(parts)):
        part = _inner(raw)
        if part is None:
            return None
        if _is_noop(part):
            continue
        if is_guard(part):
            pushed = _push([part], out)
        elif out and _open(part):
            spread = _distribute(part, out)
            pushed = None if spread is None else [spread]
        else:
            pushed = [part, *out]
        if pushed is None:
            return None
        out = pushed
    return out


def _inner(part: Part) -> Part | None:
    """``part`` with the lists inside it normalized; ``EMPTY`` / ``None`` when it vanishes."""
    if "alt" in part:
        return _alt_or_none([_norm(_items(x)) for x in part["alt"]])
    for key in ("opt", *REPEATS):
        if key in part:
            return _inner_body(key, _norm(_items(part[key])))
    return part


def _inner_body(key: str, body: list[Part] | None) -> Part | None:
    """``opt``/``star``/``plus`` over a normalized body; a body that matches nothing leaves
    the empty string (``opt``, ``star``) or nothing at all (``plus``)."""
    if body:
        return {key: _seq(body)}
    return None if key == "plus" else EMPTY


def _open(part: Part) -> bool:
    """Does a branch of this ``alt`` (or the ``opt`` body) end in a guard?"""
    if "alt" in part:
        return any(_ends_open(_items(b)) for b in part["alt"])
    if "opt" in part:
        return _ends_open(_items(part["opt"]))
    return False


def _ends_open(items: list[Part]) -> bool:
    return bool(items) and (is_guard(items[-1]) or _open(items[-1]))


def _distribute(part: Part, rest: list[Part]) -> Part | None:
    """``part`` followed by ``rest`` as one ``alt`` with ``rest`` copied into each branch."""
    if "opt" in part:
        options = [_items(part["opt"]), []]
    else:
        options = [_items(b) for b in part["alt"]]
    return _alt_or_none([_norm([*o, *rest]) for o in options])


def _push(guards: list[Part], out: list[Part]) -> list[Part] | None:
    """``guards`` evaluated at the start of the normalized list ``out``."""
    if not out or is_guard(out[0]):
        return [*guards, *out]
    head, rest = out[0], out[1:]
    if EOL_KEY in head:
        return _at_eol(guards, head)
    if not nullable_part(head):
        fused = _prefix(guards, head)
        return None if fused is None else [fused, *rest]
    branches: list[list[Part]] = []
    taken = _required(head)
    fused = None if taken is None else _prefix(guards, taken)
    if fused is not None:
        branches.append([fused, *rest])
    skipped = _push(guards, rest)
    if skipped is not None:
        branches.append(skipped)
    return [_alt(branches)] if branches else None


def _pair(guard: Part) -> Guard:
    return (guard["regex"], bool(guard.get("ci")))


def _prefix(guards: list[Part], part: Part) -> Part | None:
    """``guards`` before a Part that cannot match the empty string."""
    if "regex" in part or "literal" in part:
        return {**part, PRE_KEY: [*map(_pair, guards), *part.get(PRE_KEY, [])]}
    if "plus" in part:
        first = _push(guards, _items(part["plus"]))
        return None if first is None else _seq([*first, {"star": part["plus"]}])
    if "alt" in part:
        return _alt_or_none([_push(guards, _items(x)) for x in part["alt"]])
    pushed = _push(guards, _items(part))
    return None if pushed is None else _seq(pushed)


def _alt_or_none(branches: list[list[Part] | None]) -> Part | None:
    kept = [b for b in branches if b is not None]
    return _alt(kept) if kept else None


def _required(part: Part) -> Part | None:
    """The non-empty form of ``part`` (``part`` itself when it cannot be empty)."""
    if not nullable_part(part):
        return part
    if "regex" in part:
        return None if is_guard(part) else {**part, NONEMPTY_KEY: True}
    if "opt" in part:
        return _required(part["opt"])
    for key in REPEATS:
        if key in part:
            return _required_repeat(part[key])
    if "alt" in part:
        return _alt_or_none([_listed(_required(b)) for b in part["alt"]])
    return _required_seq(_items(part))


def _required_repeat(body: Part) -> Part | None:
    """One non-empty ``body`` and then any number of ``body``."""
    first = _required(body)
    return None if first is None else _seq([first, {"star": body}])


def _listed(part: Part | None) -> list[Part] | None:
    return None if part is None else [part]


def _required_seq(items: list[Part]) -> Part | None:
    """Non-empty form of a sequence whose items can all be empty: item ``i`` is the first
    non-empty one."""
    branches: list[list[Part]] = []
    for index, item in enumerate(items):
        first = _required(item)
        if first is not None:
            branches.append([first, *items[index + 1 :]])
    return _alt(branches) if branches else None


# --- the end of the line ----------------------------------------------------------------


def _at_eol(guards: list[Part], eol: Part) -> list[Part] | None:
    """Decide lookaheads before the line end; keep lookbehinds on the sentinel."""
    behind = [g for g in guards if LOOKBEHIND.search(g["regex"])]
    for guard in guards:
        if guard not in behind and not _holds_at_eol(*_pair(guard)):
            return None
    if not behind:
        return [eol]
    return [{**eol, PRE_KEY: [*map(_pair, behind), *eol.get(PRE_KEY, [])]}]


@cache
def _holds_at_eol(pattern: str, ci: bool) -> bool:
    return regex.match(guard_pattern(pattern, ci), LINE_END_TEXT) is not None


def _finish(items: list[Part]) -> list[Part]:
    """Drop the end-of-line sentinels; a lookbehind left on one becomes a suffix."""
    out = [_finish_inner(p) for p in items if EOL_KEY not in p]
    if items and EOL_KEY in items[-1] and PRE_KEY in items[-1]:
        return _pull(items[-1][PRE_KEY], out)
    return out


def _finish_inner(part: Part) -> Part:
    if "alt" in part:
        return {"alt": [_seq(_finish(_items(b))) for b in part["alt"]]}
    for key in ("opt", *REPEATS):
        if key in part:
            return {key: _seq(_finish(_items(part[key])))}
    return part


def _pull(guards: list[Guard], out: list[Part]) -> list[Part]:
    """``guards`` checked after the last Part; unfused when that Part can be empty."""
    if out and not nullable_part(out[-1]):
        fused = _suffix(guards, out[-1])
        if fused is not None:
            return [*out[:-1], fused]
    return [*out, *({"regex": g, "ci": ci} for g, ci in guards)]


def _suffix(guards: list[Guard], part: Part) -> Part | None:
    if "regex" in part or "literal" in part:
        return {**part, POST_KEY: [*part.get(POST_KEY, []), *guards]}
    if "alt" in part:
        branches = [_pull(guards, _items(b)) for b in part["alt"]]
        return {"alt": [_seq(b) for b in branches]}
    if "seq" in part:
        return _seq(_pull(guards, _items(part)))
    return None

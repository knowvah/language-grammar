## Observation: start keywords are a prefix test, and only Lark/TextMate had a word boundary
- **Context**: issue #7 (`@startumlx` rejected by Lark).
- **Finding**: `DiagramType.check` (core/DiagramType.java:220-232) compares the key against the
  text after `@start` as a prefix, ASCII-lowercased; `@startumlfoo` is `uml` (jar fixture
  `tests/fixtures/document/forms/name-suffix.puml`). The interpreter (`tools/interp/dispatch.py:lookup`)
  and the W3C emitter already used prefix semantics; Lark and TextMate added `(?![A-Za-z0-9])`.
  The 29 real `start_map` keys are prefix-free (tests/emit/test_framing.py), which is what lets
  every `START_<KW>` be "keyword + anything" without two terminals matching one line.
- **Impact**: a new `start_map` key that prefixes another breaks this encoding; the prefix-free
  test fails first.
- **Confidence**: High

## Observation: Lark `/i` START terminals fold non-ASCII letters; upstream does not
- **Context**: same change, probing `regex` IGNORECASE on the START terminals.
- **Finding**: `regex.match(r"[ \t]*[@\\]startuml", "@ſtartuml", regex.I)` matches (U+017F folds to
  `s`; U+212A to `k`, U+0130 to `i` per T34). Upstream `check` folds only `A`-`Z`, so `@ſtartuml` is
  not a start directive at all. W3C uses explicit `[Ss]` classes and is correct. Not fixed here.
- **Impact**: Lark over-accepts start lines with those three code points; fixing it means
  rendering START/START_OTHER with ASCII case classes instead of `/i`.
- **Confidence**: High (direct `regex` probe)

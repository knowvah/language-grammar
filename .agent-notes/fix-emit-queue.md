## Observation: context transitions are rendered as three forms (closed / tail / root)
- **Context**: queued emitter entries (activity3 set, state optional pop, timing last-line set, description trailing blanks).
- **Finding**: the entries shared one cause: a pushed context was a rule ended by a pop line, entered as `<parts> _NL block`. The interpreter's stack semantics need (1) `set` to end the block and continue with the target's block (frame replaced), (2) an unclosed push to be legal only as the last line (spine), (3) `pop` in the bottom frame to be an ordinary no-op line, `set` in the bottom frame to continue with the target as a new bottom frame, (4) newline-led blocks so an empty block after the last body line needs no extra newline. tools/emit/flow.py (pure classification) + flow_rules.py (shared builder for Lark and W3C) implement this; the first sketch (optional pop line, plain "open" variant) accepted `strict {` / `grp {` / `}` and any line of the parent inside an open child because Earley could end the child early.
- **Impact**: do not render a push as an optional pop; an open body must be a spine. `require_pop` backtracking (retry the pushing line with later rules) is not expressible.
- **Confidence**: High (tests/emit/test_flow.py compares Lark with the interpreter on 40 toy blocks).

## Observation: Lark first-match terminals vs alternation order
- **Finding**: `prefer_longest` only sorted plain-word groups. `lift_prefixed` parses every alternation (escapes, classes, group heads) and moves an alternative before an earlier alternative it extends.
- **Impact**: the match set is unchanged; only which alternative the single non-backtracking `regex.match` prefers.
- **Confidence**: High

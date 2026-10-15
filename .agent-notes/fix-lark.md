## Observation: Lark inline opt/alt groups explode into a cartesian product
- **Context**: `Lark(dist/plantuml.lark)` did not finish building in 280 s.
- **Finding**: `SimplifyRule_Visitor.expansion` (lark/load_grammar.py:387-406) distributes every inline `(a|b)` and `x?` into flat expansions (~8e8 for `class_command_link_class`). Fix: tools/emit/lark.py hoists opt/alt/compound star+plus and nullable regexes into shared `_o_N`/`_a_N`/`_g_N` rules (`_o_N: x |` is accepted by Lark). Parser build now ~1 s; max per-rule estimate 92.
- **Impact**: never emit inline `(a|b)` or `x?` in a command rule. `_` rules are inlined in trees, so `<d>_body` diagram detection is unchanged.
- **Confidence**: High

## Observation: lazy regex terminals match only the empty string under dynamic Earley
- **Context**: vega sequence blocks with `opt message received` / `alt REQUEST` are rejected by Lark (63/118 sequence, 57/62 nwdiag-packet, 14/28 class interp-accept/Lark-reject).
- **Finding**: `CommandGrouping` has part `{regex: "(.*?)", name: COMMENT}` (after the `$` anchor was stripped by the emitter). Lark's dynamic lexer calls `regex.match` once at the position and only shortens the match for `dynamic_complete`; a lazy `.*?` returns the empty match, which is dropped (nullable guard), leaving " message received" unconsumed. `dynamic_complete` gives the same result (verified). Not fixed: not a time problem; needs a semantic decision (e.g. make a trailing lazy quantifier greedy when the stripped regex ended the line).
- **Impact**: dominant Lark-vs-interpreter disagreement cause for family tasks to investigate.
- **Confidence**: Medium (mechanism confirmed on CommandGrouping; share of other disagreements not measured)

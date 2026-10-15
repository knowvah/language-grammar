## Observation: Lark inline opt/alt groups explode into a cartesian product
- **Context**: `Lark(dist/plantuml.lark)` did not finish building in 280 s.
- **Finding**: `SimplifyRule_Visitor.expansion` (lark/load_grammar.py:387-406) distributes every inline `(a|b)` and `x?` into flat expansions (~8e8 for `class_command_link_class`). Fix: tools/emit/lark.py hoists opt/alt/compound star+plus and nullable regexes into shared `_o_N`/`_a_N`/`_g_N` rules (`_o_N: x |` is accepted by Lark). Parser build now ~1 s; max per-rule estimate 92.
- **Impact**: never emit inline `(a|b)` or `x?` in a command rule. `_` rules are inlined in trees, so `<d>_body` diagram detection is unchanged.
- **Confidence**: High

## Observation: regex terminals are matched once; the lexer never extends them
- **Context**: vega Lark-vs-interpreter disagreements (142 of 301 blocks before, 1 after).
- **Finding**: Lark's dynamic lexer takes ONE `regex.match` at a position; `dynamic_complete` only retries *shorter* prefixes of that match. Everything upstream regex backtracking would do must therefore be reachable by shortening a maximal first match. Emitter now (tools/emit/lark.py): (1) `greedy()` turns every lazy quantifier greedy (`(.*?)`, `<<.+?>>`, `GENDER (...)*?`); (2) `prefer_longest()` orders plain alternations longest first (`par|partition`, `--|--++`); (3) the last consumer of a command line carries `(?=[ \t]*(?:\r?\n|\Z))` (`tail()`, one variant per possible last element when trailing parts are skippable) so a first alternative (`"..."|.*`) cannot shadow the longer one; (4) comment lines (`'`, `/' '/`) are blank lines; (5) a body needs one real command unless the model declares an `empty` context. `lark_parse.LEXER = "dynamic_complete"` is required for (1)-(3).
- **Impact**: do not revert LEXER to `dynamic`; the lookahead is NOT redundant with greedy (removing `tail()` re-breaks sub/repro2 `card "x" 'c`). `\Z` inside the lookahead is true on the shortened prefixes dynamic_complete retries, so it only filters the first match.
- **Confidence**: High

## Observation: `diagram_of` needs the `_body_N` suffix
- **Context**: many models share one `diagram:` (psystem-* are SEQUENCE), so the emitter names bodies `sequence_body`, `sequence_body_2`, ...
- **Finding**: `lark_parse.diagram_of` matched only the exact `_body` suffix, so the diagram came back None for every later model. Now `^(.+)_body(?:_\d+)?$`. The reported diagram is still whichever body Earley's ambiguity resolution picks (e.g. `Alice -> Bob : x` reports ACTIVITY), not a dispatch result.
- **Confidence**: High

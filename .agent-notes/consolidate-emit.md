## Observation: the `regex` module treats `[^\s\S]` as "match anything"
- **Context**: choosing a never-matching class for a positive class emptied by `linebound.py`.
- **Finding**: `regex.match(r"[^\s\S]", "a")` matches (the stdlib `re` does not). `[^\x00-\U0010ffff]` never matches and has static width 1 (`lark.utils.get_regexp_width` = 1), unlike `(?!)` (width 0, reads as nullable).
- **Impact**: do not use `[^\s\S]` anywhere an emitted pattern must match nothing (Lark runs terminals under `regex`).
- **Confidence**: High

## Observation: Lark `eval_escaping` rewrites `\"` to `"` anywhere in a `/.../` terminal
- **Context**: `\\"` (escaped backslash then quote, DOT header) reached the lexer as `\"`.
- **Finding**: lark/load_grammar.py `eval_escaping` doubles each `\\`, then does `.replace('\\"', '"')`, which also eats the last backslash of the doubled pair. `\x22` survives (it is only turned into `"` by `literal_eval` afterwards), so `tools/emit/lark_regex.py:render_literal_body` writes every quote as `\x22`.
- **Impact**: the fix is at the origin (terminal rendering); no model needs a `[\\]"` workaround.
- **Confidence**: High (round-trip test over six patterns in tests/emit/test_lark_regex.py)

## Observation: start keywords are derived from `start_map`, not from the diagram type
- **Context**: `@startsprites` had no block; `@startproject` (GanttDiagramFactory) had none either.
- **Finding**: `tools/emit/keywords.py:group_by_keyword` offers a model under every `start_map` keyword whose factory list names the model's `factory` (29 keywords on the real model, all with a block in Lark, W3C and TextMate; tests/emit/test_framing.py enumerates them). Models without a factory fall back to the diagram-type keyword.
- **Impact**: `@startproject` blocks are now accepted by Lark (they were rejected before). A new `start_map` keyword gets its block with no emitter change.
- **Confidence**: High

## Observation: block end is one shared terminal (any `[@\\]end...`)
- **Context**: `@startregex ... @enderegex` and `@startuml ... @endmindmap` rejected by Lark.
- **Finding**: StartUtils.isEndDirective (utils/StartUtils.java:119-121) accepts any `@end`/`\end` + suffix, case-sensitive "end". Lark `END_BLOCK`, W3C `END_BLOCK` and the TextMate block `end` (`^\s*([@\\]end[A-Za-z0-9]*)`) all follow. START terminals gained `\` (still `/i`, prefix-by-word `(?![A-Za-z0-9])` as before).
- **Impact**: body rules are not told to refuse a line starting with `@end`; a grammar could read past a first end line upstream would cut at (block extraction never hands such text over). Documented in tools/emit/keywords.py.
- **Confidence**: High

## Observation: TextMate nullable rules are skipped, not rewritten
- **Context**: CommandNope `[\s\xa0]*` matched empty at column 0 of every line and won.
- **Finding**: `textmate.py` drops every `match`/`begin` whose regex has static minimum width 0 (`textmate_regex.can_match_empty`, via lark's `get_regexp_width`). On the real model: 94 rule occurrences (13 distinct regexes: blank-line rules, `.*`/`[\s\S]*` catch-alls, `--`/`==`/`__` line rules whose only width is a lookbehind) of 3952. `end` regexes (`$`, `(?=...)`) stay. TextMate has no assertion that forces a non-empty match.
- **Impact**: the lookbehind-width rules (`(?=--).*(?<=--)`) lose their scope; rewrite them with a real width if they are wanted.
- **Confidence**: High (tests/emit/test_textmate.py, tests/textmate/real-model.test.mjs)

## Observation: generated class commands carry no TextMate scopes
- **Context**: tokenizing `class Foo` with the real model.
- **Finding**: only hand-annotated parts (EBNF, regex, ...) have `scope`; the generated class/sequence rules emit unscoped `match` rules, so their lines are `meta.diagram.plantuml` only. Not a defect of this pass.
- **Confidence**: High

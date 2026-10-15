## Observation: terminals that cross a line end were the whole `<style>` Lark slowdown
- **Context**: T18/T16 measured `<style>` blocks at 16.7 s (class maxosa-84-juci042) in Lark.
- **Finding**: 139 of 2921 terminals (negated classes such as `[^"]+`, `[^\[\]]+`, `[\s\S]+`, `\s`) matched across `\n` from
  every line start of a 28-line style region; dynamic_complete then tries every shorter prefix, so
  Earley items grow quadratically in the region size. After `tools/emit/linebound.py` no terminal crosses
  a line end (0 of 2560). Ablation on the real model: both fixes 0.24 s, line-bound only 0.41 s, tops-only 14.96 s,
  neither 18.0 s. The style model and `style_body` (never used by Lark: transitions on multiline are ignored) were not at fault.
- **Impact**: any new regex construct that can match `\n` (`\W`, `\D`, `\P{..}`, `.` with `\r`) must be covered by `line_bounded`; the
  probe test in tests/emit/test_linebound_real.py catches terminals that cross a line end.
- **Confidence**: High

## Observation: emitters emit top models only
- **Context**: sequence family left `gen-sequence-diagram` in dist.
- **Finding**: `tools/emit/tops.py:emitted_diagrams` keeps diagram-layer models that are a factory top or have no factory.
- **Impact**: a family's `remove`/narrowing now reaches Lark, TextMate and W3C.
- **Confidence**: High

## Observation: greedy() leaked state across a character class
- **Context**: `x*[a]?` lost its `?` (the `[` branch did not reset `after_quantifier`).
- **Finding**: fixed in tools/emit/lark.py; `.` is rewritten to `[^\r\n]` so the pattern shape became reachable.
- **Confidence**: High

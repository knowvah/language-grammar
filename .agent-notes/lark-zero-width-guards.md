## Observation: every zero-width-only regex part is a no-op in Lark, not just D_NOT_FORBIDDEN
- **Context**: diagnosing issue #3 (lookahead-only guards voided by the nullable encoding).
- **Finding**: `_regex` in tools/emit/lark.py hoists any nullable regex into `_o_N: T |`. For a
  part whose max width is also 0 (pure lookaround) the empty alternative skips the assertion,
  and the terminal itself cannot help: Lark's dynamic lexer files a match under `m.end()`, which
  for a zero-length match is the position already being scanned, so a zero-width token is lost.
  The resolved real model has 67 distinct zero-width-only regexes, 3467 occurrences (duplicates
  across included models counted). Next element after the guard: regex 1902, seq 653, opt 299,
  literal 180, star 175, end of line 128, alt 120, plus 10.
  Scan script: fold the guard into the following terminal(s) is the only encoding that keeps it.
- **Impact**: the fix is a guard-pushing transform (prepend the assertion to every first terminal
  reachable from the continuation, splitting nullable heads), not a local change to `_regex`.
  A parity run is needed afterwards; enforcing ~67 guards can move Lark verdicts both ways.
- **Confidence**: High for the mechanism and counts; the transform design is a proposal.

## Observation: dynamic_complete re-matches a terminal against its own truncated text
- **Context**: choosing where a fused guard is evaluated (issue #3).
- **Finding**: lark/parsers/xearley.py:64-70 retries `match(term, s[:-j])` on the matched token
  text alone, not on the stream. A guard fused as a terminal prefix therefore sees a cut-off
  string on retries; a `$` inside it would be a false line end there. Guards are translated
  with `GUARD_LINE_END = (?=\r|\n)` (no `\Z`) in `tools/emit/lark_regex.py`; body lines are
  always newline-terminated in a block, so the full-match path is unchanged.
- **Impact**: positive lookaheads that inspect text beyond a shortened token can still fail on
  retries; parity after the change showed no new disagreement.
- **Confidence**: High (source read; parity run)

## Observation: guard fusion results (parity, Lark sample, 2026-10-16)
- **Finding**: disagreements 44 -> 39 (vega 3, plantuml-ts 16, pdiff 20); FR/FA unchanged. Fixed:
  `foo` after a link (3) and `vevatu-41` (`portin` in a body, 2; previously "undiagnosed").
  Timeouts 62 -> 71: the 9 new ones take 9.4-17.5 s serially at 60 s on BOTH the old and new
  grammar (same verdicts as the jar); they sit at the 10 s budget and move with load
  (4 parity workers). `dist/plantuml.lark` grew 3% (1.27 -> 1.31 MB).
- **Impact**: compare timeouts serially against the previous grammar before calling a change slow.
- **Confidence**: High

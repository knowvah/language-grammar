## style: emitters should skip `join` entries that need a joined line (non-blocking)

`model/diagrams/style.yaml` refines `CommandStyleMultilinesCSS` into a `join` whose parts
match the whole `<style>` block (U+E100 = line joiner), plus `CommandStyleMultilinesCSSReject`
(also a join with U+E100). Emitters approximate `join` by a single line, and no single line
contains U+E100, so both entries are dead in every emitter. They are still emitted into
every diagram model that includes `style` (via `common`), ~2 KB of lookaround-heavy regex per
model. Measured on a scratch tree where all 52 top models include `style`: W3C lossiness
1,233 -> 9,375 constructs (lookaround 145 -> 7,199), `plantuml.lark` 431 KB -> 904 KB. Those
numbers also include the duplicated probe models. Parse time is NOT affected by the dead
joins: removing them from a scratch copy left Lark time unchanged. An earlier 3-5x Lark
slowdown came from a `single` + `push` emitter entry and was fixed in style.yaml by making
it a `multiline` with `end`. This entry is a size/readability improvement only. Verdicts
did not change (vega/style `disagree=0` either way).

Proposed filter (textmate.py; identical one-line guard in `lark.py` and `w3c.py` where
command entries are turned into line rules):

```diff
--- a/tools/emit/textmate.py
+++ b/tools/emit/textmate.py
@@ def context_rules(self, entries: list[Entry], skip_pop: bool) -> list[Rule]:
         for entry in entries:
             if "command" not in entry or (skip_pop and entry.get("pop")):
                 continue
+            if JOIN_KEY in entry and "" in json.dumps(entry["parts"], ensure_ascii=False):
+                continue  # needs >1 joined line: can never match one line
             rules.append(self.entry_rule(entry))
```

Failing cases: none (size and speed only). Reproduce: copy `model/` with a wrapper
`include: [<top>, style]` per factory, `python -m tools.emit.build --model-dir <copy>`.
## common: a pushed body left open at the end of the block must reject (`require_pop`)

Upstream a multiline command whose end never comes is skipped (`isMultilineCommandOk`
returns null, `command/PSystemCommandFactory.java:268-288` at 97a5992) and the start line
then fails. A model that enters a body as a context (`push`) to validate its lines (skinparam
`{ }` bodies, sprite data) has no way to say that the body must be closed: `Interpreter._run`
accepts a block whose context stack is still open. Proposal: an entry key `require_pop: true`
(only with `push`), meaning "if the block ends while this pushed context is still on the
stack, the attempt fails at the pushing line". Lark already requires the pop line.

Proposed diff (schema, guide, interpreter; emitters unchanged):

```diff
--- a/model/schema.json   ($defs.command.properties and $defs.command_patch.properties)
+        "require_pop": {"const": true},
--- a/model/schema.json   ($defs.command.allOf)
+        {"if": {"required": ["require_pop"]}, "then": {"required": ["push"]}},
--- a/tools/interp/rules.py
 class Rule:
     ...
     action: str
     target: str
+    require_pop: bool = False
 def build_rule(entry: Entry) -> Rule:
-    return Rule(entry["command"], entry["kind"], start, end, max_lines, action, target)
+    return Rule(entry["command"], entry["kind"], start, end, max_lines, action, target,
+                bool(entry.get("require_pop")))
--- a/tools/interp/engine.py   (_run)
-        stack = [context]
+        stack = [context]
+        opened: list[int | None] = [None]   # body index of a require_pop push, per frame
         i = 0
         while i < len(body):
             step = self._candidate(model, stack[-1], body, i, deadline)
             if step is not None:
+                if step[0].action == ACTION_PUSH:
+                    opened.append(i if step[0].require_pop else None)
+                elif step[0].action == ACTION_POP and len(opened) > 1:
+                    opened.pop()
                 _apply(stack, step[0])
                 i = step[1]
             ...
-        return None
+        pending = [k for k in opened if k is not None]
+        return pending[0] if pending else None
--- a/docs/grammar-guide.md   (Keys table)
+| `require_pop: true` | entry | With `push`: ending the block inside the pushed context fails the attempt at the pushing line (upstream skips a multiline command that never completes). | none (added) |
```

Then `model/diagrams/common.yaml` adds `require_pop: true` to the `CommandSkinParamMultilines`
override, the `CommandFactorySprite_1` override, the inserted `CommandFactorySpriteGray16`,
and the nested `CommandSkinParamBodyOpen`.

Failing cases it fixes (strict xfail in tests/families/test_common.py, `tests/fixtures/common/gap/`):
`skinparam-block-unterminated`, `skinparam-block-unterminated-eob`, `sprite-multi-unterminated`,
`sprite-multi-unterminated-eob`, `sprite-multi-packed-unterminated`.

## common: entry-level `reject` for execute-time errors

`CommandExecutionResult.error` (`PSystemCommandFactory.java:179-187`) makes the factory fail
on a line its regex matched (`scale 0`, `page 0x1`, `!pragma graphviz_dot`, sprite level 5).
The only way to model it today is to narrow `parts` so the line no longer matches, but then
the line falls through to later commands. A family catch-all after the common block takes it.
For example, salt's `CommandAnything` accepts `page 0x1`, where upstream `CommandPage`
matched and failed. Proposal: an entry key `reject: true` (kind `single` only) that makes
the attempt fail at that line when the entry is selected. The narrowed common overrides
would then become an `insert_before` reject entry plus the unnarrowed generated rule.

```diff
--- a/model/schema.json   ($defs.command.properties)
+        "reject": {"const": true},
--- a/model/schema.json   ($defs.command.allOf)
+        {"if": {"required": ["reject"]}, "then": {"properties": {"kind": {"const": "single"}},
+         "allOf": [{"not": {"required": ["push"]}}, {"not": {"required": ["set"]}}, {"not": {"required": ["pop"]}}]}},
--- a/tools/interp/rules.py
+    reject: bool = False          # build_rule: bool(entry.get("reject"))
--- a/tools/interp/engine.py   (_run)
             if step is not None:
+                if step[0].reject:
+                    return i
--- a/docs/grammar-guide.md   (Keys table)
+| `reject: true` | entry | `single` only: when selected, the attempt fails at this line (mirrors `CommandExecutionResult.error`). Emitters drop the entry. | none (added) |
```

Emitters (lark, w3c, textmate) must skip `reject` entries (Lark: drop the alternative).

Failing case it fixes: `tests/fixtures/common/gap/salt-page-zero.puml` (and the same class of
fall-through for every narrowed common command in any factory whose own commands follow the
common block with a catch-all).

## style: scan_join needs an early exit; uncapped joins are cubic (blocking for performance)

Mechanism: `tools/interp/scan.py` `scan_join` re-joins `body[i:j]` and full-matches for every
k up to `max_lines`, with no first-line check and no early exit (`Rule.advance` calls it on
every line that reaches the rule). `style.yaml` refines `CommandStyleMultilinesCSS` into a
join with `max_lines: 100000`, because upstream's CommandMultilines2 has no line cap. For
every body line before the style commands in `main`, the scan then joins up to the rest of
the block: O(n^2) per line, O(n^3) per block. Reported by T16:
`plantuml-ts:sequence/zudize-61-vomi445.puml#0` / `pdiff:dbhum/z_ud/zudize-61-vomi445.puml#0`
(45,512 lines, no `<style>`) times out after 60 s with a probe `include: [gen-sequence-diagram,
style]`, and takes 0.68 s without `style`. Parity timeouts: plantuml-ts 1 -> 3, pdiff 1 -> 2
(FR/FA unchanged).

Fix: stop once the joined prefix (plus the joiner the next unit would add) cannot extend to a
match, using `regex` partial matching. The result is the same: if no extension of
`joined + JOINER` can match, no larger k can.

```diff
--- a/tools/interp/scan.py
+++ b/tools/interp/scan.py
@@ class Deadline:
         try:
             return pattern.fullmatch(text, timeout=remaining) is not None
         except TimeoutError as exc:
             raise BlockTimeout from exc
+
+    def prefix(self, pattern: Any, text: str) -> bool:
+        """Could ``text`` still be extended to a full match (``regex`` partial matching)?"""
+        remaining = self._limit - self._clock()
+        if remaining <= 0:
+            raise BlockTimeout
+        try:
+            return pattern.fullmatch(text, partial=True, timeout=remaining) is not None
+        except TimeoutError as exc:
+            raise BlockTimeout from exc
@@ def scan_join(
         joined = JOINER.join(line.trimmed for line in body[i:j])
         if deadline.fullmatch(start, joined):
             return j
+        if not deadline.prefix(start, joined + JOINER):
+            return None
     return None
```

Validated by monkeypatching it in scratch: the repro finishes `ok` in 0.7 s. All 89 style
fixture blocks, 88 oracle probes and 469 corpus style regions keep their verdicts, and
`tests/interp tests/families tests/layers tests/validate` stays 1071 passed / 18 xfailed both
with and without the patch. Needs a unit test in tests/interp (for example, a join with
`max_lines: 100000` over a 5,000-line body that never starts with its first literal returns
`None` in under 1 s).

## orchestrator: resolution of the entries above (2026-10-15)
- style / emitters skip joiner-only `join` entries → done in 063d6ee (`tools/emit/skip.py`).
- common / `require_pop` → done in 063d6ee (backtracks like `PSystemCommandFactory.java:236-240`).
- common / entry-level `reject` → done in 063d6ee.
- style / `scan_join` early exit → done in 494ce06.

## sequence: test_common assumes every command factory is still probed (blocking the full suite)

Once a family model (`sequence`, T17; `class`, T18) includes `common`, `with_probes` no longer
creates `probe-gen-sequence-diagram` / `probe-gen-class-diagram`, so three T16 tests fail:
`test_each_reject_directly_follows_its_narrowed_rule` and
`test_refined_entries_are_marked_refined_by_common` (KeyError on the probe id) and
`test_every_command_factory_with_the_common_block_gets_a_probe` (Sequence/Class no longer probed).
Fix: look up the top model of the factory (probe or family model) instead of the probe id.
Validated on a scratch copy with `model/diagrams/sequence*.yaml` in place: 327 passed, 12 xfailed.

```diff
@@ -49,6 +49,7 @@
 DIAGRAM_LAYER = "diagram"
 PROBE_PREFIX = "probe-"
 UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
+SEQUENCE_FACTORY = "SequenceDiagramFactory"
 HEADER = re.compile(r"^' (?P<key>common|factory|gap): (?P<value>.+)$")
 START = re.compile(r"^@start(?P<keyword>\w+)", re.MULTILINE)
 
@@ -194,7 +195,7 @@
 ) -> None:
     errors = raw_models[ERRORS_ID].insert_after
     assert all(e.get("reject") for entries in errors.values() for e in entries)
-    main = [e["command"] for e in models[PROBE_PREFIX + "gen-sequence-diagram"].contexts[MAIN]]
+    main = [e["command"] for e in common_top(models, SEQUENCE_FACTORY).contexts[MAIN]]
     for key, entries in errors.items():
         (entry,) = entries
         assert main[main.index(key) + 1] == entry["command"], key
@@ -208,12 +209,22 @@
     ]
 
 
-def test_every_command_factory_with_the_common_block_gets_a_probe(models: ResolvedModels) -> None:
-    probed = {base.factory for _, base in probe_pairs(models)}
-    assert {"SequenceDiagramFactory", "ClassDiagramFactory", "GanttDiagramFactory"} <= probed
-    assert len(probed) >= 20
+def common_top(models: ResolvedModels, factory: str) -> ResolvedModel:
+    """Top model of ``factory``: its probe, or the family model that includes ``common``."""
+    top = models[top_models(models)[factory]]
+    assert COMMON_ID in top.includes, factory
+    return top
 
 
+def test_every_command_factory_with_the_common_block_includes_common(
+    models: ResolvedModels,
+) -> None:
+    tops = [models[mid] for mid in top_models(models).values()]
+    covered = {m.factory for m in tops if COMMON_ID in m.includes}
+    assert {SEQUENCE_FACTORY, "ClassDiagramFactory", "GanttDiagramFactory"} <= covered
+    assert len(covered) >= 20
+
+
 def test_probes_keep_the_upstream_order_of_the_base_model(
     raw_models: dict[str, Model], models: ResolvedModels
 ) -> None:
@@ -235,8 +246,8 @@
     raw_models: dict[str, Model], models: ResolvedModels
 ) -> None:
     keys = set(raw_models[COMMON_ID].overrides)
-    probe = models[PROBE_PREFIX + "gen-sequence-diagram"]
-    refined = {e["command"] for e in probe.contexts[MAIN] if e.get("refined_by") == COMMON_ID}
+    top = common_top(models, SEQUENCE_FACTORY)
+    refined = {e["command"] for e in top.contexts[MAIN] if e.get("refined_by") == COMMON_ID}
     assert refined == keys
 
 
```

- sequence / test_common top-model lookup → applied by the orchestrator (see the next commit).

## class: test_style reads every context of the CLASS top model (blocking the full suite)

`model/diagrams/class.yaml` (T18) gives ClassDiagramFactory one context per diagram state
(`main`, `main_mixing`, `class_group`, `class_group_mixing`, `class_orphan`), each
splicing `gen-class-diagram#main`, so every style entry appears once per context.
`tests/families/test_style.py::entries_named` collects entries from all contexts and
expects one copy. T17's sequence model splices its generated main into several contexts
the same way (reported by t17-sequence). Proposed change (verified: 107/107 pass on a
scratch copy with the T18 model in place):

```diff
@@ def entries_named(command: str) -> list[dict[str, Any]]:
     model = style_models()[class_top()]
-    return [e for es in model.contexts.values() for e in es if e["command"] == command]
+    return [e for e in model.contexts[MAIN] if e["command"] == command]
```

Failing today:
- test_single_line_css_is_refined_in_place
- test_structure_entry_pushes_body_closed_by_upstream_end
- test_join_entries_never_match_a_single_line[CommandStyleMultilinesCSS]
- test_join_entries_never_match_a_single_line[CommandStyleMultilinesCSSReject]

- class / test_style reads only `main` → applied by the orchestrator with the T18 commit.

## sequence: emitters must emit only the top model of each factory (blocking for every family's emitter parity)

`emit_lark`, `emit_textmate` (`_by_keyword`) and `emit_w3c_with_lossiness` emit every
`layer: diagram` model. A family model replaces its generated base in dispatch
(docs/grammar-guide.md, "Diagram dispatch"), but the base stays in the emitted union, so
none of a family's narrowing or `remove` reaches the grammars: with `sequence` in place the
Lark grammar has two SEQUENCE bodies and still accepts `end` at top level, `note accross`,
`autonumber 99999999999`, `A o- B` through the unrefined `gen-sequence-diagram` body. Non-top
diagram models today: `gen-class-diagram`, `gen-psystem-ditaa`, `gen-sequence-diagram`
(each family task adds one). Validated by calling `emit_lark` on the resolved dict filtered
to top models: the sequence negatives above are then rejected by the sequence body (the
remaining Lark accepts on tests/fixtures/sequence/neg are DESCRIPTION over-acceptance, the
lenient tails, dropped rejects, and the newline issue below). Proposed diff (same filter in
the three emitters):

```diff
--- a/tools/emit/lark.py
+++ b/tools/emit/lark.py
@@ def emit_lark(resolved: ResolvedModels) -> str:
     names = _Names()
+    tops = set(top_models(resolved).values())
     diagrams = [
         _Diagram(m, names)
         for _, m in sorted(resolved.items())
-        if m.layer == DIAGRAM_LAYER and m.diagram
+        if m.layer == DIAGRAM_LAYER and m.diagram and m.id in tops
     ]
--- a/tools/emit/textmate.py
+++ b/tools/emit/textmate.py
@@ def _by_keyword(resolved: ResolvedModels) -> dict[str, list[ResolvedModel]]:
     groups: dict[str, list[ResolvedModel]] = {}
+    tops = set(top_models(resolved).values())
     for _, model in sorted(resolved.items()):
-        if model.layer == DIAGRAM_LAYER and model.diagram:
+        if model.layer == DIAGRAM_LAYER and model.diagram and model.id in tops:
--- a/tools/emit/w3c.py
+++ b/tools/emit/w3c.py
@@ def emit_w3c_with_lossiness(resolved: ResolvedModels) -> tuple[str, list[Lossy]]:
+    tops = set(top_models(resolved).values())
     for _, model in sorted(resolved.items()):
-        if model.layer != DIAGRAM_LAYER or not model.diagram:
+        if model.layer != DIAGRAM_LAYER or not model.diagram or model.id not in tops:
             continue
```
(plus `from tools.model.resolve import top_models` in each). Every diagram model declares a
`factory` today, so no model is lost. Failing cases: tests/fixtures/sequence/neg/
note-accross.puml, autonumber-start-overflow.puml, group-stray-else.puml (Lark accepts them
as SEQUENCE with the current dist/plantuml.lark).

## sequence: Lark terminals match across line ends (`\s`, negated classes)

Lark's dynamic lexer matches each terminal regex against the whole text, so `[\s\_]+` and
negated classes such as `[^#]+` consume `\n`. Upstream matches one trimmed line. Observed
with `sequence` in place (grammar filtered to top models, see above):
* `alt x` / `Alice -> Bob` / `end` / `end`: the pop line `end` takes `[\s\_]+(.*?)` across
  the newline and eats the second `end` as its comment, so the extra `end` the jar rejects
  is accepted (neg/group-extra-end.puml).
* `box "x"` / `participant Alice` / `end box` / `end box`: CommandBoxStart NAME2 `([^#]+)`
  swallows the next two lines, so one `end box` disappears (neg/box-extra-end.puml).
Proposed fix in tools/emit/lark.py terminal rendering: rewrite `\s` to `[^\S\r\n]`, and add
`\r\n` to every negated class (`[^#]` -> `[^#\r\n]`), so no terminal crosses a line end;
the existing `tail()` lookahead already assumes line-bounded terminals.
- sequence / emit only top models → done (fix-emit-top, next commit).
- sequence / Lark terminals across line ends → done (fix-emit-top, next commit).

## activity3: Lark/W3C treat `set` like `push`, so if/else needs two `endif` lines

`activity3` (T21a) uses `set` for the first time in a diagram model. `else` (CommandElse3,
DecoratorMultine(Else3), ElseLegacy1) does `set: a3_if_else`, and `case` does
`set: a3_switch_case`. The interpreter replaces the frame. The Lark and W3C emitters nest
the target block inside the current one (`set` is "treated exactly like `push`",
tools/emit/lark.py:30-33). The pushed `a3_if_then_block` then still needs its own pop line
after the `endif` that closed `a3_if_else_block`. So every if/else and every switch with
a case is rejected by Lark, while the jar accepts it.

Measured on a 100-block plantuml-ts activity3 sample (`--lark sample --sample 100`) with
the scratch grammar:
* current emitter: 11 disagreements, 2 timeouts;
* with the diff below: 3 disagreements, 1 timeout. The baseline grammar without activity3
  has the same 3 disagreements and 2 timeouts, so activity3 adds none.

Failing cases: tests/fixtures/activity3/pos/if-else.puml, switch-cases.puml;
plantuml-ts activity/ciceto-21-zanu057, demibe-40-moda439, mukigo-10-dixi626,
rekuxa-78-lidi292, zaloze-31-jibo311, zucile-04-duga040; class/gekasa-78-jevi903,
godixi-01-fizo921.

Fix: inside a pushed context, a `set` entry ends the block like `pop` and continues
with the target's block (`<ctx>_pop_line: ... | else _NL <target>_block`). In `main`
nothing changes (no frame to replace). The same diff applies to tools/emit/w3c.py
(`_context`/`_lines` have the same shape there).
```diff
--- a/tools/emit/lark.py
+++ b/tools/emit/lark.py
@@ def _context(self, ctx: str) -> None:
-        line = self._lines(rule, entries, pop=False)
-        pop_line = self._lines(f"{rule}_pop", entries, pop=True)
+        line = self._lines(rule, entries, pop=False, pushed=True)
+        pop_line = self._lines(f"{rule}_pop", entries, pop=True, pushed=True)
@@
-    def _lines(self, base: str, entries: list[Entry], pop: bool) -> str:
+    def _lines(self, base: str, entries: list[Entry], pop: bool, pushed: bool = False) -> str:
-        chosen = [e for e in entries if bool(e.get("pop")) == pop and not skipped(e)]
+        chosen = [e for e in entries if ends_block(e, pushed) == pop and not skipped(e)]
@@ (module level)
+def ends_block(entry: Entry, pushed: bool) -> bool:
+    """Whether ``entry`` closes the current block: ``pop``, or ``set`` inside a pushed
+    context (the frame is replaced, so the block ends and the target's block follows)."""
+    return bool(entry.get("pop")) or (pushed and bool(entry.get("set")))
```
Also update the docstring bullet (lark.py:30-33): "`set` inside a pushed context ends the
block and continues with the target's block; in `main` it is treated like `push`."
TextMate still nests regions for `set` (highlighting only). document.yaml's `set`
entries are in a layer the emitters do not emit.

## activity3: Lark multiline `end` line cannot be indented

`_entry_expr` renders `multiline` + `end` as
`{expr} _NL (_BODY_LINE? _NL)* {end}`, with no `_WS?` around the end part. An indented
closing line therefore never matches, for example `  end note` of an indented
CommandNoteLong3 (`_lines` wraps first lines in `_WS? ... _WS?`, but not end lines).
This disagreement predates activity3: plantuml-ts activity/kavoro-11-jife299 and
class/tuvigo-52-redo102 are rejected by Lark and accepted by the jar and the interpreter.
Verified in a scratch copy: both parse with the diff below.
```diff
--- a/tools/emit/lark.py
+++ b/tools/emit/lark.py
@@ def _entry_expr(self, entry: Entry) -> str:
-            return f"{expr} _NL (_BODY_LINE? _NL)* {self.tail(entry['end'])}"
+            return f"{expr} _NL (_BODY_LINE? _NL)* _WS? {self.tail(entry['end'])} _WS?"
```
The analogous W3C line (`tail = [Node("NL"), Node("(BODY_LINE? NL)*"), self.part(...)]`)
has the same gap.

## state: Lark requires the pop line of a context entered without `require_pop`

`state` (T20) pushes `state_body` for `state X {` / `frame X {` without `require_pop`,
because upstream accepts a block that ends inside an open composite (no final check;
statediagram/command/CommandEndState.java, net/atmp/CucaDiagram.java:161-166). The Lark
emitter renders every pushed context as `(line? _NL)* <pop line>`, so the closing line
is mandatory and such blocks are rejected. Failing cases (Lark rejects, jar and
interpreter accept): plantuml-ts state/suzope-95-suvu383.puml, state/gizati-67-kora187.puml;
tests/fixtures/state/pos/composite-unclosed.puml. Verified with a monkeypatched emitter
in a scratch build: both corpus blocks parse.
```diff
--- a/tools/emit/lark.py
+++ b/tools/emit/lark.py
@@ def _context(self, ctx: str) -> None:
         line = self._lines(rule, entries, pop=False)
         pop_line = self._lines(f"{rule}_pop", entries, pop=True)
-        tail = pop_line if pop_line else f"{line}?"
+        if not pop_line:
+            tail = f"{line}?"
+        elif self._pop_required(ctx):
+            tail = pop_line
+        else:  # upstream accepts a block that ends inside this context
+            tail = f"({pop_line} | {line}?)"
         self.rules.append(f"{rule}: ({line}? _NL)* {tail}")
+
+    def _pop_required(self, ctx: str) -> bool:
+        """Whether an entry pushing ``ctx`` carries ``require_pop``."""
+        return any(
+            e.get("push") == ctx and e.get("require_pop")
+            for es in self.model.contexts.values()
+            for e in es
+        )
```
Approximation: Earley may then also close such a context before the block end (a
superset); the closer neg fixtures of tests/fixtures/state (brace-at-root,
endstate-at-root, extra-close-after-region, *-closes-root-region) still fail in Lark with
the patch, because no `main`/`main_concurrent` rule accepts a closer. The W3C emitter has the same shape. The sequence family (unclosed
`alt`/`box`) benefits too.

## state: Lark multiline `end` line cannot be indented (second failing case)

Same cause and diff as "activity3: Lark multiline `end` line cannot be indented" above.
Additional failing case: plantuml-ts class/tumaba-64-tosu281.puml (STATE: `    end note`
closing `note right on link` inside a composite; CommandFactoryNoteOnLink_1's generated
end `^end[\s ]?note$` has no leading whitespace, while the interpreter compares the
trimmed line). Before T20 the first note's body ran on to a later unindented `end note`,
which masked it; with `state_body` as a pushed context it no longer can. Verified: parses
with that diff (or with the optional-pop diff above).

## state: Lark terminal alternation where a later alternative extends an earlier one

CommandLinkState / CommandLinkStateReverse ENT1/ENT2 (statediagram/command/
CommandLinkStateCommon.java:74-77) is `([%pLN_.:]+|[%pLN_.:]+\[H\*?\]|\[\*\]|...)`. Lark's
dynamic lexer takes the first alternative that matches (`Stopwatch`) and
`dynamic_complete` only retries shorter prefixes, so `Stopwatch[H]` is never produced
when more text follows (`Timer --> Stopwatch[H] : left`). `prefer_longest`
(tools/emit/lark.py:149-158) only reorders groups of plain words. Failing case: plantuml-ts
class/mefici-97-tudu030.puml (also rejected by the pre-T20 grammar) and
tests/fixtures/state/pos/history.puml (`A[H] --> B`, `B[H*] --> A`). Proposed: extend
`prefer_longest` so that, in any alternation group, an alternative whose text starts with
the full text of an earlier alternative is moved before it (`A|A\[H\*?\]` ->
`A\[H\*?\]|A`); the match set is unchanged under backtracking. Verified by applying exactly
that swap to the 4 occurrences in a scratch plantuml.lark: the block and both lines parse.

## description: Lark rejects trailing whitespace after a multiline or pushing first line

`tools/emit/lark.py` `_entry_expr` writes bracket, `multiline` + `end` and `push`/`set`
entries as `<first line> _NL ...` with no `_WS?` before `_NL`, while one-line commands get
`_WS? <command> _WS?` and the interpreter matches trimmed lines. A first line with
trailing blanks therefore fails in Lark only: `title ` / `x` / `end title`, `<style> ` /
`x { y: z }` / `</style>`, and every group opener that the families turned into a push
(`rectangle r { ` / `[a]` / `}`, `together { `). The jar and the interpreter accept all
of them.
```diff
--- a/tools/emit/lark.py
+++ b/tools/emit/lark.py
@@ def _entry_expr(self, entry: Entry) -> str:
         expr = self.tail(entry["parts"])
         if entry["kind"] == KIND_BRACKET:
-            return f"{expr} _NL (_BODY_LINE? _NL)* _BRACKET_CLOSE"
+            return f"{expr} _WS? _NL (_BODY_LINE? _NL)* _BRACKET_CLOSE"
         if entry["kind"] == KIND_MULTILINE and "end" in entry:
-            return f"{expr} _NL (_BODY_LINE? _NL)* {self.tail(entry['end'])}"
+            return f"{expr} _WS? _NL (_BODY_LINE? _NL)* {self.tail(entry['end'])}"
         target = entry.get("push") or entry.get("set")
         if target:
-            return f"{expr} _NL {self._context_rule(target)}"
+            return f"{expr} _WS? _NL {self._context_rule(target)}"
```
Checked on a scratch copy of `tools/` with the T19 model tree: the 9 probes above all
parse after the change (3 failed before). Failing corpus cases: plantuml-ts
`class/refabu-21-jesu466.puml` (`title ` + `end title`, hidden before T19 because the
bare word `title` also parsed as a description element), `sequence/xozabi-42-pixa842.puml`
(`<style> `), and any group opener with trailing blanks (1 file under plantuml-ts
`component/` + `usecase/`).

## activity3: test_document pins gen-activity-diagram3 as the top model (blocking the full suite)

`activity3` (T21a) is the hand-written family model for ActivityDiagramFactory3 and
replaces `gen-activity-diagram3` in dispatch (guide, "Diagram dispatch"). That is the same
contract `class` and `sequence` follow. tests/layers/test_document.py:161 still asserts
the generated id, so `test_every_mapped_factory_has_one_top_model` fails once
model/diagrams/activity3.yaml is present.
```diff
--- a/tests/layers/test_document.py
+++ b/tests/layers/test_document.py
@@ def test_every_mapped_factory_has_one_top_model(
     assert tops["ActivityDiagramFactory"] == "gen-activity-diagram"
-    assert tops["ActivityDiagramFactory3"] == "gen-activity-diagram3"
+    assert tops["ActivityDiagramFactory3"] == "activity3"
     assert tops["PSystemDitaaFactory"] == "embedded-ditaa"
```

## timing: Lark set/push into a context without pop as the last line

`timing` (T23) switches to `timing_player` with `set` on CommandRobustConcise and
CommandAtPlayer. The Lark emitter renders a transition as `<parts> _NL <ctx>_block` and a
context without a pop line as `(line? _NL)* line?`; `<diagram>_body` then needs its own
`_NL` after the command. When the transition line is the last body line the context is
empty and two newlines are needed before `@enduml`, so Lark rejects. Failing cases (Lark
rejects, jar and interpreter accept): pdiff dbhum/b_up/bupubi-65-kigi561.puml,
dbhum/z_ip/zipuri-87-dofu527.puml, dbhum/z_up/zupuse-88-mira023.puml;
tests/fixtures/timing/pos/player-switch-as-last-line.puml. Any other pop-less `set`
target has the same shape (class `class_orphan`/`main_mixing`, description
`desc_orphan`, `CommandNewpage: {set: main}` as a last line). Verified with a
monkeypatched emitter in a scratch build: pdiff timing `--lark all` 3 -> 0
disagreements, vega and plantuml-ts timing slices stay at 0.
```diff
--- a/tools/emit/lark.py
+++ b/tools/emit/lark.py
@@ def _entry_expr(self, entry: Entry) -> str:
         target = entry.get("push") or entry.get("set")
         if target:
+            if not self._has_pop(target):  # the context ends with the block
+                return f"{expr} {self._context_rule(target)}"
             return f"{expr} _NL {self._context_rule(target)}"
         return expr
@@ def _context(self, ctx: str) -> None:
         line = self._lines(rule, entries, pop=False)
         pop_line = self._lines(f"{rule}_pop", entries, pop=True)
-        tail = pop_line if pop_line else f"{line}?"
-        self.rules.append(f"{rule}: ({line}? _NL)* {tail}")
+        if pop_line:
+            self.rules.append(f"{rule}: ({line}? _NL)* {pop_line}")
+        else:  # each line brings its newline; the body's own `_NL` ends the last one
+            self.rules.append(f"{rule}: (_NL {line}?)*")
+
+    def _has_pop(self, ctx: str) -> bool:
+        return any(e.get("pop") and not skipped(e) for e in self.model.contexts[ctx])
```
Interaction with the queued `state` entry (optional pop line): the same last-line
problem applies to `state X {` as the last body line; the analogous form there is
`<parts> <ctx>` with `<ctx>: (_NL line?)* (_NL pop_line)?`. The queued `description`
entry adds `_WS?` before that `_NL`; keep it on the `_NL` branch only.
- activity3 / test_document top-model assertion → orchestrator made it id-agnostic (T21a commit).
- activity3 / Lark+W3C `set` treated like `push` (if/else needs two `endif`) → resolved (fix-emit-queue): `set` in a pushed context now ends the block and embeds the target's block (tools/emit/flow.py `CLOSED` forms); tests/emit/test_flow.py `if-else*`.
- activity3 / Lark+W3C multiline `end` line cannot be indented → resolved (fix-emit-queue): `_WS?` before the end part, trailing blanks from the line wrapper; test_flow `indented-multiline-end`.
- state / Lark requires the pop line of a context entered without `require_pop` → resolved (fix-emit-queue): an unclosed push is a `TAIL` spine (last line only) instead of the optional-pop superset, so the closer negatives stay rejected and `grp {` + foreign line still fails; `require_pop` pushes keep a mandatory pop; test_flow `grp-*`, `strict-*`.
- state / Lark multiline `end` line cannot be indented (second failing case) → resolved with the activity3 end-line entry above.
- state / Lark terminal alternation where a later alternative extends an earlier one → resolved (fix-emit-queue): `prefer_longest` now lifts any alternative that starts with the text of an earlier one in every alternation, nested groups and top level included (tools/emit/lark_regex.py `lift_prefixed`); tests/emit/test_lark_regex.py.
- description / Lark trailing whitespace after a multiline, bracket or pushing first line → resolved (fix-emit-queue): `_WS?` before the first line's `_NL` for bracket, multiline/end and transition commands; test_flow `trailing-space-*`.
- timing / Lark set/push into a context without pop as the last line → resolved (fix-emit-queue): blocks are newline-led (`(_NL line?)*`), so an empty block needs no extra line; contexts no `pop` can reach are spine-only; test_flow `mode-last-line`, `orphan-*`. Also: a `set` from `main` continues with the target's root form (rest of the block); `pop` entries in `main` stay dropped (family models shadow them with `reject`, which emitters cannot express).
- toy_class (tests/emit/fixtures/toy) now sets `require_pop: true` on CommandPackage, since unclosed pushes are accepted otherwise.

## gantt: `JAVA_INT_RANGE` lists its shortest alternative first, so Lark cannot reach 10-digit ints mid-line

Owner: `model/diagrams/common.yaml` (common family). Found by T24 (gantt) fixtures.
Lark's dynamic lexer takes one `regex.match` per terminal and only retries shorter
prefixes of it (`.agent-notes/fix-lark.md`), so `(?:[1-9][0-9]{0,8}|1[0-9]{9}|...)`
yields the 9-digit prefix of `2147483647` and the 10-digit alternatives are never
tried. At the end of a line the emitter's tail lookahead hides it; mid-line it is a
Lark false reject (`tools/emit/lark_regex.py` `lift_prefixed` only lifts alternatives
that start with an earlier one's text). The interpreter is unaffected (fullmatch).
Longest first keeps the language and fixes Lark:
```diff
--- a/model/diagrams/common.yaml
+++ b/model/diagrams/common.yaml
@@ variables:
   JAVA_INT_RANGE:
-    regex: "(?:[1-9][0-9]{0,8}|1[0-9]{9}|20[0-9]{8}|21[0-3][0-9]{7}|214[0-6][0-9]{6}|2147[0-3][0-9]{5}|21474[0-7][0-9]{4}|214748[0-2][0-9]{3}|2147483[0-5][0-9]{2}|21474836[0-3][0-9]|214748364[0-7])"
+    regex: "(?:1[0-9]{9}|20[0-9]{8}|21[0-3][0-9]{7}|214[0-6][0-9]{6}|2147[0-3][0-9]{5}|21474[0-7][0-9]{4}|214748[0-2][0-9]{3}|2147483[0-5][0-9]{2}|21474836[0-3][0-9]|214748364[0-7]|[1-9][0-9]{0,8})"
```
Failing cases (jar and interpreter accept, Lark rejects; all pass with the diff in a
scratch build, and `2147483648` stays rejected):
- `@startgantt` / `page 2147483647x1` / `@endgantt` (common CommandPage)
- `@startgantt` / `print between D+2147483647 and D+1` / `@endgantt` (gantt-dates
  GD_COUNT_OK refs JAVA_INT; tests/fixtures/gantt/pos/print-between.puml line 4)

## gantt: final-state check "a separator or group needs a real task" (non-blocking, contract)

Owner: contract (`model/schema.json`, `docs/grammar-guide.md`, `tools/interp/engine.py`,
`tools/interp/rules.py`). No corpus case today; pinned by strict-xfail fixtures
`tests/fixtures/gantt/gap/{separator-only,separator-bare-only,group-only}.puml`.
Upstream: separators and groups enter the task map, `TimeBoundsData.initMinMax` skips
them (gantt/data/TimeBoundsData.java:131-142), so with no real task `maxDay` stays null,
`durationInDays` (:155) throws `NullPointerException: temporal`, `checkFinalError` does
not catch it (gantt/GanttDiagram.java:172-181) and PSystemBuilder.java:275-280 reports
the crash at the end of the block. It does not matter whether the task comes before or
after the separator, and a task created inside a group counts, so a context stack
cannot express it (a pop restores the frame below, which was fixed at push time).
Proposal: monotone, order-free diagram flags. Entry keys `gives: <flag>` and
`needs: <flag>`; at the end of the body the attempt fails at the end line when a matched
entry `needs` a flag no matched entry `gives`. Gantt would set `needs: real_task` on the
separator/group heads and `gives: real_task` on CommandGanttArrow2 and (T25) task
sentences. The same shape closes `.agent-notes/T17.md` (participant-less sequence).
```diff
--- a/tools/interp/rules.py
+++ b/tools/interp/rules.py
@@ class Rule:
     require_pop: bool = False
     reject: bool = False
+    gives: str = ""
+    needs: str = ""
@@ def build_rule(entry: Entry) -> Rule:
         bool(entry.get("require_pop")),
         bool(entry.get("reject")),
+        entry.get("gives", ""),
+        entry.get("needs", ""),
     )
--- a/tools/interp/engine.py
+++ b/tools/interp/engine.py
@@ class _Resume:
     index: int
     stack: tuple[str, ...]
     next_rule: int
+    matched: tuple[Rule, ...]  # rules matched before the push, restored on backtrack
@@ def _run(...)
-            if i >= len(body):
+            if i >= len(body):
                 pending = next((f for f in frames if f is not None), None)
-                if pending is None:
-                    return None
+                if pending is None:
+                    missing = {r.needs for r in matched} - {r.gives for r in matched} - {""}
+                    return len(body) if missing else None  # fails at the end line
```
(`_attempt` must map index `len(body)` to `block.end` for the failure line. `matched` is the list of rules applied so far; `_track` snapshots it into `_Resume` and
a backtrack truncates it. Emitters ignore both keys; the schema adds them as optional
strings on entries and in `overrides`.)

## mindmap-wbs: match `SingleLineCommand2(doTrim=false)` commands against the untrimmed line (non-blocking, contract + extractor)

Owner: contract (`model/schema.json`, `docs/grammar-guide.md`, `tools/interp/rules.py`)
and extractor/translator (`tools/extract`, `tools/translate`). Upstream:
`SingleLineCommand2(boolean doTrim, ...)` matches `lines.getFirst()` untrimmed when
`doTrim` is false (command/SingleLineCommand2.java:69-81, :93, :102). At 97a5992 that is
24 commands (`git grep 'super(false, '`): board CommandBoardPlus, 11 chart commands,
CommandMindMapOrgmode, CommandMindMapPlus, salt CommandAnything, CommandWBSItemNew,
CommandWBSItemOld and 7 wire commands. The interpreter always matches `Line.trimmed`
(tools/interp/rules.py:41), so leading and trailing blanks are invisible.
Failing cases (strict-xfail fixtures, jar rejects, interpreter accepts):
* `tests/fixtures/mindmap-wbs/gap/mindmap-indented-plus.puml` (`  ++ b`: `^([+-]+)`
  fails on the untrimmed line, no command matches);
* `tests/fixtures/mindmap-wbs/gap/wbs-pseudo-trailing-blank.puml` (`**_ `: the trailing
  blank matches no item command).
It is also the prerequisite for any indentation-aware tree check in mindmap/WBS
(getSmartLevel counts leading blanks, mindmap/MindMapDiagram.java:136-157,
wbs/WBSDiagram.java:187-208): pdiff FAs cupuri-11-piru303, fogari-75-febu345,
sipuja-30-deto581, input/WBS-monoline-def-0.puml#3 (reports/classify/mindmap-wbs.yaml).
Proposal: optional entry key `trim: false` (`single` only; also allowed in `overrides`),
emitted by the translator for commands whose `doTrim` field is false; emitters may
ignore it (an approximation each emitter docstring would document).
```diff
--- a/tools/interp/rules.py
+++ b/tools/interp/rules.py
@@ class Rule:
     require_pop: bool = False
     reject: bool = False
+    untrimmed: bool = False
@@ def advance(self, body: list[Line], i: int, deadline: Deadline) -> int | None:
-        if not deadline.fullmatch(self.start, body[i].trimmed):
+        line = body[i].text if self.untrimmed else body[i].trimmed
+        if not deadline.fullmatch(self.start, line):
             return None
@@ def build_rule(entry: Entry) -> Rule:
         bool(entry.get("require_pop")),
         bool(entry.get("reject")),
+        entry.get("trim") is False,
     )
```
Schema: `"trim": {"const": false}` on entries and override patches, valid only with
`kind: single`. Extractor: record `SingleLineCommand2.doTrim` (read from the declaring
class, see .agent-notes/T02.md). Until it lands, mindmap-wbs keeps these as gaps.
- gantt / JAVA_INT_RANGE longest-first → applied by the orchestrator (T24 commit).
- gantt / gives-needs final-state flags → adopted as a contract change (delegated).

## activity3: interpreter-only state heads double Lark derivations (non-blocking, contract)
T21b models the swimlane strategy (ActivityDiagram3.java:80-95, a diagram-wide flag) with
head copies of the deciding commands that `set` the top level from undecided (`a3_main`)
to `a3_nolanes_main` (model/diagrams/activity3-structure-lanes.yaml). The interpreter takes
the copy first; Lark (unordered) keeps both the generated rule (stay) and the copy (exit
into another root form) at every deciding line, so one root form per deciding line stays
alive to the end of the block. Measured on plantuml-ts blocks (oracle-preprocessed text,
same tools/ state, grammar from model/ with vs without the lanes heads): cakeca-72-kara622
1.5 s -> 3.2 s, judatu-15-xize591 16.4 s -> 19.5 s, lidumi-54-moza355 7.3 s -> 8.0 s.
Emitters cannot express the strategy anyway (rejects are dropped), so the heads only cost.
Proposal: optional entry key `emit: false` (also in `insert_*` entries and `overrides`):
emitters drop the entry like a `reject` (they keep the generated rules, which accept the
same lines). activity3-structure-lanes would set it on its 11 `a3_lanes_decide` heads and
`Activity3SplitEndTop`.
```diff
--- a/tools/emit/skip.py
+++ b/tools/emit/skip.py
@@
 JOIN_KEY = "join"
 REJECT_KEY = "reject"
+EMIT_KEY = "emit"
@@ def skipped(entry: Entry) -> bool:
     """True when emitters must drop the command ``entry``."""
-    if entry.get(REJECT_KEY):
+    if entry.get(REJECT_KEY) or entry.get(EMIT_KEY) is False:
         return True
```
Schema (model/schema.json): `"emit": {"const": false}` beside `reject` on entries, and
`"emit": {"oneOf": [{"type": "null"}, {"const": false}]}` in override patches; guide:
one row in the Keys table ("interpreter-only entry; emitters drop it").

## contract: resolution of gantt final-state flags and mindmap-wbs untrimmed matching (2026-10-15)

* gantt / final-state check "a separator or group needs a real task": implemented as `gives: <flag>` / `needs: <flag>` (schema, guide section "Diagram flags and untrimmed matching", `tools/interp/{rules,engine}.py`). The failure is reported at the block's `@end` line. Family models may now use the keys; the strict-xfail fixtures `tests/fixtures/gantt/gap/{separator-only,separator-bare-only,group-only}.puml` become fixable. Emitters ignore both keys (docstring sentence queued for `fix-emit-queue`: "`gives`/`needs` (diagram flags, final-state checks) are ignored.").
* mindmap-wbs / `SingleLineCommand2(doTrim=false)`: implemented as `trim: false` (schema, interpreter matches `Line.text`, extractor records `doTrim`, translator emits `trim: false`, `extracted/` and `model/generated/` regenerated). 23 classes / 25 entries carry it. The gap fixtures `mindmap-indented-plus` and `wbs-pseudo-trailing-blank` are now rejected by the interpreter, as by the jar. Emitters ignore the key (docstring sentence queued: "`trim: false` is ignored; the emitted pattern is matched against the trimmed line.").
* activity3 / interpreter-only state heads: implemented as entry key `emit: false` (schema entries, patches and inserts; guide Keys row; `tools/emit/skip.py` `skipped()`), dropped by all emitters like `reject`. No family model uses it yet; T21b adopts it.

## gantt: second use for the gives/needs flags (addendum to the final-state entry above)

Non-blocking; no change beyond that entry. "No starting date for the project": an absolute
`starts`/`ends` task phrase fails unless a `project starts` came first
(gantt/lang/SubjectTask.java:105-107, :172-173, :262-263, :305-306). `project starts` is only
legal before any task-like entry (GanttDiagram.java:340-346, modeled as a reject in
gantt-sentences), so an order-free flag is exact: `gives: project_start` on
NaturalGanttGantt, `needs: project_start` on a task sentence entry whose committed phrase is
an absolute `starts`/`ends` (split from NaturalGanttTask). Failing cases: pdiff
dbhum/f_ob/fobeda-14-tori503.puml#0, dbhum/f_ur/furubu-23-mecu777.puml#0 (classified `bug`
in reports/classify/gantt.yaml) and tests/fixtures/gantt/sentences/gap/no-start-date.puml.

## salt: translate Java `.` as `[^\n\r\x85  ]` (non-blocking, translator)

Java compiles every IRegex pattern without DOTALL/UNIX_LINES (regex/Pattern2.java:114), so
`.` refuses U+0085, U+2028 and U+2029, and `$` also matches before a final one; commands
are matched with find() (regex/RegexComposed.java:112-118). The translator copies `.`
verbatim, and Python's `.` matches those three characters, so every generated `.` slot
accepts lines the jar rejects. Oracle-verified on salt: `title a<U+2028>b` is rejected by the
jar (CommandTitle and CommandAnything both fail) and accepted by the interpreter
(tests/fixtures/salt/gap/title-line-separator.puml, strict xfail). salt.yaml already guards
its own CommandAnything override (SALT_JAVA_LINE); a lone or trailing U+2028 is accepted
by both. No corpus block contains these characters, so no parity number changes.
Proposed diff (tools/translate/macros.py; the class is written with literal characters,
since `\u` escapes are a load error):
```diff
+JAVA_DOT = "[^\n\r\x85  ]"  # java.util.regex `.` without DOTALL/UNIX_LINES
+
+def java_dot(pattern: str) -> str:
+    """Rewrite each unescaped `.` outside a bracket class as Java's line-bounded dot."""
+    return "".join(JAVA_DOT if tok == "." else tok for tok in _TOKEN.findall(pattern))
+
 def portable(pattern: str) -> str:
     """``expand`` followed by the Java-only syntax rewrites (currently ``\\Q...\\E``)."""
-    return convert_quotes(expand(pattern))
+    return java_dot(convert_quotes(expand(pattern)))
```
Then regenerate `model/generated/`. Emitters already line-bound every terminal, so they are
unaffected; the TextMate/W3C regex printers must accept the literal characters.

## json: do not glue `{{ ... }}` units in joins of non-command factories (non-blocking, interpreter)

`tools/interp/scan.py` `scan_join` (and `scan_multiline`) step through units built by
`unit_end`, which glues a `{{` line and everything up to its `}}` into one unit
(PSystemCommandFactory.java:288-307). That rule belongs to command factories only.
JsonDiagramFactory/StyleExtractor (jsondiagram/StyleExtractor.java:63-101) read plain
lines, so a `{{` line inside a `<style>` region of a `@startjson` block makes the
`JsonStyleError` join (model/diagrams/json.yaml) unable to stop at `</style>`, and the
interpreter accepts a region the jar rejects. Failing case (strict xfail):
tests/fixtures/json/gap/style-error-with-embedded-open.puml (jar: IllegalStateException
COLON, rejected; interpreter: accepted). No corpus block is affected.
Proposed diff: let a rule skip the gluing when its model's factory is not a
`PSystemCommandFactory` subclass (the 24 factories whose `extracted/*.json` has the
`opaque-no-regex-field` unreachable entry), e.g.
```diff
-def scan_join(start, max_lines, body, i, deadline):
+def scan_join(start, max_lines, body, i, deadline, glue_units=True):
     j = i
     for _ in range(max_lines + 1):
         if j >= len(body):
             return None
-        j = unit_end(body, j)
+        j = unit_end(body, j) if glue_units else j + 1
```
with `Rule.advance` passing `glue_units=False` for rules of such models (the resolver
knows each diagram model's `factory`).

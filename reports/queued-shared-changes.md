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

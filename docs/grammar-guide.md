# Grammar guide

The canonical artifact of this repository is the YAML command model under `model/`.
Everything else (TextMate, Sublime, Lark/EBNF) is generated from it. This guide defines
the model format (contract I2), naming conventions and the layers. Machine-readable
shape: `model/schema.json` (JSON Schema 2020-12, `additionalProperties: false`
everywhere). Vocabulary is borrowed from
[sublime-syntax](https://www.sublimetext.com/docs/syntax.html).

## Model format

One model per file: `model/**/*.yaml`. The loader walks the tree recursively and ignores
`schema.json`.

```yaml
schema_version: 1
id: class
layer: diagram
diagram: CLASS
include: [shared, creole]
variables:
  COLOR: {regex: "#\\w+"}
contexts:
  main:
    - command: CommandCreateClass
      provenance: {class: net.sourceforge.plantuml.classdiagram.command.CommandCreateClass,
                   file: src/main/java/.../CommandCreateClass.java, line: 123, engine: IRegex}
      kind: single
      parts:
        seq:
          - {literal: class, ci: true}
          - {regex: "\\s+"}
          - {ref: COLOR}
      push: class_body
    - include: common_commands
```

### Keys

| Key | Where | Meaning | sublime-syntax |
|---|---|---|---|
| `schema_version` | top | Always `1`. | none (added) |
| `id` | top | Unique model id; must equal the file stem. | none (a syntax is identified by its file) |
| `layer` | top | `document`, `preproc`, `diagram` or `shared` (see Layers). | none (added) |
| `diagram` | top | Upstream `DiagramType` name. Required when `layer: diagram`, forbidden otherwise. | none (added) |
| `include` | top | List of model ids whose variables and contexts become visible. | `extends` (inherit contexts) |
| `variables` | top | Map `UPPER_SNAKE` name to a Part. | `variables` (there: name to regex string) |
| `contexts` | top | Map `snake_case` name to an ordered list of entries. Order is the upstream `initCommandsList` order and is significant. | `contexts` |
| `overrides` | top (`diagram`, `shared`) | Map key to a partial entry, shallow-merged over each matching entry of the resolved model (see "Refining generated models"). | none (added) |
| `insert_before` / `insert_after` | top (`diagram`, `shared`) | Map key to a list of full entries inserted immediately before / after each matching entry. | none (added) |
| `include: NAME` | entry | Splice another context in place (rules below). | `include` |
| `command` | entry | Upstream `Command` simple class name; also the rule id. | none (added; a rule has no id) |
| `provenance` | entry | Where the rule comes from: `class` (FQCN, required), `file`, `line` (pinned upstream sha), `engine` (`IRegex` or `UBrex`), `also` (see below). | none (added) |
| `kind` | entry | `single`, `multiline`, `multiline-bracket` or `opaque` (see "Multiline kinds"). | none (added) |
| `parts` | entry | The Part matched by the command's first line. | `match` |
| `end` | entry | Part closing a `multiline` command. Forbidden for every other kind. | `escape` / pop-rule `match` (closest) |
| `join: {max_lines: N}` | entry | `multiline` only, instead of `end`: the lines are joined and re-matched against `parts` (see below). | none (added) |
| `push` | entry | Context to enter after matching. | `push` |
| `pop: true` | entry | Leave the current context. | `pop` |
| `set` | entry | Replace the current context by the named one. | `set` |
| `provenance.also: [str]` | entry | Optional extra `path:line` (or `path:first-last`) citations at the pin, each matching `^src/main/java/.+\.java:\d+(-\d+)?$`. The loader checks the pattern only; a corpus test checks that every citation in `model/` resolves at 97a5992. | none (added) |
| `require_pop: true` | entry | Only with `push` (also allowed in `overrides`): ending the block while the pushed frame is still open skips the command, so the interpreter backtracks to the pushing line (see "Unterminated bodies and rejected lines"). | none (added) |
| `reject: true` | entry | `single` only, no `push`/`pop`/`set` (also allowed in `insert_before`/`insert_after` entries and `overrides`): when the entry is selected the attempt fails at that line (mirrors `CommandExecutionResult.error`). Emitters drop the entry. | none (added) |
| `refined_by` | entry | Id of the model whose `overrides` changed this entry; set by the resolver, never hand-written. | none (added) |

### Multiline kinds

Mirrors `command/PSystemCommandFactory.java:268-307` (`isMultilineCommandOk`) at 97a5992.
Every consumer (interpreter, emitters) must implement these exactly as written here.

| Kind | First line | Completion |
|---|---|---|
| `single` | `parts` matches the whole trimmed line. | That line. |
| `multiline` + `end` | `parts` matches. | First later line whose trimmed text fully matches `end` (`CommandMultilines2.java:79-110`). |
| `multiline` + `join` | (lines joined) | Lines `1..k` (k ≤ `max_lines`+1) joined with U+E100 (`utils/BlocLines.java:296`, `jaws/Jaws.java:47`) fully match `parts`; the smallest such k wins (`CommandDecoratorMultine.java:77-93`, cap at `PSystemCommandFactory.java:281`). k = 1 is the single-line case. |
| `multiline-bracket` | `parts` matches (it ends in `{`). | Bracket depth returns to 0: depth starts at 1, a trimmed line ending in `{` adds one, ending in `}` removes one (`CommandMultilinesBracket.java:64-96`). |
| `opaque` | `parts` matches. | Rest of the block (non-command factory). |

Emitters that cannot express a completion rule exactly (Lark, W3C, TextMate) approximate
it and document the approximation in their module docstring: `join` as a single line;
bracket depth as a body closed by a line `\s*\}`.

### Unterminated bodies and rejected lines (`require_pop`, `reject`)

**`require_pop: true`.** Mirrors `PSystemCommandFactory.getCandidate`
(`command/PSystemCommandFactory.java:223-247`, `isMultilineCommandOk` at `:268-286`): a
multiline command whose end never arrives returns `null` and the factory does `continue`,
trying the *next* command for the same start line; only when none matches does the start line
fail (`:169-175`). A model that enters a body as a context (`push`) cannot say that the body
must close, so `require_pop` marks the pushing entry. Interpreter semantics:

* When the block ends while a `require_pop` frame is still on the stack, the interpreter
  backtracks to the **outermost** still-open `require_pop` push (upstream's outer scan
  swallows the inner lines, so an inner command never starts), restores the stack as it was
  before that push, and resumes **at the pushing line with the rules after the pushing
  rule** in the same context.
* If no later rule matches the pushing line, the attempt fails at the pushing line.
* Frames closed by `pop` before the block ends are final, and a body line no rule accepts
  still fails at that line (no backtracking): only the end of the block triggers it.
* Lark, W3C and TextMate already require the closing line of a pushed context; they ignore
  the key.

**`reject: true`.** Mirrors `CommandExecutionResult.error` -> `EXECUTION_ERROR`
(`PSystemCommandFactory.java:180-187`): the command's regex matched, so the factory fails
and no later command is tried. An entry with `reject` makes the attempt fail at its line
when it is the first match in context order, so it must precede the entries it shadows
(typically via `insert_before` the unnarrowed generated rule). Lark, W3C and TextMate drop
`reject` entries and also skip `join` entries whose `parts` need U+E100 on every path
(they can never match one line, see each emitter's docstring).

### Case sensitivity

Upstream compiles every IRegex command through `Pattern2` with `CASE_INSENSITIVE`
(`regex/Pattern2.java:114`), so generated regex Parts of such commands carry `ci: true`.
Plain `java.util.regex.Pattern` patterns (some non-command factories) are
case-sensitive and carry no `ci`. Hand-written models state `ci` explicitly where needed.

`push`, `pop` and `set` are mutually exclusive. `push`/`set` targets must name a context
visible from the model.

### Parts

A Part is exactly one of:

| Form | Meaning | sublime-syntax |
|---|---|---|
| `{seq: [Part]}` | Sequence. | concatenation inside a regex |
| `{alt: [Part]}` | Ordered alternatives. | `a\|b` |
| `{opt: Part}` / `{star: Part}` / `{plus: Part}` | `?`, `*`, `+`. | `?`, `*`, `+` |
| `{ref: VAR}` | Use a variable. Inlined by the resolver. | `{{VAR}}` interpolation |
| `{regex: str, ci?: bool, name?: str, scope?: str}` | A regex; `ci: true` = case-insensitive (absent = case-sensitive), `name` labels the capture, `scope` is a TextMate scope. | `match` + `scope` / `captures` |
| `{literal: str, ci: bool, scope?: str}` | Fixed text; `ci` = case-insensitive. | literal `match` with `(?i)` |

Regex rules (checked by the loader):

* Regexes are **expanded**: the upstream `%`-macros `%pLN`, `%s`, `%q`, `%g`
  (`regex/Pattern2.java:54-59` at 97a5992) must not appear.
* Each regex compiles with the Python `regex` module (a superset of `re` in its default
  mode). `re` itself is not used because expanded `%pLN` contains `\p{L}\p{N}`.
  Oniguruma and PCRE compilation is checked by the emitter tasks.
* A `\uXXXX` escape inside a regex is a load error: PCRE2 rejects `\u`. Write the
  character itself (a YAML double-quoted `"\uE100"` is parsed to the literal character
  before the loader sees it, so it is fine; a regex that still contains a backslash followed
  by `u` after YAML parsing is not). `\\u` (escaped backslash, then `u`) is allowed.

### Include and ref semantics

* Model-level `include: [ids]` makes the included models' variables and contexts
  visible. Lookup order: the model itself, then its includes depth-first in listed order;
  the first definition wins, so a model overrides what it includes. The resolved model
  carries the merged contexts and variables, so `push`/`set` can name an included context.
* Entry `include: NAME` splices that context's entries at that position. NAME is tried
  as (1) a context visible from the model, (2) a model id, meaning that model's `main`
  context, and `MODEL#CONTEXT` addresses a specific context of a specific model. This
  mirrors sublime-syntax, where `include: ctx` is a context of the same file and
  `include: other.sublime-syntax` is the other file's `main`.
* `ref: VAR` is looked up lexically from the model that contains it (so a spliced
  entry keeps resolving against its defining model). A variable's value is itself a Part
  and may contain `ref`.
* Cycles are errors naming the path: `include cycle: A → B → A` (model ids, or
  `model.context` nodes for context splices) and `variable cycle: m.X → m.Y → m.X`.

### Diagram dispatch (`factory`, `start_map`)

Mirrors `PSystemBuilder.java:133-200` (factory order) and `:257-287` (try loop) at 97a5992.

* `factory: <SimpleName>` (diagram layer only) names the upstream `PSystemFactory` a
  diagram model implements. Generated models set it (`gen-class-diagram` →
  `ClassDiagramFactory`).
* `start_map: {<keyword>: [<factory>, …]}` (document layer only) maps a start keyword
  (`uml` for `@startuml`) to the factories tried for it, in `PSystemBuilder` order.
* For each factory the interpreter uses the **top** diagram model declaring it: the one
  no other model with the same `factory` includes (transitively). A hand-written family
  model therefore sets the same `factory` and `include`s the generated model it
  extends; it replaces the generated one in dispatch without editing `start_map`.
  Two top models for one factory is a load error.
* Keyword lookup mirrors `DiagramType.findStartTypes`: exact key, then a key that is a
  prefix of the keyword (`@startumlfoo` → `uml`). A keyword no key covers is
  `PSystemUnsupported` (`PSystemErrorUtils.java:58-59`, `PSystemBuilder.java:283-284`),
  which is not a `PSystemError`: the verdict is accepted with `diagram`/`model` `None`,
  as the oracle reports it.
* An explicit `start_map` argument to `accepts` overrides the document model; entries
  may name factories or model ids.
* Empty bodies: command factories reject a body with no non-blank line at the start
  line. A diagram model that accepts an empty body declares an `empty` context; the
  body's lines followed by the `@end` line run through it (`embedded-welcome`,
  `embedded-json`, …).
* `Verdict.diagram` is the accepting model's `diagram` (compare with the oracle's
  `diagram_type`, which is `null` for non-`TitledDiagram` results); `Verdict.model` is
  its id.

### Refining generated models (`overrides`, `insert_before`, `insert_after`)

A hand-written diagram model replaces its generated base in dispatch (see above) and
inherits the base's contexts, but must not edit `model/generated/**`. These three
model-level keys refine individual generated entries in place, keeping upstream order.
They are allowed on `layer: diagram` and `layer: shared` models only.

```yaml
overrides:        # key -> partial entry, shallow-merged over each matched entry
  CommandCreateClassMultilines: {push: class_body}
  CommandFootboxIgnored: {remove: true}   # drops the matched entry
insert_before:    # key -> [full entries] placed immediately before each matched entry
  CommandCreateClass: [{command: ..., provenance: ..., kind: single, parts: ...}]
insert_after:     # same, immediately after
  CommandNamespace: [...]
```

**Keys.** A key matches an entry when it equals the entry's `command` (rule id, e.g.
`CommandFactoryNote_1`) or the simple class name of `provenance.class` (the part after
the last `.`, with `$` replaced by `_`). A class-name key matches every repeat of that
class. Keys live in one id space for the whole resolved model: they apply in every
context, after entry-level `include` splices are expanded. Beware that a hand-written
entry whose `provenance.class` is the same class is matched by a class-name key too; use
the unique `command` id as key, or a different provenance class, to avoid that.

**Collection.** Patches are collected from the model and its transitive model-level
includes in resolver scope order, key by key: the model's own declaration of a key wins
over an included one and is used as is (partial entries are not merged across models). A
`layer: shared` model such as `common` can therefore carry refinements for common
commands that apply to every diagram model including it. A shared model's patches never
apply to the shared model itself. `refs` inside patch entries resolve in the scope of the
model that declared them; `push`/`set` targets must be visible from the model being
resolved.

**Order of application.** Removes, then overrides, then `insert_before`/`insert_after`.
Inserted entries are not matched by overrides. Several inserts on one entry keep
declaration order. An insert key matching a removed entry is an error.

**Merge semantics.**

* The override's keys replace the entry's keys wholesale (`parts` is replaced, not merged).
  `command` and `provenance` are kept unless the override sets them.
* `null` deletes a key: `pop: null`, `push: null`, `set: null`, `end: null`, `join: null`.
  Needed to switch transition kind or turn a `multiline` into a `single`
  (`{kind: single, end: null}`).
* `remove: true` must be the only key of its patch.
* The merged entry gets `refined_by: <model id>` (the declaring model; the last one when
  several keys match) so provenance stays honest.
* The merged entry is validated against the entry schema: `push`/`pop`/`set` stay
  mutually exclusive, `multiline` still needs exactly one of `end`/`join`, `end`/`join`
  stay forbidden for the other kinds. Replacing `pop: true` by a `push` therefore needs
  `pop: null` in the same override.

**Errors** (all carry the declaring file and a JSON pointer such as
`/overrides/CommandCreateClassMultilines`):

* a key matching no entry in a diagram model that collects it, unless the winning
  declaration comes from an included `layer: shared` model (common commands are absent
  from some factories);
* a merged entry that violates the entry schema, or an unknown `push`/`set` context;
* an insert relative to a removed entry.

The loader also regex-checks `parts`/`end` inside patches. `Model` carries `overrides`,
`insert_before` and `insert_after` verbatim; `ResolvedModel` contexts already contain
the result.

Worked example, `model/diagrams/class.yaml`. It extends the generated class diagram and
the shared `common` model, refines two generated entries and adds one hand-written rule
before `CommandCreateClass`:

```yaml
schema_version: 1
id: class
layer: diagram
diagram: CLASS
factory: ClassDiagramFactory
include: [gen-class-diagram, common]    # generated `main` is inherited via the include

variables:
  COMMENT_LINE: {regex: "'.*", ci: false}

overrides:
  # 1. Enter the class body context instead of scanning for a closing line.
  CommandCreateClassMultilines:
    kind: single
    end: null                           # a single forbids `end`
    push: class_body
  # 2. This factory never reaches the footbox command.
  CommandFootboxIgnored: {remove: true}

insert_before:
  CommandCreateClass:                   # lands directly before the generated rule
    - command: CommandClassBlockComment
      provenance:
        class: net.sourceforge.plantuml.cucadiagram.BodierLikeClassOrObject
        file: src/main/java/net/sourceforge/plantuml/cucadiagram/BodierLikeClassOrObject.java
      kind: single
      parts: {ref: COMMENT_LINE}        # resolved in this model's scope

contexts:
  class_body:                           # visible to the `push` above
    - command: CommandClassBodyClose
      provenance: {class: net.sourceforge.plantuml.cucadiagram.BodierLikeClassOrObject}
      kind: single
      parts: {regex: "^\\s*\\}\\s*$"}
      pop: true
```

In the resolved `class` model `main` keeps the upstream order of `gen-class-diagram`
without `CommandFootboxIgnored`, `CommandClassBlockComment` sits right before
`CommandCreateClass`, and `CommandCreateClassMultilines` reads `kind: single`,
`push: class_body`, `refined_by: class`.

### Ids and files

`id` equals the file stem and must be unique across the whole tree: files under
`model/generated/` are identified by stem only (no directory prefix), so generated and
hand-written models share one global id namespace. Duplicates are reported with both
paths.

### Loading API

```python
from tools.model.load import load_dir  # load_dir(path) -> dict[str, Model]
from tools.model.resolve import resolve  # resolve(models) -> ResolvedModels
```

`python -m tools.model.load --check model/` exits non-zero on any error (schema
violation with file and JSON pointer, unexpanded macro, uncompilable regex, id/stem
mismatch, duplicate id, unknown include/ref/push target, cycle).

* `Model` (frozen dataclass): `id`, `layer`, `path`, `diagram`, `include`, `variables`,
  `contexts`, `factory` (str or None), `start_map` (dict keyword → list of factory
  names; empty unless `layer: document`). Parts and entries are plain dicts exactly as
  in the YAML.
* `ResolvedModels = dict[str, ResolvedModel]`; `ResolvedModel` has `id`, `layer`, `path`,
  `diagram`, `variables`, `contexts`, `factory`, `start_map`, `includes` (tuple of the
  transitive model-level include ids, depth-first, deduplicated), with no
  `include`/`ref` inside contexts or variables. `top_models(resolved) -> dict[factory,
  id]` (`tools.model.resolve`) gives the top model per factory; `resolve()` calls it, so
  two top models for one factory raise `ModelError` and fail `load --check`. Walk Parts
  recursively over the keys `seq`/`alt` (lists), `opt`/`star`/`plus` (single Part),
  and the leaves `regex`/`literal`. Resolved structures may share sub-objects: treat as
  read-only.
* `ModelError` carries `file`, `pointer`, `message`; `load_dir` raises `ModelLoadError`
  with `.errors` listing all of them.

## Naming conventions

* **Rule ids** are the upstream `Command` simple class names (`CommandCreateClass`) in
  the `command` key.
* **Variables** are `UPPER_SNAKE` (`COLOR`, `ARROW_BODY`).
* **Contexts** are `snake_case` (`main`, `class_body`). `main` is the entry context.
* **Model ids** are file stems: letters, digits, `_`, `-`.
* **Scopes** follow the
  [TextMate naming conventions](https://macromates.com/manual/en/language_grammars#naming_conventions)
  (`keyword.control`, `entity.name.type`, `string.quoted`, `comment.line`, ...) with the
  `.plantuml` suffix applied by the emitters, not in the model.

## Layers

Decision D3 splits PlantUML syntax into layers, each a set of models:

| Layer | Content |
|---|---|
| `document` | `@start*`/`@end*` framing and block detection. |
| `preproc` | Preprocessor directives (`!include`, `!define`, `!if`, ...). |
| `diagram` | One model per diagram type; `diagram` names the upstream `DiagramType`. |
| `shared` | Pieces reused by several models (colors, creole, arrows). |

**Raw mode (L1 hook).** `accepts(models, block, raw=True)` takes an unpreprocessed
block: if a `layer: preproc` model exists, every body line (after comment removal) is
first offered to it, with its own context stack starting at `main`; kinds, `multiline`,
`join`, `push`/`pop`/`set` behave exactly as for diagram rules. Matched lines are
consumed; the remaining lines form the body the diagram models see. Upstream
preprocesses the whole block before any factory runs (`BlockUmlBuilder.java:95`), so
this filter runs once per block. A block whose non-blank lines are all consumed is an
empty body. With `raw=False` (default; L2 input is already preprocessed) the preproc
model is ignored.

## Troubleshooting

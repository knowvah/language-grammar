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
| `include: NAME` | entry | Splice another context in place (rules below). | `include` |
| `command` | entry | Upstream `Command` simple class name; also the rule id. | none (added; a rule has no id) |
| `provenance` | entry | Where the rule comes from: `class` (FQCN, required), `file`, `line` (pinned upstream sha), `engine` (`IRegex` or `UBrex`). | none (added) |
| `kind` | entry | `single`, `multiline`, `multiline-bracket` or `opaque` (see "Multiline kinds"). | none (added) |
| `parts` | entry | The Part matched by the command's first line. | `match` |
| `end` | entry | Part closing a `multiline` command. Forbidden for every other kind. | `escape` / pop-rule `match` (closest) |
| `join: {max_lines: N}` | entry | `multiline` only, instead of `end`: the lines are joined and re-matched against `parts` (see below). | none (added) |
| `push` | entry | Context to enter after matching. | `push` |
| `pop: true` | entry | Leave the current context. | `pop` |
| `set` | entry | Replace the current context by the named one. | `set` |

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
  `contexts` — Parts and entries are plain dicts exactly as in the YAML.
* `ResolvedModels = dict[str, ResolvedModel]`; `ResolvedModel` has `id`, `layer`, `path`,
  `diagram`, `variables`, `contexts`, with no `include`/`ref` anywhere. Walk Parts
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

## Troubleshooting

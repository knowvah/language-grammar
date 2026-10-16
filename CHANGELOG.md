# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Public contracts: the model schema
`schema_version`, `dist/` TextMate scope names, and top-level grammar rule names.

## [Unreleased]

### Fixed
- Lark and TextMate start terminals match a start keyword as a prefix, like
  `DiagramType.check`: `@startumlx` opens a `uml` block instead of being rejected (#7).
- Lark keeps zero-width guards (lookahead/lookbehind-only Parts such as `D_NOT_FORBIDDEN`):
  each is folded into the terminals around it (`tools/emit/guards.py`) instead of being
  emitted as an optional terminal Earley could skip (#3).

### Added
- TextMate frames a start word that no keyword covers (`@startjcckit`) as an opaque
  `meta.diagram.plantuml` block, like Lark's `block_other` (#8).

## [0.1.0] - 2026-10-15

First release of the command model and the grammars generated from it. Upstream pin:
PlantUML `97a5992201a7b1bc5d4063a81da609fe7387fede` (`1.2026.8beta1`).

### Added
- **Command model.** A YAML model of PlantUML syntax under `model/`, validated by
  `model/schema.json` (`schema_version: 1`, JSON Schema 2020-12, no unknown keys). Hand-written
  models (document framing, preprocessor surface, shared fragments, creole, 75 diagram
  models, 26 embedded ones) refine the models generated from upstream by `tools/extract`
  and `tools/translate` (`model/generated/`, 30 files, never edited by hand).
- **Generated grammars in `dist/`.** `dist/plantuml.lark` (Lark/Earley), `dist/plantuml.ebnf`
  (W3C EBNF, case-insensitive literals as `[Cc][Ll]...`, approximations marked `*_lossy`)
  and `dist/plantuml.tmLanguage.json` (TextMate, Oniguruma and PCRE compatible), built by
  `python -m tools.emit.build`; two builds are byte-identical.
- **Validation harness.** Oracle verdicts from the pinned jar, an ordered line-matching
  interpreter of the model with `java.util.regex` semantics, and a parity report per corpus
  (`reports/parity-*.json`, `.md`). Result: 0 false rejects on vega, plantuml-ts and pdiff;
  every false accept is classified (see `docs/semantic-gaps.md`).
- `docs/coverage.md` (every extracted command is modeled, partial or excluded with a reason),
  `docs/semantic-gaps.md`, `docs/grammar-guide.md`.
- Additive model keys introduced while modeling (all optional, schema version unchanged):
  regex `ci`; `join: {max_lines}` for joined multilines; top-level `factory` and document
  `start_map`; entry `require_pop`, `reject`, `emit: false`, `gives`/`needs` (diagram
  flags), `trim: false`; `provenance.also`; top-level `empty_needs_end`; model-level
  `overrides`, `insert_before`, `insert_after`.
- Python (uv), Node and Java tooling scaffold; upstream pin in `upstream-pin.json`.

### Removed
- **BREAKING:** `puml.ebnf` (hand-written Lark subset of component diagrams). It is
  superseded by the YAML command model in `model/`, from which `dist/plantuml.lark`,
  `dist/plantuml.ebnf` and `dist/plantuml.tmLanguage.json` are generated. The file
  remains available in git history.

### Public contracts
- **Model schema:** `schema_version: 1`. Keys may be added in minor versions; removing or
  re-meaning a key bumps the major version.
- **TextMate:** `scopeName` `source.plantuml`, file types `puml`, `plantuml`, `pu`, `iuml`,
  `wsd`. Every scope name ends in `.plantuml`. Framing scopes: `meta.diagram.plantuml`
  (a block), `keyword.control.start.plantuml` and `keyword.control.end.plantuml` (the
  `@start...`/`@end...` words), `comment.line.apostrophe.plantuml`,
  `comment.block.plantuml`. The other scope names are in `dist/plantuml.tmLanguage.json`
  (top-level groups: `keyword`, `punctuation`, `string`, `markup`, `entity`, `constant`,
  `variable`, `comment`, `meta`, `storage`, `support`). Generated class and sequence rules
  carry no scopes.
- **TextMate top-level rules** (repository): `comments`, `preprocessor` and one
  `diagram_<word>` per start word: `uml`, `board`, `files`, `git`, `hcl`, `yaml`, `gantt`,
  `project`, `json`, `creole`, `def`, `ebnf`, `regex`, `sprites`, `mindmap`, `wbs`, `bpm`,
  `chart`, `chen`, `flow`, `wire`, `nwdiag`, `packetdiag`, `salt`, `crash`, `ditaa`, `dot`,
  `latex`, `math`.
- **Lark:** start rule `start`; `block` and one `block_<word>` per start word above plus
  `block_other` (an `@start` word with no factory); terminals `START_<WORD>` and `END_BLOCK`.
- **W3C EBNF:** start production `plantuml`; productions `block`, `block_<word>`,
  `block_other`, `START_<WORD>`, `END_BLOCK`.
- Body rule names (`class_body`, `sequence_body_2`, ...) and generated terminal names are
  not contracts.

### Known limits
- `@startumlx`-style start words are rejected by Lark (no word boundary on `START_*`).
- TextMate has no block for an unknown start word; W3C and TextMate keep Java regex text.
- The `INSECURE` security profile (`PSystemPathFactory`) is not modeled.

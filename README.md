# language-grammar
Formal grammar definition for the PlantUML language, designed for syntax parsing, validation, and editor integration.

**Status:** release 0.1.0, built against PlantUML `97a5992` (`1.2026.8beta1`). See [CHANGELOG](CHANGELOG.md).

## Purpose
PlantUML has no grammar of its own: syntax is the ordered list of regular expressions in each
diagram factory's `Command` classes. This repository keeps that syntax as one YAML *command
model* and generates editor and parser grammars from it:

- `dist/plantuml.tmLanguage.json` - TextMate grammar (Oniguruma and PCRE compatible)
- `dist/plantuml.lark` - Lark (Earley) grammar
- `dist/plantuml.ebnf` - W3C EBNF, with approximations marked `*_lossy`

Correctness is measured against the real PlantUML jar: every `@start...@end` block of three
corpora is run through the jar, through an interpreter of the model, and (for a sample)
through the generated Lark grammar.

## Layout
| Path | Content |
|---|---|
| `model/` | Hand-written model (`document`, `preproc`, `shared`, `creole`, `diagrams/`, `embedded/`) and `schema.json`. |
| `model/generated/` | Models generated from the upstream sources. Never edit by hand. |
| `extracted/` | Raw command regex trees dumped from the jar by the Java extractor. |
| `dist/` | Generated grammars (committed; reproducible from `model/`). |
| `tools/` | Python tooling: `extract`, `translate`, `model` (loader), `interp`, `emit`, `validate`, `report`; Java harness in `tools/extract` and `tools/oracle`. |
| `reports/` | Parity reports per corpus (`parity-*.json`, `.md`, slices in `parity/`), classifications (`classify/`), queued shared changes. |
| `docs/` | [Grammar guide](docs/grammar-guide.md), [command coverage](docs/coverage.md), [semantic gaps](docs/semantic-gaps.md). |
| `tests/` | pytest suite and the `vscode-textmate` proof (`tests/textmate`). |

## Prerequisites
- `uv` (Python 3.11+, dependencies in `pyproject.toml`), Node and npm, Java 21 (`javac`, `java`).
- To regenerate or run parity (not needed to use `dist/`): the PlantUML jar built from the pinned
  commit, a PlantUML checkout containing it, and the corpora. Defaults, overridable by
  environment variable:

  | Variable | Default |
  |---|---|
  | `PLANTUML_JAR` | `~/git/knowvah/plantuml-ts/oracle/dist/stock/plantuml-stock-97a5992201a7b1bc5d4063a81da609fe7387fede.jar` |
  | `PLANTUML_SRC` | `~/git/plantuml` |
  | `CORPUS_VEGA` | `$PLANTUML_SRC/src/test/resources/vega` |
  | `CORPUS_PLANTUML_TS` | `~/git/knowvah/plantuml-ts/tests/corpus` |
  | `CORPUS_PDIFF` | `~/git/pdiff` |

  The jar and corpora are not part of this repository.

## Regenerate
Setup once: `uv sync && npm ci`.

```sh
uv run python -m tools.emit.build        # model/ -> dist/ (no jar needed)
```

After an upstream bump or a change to the extractor, the full chain is
`tools.extract.build`, `tools.extract.run`, `tools.translate.run`, `tools.model.load --check
model/`, `tools.emit.build`, parity; see "Regenerating after an upstream bump" in the
[grammar guide](docs/grammar-guide.md).

```sh
uv run python -m tools.report.coverage        # docs/coverage.md
uv run python -m tools.validate.parity --corpus all --lark sample --workers 4
uv run python -m tools.validate.parity merge --corpus all
uv run python -m tools.report.semantic_gaps   # docs/semantic-gaps.md
```

## Validate
These five gates must pass:

```sh
uv run pytest --cov=tools --cov-branch --cov-fail-under=90
uv run ruff check . && uv run ruff format --check .
npm test
uv run python -m tools.model.load --check model/
uv run python -m tools.extract.build
```

Without the jar and corpora, run `uv run pytest -m "not corpus"` for the tests that need no
external input.

## Objectives
- Build upon the excellent work from [vscode-plantuml](https://github.com/qjebbs/vscode-plantuml).
- Become the official source for the PlantUML syntax used by [GitHub Linguist](https://github.com/github-linguist/linguist/blob/main/vendor/README.md).
- Enable the maintenance of syntax definitions for multiple tools and platforms, such as:
  - **Visual Studio Code**: Improved syntax highlighting and parsing extensions.
  - **GitHub Linguist**: For accurate language detection and rendering on GitHub.
  - **JetBrains IDEs**: Syntax support for IntelliJ IDEA, PyCharm, etc.
  - **TextMate/Atom**: Legacy syntax definitions for these editors.
  - **Tree-sitter**: For modern syntax parsing in tools like Neovim.
  - **Sublime Text**: Updated syntax highlighting packages.
  - **ACE Editor**: Syntax highlighting support for this lightweight, embeddable code editor.
  - **Online editors**: Such as GitPod or web-based IDEs.
  - **Language servers (LSP)**: Providing advanced features like autocompletion and diagnostics.

## Status (0.1.0)
Command coverage (`docs/coverage.md`): 1,245 extracted commands: 1,228 modeled, 2 partial (the opaque `@startyaml` and `@starthcl` bodies, D4), 15 excluded with a reason, 0 missing. Egg (XOR-decoded, not regular) is excluded.

Parity with the jar, per corpus (interpreter FR/FA; Lark on a sample of up to 200 blocks per family):

| Corpus | Blocks | FR | FA | Lark checked | Lark agree | Lark disagree | Lark timeout (10 s) |
|---|---|---|---|---|---|---|---|
| vega | 301 | 0 | 0 | 301 | 298 | 3 | 0 |
| plantuml-ts | 4401 | 0 | 32 | 1273 | 1228 | 18 | 27 |
| pdiff | 5834 | 0 | 47 | 2234 | 2176 | 23 | 35 |

Lark agree = checked minus disagree minus timeout. FR = jar accepts, model rejects. FA = jar rejects, model accepts; all FA are classified
`semantic` (upstream checks that need state or lookups across lines, listed in
[semantic gaps](docs/semantic-gaps.md)). Test suite: 4,410 tests pass (1 skipped, 148 expected failures that pin known gaps), 99.3% line and branch coverage of `tools/` (gate: 90%).

Details: [grammar guide](docs/grammar-guide.md) (model format, regeneration, troubleshooting),
[command coverage](docs/coverage.md), [semantic gaps](docs/semantic-gaps.md),
[CHANGELOG](CHANGELOG.md). Known limits of the generated grammars are listed in the guide, section "Generated grammars".

## License
This project is licensed under the [MIT License](LICENSE).

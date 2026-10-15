# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Public contracts: the model schema
`schema_version`, `dist/` TextMate scope names, and top-level grammar rule names.

## [Unreleased]

### Removed
- **BREAKING:** `puml.ebnf` (hand-written Lark subset of component diagrams). It is
  superseded by the YAML command model in `model/`, from which `dist/plantuml.lark`,
  `dist/plantuml.ebnf` and `dist/plantuml.tmLanguage.json` are generated. The file
  remains available in git history.

### Added
- Python (uv), Node and Java tooling scaffold; upstream pin in `upstream-pin.json`.

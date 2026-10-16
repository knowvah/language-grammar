import { test } from "node:test";
import assert from "node:assert/strict";
import { REAL_MODEL_DIR, emitGrammar, loadGrammar, tokenize } from "./fixtures/helpers.mjs";

const grammar = await loadGrammar(emitGrammar(REAL_MODEL_DIR, "real-framing.tmLanguage.json"));
const BASE = new Set(["source.plantuml", "meta.diagram.plantuml"]);

function scopesAt(tokens, line, text) {
  const token = tokens.find((t) => t.line === line && t.text.includes(text));
  assert.ok(token, `no token containing ${JSON.stringify(text)} on line ${line}`);
  return token.scopes;
}

function extraScopes(scopes) {
  return scopes.filter((s) => !BASE.has(s));
}

test("EBNF body lines are scoped (CommandNope does not blank them)", () => {
  const tokens = tokenize(grammar, '@startebnf\nrule = "a" ;\n(* note *)\n@endebnf\n');
  assert.ok(extraScopes(scopesAt(tokens, 2, "rule")).length > 0, "rule name has no scope");
  assert.ok(scopesAt(tokens, 3, "note").some((s) => s.startsWith("comment")));
});

test("@startsprites opens a diagram block", () => {
  const tokens = tokenize(grammar, "@startsprites\nlistsprites\n@endsprites\nclass Z\n");
  assert.ok(scopesAt(tokens, 1, "@startsprites").includes("keyword.control.start.plantuml"));
  assert.ok(scopesAt(tokens, 2, "listsprites").includes("meta.diagram.plantuml"));
  assert.deepEqual(scopesAt(tokens, 4, "class"), ["source.plantuml"]);
});

test("any @end directive closes a block, like StartUtils.isEndDirective", () => {
  const tokens = tokenize(grammar, "@startuml\nclass A\n@endmindmap\nclass B\n");
  assert.ok(scopesAt(tokens, 3, "@end").includes("keyword.control.end.plantuml"));
  assert.deepEqual(scopesAt(tokens, 4, "class"), ["source.plantuml"]);
});

test("a backslash directive opens and closes a block", () => {
  const tokens = tokenize(grammar, "\\startuml\nclass A\n\\enduml\nclass B\n");
  assert.ok(scopesAt(tokens, 1, "startuml").includes("keyword.control.start.plantuml"));
  assert.deepEqual(scopesAt(tokens, 4, "class"), ["source.plantuml"]);
});

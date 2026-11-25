// Regression: API may sometimes return null instead of a list.
// Never let AI model lookup, connected accounts, or auto-post diagnostics
// show the generic 'Cannot read properties of null (reading map)' error.
"use strict";
const fs = require("node:fs");
const assert = require("node:assert/strict");
const vm = require("node:vm");

const html = fs.readFileSync("web/index.html", "utf8");
const inline = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
    .map(m => m[1]).filter(Boolean).join("\n");
new vm.Script(inline, {filename: "web/index.html"});
const match = inline.match(/const safeList = value => Array\.isArray\(value\) \? value : \[\];/);
assert.ok(match, "Expected reusable null-safe array utility");
const safeList = vm.runInNewContext(match[0] + "\nsafeList");
assert.equal(safeList(null).length, 0);
assert.equal(safeList(undefined).length, 0);
assert.equal(safeList({models: null}).length, 0);
assert.equal(safeList("bad").length, 0);
assert.equal(safeList([1, 2]).length, 2);
assert.equal(safeList(null).map(x => x).length, 0);

const patterns = [
  ['AI model suggestions', 'const models = safeList(r?.models);'],
  ['Saved models', 'safeList(k.models).join(", ")'],
  ['Providers dropdown', 'safeList(k.providers).map('],
  ['Creator navigation', 'safeList(S.creators).map('],
  ['Connected post accounts', 'safeList(S.accounts).map('],
  ['Recent posting diagnostics', 'const recent = safeList(d?.recent);'],
  ['Notifications', 'safeList(d.items).map('],
  ['Server sync accounts', 'S.accounts = safeList(accounts);'],
  ['Server sync creators', 'S.creators = safeList(creators);'],
];
for (const [name, source] of patterns) {
    assert.ok(inline.includes(source), name + " must use null-safe list");
    process.stdout.write("PASS " + name + " null-safety\n");
}
console.log("ALL PASSED (frontend nullable array checks)");

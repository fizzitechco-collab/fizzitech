"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const html = fs.readFileSync("web/index.html", "utf8");
const js = Array.from(html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g), m=>m[1]).join("\n");
new vm.Script(js, {filename:"web/index.html"});

assert.ok(html.includes('id="o_watch_more_enabled"'), "Normal clip Options switch missing");
assert.ok(html.includes('data-k="watch_more_enabled"'), "Creator Setup live default switch missing");
assert.ok(js.includes('watch_more_enabled:$("#o_watch_more_enabled")?.checked || false'),
          "Normal clip request must include switch state");
assert.ok(js.includes('localStorage.setItem("legend_watch_more_enabled"'),
          "Normal clip choice must persist between page visits");
assert.ok(html.includes('Watch more on #Creator #Platform'),
          "Show explicit meaning of end CTA to user");
assert.ok(js.includes('if (e.target?.id !== "o_creator") return;') &&
          js.includes('input.checked = !!selected?.watch_more_enabled;'),
          "Selecting a creator on Home must load that creator's CTA default");
assert.ok(html.includes('Requires "File under creator" selection'),
          "Creator identity must be selected instead of guessed");
console.log("ALL PASSED (normal clip CTA control, creator defaults, persisted options, JS syntax)");

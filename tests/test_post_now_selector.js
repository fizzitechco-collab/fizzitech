"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const html = fs.readFileSync("web/index.html", "utf8");
const selector = 'const accs = $$("#clipdlg [data-pacc]:checked").map(i => i.value);';
assert.ok(html.includes(selector), "Post now / Add to queue must select ALL checked account controls");
assert.ok(!html.includes('const accs = $("#clipdlg [data-pacc]:checked").map'), "Never map a single DOM element");
const helpers = [
  'const $ = (s, r = document) => r.querySelector(s);',
  'const $$ = (s, r = document) => [...r.querySelectorAll(s)];',
];
for (const x of helpers) assert.ok(html.includes(x), "Missing DOM selector helper");
const inputs = [{value:"ig_valid"}, {value:"yt_valid"}];
const document = {
  querySelector() { return inputs[0]; },
  querySelectorAll(selector) {
    assert.equal(selector, "#clipdlg [data-pacc]:checked");
    return inputs;
  }
};
const context = vm.createContext({document});
const selected = vm.runInContext(helpers.join("\n") + "\n" + selector + "\naccs", context);
assert.deepEqual(Array.from(selected), ["ig_valid", "yt_valid"]);
document.querySelectorAll = () => [];
const none = vm.runInContext(helpers.join("\n") + "\n" + selector + "\naccs", vm.createContext({document}));
assert.equal(none.length, 0, "No checked accounts should produce empty list, not crash");
console.log("ALL PASSED (Post now + queue account selection; 0 and 2 checked accounts)");

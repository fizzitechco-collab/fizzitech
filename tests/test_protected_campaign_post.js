"use strict";
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const html = fs.readFileSync("web/index.html", "utf8");
const matched = html.match(/function changedPostFields\(draft, clip\) \{[\s\S]*?\n\}/);
assert.ok(matched, "Missing campaign copy comparison helper");
const diff = vm.runInNewContext(matched[0] + "\nchangedPostFields");
const original = {
  title: "IShowSpeed x Expedia",
  description: "Travel moment\nDestination: Paris",
  hashtags: ["#IShowSpeed", "Expedia"]
};
const equivalent = {
  title: " IShowSpeed x Expedia ",
  description: "Travel moment\r\nDestination: Paris ",
  hashtags: ["IShowSpeed", "#Expedia"]
};
assert.deepEqual(Array.from(diff(equivalent, original)), []);
console.log("PASS formatting differences do not falsely mark approved campaign copy as changed");

const changed = {
  title: "Changed campaign title",
  description: "Different destination",
  hashtags: ["other"]
};
assert.deepEqual(Array.from(diff(changed, original)), ["title", "description", "hashtags"]);
console.log("PASS genuinely modified protected campaign fields are identified");

const unfilled = {title:null, description:null, hashtags:null};
assert.deepEqual(Array.from(diff({title:"", description:"", hashtags:[]}, unfilled)), []);
console.log("PASS missing legacy campaign metadata does not crash");

const handler = html.slice(html.indexOf('if (a === "postnow" || a === "postqueue") {'));
const protectedCheck = handler.indexOf("if (changed && protectedCampaign) {");
const askSaved = handler.indexOf('await ask("Use original saved campaign text?"');
const optOut = handler.indexOf("if (!approved) return;");
const originalRestore = handler.indexOf("const savedText = {title: clip.title");
const saveUnprotected = handler.indexOf("if (changed && !protectedCampaign) {");
const post = handler.indexOf('await send("/api/posts",');
assert.ok(protectedCheck >= 0 && protectedCheck < askSaved && askSaved < optOut
          && optOut < originalRestore && originalRestore < saveUnprotected
          && saveUnprotected < post, "Protected edits must prompt, preserve original and never change stored copy");
assert.ok(!handler.slice(0, post).includes('throw new Error("Protected campaign copy changed.'));
console.log("PASS protected campaign posting offers original approved copy without text overwrite/re-render");
assert.ok(handler.includes('a === "postnow" ? "Post original text" : "Queue original text"'),
          "Post now and Add to queue must both be supported");
console.log("ALL PASSED (protected campaign posting and confirmation checks)");

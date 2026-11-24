"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const html = fs.readFileSync("web/index.html", "utf8");
const js = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(x=>x[1]).join("\n");
new vm.Script(js, {filename:"web/index.html"});

for (const name of ["youtube", "instagram"])
  assert.ok(html.includes('data-schedule="' + name + '"'), "Missing " + name + " datetime-local input");
assert.ok(html.includes("type=\"datetime-local\""), "Schedule must let user choose date and time");
assert.ok(html.includes("Instagram is LOCAL:"), "Do not claim Instagram is remotely scheduled");
assert.ok(html.includes("YouTube scheduled"), "Home queue must show confirmed remote YouTube schedule");
assert.ok(html.includes("Instagram locally queued"), "Home queue must show Instagram local pending status");

const func = js.match(/function clipScheduleUTC\(platform\) \{[\s\S]*?\n\}/);
assert.ok(func, "Missing explicit timezone conversion for calendar values");
const form = {"youtube":"2026-12-05T11:30","instagram":""};
const document = {querySelector: key => ({value:form[key.includes("'youtube'")?"youtube":"instagram"]})};
const clipScheduleUTC = vm.runInNewContext(
  'const $ = selector => document.querySelector(selector);\n' + func[0] + '\nclipScheduleUTC',
  {document, Date, Number, Error}
);
const expect = new Date("2026-12-05T11:30").toISOString();
assert.equal(clipScheduleUTC("youtube"), expect, "The user's local datetime should become explicit UTC");
assert.equal(clipScheduleUTC("instagram"), null, "No chosen schedule must preserve ordinary queue behavior");
form.instagram = "invalid-date";
assert.throws(() => clipScheduleUTC("instagram"), /valid instagram schedule/);
assert.ok(js.includes("youtube_publish_at, instagram_publish_at"), "Both schedule dates must reach /api/posts");
assert.ok(js.includes('now:a === "postnow"'), "Post now must remain distinct from schedule");
assert.ok(js.includes("Post original text"), "Protected campaign copy still requires confirmation");
console.log("ALL PASSED (YouTube remote + Instagram local scheduling UI, UTC conversion, existing safety)");

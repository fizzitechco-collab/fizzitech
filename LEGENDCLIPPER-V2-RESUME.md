# LegendClipper V2 — !clipv2 resume context
Updated: 2026-11-24

## Core project
- Name: LegendClipper V2 (`!clipv2`) — customized fork of an older PeakCut release; do not confuse with `!clip`.
- Repository: https://github.com/fizzitechco-collab/fizzitech
- Active branch: `legend/facecam-preview-audio-repair`
- Pull request: https://github.com/fizzitechco-collab/fizzitech/pull/1
- Original PeakCut reference: https://github.com/haziqahmedqasmi/PeakCut
- Main PC Windows checkout: `D:\Clippers\PeakCut-main` (PowerShell, Python 3.11 virtual environment `.venv`).
- Local server port 8765; configured public tunnel: `https://runt-uncle-dumping.ngrok-free.dev`.

## User-confirmed status — do not revert to stale bug reports
- Dashboard V2, downloader/cleanup, previously broken YouTube clip download, facecam selector, and social auto-upload were completed.
- User reports current recording and clipping working well; preserve working flows and avoid rewrites without evidence.
- Prior 403/360p fallback errors were part of historical debugging and should not be called ongoing issues based on old logs.
- Stream clips use vertical layout with facecam selection over preview frame and centered gameplay; CTA can show source YouTube channel name.
- Features include YouTube/Instagram/TikTok connection workflows, manual clipping and AI/loudness clip detection.

## Recent feature branch additions
- Fixed facecam blob image preview CSP and JPEG validation.
- Progressive/on-demand audio scan in short sections with existing full-audio compatibility fallback.
- Early stopping at selected clip count (1 -> 1, 10 -> 10), MAX scans selected recording.
- Game-aware titles/hashtags helpers ported from upstream, while GTA6/Expedia custom campaign behavior preserved.
- Auto source-matched export quality up to 4K, with manual presets 360/720/1080/2160 and native-resolution composition; high-res NVENC optional with fallback.
- HP Victus one-click Windows installer: `SETUP-VICTUS-ONE-CLICK.bat`, checks Python 3.11, FFmpeg/ffprobe, Deno, ngrok, dependencies and basic tests, never intentionally deletes private `.env` or `data`.
- AI Settings has separate `Save settings` and `Test AI connection` actions; persisted `data/ai.json` is verified on readback.
- Social app credentials saving supports rotation with existing .env app ID; persisted `data/apps.json` verified; secret values masked in UI.
- Errors on failed credential persistence are displayed rather than silently treated as a successful save.
- Original PeakCut `main` inspected on 2026-11-22: it has creator-level campaign rate/footer and upstream Big text / Description / post-copy edits, but no dedicated Custom Campaigns manager. The user correctly distinguished GTA VI clipping from a true Campaigns dashboard.
- Dedicated **Custom Campaigns** shipped on this feature branch (not a GTA VI mode): sidebar `/app/campaigns`, create/edit/activate/pause/delete per-user campaign definitions, brand brief, optional fixed hook/description/hashtags and informational rate, optional selection in Make clips -> Options (Gaming or IRL). New video jobs save immutable snapshots so editing/deleting a campaign doesn't alter old jobs. Campaign-aware Gemini selection uses the brief, refusing unrelated loudness fallback when AI fails. A campaign badge and selection reason appear on clip cards. Campaign-specific video filtering works through View clips -> All videos. Branded campaign jobs are NEVER queued for auto-posting by inheriting creator autopost; manual review/publishing is required.
- Original safe UI improvements inspired by reviewing SupoClip: short/medium/long duration shortcut buttons and more visible clip-selection reason on cards; no SupoClip code copied because its noncommercial source license restricts commercial reuse. Advanced editor/B-roll/analytics were not imported.
- Current campaign selection is deliberately **per-video and opt-in**, not permanent (and Watch LIVE URL campaign clips are out of scope for this version). Normal GTA VI/Expedia clipping stays separate and unchanged.
- Regression test `tests/test_custom_campaigns.py` checks per-user isolation, persistence, AI prompt constraints, safe fallback and no auto-post. Added `.github/workflows/legendclipper-regression.yml` with isolated tests, including key persistence, Auto 4K and JS syntax.


## Latest concrete Windows verification
- Previously, full offline suite: 390 / 390 checks passed (prior stage).
- Main PC pulled commit `c9436b7` successfully on 2026-11-22.
- `python -m compileall -q studio` succeeded.
- `python tests\test_keys_persistence.py` succeeded: ALL PASSED (18 key save checks).
- These are mock/offline credential tests: they do NOT prove the user's real Gemini API key/model responds, or that a real 4K video completes a render/upload.
- User's actual Gemini connection test remains separate: go Settings > AI > Save settings, then Test AI connection.
- NEW 2026-11-22 GitHub Actions workflow runs **45056624172** and **45056623885**: successful Python compilation, Custom Campaigns offline tests, upstream metadata tests, key persistence tests, source-quality tests and JS syntax checks. These are genuine GitHub-hosted test results, NOT a Windows end-to-end recording/upload test.
- User's main Windows PC has NOT yet pulled the latest Custom Campaigns commits after the earlier key-saving commit; ask them to pull/test and restart before expecting the new UI. Sister's Victus is still old.


## Auto-post visibility and November 24 troubleshooting patch
- Issue reported: creator auto-post not working, exact platform/queue error not supplied; do not claim provider upload is fixed or tokens are verified.
- Code audited: automatic post runs only for a completed clip belonging to a creator with Auto-post ON, connected destination account, publishing rights confirmed, and clip score meeting post_min_score. Home jobs with No creator are never auto-posted. Content campaign clips intentionally require human review, never autopost.
- Feature branch now adds creator-level `GET /api/creators/{cid}/autopost-diagnostics`, visible on Creator -> Setup -> "Why isn't auto-post working?". It explains permissions, no destination, paused queue, score threshold, disconnected accounts and recent queue/provider failures without exposing credentials.
- `studio/posting.py` centralizes eligibility and logs skip reason to creator activity, ensures only connected selected destinations are queued, and honors chosen YouTube channel. Existing manual posting, normal creator auto-post, and campaign manual review behavior retained.
- `tests/test_autopost_diagnostics.py` added; corrected old Custom Campaigns test fixtures. GitHub Actions run #45410611603 on feature commit f6075bd passed auto-post checks, Custom Campaigns checks, key tests, source quality and JavaScript syntax.
- Actual Instagram/TikTok/YouTube live authorization, platform permissions and uploads still need diagnosis from Home -> Post queue error text. Never request API keys or login tokens in chat.
- Important user clarification: user ultimately wants a Content Rewards **real available campaigns** listing, NOT the previously implemented self-created Custom Campaigns manager. The latter remains in the feature branch but does not satisfy that requirement. Do not describe it as a Content Rewards integration.

## November 24: JavaScript null-array crash defensive fix
- User reported: `Cannot read properties of null (reading 'map')` (without specifying which page).
- Frontend `web/index.html` now uses `safeList(value)` for nullable AI models/providers, connected posting accounts, creator navigation, notification lists, auto-post diagnostics, recent UI list items, and normalized sync response lists. Prevents generic null-map crash but does not establish the root cause of the provider auto-post failure.
- New `tests/test_frontend_null_arrays.js` checks null-safe helper and critical UI source guards. Added to GitHub Actions workflow using Node. Prior release version on Windows must pull and refresh.
- If UI still errors, request the affected screen and first red Chrome/Edge F12 Console line; do not claim that any platform upload problem was fixed by this frontend hardening.
- GitHub branch remains `legend/facecam-preview-audio-repair`; sister's Victus remains intentionally unupdated.

## November 24: Post now safe original campaign copy
- User experienced "Protected campaign copy changed. Save and re-make this clip before posting." after the Post now account-selector fix. This is a frontend guard for GTA VI / legacy Expedia protected metadata, NOT a provider API rejection.
- `web/index.html` now normalizes harmless whitespace/CRLF/hashtag-prefix differences before comparing editor draft with stored post copy. If protected title, description or hashtags genuinely differ, Post now and Add to queue offer explicit "Post original text / Queue original text" confirmation. If approved, editor reverts to stored title/description/hashtags and queues original saved metadata, **without rerendering and without mutating protected campaign text**. Cancel retains editor draft, queues nothing. To publish changed protected content, user still must use the existing review/remake workflow.
- `tests/test_protected_campaign_post.js` plus CI regression verify the behavior. Normal gaming/IRL free text edit-and-post workflow remains unchanged. Genuine platform permissions and successful live uploads are separate checks.

## Deferred work
- Original upstream PeakCut has no standalone Custom Campaigns manager in its current `main`; the independent one was implemented above. Further upstream sync (other modules, complete editor/B-roll/analytics) is still pending; do not assume full PeakCut/SupoClip feature parity.
- Broader Settings UI polish may be addressed in a later fix. AI key saving logic itself was fixed and 18 offline tests passed.
- Sister's HP Victus laptop remains on its **old version**; user deferred updating it. When asked `Victus update`, prepare upgrade keeping private config, recordings, accounts, and data. Do not suggest it was already upgraded.
- Verify current issues against active branch; do not revive stale old `!clip` bugs.

## Main PC PowerShell update order
1. Stop server after current jobs finish.
2. `cd "D:\Clippers\PeakCut-main"`
3. `git status --short`
4. `git pull --ff-only origin legend/facecam-preview-audio-repair`
5. `.\.venv\Scripts\python.exe -m compileall -q studio`
6. `.\.venv\Scripts\python.exe tests\test_keys_persistence.py`
7. `.\.venv\Scripts\python.exe tests\test_custom_campaigns.py`
8. `.\.venv\Scripts\python.exe tests\run.py` (optional full test suite)
9. `.\.venv\Scripts\python.exe -m studio.server`
The server command runs in the foreground: don't put it first in a multiline batch.

## Security
- NO API keys, access tokens, ngrok auth token, Instagram/TikTok secrets or other credentials are stored in this file.
- Prior keys/secrets were exposed in chat: rotate them at the provider. Do not commit `.env`, `data` or source files containing secrets.
- Avoid copying sensitive values into chat again.

## Resume instruction
When the user says `!clipv2`, resume LegendClipper V2 using this file and newest chat/commit context, treating `!clip` as a separate earlier project. Preserve finished recording, clipping, downloader, facecam, social features, and user's changes. Only start deferred work when requested.

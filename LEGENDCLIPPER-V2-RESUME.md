# LegendClipper V2 — !clipv2 resume context
Updated: 2026-11-22

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

## Latest concrete Windows verification
- Previously, full offline suite: 390 / 390 checks passed (prior stage).
- Main PC pulled commit `c9436b7` successfully on 2026-11-22.
- `python -m compileall -q studio` succeeded.
- `python tests\test_keys_persistence.py` succeeded: ALL PASSED (18 key save checks).
- These are mock/offline credential tests: they do NOT prove the user's real Gemini API key/model responds, or that a real 4K video completes a render/upload.
- User's actual Gemini connection test remains separate: go Settings > AI > Save settings, then Test AI connection.

## Deferred work
- Original upstream PeakCut's newer Campaigns feature and full feature sync remain **deferred** by explicit user instruction; do not assume already integrated.
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
7. `.\.venv\Scripts\python.exe -m studio.server`
The server command runs in the foreground: don't put it first in a multiline batch.

## Security
- NO API keys, access tokens, ngrok auth token, Instagram/TikTok secrets or other credentials are stored in this file.
- Prior keys/secrets were exposed in chat: rotate them at the provider. Do not commit `.env`, `data` or source files containing secrets.
- Avoid copying sensitive values into chat again.

## Resume instruction
When the user says `!clipv2`, resume LegendClipper V2 using this file and newest chat/commit context, treating `!clip` as a separate earlier project. Preserve finished recording, clipping, downloader, facecam, social features, and user's changes. Only start deferred work when requested.

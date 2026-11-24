# PeakCut

Turn long videos and live streams into captioned vertical clips, ready to post. Free and open source: run it on
your own computer or server, with your own AI key.

Paste a YouTube, Twitch or Kick link (or upload a file) and PeakCut finds the moments worth clipping, cuts them to
9:16, adds word-by-word captions and a hook, and can post them to your connected accounts. It can also record a
creator's live stream and clip the highlights while the stream is still running.

## What it does

- **Clips from any video.** Transcribes the audio, asks an AI which moments would hold a stranger's attention, and
  renders each one with captions in one of three styles.
- **Live clipping.** Records a stream into a rolling buffer and clips as it happens, using loudness, chat activity
  and the transcript.
- **Workspaces per creator.** Channels, clip settings, posting rules and an activity log for each creator you clip.
- **Posting.** Connect YouTube, Instagram and TikTok in one click, then queue or auto-post finished clips, with
  spacing and daily caps (see [DEPLOY.md](DEPLOY.md#connecting-youtube-instagram-and-tiktok) for the one-time setup).
- **No sign-in on your own computer.** It opens straight into the dashboard. On a shared server, switch accounts on
  (`PEAKCUT_ACCOUNTS=1`) for email or Google sign-in and an admin dashboard.
- **Your own AI.** Gemini, OpenAI, Grok, Groq, OpenRouter, Claude, a local model through Ollama, or anything that
  speaks the OpenAI chat format. No key at all also works: clips are then picked by loudness.

## Quick start

You need Python 3.10 or newer and `ffmpeg`. On Windows: `winget install Gyan.FFmpeg`. On a Mac: `brew install ffmpeg`.
On Linux: `sudo apt install ffmpeg`. PeakCut finds it by itself and tells you in the dashboard if it is missing.

```bash
git clone <this repository> peakcut
```

```bash
cd peakcut
```

```bash
pip install -r requirements.txt
```

Start the server:

```bash
python -m studio.server
```

The first start downloads the speech model by itself (about 480 MB, once).

Open http://127.0.0.1:8765. There is no sign-in: it opens straight into the dashboard. Go to **Settings, AI**, choose
your AI service, paste your key and press **Save settings**, then **Test AI connection** (see [Choose your AI](#choose-your-ai)).

## Choose your AI

PeakCut needs a chat model that can return JSON. The easy way is in the dashboard: **Settings, AI**. Pick the
service, paste your key, press **Find models** to choose from the service's own list, then **Save settings** and separately **Test AI connection**. The
key is kept in the data folder on your machine and is never shown again.

If you prefer a file (or run a server), the same three things can go in `.env`. What is saved in the dashboard wins:

```ini
PEAKCUT_AI_PROVIDER=gemini
PEAKCUT_AI_MODELS=gemini-2.5-flash
PEAKCUT_AI_KEY=your-key-here
```

| `PEAKCUT_AI_PROVIDER` | Service | Where to get a key |
|---|---|---|
| `gemini` | Google Gemini | https://aistudio.google.com/apikey |
| `openai` | OpenAI | https://platform.openai.com/api-keys |
| `xai` | Grok (xAI) | https://console.x.ai |
| `groq` | Groq | https://console.groq.com/keys |
| `openrouter` | OpenRouter (many models, one key) | https://openrouter.ai/keys |
| `anthropic` | Claude | https://console.anthropic.com |
| `ollama` | A model on your own machine, no key | https://ollama.com |
| `custom` | Any OpenAI-compatible address: also set `PEAKCUT_AI_BASE_URL` | |

- `PEAKCUT_AI_MODELS` is the model id exactly as the service names it. Model names change often, so check the
  service's current list. Several ids separated by commas are tried in order, which gives you a fallback.
- A fast, inexpensive model is the right choice. A one-hour video is read in about four requests.
- You pay the AI service directly for what you use. The **AI usage** page in the app shows how many requests and
  tokens each video took.
- Speech to text does not use the AI service. It runs on your own machine, so audio never leaves it.

## Troubleshooting automatic posting

Open **Creator → Setup → Why isn't auto-post working? → Refresh**. The diagnostic shows whether the creator has Auto-post on, approved publishing rights, connected posting destinations, and a global queue pause. It also lists recent completed clip scores and explains why each was skipped or what error the destination returned.

For automatic posting, **select a creator workspace when starting a new clip job**, then enable **Creator → Setup → Posting → Post new clips automatically**, tick the destination account(s), tick the permission confirmation and choose a reasonable score threshold. Clips made under `No creator` do not have a destination. Auto-post runs only when **new clips finish**, not retroactively on old videos. Do not disable publisher permission safeguards; only upload footage you are authorized to publish.

Use **Home → Post queue** for actual upload results. If a provider rejects the post (missing TikTok video.publish permission, Instagram professional account/media-fetch access, expired OAuth sign-in or an unreachable public HTTPS URL), its error appears there after retries. Clicking Retry after correcting the account is a manual action; queued posts still respect account spacing/daily limits. Creating a brand/paid campaign does not automatically authorize unattended publishing.

## Schedule YouTube Shorts and Instagram Reels

From **All videos → finished clip → Post it**, select the connected YouTube and/or Instagram destinations. Enter optional **YouTube publish date/time** and/or **Instagram publish date/time** in your browser's local timezone, then choose **Add to queue / Schedule**. With both dates specified, each connected platform uses its own schedule; other selected platforms retain the ordinary local posting queue. **Post now** is still for immediate publishing and refuses future dates.

- **YouTube (remote schedule):** Allow at least 20 minutes before release. LegendClipper uploads the video *immediately* as **private**, including YouTube's official `status.publishAt` metadata. Wait in **Home → Post queue** for **YouTube scheduled** and the returned Shorts link. Only after YouTube accepts the complete upload is the scheduling handed off to YouTube; then the laptop and server can be closed and the chosen future release proceeds on YouTube's side. Changes/cancellation of an already handed-off release are performed in **YouTube Studio**, not by cancelling a local queue record. Unverified YouTube API projects or YouTube permission/review restrictions can prevent public release; check YouTube Studio.
- **Instagram (local schedule):** Allow at least five minutes. LegendClipper stores the Reel and intended time locally, then initiates the existing Instagram publishing flow when the time arrives. Instagram's Content Publishing API has **no native future `publishAt` field**. The **laptop, Python server, Internet connection and required HTTPS public media route (for applicable Meta auth)** must remain available until the Reel is actually published. Instagram video processing can delay release beyond the exact chosen minute. If LegendClipper is off and the deadline is missed by more than fifteen minutes, the post fails instead of unexpectedly publishing hours late; review and press **Retry** to post immediately. Cancel a still-waiting Instagram entry from **Home → Post queue**.
- **Both:** The queue is persisted in the server's normal `data` folder, not uploaded to any separate 24/7 scheduler. A date field alone does not upload media. YouTube displays **YouTube scheduled** only after the upload succeeds, not as soon as queued. Instagram displays **Instagram locally queued** while waiting. If either platform returns a permission/connection error, resolve it under **Settings → Connected apps** and review **Home → Post queue** before retrying. Use only clips you have rights to publish.

For a truly **server-off Instagram schedule**, use Instagram/Meta's own scheduling interface or run a trusted scheduler on an always-on host; the direct Instagram API cannot provide that guarantee from an offline laptop.

## LegendClipper improvements (feature branch)

- **Facecam from the source video:** after adding a video link, choose a real frame at a timestamp; draw, move, and resize the webcam rectangle. The final 9:16 render puts the facecam above center-cropped gameplay. You can also skip facecam.
- **Smart early-stop audio scanning:** for 1–10 requested clips in a recording longer than three minutes, download small audio sections as needed and stop searching when the requested number of strong clips has been selected. If fewer strong moments exist, it continues searching the available range. If section downloading is unavailable, it falls back to the existing full-audio download method.
- **MAX mode:** scan the complete selected recording, capped at up to 100 clips by the dashboard.
- **Game-aware metadata:** selected ordinary gaming clips receive more relevant hashtags from the game's title (Minecraft, GTA, Fortnite and other recognized games). Existing custom GTA VI and Expedia campaign logic is unchanged.
- **Auto resolution (up to 4K):** choose **Auto** in Make clips → Export quality, or Creator → Automatic live clip quality. Remote clips and live recordings fetch at most 2160p; the rendered export is chosen from the **actual downloaded source** (1080p → 1080p, 2160p → 2160p, 1440p → 1440p). Fixed 360p/720p/1080p formats retain their working download rules. Explicit 4K refuses lower-resolution sources. 4K exports use a native-size composition canvas and may use substantially more CPU, RAM, disk and time.
- **HP Victus:** the included `SETUP-VICTUS-ONE-CLICK.bat` checks Python 3.11, FFmpeg, FFprobe, Deno, ngrok, the local virtual environment and light regressions; it does not overwrite `.env` or `data` and does not start two competing servers.
- **Custom Campaigns — separate from GTA 6 clipping:** create, edit, activate/pause and delete named brand campaigns in a dedicated sidebar page. Each campaign can store a brand, a requirements brief, optional exact hook/description, hashtags and an informational rate. Choose an active campaign explicitly in **Make clips → Options**. Gemini uses the brief when scouting relevant transcript moments; campaign branding applies only to clips created with that selected campaign. If Gemini is unavailable, a branded campaign will NOT silently fall back to unrelated loudness-only highlights. Campaign deletion does not delete previously rendered clips, and old job snapshots are preserved even on retry. Use **View clips** to filter the library by a campaign; no auto-posting or payout tracking is triggered by campaign creation.
- **Clip review & pacing:** clip cards show the AI's existing reason for selecting the moment and its campaign tag where applicable; Short (15–30s), Medium (30–60s) and Long (60–120s) buttons speed up setting clip durations without changing existing defaults or the caption pipeline.
- **Settings key persistence fix:** AI service/model/key saving is separate from the provider connection test. Saves are verified against `data/ai.json`, and the Settings page explicitly shows where credentials are stored (or that the key came from `.env`). An invalid model or rejected key can still be saved; **Test AI connection** reports that error without deleting the saved values. Connected-app credentials now accept rotating only a secret while keeping an ID already configured in `.env`; saves are verified in `data/apps.json`. Keys are private to each laptop/server and never committed to GitHub.

SupoClip (https://github.com/FujiwaraChoki/supoclip) was reviewed for product ideas including clearer clip-selection explanations and quick length presets. Its source is under a **noncommercial license with restrictions on commercial reuse**, so no SupoClip code was copied into LegendClipper. These features are original implementation adapted to the existing PeakCut-based Python/JavaScript architecture. Advanced video editing/B-roll, analytics and automatic social performance sync were NOT imported in this update.

Run the offline regressions on Windows with `.\\.venv\\Scripts\\python.exe tests\\test_custom_campaigns.py` and the existing complete `tests\\run.py` suite. This update is on branch `legend/facecam-preview-audio-repair` until tested/merged; actual Gemini relevance and source-based 4K renders still require real-world checking.

Set `PEAKCUT_SMART_AUDIO=0` in `.env` to disable short-section audio scanning and use the previous full-audio workflow. The source format code was extended for Auto/4K without changing the fixed-quality 360p/720p/1080p selection rules.

For Windows upgrades on both laptops, switch/pull `legend/facecam-preview-audio-repair` (this change is in the feature branch until PR #1 is merged). On the Victus run `SETUP-VICTUS-ONE-CLICK.bat` from the project folder **after updating Git**. If the laptop has only an old ZIP copy without `.git`, clone the repository in a new folder, then transfer your private `.env`, `data` and launcher while the old app is stopped. Do not run the same ngrok reserved domain from two laptops at once.

## Selective upstream PeakCut sync (November 2026)

This branch selectively integrates features from [PeakCut](https://github.com/haziqahmedqasmi/PeakCut) without replacing LegendClipper's known-working recording, selective video-segment downloads, AI provider/key settings, facecam preview, custom GTA VI/Expedia campaigns, or Auto up to 4K.

- **Creator campaign text:** in Creator → Setup → Clips, optionally choose **Big text on every clip** and **Description for every clip**. Leave blank for the usual per-clip AI hook and description. Special GTA VI/Expedia campaign copy takes priority over these defaults. The new overlay headline is deliberately named `overlay_hook_text` because the existing `hook_text` value controls the overlay **color**.
- **Post-text editing without re-encode:** open a finished normal Gaming/IRL clip and edit title, description or hashtags. **Save post text only** writes metadata without touching the encoded video; publishing uses the latest saved copy. Protected campaign text still requires the existing review/re-make flow.
- **Write again with AI:** request an optional draft title/description/hashtags from the clip's spoken transcript; edit/review before saving. It uses the currently configured AI provider and never posts or saves automatically. If speech text is missing, manually edit instead.
- **Friendly download filenames:** individual MP4s and ZIP entries use a safe clip-title name. Actual stored filenames remain stable; posting/preview links are unchanged.
- **Avoid duplicate hashtags:** prewritten creator descriptions are not given another AI hashtag line. Existing creator-specific posting hashtags and footer behavior remain intact.

Offline regression: `.venv\\Scripts\\python.exe tests\\test_upstream_campaign_sync.py`. Full isolated test suite: `.venv\\Scripts\\python.exe tests\\run.py`. These checks are included in `tests/run.py`; they need to be executed on Windows before declaring the sync verified. The original PeakCut changes beyond this selective batch are **not** yet fully merged.

## Settings

Everything is set through environment variables, normally in a `.env` file next to this README.
[`.env.example`](.env.example) lists every setting with a short explanation. The ones that matter first:

| Setting | What it is for |
|---|---|
| `PEAKCUT_AI_PROVIDER`, `PEAKCUT_AI_MODELS`, `PEAKCUT_AI_KEY` | The AI that picks clips and writes titles (or set it in the dashboard) |
| `PEAKCUT_ACCOUNTS` | `1` makes everyone sign in. Use it on any server other people can reach |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Optional: Sign in with Google, and connecting YouTube |
| `PEAKCUT_SMTP_*`, `PEAKCUT_MAIL_FROM` | Optional: confirmation and password emails |
| `PEAKCUT_DATA` | Where videos, clips and the database are kept (default `./data`) |

`.env`, the `secrets/` folder and all user data are ignored by git. Keep keys there, never in the code.

## Admins

This only matters with accounts switched on (`PEAKCUT_ACCOUNTS=1`); without them you are the owner and can do
everything. An account is an admin only when the database says so. No email address is special in the code and no web request
can change a role. Do it on the machine that runs PeakCut:

```bash
python -m studio.admin grant you@example.com
```

`revoke` and `list` work the same way. The admin dashboard is at `/admin` and answers "not found" to everyone else.

## How it is built

| Part | What it is |
|---|---|
| `studio/` | The server: FastAPI, the clip pipeline, live recording, accounts |
| `studio/ai.py` | The only file that talks to an AI service. Add a provider here |
| `web/` | The pages: landing, sign-in, the app, the admin dashboard (plain HTML, CSS and JavaScript, no build step) |
| `tests/` | Tests that run against a throwaway copy of the app |
| `deploy/`, `Dockerfile`, `docker-compose.yml` | One-server deployment with PostgreSQL and automatic HTTPS |

Video work is done with `ffmpeg` and `yt-dlp`. Speech is transcribed with `sherpa-onnx` and the Parakeet model.
Data is kept per user: accounts in the database (SQLite on your own computer, PostgreSQL on a server), videos and
clips in each user's own folder. [AGENTS.md](AGENTS.md) is a short map of the code for contributors and AI coding
assistants.

## Where your videos and clips are kept

Everything PeakCut keeps is in one folder: videos, clips, recordings, creators, settings and the speech model. By
default it is the `data` folder inside PeakCut. **Settings, Storage** shows the folder and how much room its drive
has, opens it in one click, and lets you move it to another drive: choose the new folder, and PeakCut moves
everything there the next time it starts. If the drive is nearly full, PeakCut says so and stops taking new videos
until there is room. (`PEAKCUT_DATA` in `.env` still works and takes priority.)

## Updating

PeakCut checks GitHub once a minute while it runs. When a newer version is out, the dashboard shows a notice
within a minute or two (no restart needed), with what changed
and how to update: ask your AI coding assistant to do it (the notice has a sentence to paste), or run
`git pull && pip install -r requirements.txt` in the PeakCut folder and restart it (with Docker:
`git pull && docker compose up -d --build`). Your `.env`, keys and clips are not touched. Only the two commit ids
are sent to GitHub; set `PEAKCUT_UPDATE_CHECK=0` to turn the check off.

## Deploy

[DEPLOY.md](DEPLOY.md) walks through a single server with Docker: the app, PostgreSQL, and Caddy for HTTPS.

```bash
docker compose up -d --build
```

## How it behaves under load

- The page asks the server one small question every few seconds. When nothing has changed, the answer comes
  straight from memory.
- Each person's videos wait in their own line and the lines take turns, so one person cannot hold everyone up.
- The server measures its own processor, memory and disk every second. Extra videos and recordings start only
  while there is room, wait briefly when it is nearly full, and continue the moment it frees up.
- There are no limits on upload size, video length, recordings, creators or storage unless you set them in
  `.env`. Five videos can be sent at once. Request sizes are always capped, so junk can't fill the memory.

## Tests

```bash
python tests/run.py
```

This starts a copy of the app on a spare port with an empty temporary data folder, runs the permission, abuse and
queue tests against it, then removes it. It needs no keys and never touches real data.

## Security

- With sign-in off, PeakCut listens on this computer only (`127.0.0.1`), refuses changes sent by other websites,
  and only answers to its own address. Do not expose it to the internet that way: turn accounts on.
- Passwords are stored only as salted scrypt hashes. Sessions are random tokens stored hashed; cookies are HTTP-only.
- Every route works out who is asking from the session, never from the request, so users only reach their own data.
- Only known video sites are fetched, and text from videos is treated as data when it is shown to the AI.
- Found a problem? Please report it privately through the repository's security advisories instead of opening a
  public issue.

## Using it responsibly

Clip videos you made, or have permission to use. You are responsible for the rights to what you download, clip and
post, and for following the terms of the sites you fetch from and post to.

## Licence

[MIT](LICENSE). Caption fonts in `studio/fonts/` (Anton, Archivo Black, Poppins) are under the SIL Open Font
License; the licence texts are in the same folder.

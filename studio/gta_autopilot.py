"""GTA VI per-user, per-language opt-in autopilot.

LEGEND_GTA_DASHBOARD_V2: best available source, MAX clip counts and separate destinations.

Runs only for channel links the owner supplied.  LIVE before archived streams;
for VOD, finish one clip/job and its optional post before searching next.
No public-data scraping by subscriber-language guessing, no mass-upload defaults.
"""
from __future__ import annotations

import copy
import json
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from . import accounts, auth, config, creators, ctx, gta6, jobs, live, media, posting, profiles

# LEGEND_GTA_TIKTOK_V1: English/Hindi per-lane TikTok destination.
POLL_SECONDS = 300
LANES = ("english", "hindi")
LOCK = threading.RLock()
STOP = {}             # (user, language) -> Event
THREADS = {}

def _defaults():
    return {"version": 2, "mode": "both", "lanes": {
        "english": {"channels": [], "youtube_account": "", "instagram_account": "", "tiktok_account": "", "autopost": False,
                    "rights": False, "cta": True, "quality": "auto", "daily_cap": 0,
                    "max_per_video": 0, "min_score": 75, "min_subs": 500000, "enabled": False},
        "hindi": {"channels": [], "youtube_account": "", "instagram_account": "", "tiktok_account": "", "autopost": False,
                  "rights": False, "cta": True, "quality": "auto", "daily_cap": 0,
                  "max_per_video": 0, "min_score": 75, "min_subs": 100000, "enabled": False}}}

def _file():
    return config.user_dir(ctx.uid()) / "gta_autopilot.json"

def _read():
    base = _defaults()
    f = _file()
    if f.is_file():
        try:
            saved = json.loads(f.read_text(encoding="utf-8"))
            if saved.get("mode") in ("english", "hindi", "both"):
                base["mode"] = saved["mode"]
            for lang in LANES:
                base["lanes"][lang].update({k: v for k, v in (saved.get("lanes", {}).get(lang) or {}).items()
                                            if k in base["lanes"][lang]})
            # One-time migration from the old UI's forced 4K / 6-per-day / 1-per-VOD defaults.
            # User requested Best Available and MAX. Save writes version=2.
            if int(saved.get("version") or 0) < 2:
                for lang in LANES:
                    base["lanes"][lang].update(quality="auto", daily_cap=0, max_per_video=0)
        except (ValueError, TypeError):
            pass
    return base

def _write(v):
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    temp = f.with_name(f.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(v, indent=2), encoding="utf-8")
    temp.replace(f)
    ctx.bump()

def _rt_file(lang):
    return config.user_dir(ctx.uid()) / ("gta_autopilot_" + lang + "_state.json")

def _state(lang):
    try:
        d = json.loads(_rt_file(lang).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return {"status": d.get("status", "idle"), "message": d.get("message", ""),
            "job_id": d.get("job_id", ""), "live_job_id": d.get("live_job_id", ""),
            "source_url": d.get("source_url", ""), "cursor": d.get("cursor", {}), "video_counts": d.get("video_counts", {}),
            "seen": d.get("seen", [])[-400:], "creator_id": d.get("creator_id", ""),
            "processed_today": d.get("processed_today", ""), "processed": d.get("processed", 0),
            "last_check": d.get("last_check", 0), "error": d.get("error", "")}

def _set(lang, **kw):
    d = _state(lang)
    d.update(kw)
    f = _rt_file(lang)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    tmp.replace(f)
    ctx.bump()
    return d

def _url(x):
    x = str(x).strip().rstrip("/")
    u = urlparse(x)
    if u.scheme != "https" or (u.hostname or "").lower() not in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        raise ValueError("Paste HTTPS YouTube channel URLs (youtube.com/@name or /channel/ID).")
    if not re.fullmatch(r"/(?:@[\w.\-]+|channel/UC[\w-]{16,}|c/[\w.\-]+)", u.path):
        raise ValueError("Use a YouTube channel address, not a single video or playlist URL.")
    if u.query or u.fragment:
        raise ValueError("Remove query parameters from channel URL.")
    return x

def save(patch):
    if not isinstance(patch, dict):
        raise ValueError("Invalid settings")
    with LOCK:
        state = _read()
        mode = patch.get("mode", state["mode"])
        if mode not in ("english", "hindi", "both"):
            raise ValueError("Choose English, Hindi or Both.")
        state["mode"] = mode
        for lang in LANES:
            got = (patch.get("lanes") or {}).get(lang)
            if got is None:
                continue
            if not isinstance(got, dict):
                raise ValueError("Invalid language lane")
            old = state["lanes"][lang]
            if "channels" in got:
                if not isinstance(got["channels"], list):
                    raise ValueError("Channel URLs must be a list")
                cs = list(dict.fromkeys(_url(c) for c in got["channels"] if str(c).strip()))
                if len(cs) > 20:
                    raise ValueError("Maximum 20 channels per language")
                old["channels"] = cs
            for k in ("youtube_account", "instagram_account", "tiktok_account"):
                if k in got:
                    aid = str(got[k] or "")[:100]
                    a = accounts.get(aid) if aid else None
                    if aid and (not a or a["platform"] != k.split("_")[0]):
                        raise ValueError("Connect your " + k.split("_")[0].title() + " account in Settings first")
                    old[k] = aid
            for k in ("autopost", "rights", "cta"):
                if k in got:
                    old[k] = got[k] is True
            if "quality" in got:
                q = got["quality"]
                if q == "auto":
                    old["quality"] = "auto"
                elif str(q) in ("360", "720", "1080", "2160"):
                    old["quality"] = int(q)
                else:
                    raise ValueError("Choose best available or a supported fixed resolution")
            for k, lo, hi in (("daily_cap", 0, 1000), ("max_per_video", 0, 1000),
                              ("min_score", 0, 100), ("min_subs", 0, 20000000)):
                if k in got:
                    old[k] = max(lo, min(hi, int(got[k])))
            if old["autopost"] and (not old["rights"] or not any(old[k] for k in ("youtube_account", "instagram_account", "tiktok_account"))):
                raise ValueError(lang.title() + ": publishing needs rights confirmed and a connected destination account")
        state["version"] = 2
        # Both language lanes must not publish to the SAME account on any platform.
        if state["mode"] == "both" and all(state["lanes"][l]["autopost"] for l in LANES):
            for platform in ("youtube", "instagram", "tiktok"):
                x, y = (state["lanes"][l].get(platform + "_account", "") for l in LANES)
                if x and y and x == y:
                    raise ValueError(f"English and Hindi must use different {platform.title()} upload accounts")
        # LEGEND_SOURCE1080_GTA_V1: every enabled lane <=1080 download/export.
        for lang in LANES:
            q = state["lanes"][lang].get("quality", 1080)
            if str(q).lower() == "auto" or int(q) > 1080:
                state["lanes"][lang]["quality"] = 1080
        _write(state)
        for lang in LANES:
            lane = state["lanes"][lang]
            if not lane["autopost"] or not lane["rights"]:
                current = _state(lang)
                if current["creator_id"] and creators.get(current["creator_id"]):
                    creators.update(current["creator_id"], {"autopost": False})
        return status()

def status():
    cfg = _read()
    acc = [{"id": a["id"], "platform": a["platform"], "name": a.get("name", "Connected account")}
           for a in accounts.list_accounts() if a.get("platform") in ("youtube", "instagram", "tiktok")]
    return {**cfg, "accounts": acc, "runtime": {l: _state(l) for l in LANES},
            "poll_seconds": POLL_SECONDS}

def selected(cfg):
    return LANES if cfg["mode"] == "both" else (cfg["mode"],)

def start():
    cfg = _read()
    active = selected(cfg)
    if any(not cfg["lanes"][l]["channels"] for l in active):
        raise ValueError("Add at least one source channel in each enabled lane")
    for l in active:
        lane = cfg["lanes"][l]
        if lane["autopost"] and (not lane["rights"] or not lane["youtube_account"] and not lane["instagram_account"] and not lane["tiktok_account"]):
            raise ValueError("Connect destination account and confirm reuse rights before enabling auto posting")
    with LOCK:
        for l in LANES:
            if l in active:
                cfg["lanes"][l]["enabled"] = True
            else:
                cfg["lanes"][l]["enabled"] = False
                key = (ctx.uid(), l)
                if key in STOP: STOP[key].set()
        _write(cfg)
    for l in active:
        _spawn(ctx.uid(), l)
    return status()

def stop(lang="both"):
    if lang not in ("english", "hindi", "both"):
        raise ValueError("Invalid lane")
    which = LANES if lang == "both" else (lang,)
    cfg = _read()
    for l in which:
        cfg["lanes"][l]["enabled"] = False
        key = (ctx.uid(), l)
        if key in STOP:
            STOP[key].set()
        s = _state(l)
        # Cancel an active video; stop a live recorder rather than killing the web server.
        j = jobs.get(s["job_id"]) if s["job_id"] else None
        if j and j["status"] in ("queued", "running", "cancelling"):
            try: jobs.cancel(j["id"])
            except (ValueError, KeyError): pass
        session = live.mine(s["live_job_id"]) if s["live_job_id"] else None
        if session and not session.finished:
            session.stop("Stopped GTA 6 autopilot")
        if s["creator_id"] and creators.get(s["creator_id"]):
            creators.update(s["creator_id"], {"autopost": False})
            for post in list(posting._mine()):
                if post.get("creator") == s["creator_id"] and post.get("status") == "scheduled":
                    try: posting.cancel(post["id"])
                    except ValueError: pass
        _set(l, status="stopped", message="Stopped by you")
    _write(cfg)
    return status()

def _spawn(uid, lang):
    key = (uid, lang)
    with LOCK:
        thread = THREADS.get(key)
        if thread and thread.is_alive():
            return
        e = threading.Event()
        STOP[key] = e
        thread = threading.Thread(target=_worker, args=(uid, lang, e), daemon=True,
                                  name="legend-gta-auto-" + lang)
        THREADS[key] = thread
        thread.start()

def resume_all():
    """Only explicitly enabled lanes resume on server restart, after job state loads."""
    for uid in auth.user_ids():
        try:
            with ctx.as_user(uid):
                cfg = _read()
                for lang in LANES:
                    if cfg["lanes"][lang]["enabled"] and lang in selected(cfg):
                        _spawn(uid, lang)
        except Exception as e:
            print("[Legend GTA auto] resume skipped:", str(e)[-120:])

def _ensure_creator(lang, lane):
    s = _state(lang)
    c = creators.get(s.get("creator_id")) if s.get("creator_id") else None
    if not c:
        c = creators.create({"name": "GTA 6 Auto · " + lang.title(), "channel": lane["channels"][0],
                             "clip_mode": "gta6", "gta6_only_live": True, "facecam_review": False})
        _set(lang, creator_id=c["id"])
    ids = [lane[k] for k in ("youtube_account", "instagram_account", "tiktok_account") if lane[k]]
    # Use 1080 as provisional quality for auto. Set the real live source quality
    # immediately after live.resolve() reports the selected stream format.
    output_quality = 1080 if lane["quality"] == "auto" else int(lane["quality"])
    # The creator's own posting scheduler still respects platform/provider limits.
    cap = 1000 if not lane["daily_cap"] else int(lane["daily_cap"])
    return creators.update(c["id"], {"channel": lane["channels"][0], "clip_mode": "gta6", "gta6_only_live": True,
           "facecam_review": False, "clip_quality": output_quality, "max_clips": 20,
           "live_per_hour": 60, "ai_every_min": 1, "min_gap_min": 0,
           "post_min_score": lane["min_score"], "daily_cap": cap,
           "post_rights_confirmed": bool(lane["rights"]), "trigger_words": "",
           "accounts": ids, "autopost": bool(lane["autopost"] and lane["rights"]),
           "gta_auto_sequential": True,
           "cta_enabled": bool(lane["cta"] and not (lane["autopost"] and lane["tiktok_account"])),
           "cta_creator_name": ""})

def _quality_from_height(height):
    """Never advertise/render a resolution higher than the actual source."""
    try: h = int(height)
    except (ValueError, TypeError): h = 0
    if h >= 2160: return 1080
    if h >= 1080: return 1080
    if h >= 720: return 720
    if h >= 360: return 360
    return 0


def _vod_best_quality(url):
    """Read the video format metadata and select the best usable export size <=4K.
    Do not claim a 4K source just because the user selected MAX.
    """
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True,
                           "skip_download": True, "socket_timeout": 15}) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    heights = [int(f.get("height") or 0) for f in (info.get("formats") or [])
               if f.get("vcodec") not in ("none", None)]
    heights.append(int(info.get("height") or 0))
    size = _quality_from_height(max(heights or [0]))
    if size == 0:
        raise ValueError("Could not verify a >=360p video source; refusing fake HD")
    return size


def _subscriber_count(chan):
    try:
        p = profiles.fetch(chan)
        text = (p.get("followers") or "").replace(",", "")
        m = re.search(r"([\d.]+)\s*([KMB]?)\s*subscribers", text, re.I)
        if not m: return None
        return int(float(m.group(1)) * {"":1,"K":1000,"M":1000000,"B":1000000000}[m.group(2).upper()])
    except Exception:
        return None

def _videos(chan):
    """Only the supplied channel's archived stream listing (never global creator discovery)."""
    import yt_dlp
    url = chan.rstrip("/") + "/streams"
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                           "extract_flat": "in_playlist", "playlistend": 12, "socket_timeout": 12,
                           "ignoreerrors": True}) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    for item in (info.get("entries") or []):
        if not item: continue
        title = str(item.get("title") or "")[:250]
        if not gta6.stream_eligible(title, True): continue
        video_id = str(item.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id): continue
        yield "https://www.youtube.com/watch?v=" + video_id, title

def _day():
    return time.strftime("%Y-%m-%d")

def _posts_finished(job, clip, aids):
    # Auto-post is a separate 15-second queue; wait before next discovery / render.
    found = [p for p in posting._mine() if p["job"] == job["id"] and p["clip"] == clip["id"]
             and p["account"] in aids]
    if not aids: return True
    if len({p["account"] for p in found}) < len(set(aids)): return False
    return all(p["status"] in ("posted", "failed", "cancelled") for p in found)

def live_ready(job):
    """Keep a LIVE GTA lane to one clip at a time, including its posting completion."""
    c = creators.get(job.get("creator"))
    if not c or not c.get("gta_auto_sequential"):
        return True
    last = job.get("clips", [])[-1:]
    if not last: return True
    k = last[0]
    if k.get("status") not in ("done", "error", "cancelled"): return False
    if k.get("status") == "done" and c.get("autopost") and k.get("score", 0) >= c.get("post_min_score", 0):
        return _posts_finished(job, k, c.get("accounts", []))
    return True

def _wait_job(lang, jid, stop_event, timeout=60*60*4):
    began = time.time()
    while not stop_event.wait(3):
        j = jobs.get(jid)
        if not j or j["status"] in ("done", "error", "cancelled"):
            return j
        if time.time() - began > timeout:
            raise RuntimeError("Video processing exceeded 4 hours; review job in All videos")
    return None

def _worker(uid, lang, stop_event):
    with ctx.as_user(uid):
        try:
            _loop(lang, stop_event)
        except Exception as exc:
            _set(lang, status="error", error=str(exc)[-240:], message="Autopilot paused after an error")
            with LOCK:
                c = _read(); c["lanes"][lang]["enabled"] = False; _write(c)

def _loop(lang, e):
    while not e.is_set():
        cfg = _read()
        lane = cfg["lanes"][lang]
        if not lane["enabled"] or lang not in selected(cfg): return
        if not lane["channels"]: raise ValueError("No channels configured in " + lang)
        c = _ensure_creator(lang, lane)
        s = _state(lang)
        if s["processed_today"] != _day():
            _set(lang, processed_today=_day(), processed=0)
            s = _state(lang)
        if lane["daily_cap"] and s["processed"] >= lane["daily_cap"]:
            _set(lang, status="daily_limit", message="Daily clip cap reached; next day resumes")
            e.wait(min(300, max(30, 86400 - time.time() % 86400)))
            continue
        # Resume unfinished previous job instead of generating the same clip twice.
        if s["job_id"]:
            j = jobs.get(s["job_id"])
            if j:
                if j["status"] in ("queued", "running", "cancelling"):
                    _set(lang, status="rendering", message="Finishing existing video job")
                    j = _wait_job(lang, j["id"], e)
                if j and j["status"] == "done":
                    ready = next((k for k in j["clips"] if k["status"] == "done"), None)
                    if ready:
                        # Original source already checked by GTA6 mode; score must pass threshold.
                        if ready.get("score", 0) >= lane["min_score"]:
                            if lane["autopost"]:
                                aids = [lane[k] for k in ("youtube_account", "instagram_account", "tiktok_account") if lane[k]]
                                _set(lang, status="posting", message="Waiting for uploads to finish")
                                while not e.wait(5):
                                    if not accounts.settings().get("paused") and _posts_finished(j, ready, aids): break
                                if e.is_set(): return
                            _set(lang, processed=s["processed"] + 1)
                        # Advance to the next range only after rendering + posting.
                        cursor = dict(s["cursor"])
                        cursor[s["source_url"]] = round(float(ready["end"]) + 12, 2)
                        counts = dict(s.get("video_counts") or {})
                        counts[s["source_url"]] = int(counts.get(s["source_url"], 0)) + 1
                        _set(lang, cursor=cursor, video_counts=counts)
                        if lane["max_per_video"] and counts[s["source_url"]] >= lane["max_per_video"]:
                            _set(lang, seen=(_state(lang)["seen"] + [s["source_url"]])[-400:])
                    else:
                        _set(lang, seen=(s["seen"] + [s["source_url"]])[-400:])
                else:
                    _set(lang, seen=(s["seen"] + [s["source_url"]])[-400:])
            _set(lang, job_id="")
            continue
        # A live job may be ongoing. Do not run a VOD job or a second source in this lane.
        if s["live_job_id"]:
            sess = live.mine(s["live_job_id"])
            if sess and not sess.finished:
                _set(lang, status="recording", message="LIVE GTA 6 stream: clipping one moment at a time")
                e.wait(20)
                continue
            _set(lang, live_job_id="")
        _set(lang, status="checking", last_check=time.time(), message="Checking your channel links: LIVE first")
        for chan in lane["channels"]:
            if e.is_set(): return
            try:
                data = live.resolve(live.normalize(chan), 1080 if lane["quality"] == "auto" else min(1080, int(lane["quality"])))
                if not gta6.stream_eligible(data.get("title"), True):
                    continue
                output_quality = (_quality_from_height(data.get("source_height"))
                                  if lane["quality"] == "auto" else int(lane["quality"]))
                if not output_quality:
                    _set(lang, message="LIVE stream resolution could not be verified; skipped to avoid fake HD")
                    continue
                c = creators.update(c["id"], {"clip_quality": output_quality})
                _set(lang, status="live_found", message=data.get("title", "GTA VI LIVE")[:100], source_url=chan)
                sess_job = live.start_session(c, chan)
                _set(lang, live_job_id=sess_job["id"], status="recording")
                break
            except live.NotLive:
                continue
            except (ValueError, OSError) as exc:
                _set(lang, message=str(exc)[-120:])
        if _state(lang)["live_job_id"]:
            continue
        # No live stream. ONLY older streams from provided channels with known subscriber count.
        found = False
        for chan in lane["channels"]:
            if e.is_set(): return
            subscribers = _subscriber_count(chan)
            if subscribers is None or subscribers < lane["min_subs"]:
                _set(lang, message=f"Archived VOD skipped: subscriber count not verified or below {lane['min_subs']:,}")
                continue
            try:
                for url, title in _videos(chan):
                    s = _state(lang)
                    if url in s["seen"] or (lane["max_per_video"] and int(s.get("video_counts", {}).get(url, 0)) >= lane["max_per_video"]): continue
                    if e.is_set(): return
                    meta = media.info(url)
                    if meta["is_live"]: continue
                    duration = meta.get("duration") or 0
                    start_sec = float(s["cursor"].get(url, 0))
                    if not duration or duration <= start_sec + 35:
                        _set(lang, seen=(s["seen"]+[url])[-400:])
                        continue
                    if not gta6.stream_eligible(meta["title"], True): continue
                    # 1 clip per job: only after ready/post do we search the NEXT range.
                    # No unverified 'AI found X' uploads; the original GTA6 transcript gate stays active.
                    quality = _vod_best_quality(url) if lane["quality"] == "auto" else int(lane["quality"])
                    opts = {"max_clips": 1, "quality": quality, "min_len": 15, "max_len": 60,
                            "clip_mode": "gta6", "gta6_only_live": True, "facecam_review": False,
                            "range_start": start_sec,
                            "range_end": min(float(duration), start_sec + 600),
                            "cta_enabled": bool(lane["cta"] and not (lane["autopost"] and lane["tiktok_account"])),
                            "cta_creator_name": meta.get("uploader") or title[:50]}
                    j = jobs.create({"type":"url", "url": url, "name": title}, opts, creator=c["id"])
                    _set(lang, source_url=url, job_id=j["id"], status="rendering",
                         message="Find 1 highlight → render → post (if on) → next")
                    found = True
                    break
            except Exception as exc:
                _set(lang, error=str(exc)[-200:], message="Channel/video lookup failed; retry next cycle")
            if found: break
        if not found:
            _set(lang, status="waiting", message="No eligible GTA VI livestream or older video; checking again in 5 min")
            e.wait(POLL_SECONDS)

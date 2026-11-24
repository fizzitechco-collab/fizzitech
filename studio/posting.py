"""Post queue: decides when each finished clip goes to which account, posts it, and tracks views."""
import secrets
import re
import os
import threading
import time
from pathlib import Path

import json

from . import accounts, alerts, config, creators, ctx, jobs, live

_lock = threading.RLock()
_FILE = config.DATA_DIR / "posts.json"
try:
    _posts: list = json.loads(_FILE.read_text(encoding="utf-8")) if _FILE.exists() else []
except ValueError:
    _posts = []


def _mine() -> list:
    u = ctx.uid()
    return [p for p in _posts if p.get("user") == u]
OPEN = ("scheduled", "posting")
# "youtube_scheduled" means the PRIVATE video is already safely uploaded to
# YouTube, which will publish it at publish_at even if PeakCut is switched off.
YOUTUBE_SCHEDULED = "youtube_scheduled"


def _save():
    with _lock:
        # Distinct temp path avoids Windows shared .tmp replace races.
        tmp = _FILE.with_name(f"posts.{secrets.token_hex(4)}.tmp")
        try:
            tmp.write_text(json.dumps(_posts, indent=1), encoding="utf-8")
            for attempt in range(6):
                try:
                    os.replace(tmp, _FILE)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(.08 * (attempt + 1))
        finally:
            tmp.unlink(missing_ok=True)


def _day(t):
    return time.strftime("%Y-%m-%d", time.localtime(t))


def _mirror(p):
    """Copy the post's state onto its clip so the clip card can show it."""
    job = jobs.get(p["job"])
    clip = next((c for c in job["clips"] if c["id"] == p["clip"]), None) if job else None
    if clip is not None:
        clip.setdefault("posts", {})[p["id"]] = {k: p.get(k) for k in ("account_name", "platform", "status", "url", "due_at", "publish_at", "instagram_publish_at", "error")}
        jobs.save(job)


def _next_slot(account_id, gap_min, cap):
    """Earliest time that respects the gap between posts and the daily cap for this account."""
    mine = [p for p in _mine() if p["account"] == account_id and p["status"] in OPEN + ("posted", YOUTUBE_SCHEDULED)]
    def effective_slot(p):
        if p.get("status") == YOUTUBE_SCHEDULED and p.get("publish_at"):
            from datetime import datetime
            return datetime.fromisoformat(p["publish_at"].replace("Z", "+00:00")).timestamp()
        return p.get("posted_at") or p["due_at"]
    t = max(time.time(), max((effective_slot(p) for p in mine), default=0) + gap_min * 60)
    for _ in range(30):
        if sum(1 for p in mine if _day(effective_slot(p)) == _day(t)) < cap:
            break
        lt = time.localtime(t + 86400)
        t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 9, 0, 0, 0, 0, -1))  # 9:00 next day
    return t


def enqueue(job, clip, account_ids, now=False, youtube_publish_at=None, instagram_publish_at=None) -> list:
    c = creators.get(job["creator"]) or creators.DEFAULTS
    # YouTube remotely schedules a PRIVATE upload. Instagram only has our LOCAL
    # worker: Meta's media_publish API cannot schedule a future release.
    publish_at = accounts.youtube_publish_time(youtube_publish_at) if youtube_publish_at else None
    instagram_at = accounts.instagram_publish_time(instagram_publish_at) if instagram_publish_at else None
    if (publish_at or instagram_at) and now:
        raise ValueError("Use Add to queue when choosing a future publish time, not Post now.")
    selected = [accounts.get(aid) for aid in dict.fromkeys(account_ids)]
    selected = [acc for acc in selected if acc]
    if publish_at and not any(a["platform"] == "youtube" for a in selected):
        raise ValueError("Select your YouTube account to use YouTube scheduling.")
    if instagram_at and not any(a["platform"] == "instagram" for a in selected):
        raise ValueError("Select your Instagram account to schedule a Reel.")
    made = []
    with _lock:
        for aid in account_ids:
            acc = accounts.get(aid)
            if not acc:
                continue
            if any(p["job"] == job["id"] and p["clip"] == clip["id"] and p["account"] == aid
                   and p["status"] in OPEN + ("posted",) for p in _mine()):
                continue  # never post the same clip to the same account twice
            yt_schedule = publish_at if acc["platform"] == "youtube" else None
            ig_schedule = instagram_at if acc["platform"] == "instagram" else None
            # YouTube uploads NOW; Instagram's LOCAL worker waits until its time.
            from datetime import datetime
            if ig_schedule:
                due = datetime.fromisoformat(ig_schedule.replace("Z", "+00:00")).timestamp()
            else:
                due = time.time() if now or yt_schedule else _next_slot(aid, c["post_gap_min"], c["daily_cap"])
            p = {"id": secrets.token_hex(8), "user": ctx.uid(), "job": job["id"], "clip": clip["id"], "creator": job["creator"],
                 "account": aid, "account_name": acc["name"], "platform": acc["platform"], "status": "scheduled",
                 "due_at": due, "publish_at": yt_schedule, "instagram_publish_at": ig_schedule,
                 "created": time.time(), "title": clip.get("title") or clip.get("hook") or "Clip",
                 "score": clip.get("score", 0), "tries": 0, "url": "", "remote_id": "", "error": None, "views": None}
            _posts.append(p)
            made.append(p)
        _save()
    for p in made:
        _mirror(p)
    return made


def _auto_targets(c: dict) -> list[str]:
    """Only connected, deliberately selected posting destinations."""
    ids = list(dict.fromkeys(c.get("accounts") or []))
    chosen_youtube = c.get("youtube_account")
    if chosen_youtube:
        ids = [aid for aid in ids if (accounts.get(aid) or {}).get("platform") != "youtube"]
        ids.append(chosen_youtube)
    return [aid for aid in ids if accounts.get(aid)]


def auto_post_check(job, clip, creator=None) -> tuple[bool, str, list[str]]:
    """Single transparent explanation used by the callback and dashboard.

    This is an eligibility check, not a platform token/API verification.
    """
    cid = job.get("creator")
    if not cid:
        return False, "Video has no creator workspace. Select 'File under creator' when making clips.", []
    c = creator if creator is not None else creators.get(cid)
    if not c:
        return False, "Creator workspace no longer exists.", []
    if job.get("custom_campaign") or (job.get("options") or {}).get("clip_mode") == "expedia_ishowspeed":
        return False, "Campaign clips require manual review and posting.", []
    if clip.get("status") != "done":
        return False, "Clip is not finished rendering yet.", []
    if not c.get("autopost"):
        return False, "Creator Auto-post is OFF in Setup → Posting.", []
    if not c.get("post_rights_confirmed"):
        return False, "Confirm your permission to publish in Creator → Setup → Posting.", []
    targets = _auto_targets(c)
    if not targets:
        return False, "No connected publishing destination selected for this creator.", []
    score = float(clip.get("score") or 0)
    threshold = int(c.get("post_min_score", 75))
    if score < threshold:
        return False, f"Clip score {score:g} is below the auto-post minimum {threshold}.", []
    return True, "Eligible for auto-post queue.", targets


def on_clip_ready(job, clip):
    """Called once when a clip first finishes rendering."""
    c = creators.get(job.get("creator"))
    allowed, reason, targets = auto_post_check(job, clip, c)
    if not allowed:
        if c:
            creators.log(job.get("creator"), f"Auto-post skipped: {reason}")
        return
    made = enqueue(job, clip, targets, now=bool(c.get("gta_auto_sequential")))
    if made:
        creators.log(job.get("creator"), f"Queued for {len(made)} account(s): {clip.get('title') or clip.get('hook')}")


def diagnostics(creator_id: str) -> dict:
    """Diagnose local auto-post settings, existing queue and completed clips.

    Only server-visible user-owned records; never expose OAuth tokens.
    """
    c = creators.get(creator_id)
    if not c:
        raise KeyError(creator_id)
    targets = _auto_targets(c)
    selected = list(dict.fromkeys((c.get("accounts") or []) +
                                  ([c["youtube_account"]] if c.get("youtube_account") else [])))
    disconnected = [aid for aid in selected if not accounts.get(aid)]
    paused = bool(accounts.settings().get("paused"))
    notices = []
    if not c.get("autopost"):
        notices.append("Auto-post is OFF for this creator.")
    if not c.get("post_rights_confirmed"):
        notices.append("Permission to publish is not confirmed.")
    if not targets:
        notices.append("No connected destination is selected.")
    if disconnected:
        notices.append(f"{len(disconnected)} selected account(s) are no longer connected.")
    if paused:
        notices.append("Global posting queue is PAUSED on Home.")
    recent = []
    all_posted = _mine()
    for job in sorted((j for j in jobs.list_jobs() if j.get("creator") == creator_id),
                      key=lambda j: j.get("created", 0), reverse=True):
        for clip in reversed(job.get("clips") or []):
            if clip.get("status") != "done":
                continue
            posts = [p for p in all_posted if p.get("job") == job.get("id") and p.get("clip") == clip.get("id")]
            allowed, reason, eligible_targets = auto_post_check(job, clip, c)
            if posts:
                # Posting service records take precedence over eligibility; old jobs
                # can have been queued under settings which have since changed.
                reason = "Post records: " + ", ".join(
                    f"{p.get('platform')}: {p.get('status')}" +
                    (f" ({p.get('error')})" if p.get("status") == "failed" and p.get("error") else "")
                    for p in posts[:5])
            elif allowed:
                reason = "Eligible but not queued. Auto-post applies when a NEW clip finishes; use Post for existing clips."
            recent.append({"job": job.get("id"), "clip": clip.get("id"),
                           "title": str(clip.get("title") or clip.get("hook") or "Clip")[:110],
                           "score": clip.get("score", 0), "reason": reason,
                           "queued": bool(posts)})
            if len(recent) >= 8:
                break
        if len(recent) >= 8:
            break
    return {"creator": creator_id, "enabled": bool(c.get("autopost")),
            "rights_confirmed": bool(c.get("post_rights_confirmed")),
            "selected_accounts": len(selected), "connected_destinations": len(targets),
            "disconnected_accounts": len(disconnected), "paused": paused,
            "min_score": int(c.get("post_min_score", 75)),
            "notices": notices, "recent": recent}



# LEGEND_CREATOR_HASHTAG_V1: add the source creator's hashtag to auto-posts.
def _creator_hashtag(creator):
    """Turn a saved creator name (e.g. 'Kai Cenat') into '#KaiCenat'."""
    name = str(creator.get("name") or "").strip()
    # Names are user-controlled; keep only characters accepted by common hashtags.
    tag = "".join(re.findall(r"[^\W_]+", name, flags=re.UNICODE))[:60]
    return "#" + tag if tag and not tag.isdigit() else ""


def _with_creator_hashtag(text, hashtag, max_length=None):
    """Append once, respecting YouTube's 100-character title limit."""
    text = str(text or "").strip()
    if not hashtag or re.search(r"(?<![\w])" + re.escape(hashtag) + r"(?![\w])", text, re.IGNORECASE):
        return text[:max_length].rstrip() if max_length else text
    if max_length:
        text = text[:max(0, max_length - len(hashtag) - 1)].rstrip()
    return f"{text} {hashtag}".strip()


def _caption(clip, creator):
    tags = "" if clip.get("fixed_description") or clip.get("hashtags_in_description") else " ".join(
        "#" + str(h).lstrip("#") for h in clip.get("hashtags", []) if h)
    base = "\n\n".join(x for x in (clip.get("description", ""), tags, creator.get("post_footer", "")) if x)
    return _with_creator_hashtag(base, _creator_hashtag(creator))


def _post(p):
    job = jobs.get(p["job"])
    clip = next((c for c in job["clips"] if c["id"] == p["clip"]), None) if job else None
    acc = accounts.get(p["account"])
    try:
        if not clip or clip.get("status") != "done":
            raise RuntimeError("The clip no longer exists or is not finished.")
        if not acc:
            raise RuntimeError("That account was disconnected.")
        path = Path(job["dir"]) / "clips" / clip["file"]
        creator = creators.get(job["creator"]) or dict(creators.DEFAULTS, name="clips")
        title, cap = clip.get("title") or clip.get("hook") or "Clip", _caption(clip, creator)
        creator_tag = _creator_hashtag(creator)
        if acc["platform"] == "youtube":
            # YouTube Shorts: include the creator tag in the video title and description.
            yt_title = _with_creator_hashtag(title, creator_tag, max_length=100)
            # A resumed YouTube upload can continue after a network interruption.
            def remember_upload(session, position):
                p["youtube_session"] = session
                p["youtube_offset"] = int(position)
                _save()
            rid, url = accounts.youtube_upload(acc, path, yt_title, cap + "\n\n#Shorts", clip.get("hashtags", []), creator["privacy"],
                                               resume_session=p.get("youtube_session"), on_progress=remember_upload,
                                               publish_at=p.get("publish_at"))
            p.pop("youtube_session", None)
            p.pop("youtube_offset", None)
        elif acc["platform"] == "instagram":
            if p.get("instagram_publish_at") and time.time() > p["due_at"] + 900:
                raise RuntimeError("Instagram schedule was missed by over 15 minutes while the server was offline. "
                                   "Review this post, then press Retry to publish immediately.")
            rid, url = accounts.instagram_upload(acc, path, f"{title}\n\n{cap}", job["id"])
        elif acc["platform"] == "tiktok":
            rid, url = accounts.tiktok_upload(acc, path, f"{title}\n\n{cap}", creator["privacy"])
        else:
            raise RuntimeError("That kind of account is no longer supported.")
        if p.get("publish_at") and acc["platform"] == "youtube":
            p.update(status=YOUTUBE_SCHEDULED, uploaded_at=time.time(),
                     remote_id=rid, url=url, error=None)
            creators.log(p["creator"], f"Scheduled on YouTube for {p['publish_at']}: {title}")
        else:
            p.update(status="posted", posted_at=time.time(), remote_id=rid, url=url, error=None)
            creators.log(p["creator"], f"Posted to {acc['name']}: {title}")
    except Exception as e:  # noqa: BLE001
        p["tries"] += 1
        p["error"] = str(e)[-300:]
        overdue_instagram = bool(p.get("instagram_publish_at") and time.time() > p["due_at"] + 900)
        overdue_youtube = False
        if p.get("publish_at"):
            from datetime import datetime
            overdue_youtube = (datetime.fromisoformat(p["publish_at"].replace("Z", "+00:00")).timestamp()
                               - time.time() < 1200)
        if p["tries"] < 3 and clip and acc and not (overdue_instagram or overdue_youtube):
            p.update(status="scheduled", due_at=time.time() + 600)  # try again in 10 minutes
        else:
            p["status"] = "failed"
            creators.log(p["creator"], f"Post failed on {p['account_name']}: {p['error']}")
            alerts.notify(f"post failed on {p['account_name']} ({p['title']}): {p['error'][:200]}", kind="post")
    _save()
    _mirror(p)



# LEGEND_POST_CLEANUP_5MIN_V1
# Successful, persistent post records are the source of truth. Do not delete when
# any destination is pending/failed, and never remove an original outside the job.
POST_CLEANUP_DELAY = 300


def cleanup_published(now=None):
    """Delete only locally rendered MP4s 5 minutes after ALL posts succeed.

    No posts => no cleanup. Pending, retries, failed, or interrupted posts => no
    cleanup. Only files under job/clips matching the exact stored rendered name
    are eligible; user files, source recordings and data remain untouched.
    The published URL/post record/preview metadata are kept for the dashboard.
    """
    now = time.time() if now is None else float(now)
    cleaned = 0
    with _lock:
        by_clip = {}
        for p in _posts:
            by_clip.setdefault((p.get('user'), p.get('job'), p.get('clip')), []).append(p)
        for key, posts in by_clip.items():
            if not posts or any(p.get('status') != 'posted' or not p.get('posted_at') for p in posts):
                continue
            last_success = max(float(p['posted_at']) for p in posts)
            if last_success + POST_CLEANUP_DELAY > now:
                continue
            uid, jid, cid = key
            if not uid or not jid or not cid:
                continue
            try:
                with ctx.as_user(uid):
                    job = jobs.get(jid)
                    if not job or job.get('user') != uid:
                        continue
                    clip = next((c for c in job.get('clips', []) if c.get('id') == cid), None)
                    if not clip or clip.get('status') != 'done' or clip.get('local_deleted_at'):
                        continue
                    # Do not delete a newly re-rendered version after an older post.
                    rendered_at = float(clip.get('rendered_at') or clip.get('made_at') or 0)
                    if rendered_at and rendered_at > min(float(p['posted_at']) for p in posts):
                        continue
                    name = clip.get('file') or ''
                    if not name or Path(name).name != name or Path(name).suffix.lower() != '.mp4':
                        continue
                    directory = (Path(job['dir']) / 'clips').resolve()
                    target = (directory / name).resolve()
                    if target.parent != directory or not target.exists() or not target.is_file():
                        continue
                    # Never auto-delete media shared by another clip.
                    if any(other is not clip and other.get('file') == name for other in job.get('clips', [])):
                        continue
                    target.unlink()  # Windows AV/player lock: retry on next worker pass
                    # Long-video segment source copies are also job-only media;
                    # free these bytes only after the final destination posted.
                    stem = str(clip.get('id') or '') + '.src.'
                    for original in directory.glob(stem + '*'):
                        if (original.parent == directory and original.name.startswith(stem)
                                and original.suffix.lower() in ('.mp4', '.mkv', '.webm', '.mov')):
                            try: original.unlink()
                            except OSError: pass
                    clip['local_deleted_at'] = now
                    clip['local_cleanup_note'] = 'All chosen uploads succeeded; local clip and segment deleted 5 minutes after completion.'
                    jobs.save(job)
                    cleaned += 1
                    # Only URL jobs: when EVERY clip is posted, also free shared
                    # downloaded source/fallback video. Never delete uploads.
                    if (job.get('status') == 'done' and (job.get('source') or {}).get('type') == 'url'
                            and not job.get('source_cleanup_at') and job.get('clips')
                            and all(c.get('local_deleted_at') for c in job['clips'])):
                        base = Path(job['dir']).resolve()
                        for glob in ('source.*', 'peakcut_fallback_source.*'):
                            for original in base.glob(glob):
                                if (original.parent.resolve() == base and original.suffix.lower()
                                        in ('.mp4', '.mkv', '.webm', '.mov')):
                                    try: original.unlink()
                                    except OSError: pass
                        job['source_cleanup_at'] = now
                        jobs.save(job)
            except (OSError, PermissionError, ValueError, TypeError):
                continue
    return cleaned

def _run():
    while True:
        time.sleep(15)
        try:
            cleanup_published()
        except Exception:
            pass  # Keep posting worker healthy even when a local file is locked.
        due = [p for p in list(_posts) if p["status"] == "scheduled" and p["due_at"] <= time.time() and p.get("user")]
        for p in due:
            try:
                with ctx.as_user(p["user"]):
                    if accounts.settings()["paused"]:
                        continue
                    with _lock:
                        if p["status"] != "scheduled":
                            continue
                        p["status"] = "posting"
                    _post(p)
            except Exception as e:  # noqa: BLE001
                # A worker must never leave posts silently stuck in "posting".
                try:
                    with _lock:
                        if p.get("status") == "posting":
                            p["status"] = "failed"
                            p["error"] = ("Unexpected posting worker failure: " + str(e))[-300:]
                            _save()
                except Exception:
                    pass  # A disk failure may prevent state saving; next boot recovers it.


def _stats_for(recent):
    for aid in {p["account"] for p in recent if p["platform"] == "youtube"}:
        acc = accounts.get(aid)
        if acc:
            views = accounts.youtube_views(acc, [p["remote_id"] for p in recent if p["account"] == aid])
            for p in recent:
                if p["account"] == aid and p["remote_id"] in views:
                    p["views"] = views[p["remote_id"]]
    for p in recent:
        acc = accounts.get(p["account"]) if p["platform"] == "instagram" else None
        if acc:
            v = accounts.instagram_views(acc, p["remote_id"])
            if v is not None:
                p["views"] = v


def _stats():
    while True:
        for uid in {p.get("user") for p in _posts if p.get("user")}:
            try:
                with ctx.as_user(uid):
                    _stats_for([p for p in _mine() if p["status"] == "posted" and time.time() - p["posted_at"] < 14 * 86400])
            except Exception:  # noqa: BLE001
                pass
        _save()
        time.sleep(1800)


def cancel(pid):
    with _lock:
        p = next((p for p in _mine() if p["id"] == pid), None)
        if not p or p["status"] != "scheduled":
            raise ValueError("Only posts that are still waiting can be cancelled.")
        p["status"] = "cancelled"
        _save()
    _mirror(p)


def retry(pid):
    with _lock:
        p = next((p for p in _mine() if p["id"] == pid), None)
        if not p or p["status"] not in ("failed", "cancelled"):
            raise ValueError("Only failed or cancelled posts can be retried.")
        # Retry after a missed Instagram release is an explicit request to
        # publish NOW; never leave it stuck with the stale original schedule.
        if p.get("instagram_publish_at"):
            p["instagram_publish_at"] = None
        p.update(status="scheduled", due_at=time.time(), tries=0, error=None)
        _save()
    _mirror(p)


def overview() -> dict:
    today = _day(time.time())
    _posts = _mine()  # everything below is about the signed-in user only
    rows = []
    all_cs, all_js = creators.all_creators(), jobs.list_jobs()
    for c in all_cs:
        js = [j for j in all_js if j["creator"] == c["id"]]
        clips = [k for j in js for k in j["clips"] if k.get("status") == "done"]
        ps = [p for p in _posts if p["creator"] == c["id"]]
        views = sum(p["views"] or 0 for p in ps)
        rows.append({
            "id": c["id"], "name": c["name"],
            "state": "recording" if live.active_for(c["id"]) else "waiting" if c["auto_watch"] and c["channel"] else "idle",
            "autopost": c["autopost"] and bool(c["accounts"]),
            "clips_today": sum(1 for k in clips if _day(k.get("made_at", 0)) == today), "clips_total": len(clips),
            "posted_today": sum(1 for p in ps if p["status"] == "posted" and _day(p["posted_at"]) == today),
            "posted_total": sum(1 for p in ps if p["status"] == "posted"),
            "queued": sum(1 for p in ps if p["status"] in OPEN), "youtube_scheduled": sum(1 for p in ps if p["status"] == YOUTUBE_SCHEDULED),
            "failed": sum(1 for p in ps if p["status"] == "failed"),
            "views": views, "earnings": round(views / 1000 * c["rate_per_1k"], 2)})
    names = {c["id"]: c["name"] for c in all_cs}
    queue = sorted((p for p in _posts if p["status"] in OPEN or p["status"] == YOUTUBE_SCHEDULED),
                   key=lambda p: p["due_at"])
    done = sorted((p for p in _posts if p["status"] in ("posted", "failed")), key=lambda p: -(p.get("posted_at") or p["due_at"]))[:15]
    show = [{**{k: v for k, v in p.items() if k != "user"}, "creator_name": names.get(p["creator"], "")} for p in queue + done]
    # last 14 days, oldest first, for the home graph
    days = [_day(time.time() - 86400 * i) for i in range(13, -1, -1)]
    made, posted, views = {d: 0 for d in days}, {d: 0 for d in days}, {d: 0 for d in days}
    for j in all_js:
        for k in j["clips"]:
            d = _day(k.get("made_at") or j["created"])
            if k.get("status") == "done" and d in made:
                made[d] += 1
    for p in _posts:
        if p["status"] == "posted" and _day(p["posted_at"]) in posted:
            posted[_day(p["posted_at"])] += 1
            views[_day(p["posted_at"])] += p["views"] or 0
    daily = [{"day": d, "clips": made[d], "posted": posted[d], "views": views[d]} for d in days]
    return {"paused": accounts.settings()["paused"], "creators": rows, "posts": show, "daily": daily,
            "alerts": alerts.configured(), "recording": len(live.active_mine())}


def digest_text() -> str:
    o = overview()
    lines = ["PeakCut daily summary"]
    for r in o["creators"]:
        lines.append(f"- {r['name']}: {r['state']}, {r['clips_today']} clips today, {r['posted_today']} posted today, "
                     f"{r['queued']} waiting, {r['failed']} failed, {r['views']} views")
    if not o["creators"]:
        lines.append("No creators set up yet.")
    if o["paused"]:
        lines.append("Posting is paused.")
    return "\n".join(lines)


def start():
    with _lock:
        for p in _posts:
            if p["status"] == "posting":  # interrupted mid-upload last time
                p.update(status="failed", error="The studio closed during this upload. Check the account, then retry.")
        _save()
    jobs.on_clip_ready.append(on_clip_ready)
    threading.Thread(target=_run, daemon=True).start()
    threading.Thread(target=_stats, daemon=True).start()
    threading.Thread(target=alerts.digest_loop, args=(digest_text,), daemon=True).start()
    threading.Thread(target=alerts.keep_awake_loop,
                     args=(lambda: bool(live.active()) or any(p["status"] in OPEN for p in _posts),), daemon=True).start()

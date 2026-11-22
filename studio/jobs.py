"""Job pipeline: get video -> audio -> transcript -> AI picks -> rendered clips. One heavy task at a time."""
import collections
import json
import os
import math
import queue
import re
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path

from . import brain, campaigns, clip_taste, neon_signals, config, creators, ctx, load, media, render, roman, safe, transcribe, usage, games, hashtags

class _FairQueue:
    """Whose video is next. Each person has their own line and the lines take turns, so someone who adds ten
    videos does not make everyone else wait behind all ten. Small tasks (re-making one clip) go first."""

    def __init__(self):
        self.cv = threading.Condition()
        self.quick = collections.deque()
        self.lines = {}                       # user -> their waiting videos, oldest first
        self.turn = collections.deque()       # users with something waiting, in the order they will be served
        self.epoch = 0                        # goes up whenever the line moves
        self._pos = (0.0, {})
        self.running = 0                      # videos being worked on right now
        self.last_start = 0.0
        self.held = False                     # videos are waiting only because the machine is near full

    def _room(self) -> bool:
        """May one more video start? One always may. More only while the machine has room, and a few seconds
        after the last one started, so its weight is already showing in the measurements."""
        if self.running == 0:
            return True
        return self.running < config.JOB_WORKERS and time.time() - self.last_start > 6 and not load.busy()

    def done(self):
        with self.cv:
            self.running = max(0, self.running - 1)
            self.cv.notify_all()

    def put(self, item, user=None):
        with self.cv:
            if user is None:
                self.quick.append(item)
            else:
                if user not in self.lines:
                    self.lines[user] = collections.deque()
                    self.turn.append(user)
                self.lines[user].append(item)
            self.epoch += 1
            self.cv.notify()

    def get(self, quick_only=False):
        with self.cv:
            while True:
                if self.quick:
                    self.epoch += 1
                    return self.quick.popleft()
                if not quick_only and self.turn:
                    if self._room():
                        break
                    if not self.held:
                        self.held = True
                        self.epoch += 1
                elif self.held:
                    self.held = False
                    self.epoch += 1
                self.cv.wait(1.0)             # looked at again every second: the line moves the moment there is room
            self.epoch += 1
            self.held = False
            self.running += 1
            self.last_start = time.time()
            user = self.turn.popleft()
            item = self.lines[user].popleft()
            if self.lines[user]:
                self.turn.append(user)
            else:
                del self.lines[user]
            return item

    def remove(self, jid):
        """Remove a waiting video when cancelled, without affecting running workers."""
        with self.cv:
            for user, line in list(self.lines.items()):
                kept = collections.deque(x for x in line if not (x[0] == "job" and x[1] == jid))
                if len(kept) != len(line):
                    if kept:
                        self.lines[user] = kept
                    else:
                        del self.lines[user]
                        try:
                            self.turn.remove(user)
                        except ValueError:
                            pass
                    self.epoch += 1
                    self._pos = (0.0, {})
                    self.cv.notify_all()
                    return True
            return False

    def ahead(self) -> dict:
        """job id -> how many videos will start before it. Worked out at most once a second."""
        with self.cv:
            if time.time() - self._pos[0] < 1:
                return self._pos[1]
            out, lines, order, n = {}, {u: list(q) for u, q in self.lines.items()}, list(self.turn), 0
            depth = 0
            while order:
                nxt = []
                for u in order:
                    if depth < len(lines[u]):
                        out[lines[u][depth][1]] = n
                        n += 1
                        if depth + 1 < len(lines[u]):
                            nxt.append(u)
                order, depth = nxt, depth + 1
            self._pos = (time.time(), out)
            return out


_q = _FairQueue()
_live_q: "queue.Queue" = queue.Queue()   # live clips never wait behind a long video
_jobs: dict = {}
_by_user: dict = {}                       # user -> {job id: job}: listing one person's videos never scans everyone's
_lock = threading.RLock()
on_clip_ready: list = []   # callbacks (job, clip), run once when a clip first finishes

DEFAULTS = {"max_clips": 6, "min_len": 15, "max_len": 60, "style": "bounce", "layout": "auto", "quality": 360,
            "caption_base": "FFFFFF", "caption_active": "6BD7FF", "hook_box": "FFFFFF", "hook_text": "14100E",
            "overlay_hook_text": "", "description_text": "", "clip_mode": "gaming", "gta6_only_live": False, "facecam_review": False, "caption_language": "auto", "campaign_destination": "", "facecam_position": "auto", "facecam_size": "medium", "facecam_rect": "", "range_start": None, "range_end": None, "cta_enabled": False, "cta_creator_name": ""}  # LEGEND_GTA6_AUTO_V2


# LEGEND NEON V1: safe per-job analysis defaults
DEFAULTS['analysis_mode'] = 'fast'
DEFAULTS['scan_entire'] = False  # MAX mode: inspect the complete selected recording

LIMITS = {"max_clips": (1, 100), "min_len": (5, 120), "max_len": (10, 180)}


def clean_options(options) -> dict:
    """Only known settings, each inside its allowed range. Raises ValueError on nonsense."""
    out = {}
    for k, v in (options if isinstance(options, dict) else {}).items():
        if k not in DEFAULTS or v in ("", None):
            continue
        if k == "quality":
            v = int(v)
            if v not in (0, 360, 720, 1080, 2160):
                raise ValueError("Select Auto (up to 4K), 360p, 720p, 1080p or 4K.")
        elif k in LIMITS:
            lo, hi = LIMITS[k]
            v = max(lo, min(hi, int(float(v))))
        elif k == "style":
            v = v if v in render.STYLES else DEFAULTS["style"]
        elif k == "layout":
            v = v if v in render.LAYOUTS else DEFAULTS["layout"]
        elif k == "overlay_hook_text":
            v = creators.clean_overlay_hook(v)
        elif k == "description_text":
            v = creators.clean_description_text(v)
        elif k == "facecam_position":
            v = v if v in ("auto", "top_left", "top_right", "bottom_left", "bottom_right") else "auto"
        elif k == "facecam_size":
            v = v if v in ("small", "medium", "large") else "medium"
        elif k == "facecam_rect":
            from .facecam import parse_webcam_rect
            if str(v).strip():
                parse_webcam_rect(v)
            v = str(v).strip()[:60]
        elif k in ("gta6_only_live", "facecam_review", "cta_enabled", "scan_entire"):
            v = v is True or str(v).lower() in ("1", "true", "yes", "on")
        elif k == "cta_creator_name":
            v = str(v).strip()[:70]
        elif k == "caption_language":
            v = v if v in ("auto", "roman", "english") else "auto"
        elif k == "analysis_mode":
            v = str(v).lower()
            if v not in ("fast", "deep"):
                raise ValueError("Choose Fast or Deep analysis.")
        elif k == "clip_mode":
            v = str(v)
            if v not in campaigns.MODES:
                raise ValueError("Choose Gaming, IRL, or GTA 6 clipping mode.")
        elif k == "campaign_destination":
            v = str(v).strip()[:55]
            if v and not re.fullmatch(r"[\w\- .,']+", v):
                raise ValueError("Destination contains unsupported characters.")
        elif k in ("caption_base", "caption_active", "hook_box", "hook_text"):
            v = render._hex(v, DEFAULTS[k])
        else:                                    # range_start, range_end: seconds into the video
            v = float(v)
            if not math.isfinite(v) or v < 0:
                raise ValueError("That part of the video isn't valid.")
        out[k] = v
    if out.get("range_end") is not None and out["range_end"] <= out.get("range_start", 0):
        raise ValueError("The end of the chosen part must be after its start.")
    return out


def job_dir(jid) -> Path:
    return Path(_jobs[jid]["dir"])


HIDDEN = ("dir", "user", "source_path", "recover")


def public(job) -> dict:
    """What the browser may see: no server paths, no owner id."""
    out = {k: v for k, v in job.items() if k not in HIDDEN}
    out["source"] = {k: v for k, v in job["source"].items() if k != "path"}
    out["clips"] = [{k: v for k, v in c.items() if k not in ("src", "fixed_words", "fixed_for")} for c in job["clips"]]
    ai = job.get("ai") or {}
    out["ai"] = {"tokens": ai.get("tokens", 0), "note": ai.get("note", ""), "used": bool(ai.get("model"))}   # never the model, never raw errors
    if job.get("status") == "queued":
        n = _q.ahead().get(job["id"])
        if n:
            out["stage"] = (f"High demand right now: {n} video{'s' if n != 1 else ''} ahead of yours" if _q.held else
                            f"Waiting in line: {n} video{'s' if n != 1 else ''} ahead of yours")
        elif n == 0 and _q.held:
            out["stage"] = "High demand right now: yours is next"
    return out


def save(job):
    ctx.bump(job.get("user"))
    with _lock:
        d = Path(job["dir"])
        for _ in range(5):
            try:
                text = json.dumps(job, indent=1)
                break
            except RuntimeError:  # changed mid-dump by another thread
                time.sleep(0.05)
        else:
            return
        # Windows can briefly lock job.json while a browser, indexer or antivirus scans it.
        # Give each write its own temp file so concurrent processes cannot overwrite one another's temp data.
        tmp = d / f"job.json.{uuid.uuid4().hex}.tmp"
        try:
            tmp.write_text(text, encoding="utf-8")
            for attempt in range(12):
                try:
                    tmp.replace(d / "job.json")  # atomic on the same filesystem
                    break
                except PermissionError:
                    if attempt == 11:
                        raise  # a real permission problem should still be visible
                    time.sleep(min(0.05 * (attempt + 1), 0.5))
        finally:
            try:
                tmp.unlink(missing_ok=True)  # don't leave temp files after failed writes
            except PermissionError:
                pass  # Windows may still be holding the temporary file; never hide the original error


class JobCancelled(Exception):
    """A user requested that this video job stop."""


def _check_cancel(job):
    if job.get("cancel_requested") or job.get("status") == "cancelled":
        raise JobCancelled("Video stopped by user")


def cancel(jid):
    """Cancel a queued job immediately; running work stops at its next safe checkpoint."""
    with _lock:
        job = _jobs[jid]
        if job.get("kind") != "video" or job.get("status") not in ("queued", "running", "cancelling"):
            raise ValueError("Only queued or running videos can be stopped.")
        if job["status"] == "queued":
            _q.remove(jid)
            job.update(status="cancelled", stage="Cancelled", cancel_requested=True, error=None)
            for clip in job.get("clips", []):
                if clip.get("status") in ("queued", "rendering"):
                    clip.update(status="cancelled", error=None)
        else:
            job.update(status="cancelling", stage="Stopping after current operation…", cancel_requested=True, error=None)
        save(job)
        return job


def cancel_clip(jid, cid):
    """Stop only a queued/rendering clip; other clips in the video continue."""
    with _lock:
        job = _jobs[jid]
        clip = next((c for c in job.get("clips", []) if c.get("id") == cid), None)
        if not clip:
            raise KeyError(cid)
        if clip.get("status") not in ("queued", "rendering", "stopping"):
            raise ValueError("This clip is not currently being made.")
        if clip.get("status") == "queued":
            clip.update(status="cancelled", cancel_requested=True, error=None)
        else:
            clip.update(status="stopping", cancel_requested=True, error=None)
        save(job)
        return clip


def _check_clip(job, clip):
    _check_cancel(job)
    if clip.get("cancel_requested") or clip.get("status") == "cancelled":
        raise JobCancelled("Clip stopped by user")


def retry(jid):
    """Create a fresh video job, keeping the previous job and its completed clips."""
    old = _jobs[jid]
    if old.get("kind") != "video" or old.get("status") in ("queued", "running", "cancelling"):
        raise ValueError("Stop the active video before retrying it.")
    source = dict(old["source"])
    if source.get("type") == "file" and not Path(source.get("path") or "").is_file():
        raise ValueError("Original uploaded video is missing. Upload the file again.")
    new = create(source, dict(old["options"]), enqueue=False, creator=old.get("creator"))
    if source.get("type") == "file":
        original = Path(source["path"])
        new_path = Path(new["dir"]) / ("source" + original.suffix)
        try:
            shutil.copy2(original, new_path)
        except OSError:
            delete(new["id"])
            raise
        new["source"]["path"] = str(new_path)
    enqueue(new)
    return new


def _set(job, **kw):
    with _lock:
        _check_cancel(job)
        job.update(kw)
    save(job)


def _remap(path, folder: Path):
    """Paths saved before data moved into per-user folders (or on another machine): find the file by name."""
    if path and not Path(path).exists():
        cand = folder / Path(str(path).replace("\\", "/")).name
        if cand.exists():
            return str(cand)
    return path


def _load_file(f: Path, uid: str):
    try:
        job = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    job.update(dir=str(f.parent), user=uid)
    job.setdefault("kind", "video")
    job.setdefault("creator", None)
    if job.get("source_path"):
        job["source_path"] = _remap(job["source_path"], f.parent)
    if job.get("source", {}).get("path"):
        job["source"]["path"] = _remap(job["source"]["path"], f.parent)
    if job.get("status") in ("queued", "running", "cancelling") and job.get("kind") != "live" and not job.get("cancel_requested"):
        # Picked up again as soon as the server is back (jobs.start), from the last finished part of the transcript.
        job.update(status="queued", stage="Picking up where it stopped", error=None, resume=True)
    if job.get("cancel_requested") and job.get("status") == "cancelling":
        job.update(status="cancelled", stage="Cancelled")
    if job.get("status") == "live":
        job.update(status="done", stage="Recording paused by a server update", was_live=True)
    buffered = job.get("kind") == "live" and any((f.parent / "buffer").glob("*.ts"))
    for c in job.get("clips", []):
        if c.get("src"):
            c["src"] = _remap(c["src"], f.parent / "clips")
        if c.get("cancel_requested") and c.get("status") == "stopping":
            c["status"] = "cancelled"
        if c.get("status") in ("rendering", "queued"):
            if buffered and not c.get("src"):
                c["status"] = "queued"  # the stream is still on disk: live.recover() finishes these
                job["recover"] = True
            elif job.get("resume"):
                c["status"] = "queued"  # the video is being picked up again: this clip is made then
            elif job.get("kind") != "live" and (f.parent / "words.json").is_file():
                c["status"] = "queued"  # a single clip being re-made: jobs.start() makes it again
                job.setdefault("remake", []).append(c["id"])
            else:
                c.update(status="error", error="Interrupted by a restart. Open it and press Save and re-make.")
    _jobs[job["id"]] = job
    _by_user.setdefault(uid, {})[job["id"]] = job


def load_user(uid: str):
    d = config.USERS_DIR / uid
    for f in list((d / "jobs").glob("*/job.json")) + list((d / "creators").glob("*/*/*/job.json")):
        _load_file(f, uid)


def load_all():
    for d in config.USERS_DIR.iterdir():
        if d.is_dir():
            load_user(d.name)


def all_jobs() -> list:
    """Every user's jobs. Only for background work; never send this to a browser."""
    with _lock:
        return list(_jobs.values())


def list_jobs():
    u = ctx.uid()
    with _lock:
        return sorted((dict(j) for j in _by_user.get(u, {}).values()), key=lambda j: -j["created"])


def get(jid):
    """The job, only if it belongs to whoever this code is running for."""
    job = _jobs.get(jid)
    return job if job and job["user"] == ctx.uid() else None


def busy_count() -> int:
    u = ctx.uid()
    return sum(1 for j in list(_by_user.get(u, {}).values()) if j["kind"] == "video" and j["status"] in ("queued", "running"))


def waiting_total() -> int:
    return sum(1 for j in list(_jobs.values()) if j["kind"] == "video" and j["status"] == "queued")


def queue_epoch() -> int:
    return _q.epoch


def running_now() -> int:
    return _q.running


def create(source: dict, options: dict, enqueue=True, creator=None, kind="video") -> dict:
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:10]
    c = creators.get(creator) if creator else None
    if c:
        d = creators.root(c["id"]) / ("live" if kind == "live" else "videos") / jid
        base = {**DEFAULTS, **{k: c[k] for k in ("max_clips", "min_len", "max_len", "style", "layout", "facecam_position", "facecam_size", "facecam_rect", "cta_enabled", "cta_creator_name", "overlay_hook_text", "description_text") if k in c}}
        if kind == "live":
            base["quality"] = int(c.get("clip_quality", 1080))
            base["clip_mode"] = str(c.get("clip_mode", "gaming"))
            base["gta6_only_live"] = bool(c.get("gta6_only_live", False))
            base["facecam_review"] = bool(c.get("facecam_review", False))
    else:
        d, base, creator = config.user_dir(ctx.uid()) / "jobs" / jid, dict(DEFAULTS), None
    opts = campaigns.approved_range({**base, **clean_options(options)})
    campaigns.validate_source(source, opts)
    d.mkdir(parents=True)
    if opts["min_len"] >= opts["max_len"]:
        opts["min_len"] = max(5, opts["max_len"] - 5)
    job = {"id": jid, "user": ctx.uid(), "kind": kind, "creator": creator, "dir": str(d), "created": time.time(), "source": source,
           "options": opts, "status": "queued", "stage": "Waiting", "progress": 0.0,
           "title": source.get("name", ""), "uploader": "", "duration": 0, "clips": [], "error": None, "ai": {}}
    with _lock:
        _jobs[jid] = job
        _by_user.setdefault(job["user"], {})[jid] = job
    save(job)
    if enqueue:
        _q.put(("job", jid, None), user=job["user"])
    return job


def enqueue(job):
    save(job)
    _q.put(("job", job["id"], None), user=job["user"])


def submit(fn):
    """Run any heavy task (a render, a cleanup) on the single worker, in order."""
    _q.put(("fn", ctx.bind(fn), None))


def submit_live(fn):
    """Live-stream renders and cleanups: their own worker, so a long video can never hold them up."""
    _live_q.put(ctx.bind(fn))


def _live_worker():
    while True:
        fn = _live_q.get()
        try:
            fn()
        except Exception:  # noqa: BLE001
            traceback.print_exc()


def delete(jid):
    with _lock:
        job = _jobs.pop(jid, None)
        if job:
            _by_user.get(job["user"], {}).pop(jid, None)
    if job:
        ctx.bump(job["user"])
        shutil.rmtree(job["dir"], ignore_errors=True)
    return bool(job)


def clean_hashtags(value) -> list:
    """Accept manually edited tags without allowing HTML, separators or excess length."""
    if isinstance(value, str):
        value = value.split()
    if not isinstance(value, list):
        raise ValueError("Hashtags must be words separated by spaces.")
    tags = []
    for entry in value[:50]:
        if not isinstance(entry, (str, int)):
            continue
        tag = re.sub(r"[^A-Za-z0-9_]", "", str(entry).lstrip("#"))[:30]
        if tag and tag.lower() not in {x.lower() for x in tags}:
            tags.append(tag)
        if len(tags) >= 8:
            break
    return tags


def save_post_text(job, clip, changes: dict):
    """Save clip publishing copy without touching/re-encoding the video.
    
    Protected GTA VI/Expedia campaigns still use the existing review/re-make path.
    """
    if clip.get("status") != "done":
        raise ValueError("Wait until the clip finishes before changing its post text.")
    if clip.get("campaign_review_required") or job.get("options", {}).get("clip_mode") not in ("gaming", "irl"):
        raise ValueError("Protected campaign copy must be updated through Save and re-make clip.")
    if not isinstance(changes, dict):
        raise ValueError("Provide the post text fields.")
    new = {}
    if "title" in changes:
        new["title"] = str(changes["title"] or "")[:100].strip()
    if "description" in changes:
        new["description"] = creators.clean_description_text(changes["description"])
    if "hashtags" in changes:
        new["hashtags"] = clean_hashtags(changes["hashtags"])
    # The automatic description may already have a generated hashtag line.
    # When only the hashtag selection changed, update that line too.
    if clip.get("hashtags_in_description") and not clip.get("fixed_description") and new:
        changed_description = "description" in new and new["description"] != clip.get("description", "")
        if changed_description:
            # A human's edited copy is authoritative: do not rewrite it.
            new["fixed_description"] = True
            new["hashtags_in_description"] = False
        elif "hashtags" in new:
            text = str(clip.get("description") or "")
            old_line = " ".join("#" + str(tag).lstrip("#") for tag in clip.get("hashtags", []))
            if old_line and text.endswith(old_line):
                text = text[:-len(old_line)].rstrip()
            fresh_line = " ".join("#" + tag for tag in new["hashtags"])
            new["description"] = (text + ("\n\n" if text and fresh_line else "") + fresh_line)[:2000]
    if not new:
        raise ValueError("Choose at least one post text field.")
    with _lock:
        clip.update(new)
        save(job)
    side = Path(job["dir"]) / "clips" / f"{clip['id']}.json"
    try:
        if side.is_file():
            previous = json.loads(side.read_text(encoding="utf-8"))
            if not isinstance(previous, dict):
                previous = {}
            side.write_text(json.dumps({**previous, **new}, indent=1), encoding="utf-8")
    except (OSError, ValueError):
        pass
    return clip


def request_render(jid, cid, changes: dict):
    job = _jobs[jid]
    clip = next(c for c in job["clips"] if c["id"] == cid)
    new = dict(clip)
    for k in ("start", "end"):
        if k in changes:
            new[k] = round(float(changes[k]), 2)
    if "src_offset" in clip:  # live clip: can only move inside the saved piece of stream
        new["start"] = max(new["start"], clip["src_offset"])
        new["end"] = min(new["end"], clip["src_end"])
    if not (math.isfinite(new["start"]) and math.isfinite(new["end"])) or new["start"] < 0:
        raise ValueError("Those times aren't valid.")
    if not 3 <= new["end"] - new["start"] <= 180:
        raise ValueError("A clip can be 3 to 180 seconds long.")
    if job["options"].get("clip_mode") == campaigns.EXPEDIA_CAMPAIGN and new["start"] < campaigns.EXPEDIA_START:
        raise ValueError("This campaign only permits footage from 02:56:29 onward.")
    for k in ("hook", "title", "description", "style", "layout", "caption_base", "caption_active", "hook_box", "hook_text", "facecam_rect"):
        # Exact webcam rectangle is a source-normalized x,y,width,height string.
        if k in changes:
            new[k] = str(changes[k])[:{"hook": 60, "title": 100, "description": 2000}.get(k, 20)]
    if new.get("style") not in render.STYLES:
        new["style"] = DEFAULTS["style"]
    if new.get("layout") not in render.LAYOUTS:
        new["layout"] = DEFAULTS["layout"]
    for k in ("caption_base", "caption_active", "hook_box", "hook_text"):
        if k in new:
            new[k] = render._hex(new[k], DEFAULTS[k])
    if job["options"].get("clip_mode") == campaigns.EXPEDIA_CAMPAIGN:
        destination = str(changes.get("campaign_destination", new.get("campaign_destination", ""))).strip()[:55]
        if destination and not re.fullmatch(r"[\w\- .,']+", destination):
            raise ValueError("Destination contains unsupported characters.")
        new["campaign_destination"] = destination
        new["campaign_review_required"] = True
        if destination:
            new["hook"] = ("EXPEDIA: " + destination.upper())[:60]
            desc = str(new.get("description", ""))
            if "expedia" not in desc.lower():
                desc = "IShowSpeed and Expedia: " + desc
            if "destination:" in desc.lower():
                desc = re.sub(r"(?im)^destination:.*$", "Destination: " + destination, desc)
            else:
                desc += "\nDestination: " + destination
            new["description"] = desc[:2000]
        if "expedia" not in str(new.get("hook", "")).lower():
            new["hook"] = ("EXPEDIA: " + str(new.get("hook", "")))[:60]
        new["hashtags"] = ["IShowSpeed", "Expedia"] + [t for t in new.get("hashtags", [])
                           if str(t).lower().lstrip("#") not in ("ishowspeed", "expedia")][:6]
    if "facecam_rect" in changes:
        from .facecam import parse_webcam_rect
        rect = parse_webcam_rect(changes["facecam_rect"])
        if rect:
            new["facecam_rect"] = ",".join(str(v) for v in rect)
            new["layout"] = "facecam"
        else:
            new["facecam_rect"] = ""
    if changes.get("facecam_skip") is True:
        new.update(layout="crop", facecam_rect="", facecam_reviewed=True)
    elif "facecam_rect" in changes:
        new["facecam_reviewed"] = True
    elif clip.get("status") == "needs_facecam":
        raise ValueError("First choose a webcam rectangle, or press Skip facecam.")
    clip.update(new, status="queued", cancel_requested=False, timed_out=False, error=None)
    save(job)
    _q.put(("clip", jid, cid))


def render_one(job, clip, words):
    if job.get("cancel_requested") or clip.get("cancel_requested"):
        clip.update(status="cancelled", error=None)
        return
    d = Path(job["dir"])
    with _lock:
        if job.get("cancel_requested") or clip.get("cancel_requested"):
            clip.update(status="cancelled", error=None)
            save(job)
            return
        clip["status"] = "rendering"
        clip["phase"] = "Rendering"
        save(job)
    try:
        off = clip.get("src_offset", 0.0)
        # Long URL jobs may not retain a whole-video source_path. A timed-out
        # initial segment fetch leaves no clip src either; recover on re-make.
        existing = clip.get("src") or job.get("source_path")
        if existing and not Path(existing).is_file():
            existing = None
        if not existing:
            if (job.get("source") or {}).get("type") != "url":
                raise FileNotFoundError("Source video file is missing. Restore the original upload to re-make this clip.")
            _refetch_clip_source(job, clip)
            existing = clip["src"]
        src = Path(existing)
        off = clip.get("src_offset", 0.0)
        if not clip.get("src"):
            clip["end"] = min(clip["end"], job["duration"])
        local = dict(clip, start=clip["start"] - off, end=clip["end"] - off,
                     hook=roman.to_roman(clip.get("hook") or ""), quality=job["options"].get("quality", 360),
                     facecam_position=clip.get("facecam_position", job["options"].get("facecam_position", "auto")),
                     facecam_size=clip.get("facecam_size", job["options"].get("facecam_size", "medium")),
                     facecam_rect=clip.get("facecam_rect", job["options"].get("facecam_rect", "")))
        # Ask for a manual webcam panel before expensive encoding, when requested.
        # The preview lives beside this clip in its protected job folder.
        if clip.get("facecam_review") and not clip.get("facecam_reviewed"):
            preview = d / "clips" / f"{clip['id']}-facecam.jpg"
            preview.parent.mkdir(parents=True, exist_ok=True)
            if not preview.is_file():
                moment = max(0.1, (local["start"] + local["end"]) / 2)
                media.run(["ffmpeg", "-y", "-nostdin", "-v", "error", "-ss", f"{moment:.2f}",
                           "-i", str(src), "-frames:v", "1", "-vf", "scale=960:-2",
                           "-q:v", "4", str(preview)])
            clip.update(status="needs_facecam", phase="Select webcam or skip", facecam_preview=preview.name)
            save(job)
            return
        span = [round(clip["start"], 2), round(clip["end"], 2), "lang:" + job.get("options", {}).get("caption_language", "auto")]      # keep caption-language cached correctly
        if clip.get("fixed_for") == span and clip.get("fixed_words") and not any(
                roman.needs_roman(w.get("w", "")) for w in clip["fixed_words"]):
            raw = clip["fixed_words"]          # already tidied for this exact span: no second AI call
        else:
            raw = [w for w in words if clip["start"] - 1 <= w["s"] <= clip["end"] + 1]
            try:
                usage.set_context(job.get("creator"), job.get("title") or "")
                cap_lang = job.get("options", {}).get("caption_language", "auto")
                if cap_lang == "english" and brain.needs_translation(job.get("lang") or ""):
                    raw = brain.translate_caption_words(raw, job.get("lang") or "", job.get("title") or "")
                else:
                    raw = brain.english_captions(raw, job.get("lang") or "", job.get("title") or "",
                                                 youtube_english=lambda: _english_part(job, clip))
                clip.update(fixed_words=raw, fixed_for=span)
            except Exception:  # noqa: BLE001 - captions still render with the words as heard
                pass
        # the last word on it: whatever was said, nothing is drawn in Hindi or Urdu script
        near = [dict(w, s=w["s"] - off, e=w["e"] - off) for w in roman.words(raw)]
        out = render.render_clip(src, d / "clips", clip["id"], local, near, job["width"], job["height"],
                                 cancelled=lambda: bool(job.get("cancel_requested") or clip.get("cancel_requested")))
        _check_clip(job, clip)
        clip.update(out, status="done", version=clip.get("version", 0) + 1, error=None, rendered_at=time.time())
        post = {k: clip[k] for k in ("title", "description", "hashtags", "hook", "start", "end", "score")}
        (d / "clips" / f"{clip['id']}.json").write_text(json.dumps(post, indent=1), encoding="utf-8")
        if clip["version"] == 1:
            clip.setdefault("made_at", time.time())
            creators.log(job["creator"], f"Clip ready (score {clip['score']}): {clip['title'] or clip['hook']}")
            save(job)
            # Paid campaign clips always require manual compliance review before posting.
            # Do not send them to creator auto-post callbacks.
            if job["options"].get("clip_mode") != campaigns.EXPEDIA_CAMPAIGN:
                for fn in on_clip_ready:
                    try:
                        fn(job, clip)
                    except Exception:  # noqa: BLE001
                        traceback.print_exc()
    except (JobCancelled, media.DownloadCancelled):
        if not clip.get("timed_out"):
            clip.update(status="cancelled", error=None)
    except Exception as e:  # noqa: BLE001
        clip.update(status="error", error=safe.friendly(e, 400))
        creators.log(job["creator"], f"Clip failed: {safe.friendly(e, 200)}")
    if not job.get("cancel_requested"):
        save(job)


CLIP_MINUTES = float(config.env("PEAKCUT_CLIP_MINUTES", "30"))     # the longest one clip may take to make


def _wait_for_clips(job, futures, began, workers):
    """Wait for a video's clips, but not for ever. A clip that hangs (a download that stalls, an encoder that
    freezes) used to keep the whole video "in progress", and no other clip could be re-made. Now it is marked as
    failed after CLIP_MINUTES and the video finishes with the clips that did work."""
    left, given_up = list(futures), 0
    shown = None
    late = "This clip took too long and was stopped. Open it and press Save and re-make to try again."
    while left:
        _check_cancel(job)
        still = []
        for f, clip in left:
            if clip.get("cancel_requested"):
                if f.done():
                    try:
                        f.result()
                    except JobCancelled:
                        pass
                continue
            if f.done():
                f.result()
                continue
            t = began.get(clip["id"])
            if (t and time.time() - t > CLIP_MINUTES * 60) or (not t and given_up >= workers):
                given_up += 1
                # Ask the underlying bounded downloader/encoder to kill its own process tree.
                clip.update(status="error", error=late, cancel_requested=True, timed_out=True)
                creators.log(job["creator"], f"Clip stopped after {CLIP_MINUTES:g} minutes: {clip.get('title') or clip.get('hook') or clip['id']}")
                save(job)
                continue
            still.append((f, clip))
        left = still
        # Progress in the final stage is measured by actual finished clips, not elapsed time.
        # Keep failures visible separately so 3 done + 1 failed is not advertised as 4 done.
        clips = job.get("clips", [])
        total = len(clips)
        done = sum(c.get("status") == "done" for c in clips)
        failed = sum(c.get("status") in ("error", "cancelled") for c in clips)
        finished = done + failed
        active = next(((i, c) for i, c in enumerate(clips, 1)
                       if c.get("status") in ("queued", "rendering") and
                       any(c is fc for _, fc in left)), None)
        detail = (f"{active[1].get('phase') or 'Preparing'} clip {active[0]} of {total}"
                  if active else ("Finalizing video" if total else "No clips found"))
        progress_info = {"done": done, "total": total, "failed": failed,
                         "active": detail, "finished": finished}
        current = (done, total, failed, detail)
        if current != shown:
            _set(job, stage="Finishing the clips", progress=max(0.92, min(0.99, 0.92 + 0.07 * finished / max(1, total))),
                 clip_progress=progress_info)
            shown = current
        if left:
            time.sleep(1)


def _english_part(job, clip):
    """YouTube's English captions for just this clip, for a video in another language. Fetched once per video."""
    if (job.get("source") or {}).get("type") != "url":
        return None
    f = Path(job["dir"]) / "words_en.json"
    if f.is_file():
        en = json.loads(f.read_text(encoding="utf-8"))
    else:
        try:
            en = media.youtube_english_words(job["source"]["url"]) or []
        except Exception:  # noqa: BLE001 - YouTube often refuses its translations: the AI translates instead
            en = []
        f.write_text(json.dumps(en), encoding="utf-8")       # asked once per video, refused or not
    return [w for w in en if clip["start"] - 0.5 <= w["s"] <= clip["end"] + 0.5]


LONG_VIDEO = 40 * 60   # above this, fetch only the pieces that become clips
PAD = 8                # seconds kept either side of a fetched piece, so clips can be re-trimmed


def _fetch_piece(job, clip, full_audio):
    """Long-video segment fetch; retries and fallback without repeating AI highlight selection."""
    d = Path(job["dir"])
    o = job["options"]

    def update_stage(detail):
        if not (job.get("cancel_requested") or clip.get("cancel_requested")) and clip.get("phase") != detail:
            clip["phase"] = detail
            save(job)

    try:
        _check_clip(job, clip)
        want = max(0.0, clip["start"] - PAD)
        piece = media.download_section(job["source"]["url"], d / "clips", f"{clip['id']}.src", want,
                                       min(job["duration"], clip["end"] + PAD), int(o["quality"]),
                                       cache_dir=d, cancelled=lambda: bool(job.get("cancel_requested") or clip.get("cancel_requested")),
                                       stage=update_stage)
        _check_clip(job, clip)
        update_stage("Checking downloaded clip")
        wav = d / "clips" / f"{clip['id']}.wav"
        media.extract_audio(piece, wav)
        part = media.load_audio(wav)
        wav.unlink(missing_ok=True)
        meta = media.probe(piece)
        clip["source_resolution"] = f"{meta['width']}x{meta['height']}"
        off = media.find_offset(full_audio, part, want)
        clip.update(src=str(piece), src_offset=round(off, 2), src_end=round(off + meta["duration"], 2))
        clip["start"], clip["end"] = max(clip["start"], clip["src_offset"]), min(clip["end"], clip["src_end"])
        job.setdefault("width", meta["width"])
        job.setdefault("height", meta["height"])
    except (JobCancelled, media.DownloadCancelled):
        if not clip.get("timed_out"):
            clip.update(status="cancelled", error=None)
        raise JobCancelled("Clip stopped")
    except Exception as e:  # noqa: BLE001
        clip.update(status="error", error=f"Could not fetch this part of the video: {safe.friendly(e, 250)}")
        save(job)


def _refetch_clip_source(job, clip):
    """Re-fetch a missing YouTube clip section when an original download timed out.

    The start of the segment is approximate if no full-audio reference remains;
    the seek may land on an earlier video keyframe.
    """
    d = Path(job["dir"])
    start = max(0.0, float(clip["start"]) - PAD)
    end = min(float(job["duration"]), float(clip["end"]) + PAD)
    if end <= start:
        raise ValueError("Invalid clip time range; cannot re-fetch this clip.")
    piece = media.download_section(job["source"]["url"], d / "clips", f"{clip['id']}.src", start,
                                   end, int(job["options"]["quality"]), cache_dir=d,
                                   cancelled=lambda: bool(job.get("cancel_requested") or clip.get("cancel_requested")),
                                   stage=lambda phase: clip.update(phase=phase))
    meta = media.probe(piece)
    clip.update(src=str(piece), src_offset=round(start, 2),
                src_end=round(start + meta["duration"], 2))
    job.setdefault("width", meta["width"])
    job.setdefault("height", meta["height"])
    save(job)


BLOCK = 10 * 60         # long videos are transcribed and clipped one block at a time
PROGRESSIVE_FROM = 20 * 60


def _covers(words: list, start: float, end: float) -> bool:
    """Is a borrowed transcript good enough to find clips with? It has to reach the end of the part being clipped
    and have a normal amount of talking in it; otherwise our own model writes the transcript."""
    inside = [w for w in words if start <= w["s"] <= end]
    minutes = max(0.5, (end - start) / 60)
    return len(inside) >= 25 * minutes and inside[-1]["s"] >= start + 0.85 * (end - start)


def _scan_quota_met(job) -> bool:
    """Fixed clip counts stop once enough moments are chosen; MAX scans all."""
    options = job["options"]
    return (not options.get("scan_entire")
            and len(job["clips"]) >= int(options["max_clips"]))


def _run_job(job):
    _check_cancel(job)
    import math
    from concurrent.futures import ThreadPoolExecutor
    d = Path(job["dir"])
    o = job["options"]
    # Ratings only steer this creator's future videos, never unrelated niches.
    taste_weights = clip_taste.profile([j for j in list_jobs() if j.get("creator") == job.get("creator")])
    src = job["source"]
    t0 = time.time()
    notes = []
    usage.set_context(job["creator"], job["title"] or src.get("name"))
    resuming = bool(job.pop("resume", False)) and (d / "words.json").is_file()
    if resuming:   # after a restart: keep the transcript parts, clips and AI answers already made, and carry on
        _set(job, status="running", stage="Picking up where it stopped", error=None)
    else:
        _set(job, status="running", stage="Getting the audio", progress=0.03, error=None, clips=[], ai={}, done_blocks=0)
    if not transcribe.model_ready() and not transcribe.REMOTE:
        from . import fetch_model
        _set(job, stage="Getting the speech model (one time, about 480 MB)")
        fetch_model.ensure()
        _set(job, stage="Getting the audio")
    fetch = ThreadPoolExecutor(1)
    video = None
    fast_audio = False
    if src["type"] == "url":
        meta = media.info(src["url"])
        if meta["kind"] != "video":
            raise RuntimeError("That link is a channel or playlist, not a single video. Paste the link of one video.")
        if ((o["range_end"] or meta["duration"]) - (o["range_start"] or 0)) > config.MAX_VIDEO_HOURS * 3600:
            raise RuntimeError(f"That is longer than {config.MAX_VIDEO_HOURS:g} hours. Choose a shorter part of it under Options.")
        if meta["is_live"]:
            raise RuntimeError("This link is a live stream, so it would never finish downloading. Open the creator, "
                               "put this link under Setup, and press Start recording instead.")
        _set(job, title=meta["title"], uploader=meta["uploader"], duration=meta["duration"])
        if not job.get("thumb") and media.save_thumb(d, url=src["url"]):
            _set(job, thumb=True)
        usage.set_context(job["creator"], meta["title"])
        span = (o["range_end"] or meta["duration"]) - (o["range_start"] or 0)
        pieces = (config.env("PEAKCUT_SEGMENTS_ONLY", "1") == "1" or span > LONG_VIDEO or meta["duration"] <= 0)
        # Small requested counts scan short audio sections and stop once enough
        # good highlights are selected. MAX keeps the full-range analysis.
        fast_audio = (int(o["max_clips"]) <= 10 and not o.get("scan_entire")
                      and span > 180 and meta["duration"] > 180
                      and config.env("PEAKCUT_SMART_AUDIO", "1") != "0")
        # A job started on an older release used 10-minute blocks.
        # Do not reinterpret its saved done_blocks as 3-minute blocks.
        if fast_audio and resuming and job.get("scan_block_seconds") != 180:
            fast_audio = False
        if fast_audio:
            pieces = True
            job["scan_block_seconds"] = 180
        if not pieces:  # shorter video: fetch all of it in the background while the audio is worked on
            video = fetch.submit(media.download, src["url"], d, int(o["quality"]))
        if fast_audio:
            from .progressive_audio import ProgressiveAudio
            audio = ProgressiveAudio(src["url"], d, meta["duration"],
                                     cancelled=lambda: bool(job.get("cancel_requested")))
            _set(job, stage="Scanning audio in small sections")
        else:
            audio_file = media.download_audio(src["url"], d, lambda p: _set(job, progress=0.03 + 0.1 * p),
                                              cancelled=lambda: bool(job.get("cancel_requested")))
    else:
        pieces, audio_file = False, Path(src["path"])
        info = media.probe(audio_file)
        if info["duration"] > config.MAX_VIDEO_HOURS * 3600:
            raise RuntimeError(f"That video is longer than {config.MAX_VIDEO_HOURS:g} hours, which is the limit.")
        _set(job, source_path=str(audio_file), width=info["width"], height=info["height"], duration=info["duration"])
        if not job.get("thumb") and media.save_thumb(d, video=audio_file):
            _set(job, thumb=True)
    if not fast_audio:
        wav = d / "audio.wav"
        media.extract_audio(audio_file, wav,
                            cancelled=lambda: bool(job.get("cancel_requested")))
        audio = media.load_audio(wav)
        wav.unlink(missing_ok=True)
        if src["type"] == "url":
            audio_file.unlink(missing_ok=True)
    if not job["duration"]:
        job["duration"] = len(audio) / 16000
    lo = int((o["range_start"] or 0) * 16000)
    hi = min(len(audio), int(o["range_end"] * 16000)) if o["range_end"] else len(audio)
    span = (hi - lo) / 16000
    db = None if fast_audio else media.loudness_per_second(audio[lo:hi])

    vlock, vstate = threading.Lock(), {}

    def whole_video():
        """Wait for the background download once; retry it, or give up and use pieces."""
        with vlock:
            if "path" not in vstate:
                path = None
                try:
                    path = video.result()
                except Exception as e:  # noqa: BLE001 - sites sometimes refuse a download
                    notes.append(f"Video download refused once ({str(e)[-80:]}), retrying")
                    try:
                        path = media.download(src["url"], d, int(o["quality"]))
                    except Exception as e2:  # noqa: BLE001
                        notes.append(f"Whole-video download failed ({str(e2)[-80:]}), fetching clip parts instead")
                if path:
                    info = media.probe(path)
                    job.update(source_path=str(path), width=info["width"], height=info["height"])
                vstate["path"] = path
            return vstate["path"]

    game_name, _ = games.detect(job.get("title", ""), job.get("uploader", ""))
    exact = {}      # clip id -> (from, to, words): our own model's words for just that clip

    began = {}      # clip id -> when work on it started

    def make(clip, words_now):
        if clip.get("cancel_requested") or job.get("cancel_requested"):
            clip.update(status="cancelled", error=None)
            return
        began[clip["id"]] = time.time()
        if src["type"] == "url" and (pieces or not whole_video()):
            clip["phase"] = "Downloading"
            save(job)
            _check_clip(job, clip)
            try:
                _fetch_piece(job, clip, audio)
            except JobCancelled:
                if not clip.get("timed_out"):
                    clip.update(status="cancelled", error=None)
                save(job)
                return
        if o.get("analysis_mode", "fast") == "deep" and not clip.get("visual_checked") and not clip.get("cancel_requested") and clip.get("status") != "error":
            # Analyze only this selected, local clip (max 9 seconds at 160x90, 2fps).
            visual_source = clip.get("src") or job.get("source_path") or src.get("path")
            if visual_source:
                offset = float(clip.get("src_offset") or 0)
                visual = neon_signals.analyze(visual_source, clip["start"] - offset, clip["end"] - offset)
                clip["visual_checked"] = True
                if visual:
                    clip["visual_score"] = visual["action_score"]
                    clip["visual_cuts"] = visual["cuts"]
                    clip["visual_bonus"] = neon_signals.boost(visual)
                    clip["score"] = min(100, max(0, int(clip.get("score") or 0) + clip["visual_bonus"]))
                save(job)
        if not clip.get("cancel_requested") and clip["status"] != "error" and yt and yt[1].lower().startswith("en"):
            # The clip was found with YouTube's transcript. What is shown on screen comes from our own model,
            # run on just this clip: full punctuation, nothing blanked out, timings to the word.
            a0, b0 = max(lo, int((clip["start"] - 1.5) * 16000)), min(hi, int((clip["end"] + 1.5) * 16000))
            try:
                tw = [dict(w, s=round(w["s"] + a0 / 16000, 2), e=round(w["e"] + a0 / 16000, 2)) for w in transcribe.transcribe(audio[a0:b0])]
            except Exception:  # noqa: BLE001 - the clip is still made, with YouTube's words
                tw = []
            if len(tw) >= 3:
                exact[clip["id"]] = (a0 / 16000, b0 / 16000, tw)
                words_now = tw
        if not clip.get("cancel_requested") and clip["status"] != "error":
            render_one(job, clip, words_now)

    cpus = os.cpu_count() or 4
    # On a desktop, downloading multiple separate segments of a 3-hour VOD at once
    # causes repeated seeks and saturates RAM/network; default to one clip at a time.
    render_workers = max(1, min(4, int(config.env("PEAKCUT_RENDER_WORKERS", "1"))))
    renders = ThreadPoolExecutor(render_workers)
    futures = []
    step = (180 * 16000 if fast_audio else BLOCK * 16000 if span > PROGRESSIVE_FROM else hi - lo)
    blocks = [(x, min(hi, x + step)) for x in range(lo, hi, step)] or [(lo, hi)]
    words, tokens, model = [], 0, None
    done_blocks = 0
    yt = None
    if src["type"] == "url" and config.YT_TRANSCRIPT and media.is_youtube(src["url"]):
        try:
            yt = media.youtube_words(src["url"])
        except Exception:  # noqa: BLE001 - no transcript to borrow: ours is written as usual
            yt = None
        if yt and not _covers(yt[0], lo / 16000, hi / 16000):
            yt = None
        job["transcript_from"] = "youtube" if yt else "own"
        job["lang"] = yt[1] if yt else ""          # the language spoken, when YouTube says (decides the captions)
    if resuming:
        try:
            words = json.loads((d / "words.json").read_text(encoding="utf-8"))
        except ValueError:
            words = []
        done_blocks = min(int(job.get("done_blocks", 0)), len(blocks)) if words else 0
        tokens, model = int((job.get("ai") or {}).get("tokens", 0)), (job.get("ai") or {}).get("model")
        if done_blocks < len(blocks):     # words past the last finished part are transcribed again
            cut = blocks[done_blocks][0] / 16000
            words = [w for w in words if w["s"] < cut]
        for c in job["clips"]:            # clips found before the restart that were not finished yet
            if c.get("status") not in ("done", "error"):
                c["status"] = "queued"
                futures.append((renders.submit(ctx.bind(make), c, list(words)), c))
        save(job)
    # The transcript of the next part is written while the AI is still reading this one (the AI is a wait on the
    # network, the transcript is work on this machine), so neither waits for the other.
    ahead = ThreadPoolExecutor(2, thread_name_prefix="ahead")
    heard, now_on = {}, [done_blocks]

    def hear(i):
        if i < len(blocks) and i >= done_blocks and i not in heard:
            a_, b_ = blocks[i]
            last = [0.0]

            def tp(p, i=i, a_=a_, b_=b_):
                if now_on[0] == i and p - last[0] > 0.05:      # only the part being shown moves the bar
                    last[0] = p
                    _set(job, progress=max(job["progress"], 0.14 + 0.78 * ((a_ - lo) + p * (b_ - a_)) / max(1, hi - lo)))
            heard[i] = ahead.submit(ctx.bind(transcribe.transcribe), audio[a_:b_], tp)

    for bi, (a, b) in enumerate(blocks):
        _check_cancel(job)
        if bi < done_blocks:
            continue                      # transcribed and checked by the AI before the restart
        shift = a / 16000
        where = f" (minute {round((a - lo) / 16000 / 60)} of {round(span / 60)})" if len(blocks) > 1 else ""
        if yt:
            _set(job, stage="Reading the transcript" + where)
            bw = [dict(w, s=round(w["s"] - shift, 2), e=round(w["e"] - shift, 2)) for w in yt[0] if a / 16000 <= w["s"] < b / 16000]
        else:
            _set(job, stage="Writing the transcript" + where)
            now_on[0] = bi
            hear(bi)
            if not fast_audio:  # never pre-download audio beyond the desired highlights
                hear(bi + 1)
            bw = heard.pop(bi).result()
        _set(job, progress=max(job["progress"], 0.14 + 0.78 * (b - lo) / max(1, hi - lo)))
        words += [dict(w, s=round(w["s"] + shift, 2), e=round(w["e"] + shift, 2)) for w in bw]
        (d / "words.json").write_text(json.dumps(words), encoding="utf-8")
        _set(job, stage="Finding the best moments" + where, word_count=len(words))
        left = int(o["max_clips"]) - len(job["clips"])
        if left <= 0 or len(bw) < 8:
            job["done_blocks"] = bi + 1
            save(job)
            if _scan_quota_met(job):
                break
            continue
        quota = max(1, math.ceil(left / (len(blocks) - bi)))
        # Uploaded/local videos: rerank up to 12 AI candidates by visual motion
        # before picking winners. A remote URL is still segment-only.
        visual_ranker = None
        if o.get("analysis_mode") == "deep":
            local_source = job.get("source_path") or src.get("path")
            if local_source and Path(local_source).is_file():
                budget = [0]
                def visual_ranker(candidate, video=local_source, base=shift, budget=budget):
                    if "_visual_info" not in candidate:
                        if budget[0] >= 12:
                            return 0
                        try:
                            rs, re = float(candidate.get("start", 0)), float(candidate.get("end", 0))
                            if not (0 <= rs < re <= (b - a) / 16000 + 5):
                                return 0
                        except (ValueError, TypeError):
                            return 0
                        budget[0] += 1
                        candidate["_visual_info"] = neon_signals.analyze(video, base + rs, base + re, timeout=10)
                    return neon_signals.boost(candidate["_visual_info"])
        s0 = int((a - lo) / 16000)
        levels = (media.loudness_per_second(audio[a:b]) if fast_audio
                  else db[s0: s0 + int((b - a) / 16000) + 1])
        found, ai = brain.find_clips(bw, levels, (b - a) / 16000, job["title"],
                                     job["uploader"], quota, int(o["min_len"]), int(o["max_len"]), notes.append,
                                     clip_mode=o.get("clip_mode", "gaming"), campaign_destination=o.get("campaign_destination", ""),
                                     gta6_only_live=o.get("gta6_only_live", False), taste_weights=taste_weights,
                                     visual_ranker=visual_ranker, game=game_name)
        tokens += ai.get("tokens", 0)
        model = ai.get("model") or model
        if ai.get("note"):
            notes.append(ai["note"])
        for c in found:
            c.update(id=f"clip{len(job['clips']) + 1:02d}", start=round(c["start"] + shift, 2),
                     end=round(c["end"] + shift, 2), style=o["style"], layout=o["layout"], caption_base=o.get("caption_base", "FFFFFF"),
                     caption_active=o.get("caption_active", "6BD7FF"), hook_box=o.get("hook_box", "FFFFFF"),
                     hook_text=o.get("hook_text", "14100E"), facecam_review=o.get("facecam_review", False), cta_enabled=o.get("cta_enabled", False), cta_creator_name=o.get("cta_creator_name") or job.get("uploader", ""), status="queued", version=0)
            # Upstream creator-wide campaign copy. Keep the existing hook_text
            # field as a COLOR; the new overlay_hook_text is the actual headline.
            # Protected GTA VI/Expedia campaigns retain their own rules/copy.
            if o.get("clip_mode") in ("gaming", "irl") and not o.get("campaign_destination"):
                if o.get("overlay_hook_text"):
                    c["hook"] = o["overlay_hook_text"]
                if o.get("description_text"):
                    c["description"] = o["description_text"]
                    c["fixed_description"] = True
            if o.get("clip_mode") == "gaming" and game_name and not c.get("fixed_description"):
                # Upstream game tags, but keep special GTA6 and Expedia campaign copy intact.
                block_words = [dict(w, s=w["s"] + shift) for w in bw]
                hashtags.apply(c, block_words, job["title"], job["uploader"], game_name)
            job["clips"].append(c)
            futures.append((renders.submit(ctx.bind(make), c, list(words)), c))
        job["ai"] = {"model": model, "tokens": tokens, "note": "", "log": notes[-5:]}
        job["done_blocks"] = bi + 1       # a restart from here on carries on with the next part
        save(job)
        if _scan_quota_met(job):
            notes.append(f"Stopped audio analysis after finding {len(job['clips'])} requested clips.")
            break
    _check_cancel(job)
    if futures:
        _set(job, stage="Finishing the clips", progress=max(job["progress"], 0.92),
             clip_progress={"done": sum(c.get("status") == "done" for c in job["clips"]),
                            "total": len(job["clips"]), "failed": 0,
                            "active": "Preparing clips", "finished": 0})
    _wait_for_clips(job, futures, began, renders._max_workers)
    _check_cancel(job)
    if exact:           # keep our own words for the clips in the saved transcript, so editing a clip later uses them
        for a_s, b_s, tw in exact.values():
            words = [w for w in words if not a_s <= w["s"] < b_s] + tw
        words.sort(key=lambda w: w["s"])
        (d / "words.json").write_text(json.dumps(words), encoding="utf-8")
    renders.shutdown(wait=False)
    ahead.shutdown(wait=False)
    fetch.shutdown(wait=False)
    del audio
    clips = job["clips"]
    job["ai"] = {"model": model, "tokens": tokens, "log": notes[-5:],
                 "note": "The AI was unavailable, so clips were picked by loudness only." if clips and not model else ""}
    ready = sum(c.get("status") == "done" for c in clips)
    failed = sum(c.get("status") == "error" for c in clips)
    if clips and not ready:
        # AI can find excellent moments even when YouTube segment fetching is blocked.
        # Don't report the job as successfully finished when no actual MP4 was produced.
        _set(job, status="error", stage="No clips could be downloaded", progress=1.0,
             error="Highlight selection finished, but video segments could not be fetched. Try uploading the source MP4.",
             took=round(time.time() - t0))
    else:
        stage = ((f"Done: {ready} clips ready, {failed} failed" if failed else "Done")
                 if clips else "Done, but nothing clip-worthy was found")
        _set(job, status="done", stage=stage, progress=1.0, took=round(time.time() - t0))
    try:
        from . import notices
        name = job.get("title") or job["source"].get("name") or "your video"
        notices.add(job.get("user"), "clips", f"{len(clips)} clip{'s' if len(clips) != 1 else ''} ready" if clips else "Nothing clip-worthy found",
                    name, f"/app/creators/{job['creator']}" if job.get("creator") else "/app/videos")
    except Exception:  # noqa: BLE001
        pass
    creators.log(job["creator"], f"Video finished with {len(clips)} clips in {round(time.time() - t0)}s: {job['title']}")


def _worker(quick_only=False):
    while True:
        kind, a, cid = _q.get(quick_only)
        if kind == "fn":
            try:
                a()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            continue
        job = _jobs.get(a)
        if job and kind == "job" and job.get("cancel_requested"):
            _q.done()
            continue
        if not job:
            if kind == "job":
                _q.done()
            continue
        token = ctx._uid.set(job["user"])  # everything this job does runs as its owner
        try:
            if kind == "job":
                _run_job(job)
            else:
                words = json.loads((Path(job["dir"]) / "words.json").read_text(encoding="utf-8"))
                clip = next(c for c in job["clips"] if c["id"] == cid)
                if not clip.get("cancel_requested"):
                    render_one(job, clip, words)
                # A successful re-make should clear the parent video's old all-failed status,
                # without re-running the transcript/Gemini analysis or altering completed files.
                if job.get("kind") == "video" and job.get("status") in ("done", "error", "cancelled"):
                    if not any(c.get("status") in ("queued", "rendering", "stopping") for c in job["clips"]):
                        ready = sum(c.get("status") == "done" for c in job["clips"])
                        failed = sum(c.get("status") in ("error", "cancelled") for c in job["clips"])
                        if ready:
                            job.update(status="done", error=None, stage=(f"Done: {ready} ready, {failed} failed"
                                           if failed else "Done"), progress=1.0)
                            save(job)
        except JobCancelled:
            if kind == "clip":
                if not clip.get("timed_out"):
                    clip.update(status="cancelled", error=None)
                save(job)
        except Exception as e:  # noqa: BLE001
            (Path(job["dir"]) / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
            if kind == "job":
                for c in job["clips"]:
                    if c.get("status") in ("queued", "rendering"):
                        c.update(status="error", error="The video stopped before this clip was made.")
                _set(job, status="error", error=safe.friendly(e), stage="Stopped")
                creators.log(job["creator"], f"Video failed: {safe.friendly(e)[:200]}")
        finally:
            if kind == "job" and job.get("cancel_requested"):
                job.update(status="cancelled", stage="Cancelled", error=None)
                for clip in job.get("clips", []):
                    if clip.get("status") in ("queued", "rendering"):
                        clip.update(status="cancelled", error=None)
                try:
                    save(job)
                except OSError:
                    traceback.print_exc()
            ctx._uid.reset(token)
            if kind == "job":
                _q.done()


def _pick_up_after_restart():
    """Videos and single clips that were being made when the server stopped: queued again, oldest first."""
    waiting = sorted((j for j in all_jobs() if j.get("status") == "queued" and j.get("resume")), key=lambda j: j["created"])
    for j in waiting:
        _q.put(("job", j["id"], None), user=j["user"])
    for j in all_jobs():
        for cid in j.pop("remake", []):
            _q.put(("clip", j["id"], cid))
        if j.get("status") == "done":
            save(j)


def start():
    load.start()
    load_all()
    _pick_up_after_restart()
    for _ in range(max(1, config.JOB_WORKERS)):
        threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_worker, args=(True,), daemon=True).start()   # re-making a single clip never waits behind whole videos
    threading.Thread(target=_live_worker, daemon=True).start()

"""Explicit opt-in 5-minute livestream-link watcher for the signed-in user's account.

Monitoring runs while the server is running. No externally hosted scheduler and
no background job when PeakCut is shut down. The session becomes a normal creator
live job when the stream is found, preserving user data and Stop semantics.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from . import creators, ctx, live, media

INTERVAL = 300
_LOCK = threading.RLock()
_WATCHES = {}


@dataclass
class Watch:
    id: str
    uid: str
    url: str
    creator_id: str
    status: str = "checking"
    error: str = ""
    last_check: float = 0.
    next_check: float = 0.
    job_id: str = ""
    stop_event: threading.Event = field(default_factory=threading.Event)

    def public(self):
        return {"id": self.id, "url": self.url, "creator_id": self.creator_id,
                "status": self.status, "error": self.error[-180:], "job_id": self.job_id,
                "last_check": self.last_check, "next_check": self.next_check,
                "interval_seconds": INTERVAL}


def mine():
    with _LOCK:
        return [w.public() for w in _WATCHES.values() if w.uid == ctx.uid()]


def start(url, options):
    url = live.normalize(url)
    if not media.site_allowed(url):
        raise ValueError("A valid YouTube, Twitch or Kick stream/video URL is required.")
    with _LOCK:
        active = [w for w in _WATCHES.values() if w.uid == ctx.uid() and not w.stop_event.is_set()]
        if len(active) >= 4:
            raise ValueError("Stop one of your 4 live-link monitors first.")
        if any(w.url == url for w in active):
            raise ValueError("This live link is already being monitored.")
    # The watcher has its own creator workspace, which the user can configure
    # later for upload destination and AI checks. New auto-post is OFF.
    from urllib.parse import urlparse
    item = urlparse(url)
    label = item.path.strip("/").split("/")[-1] or item.hostname or "stream"
    c = creators.create({"name": ("Live · " + label)[:60], "channel": url,
                         "clip_mode": options.get("clip_mode", "gaming"),
                         "gta6_only_live": bool(options.get("gta6_only_live", False)),
                         "facecam_review": bool(options.get("facecam_review", False)),
                         "clip_quality": int(options.get("quality", 1080)),
                         "style": options.get("style", "clean"),
                         "layout": options.get("layout", "auto"),
                         "autopost": False, "auto_watch": False})
    w = Watch(secrets.token_urlsafe(10), ctx.uid(), url, c["id"])
    with _LOCK:
        _WATCHES[w.id] = w
    threading.Thread(target=_run, args=(w,), daemon=True, name="legend-live-watch").start()
    return w.public()


def stop(ident):
    with _LOCK:
        w = _WATCHES.get(ident)
        if not w or w.uid != ctx.uid():
            raise KeyError("No such live-link monitor")
        w.stop_event.set()
        w.status = "stopped"
    if w.job_id:
        s = live.mine(w.job_id)
        if s and not s.ended:
            s.stop()
    return w.public()


def _run(w):
    with ctx.as_user(w.uid):
        while not w.stop_event.is_set():
            try:
                w.last_check = time.time()
                w.status = "checking"
                live.resolve(w.url, int(creators.get(w.creator_id).get("clip_quality", 1080)))
                if w.stop_event.is_set():
                    break
                c = creators.get(w.creator_id)
                job = live.start_session(c, w.url)
                w.job_id = job["id"]
                w.status = "recording"
                w.error = ""
                return
            except live.NotLive as e:
                w.error = str(e)[-180:]
                w.status = "waiting"
            except (ValueError, RuntimeError, OSError) as e:
                w.error = str(e)[-180:]
                w.status = "waiting"
            w.next_check = time.time() + INTERVAL
            w.stop_event.wait(INTERVAL)
        w.status = "stopped"

"""Offline YouTube native and Instagram local scheduling tests.

No real YouTube/Meta requests, user tokens or media uploaded.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

root = tempfile.mkdtemp(prefix="legend-platform-scheduling-")
os.environ["PEAKCUT_DATA"] = root
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio import accounts, creators, ctx, jobs, posting

checks = 0

def check(name, ok):
    global checks
    assert ok, name
    checks += 1
    print("PASS " + name)


def iso(delta_minutes):
    return (datetime.now(timezone.utc) + timedelta(minutes=delta_minutes)).isoformat(timespec="seconds").replace("+00:00", "Z")


saved = {
    "accounts_get": accounts.get,
    "creator_get": creators.get,
    "job_get": jobs.get,
    "logs": creators.log,
    "mirror": posting._mirror,
    "yt_upload": accounts.youtube_upload,
    "ig_upload": accounts.instagram_upload,
    "yt_token": accounts._yt_token,
    "yt_resume": accounts._yt_resume_position,
    "http_get": accounts.httpx.get,
    "http_post": accounts.httpx.post,
}
try:
    accs = {
        "yt_ABC": {"id": "yt_ABC", "platform": "youtube", "name": "YouTube Channel"},
        "ig_123": {"id": "ig_123", "platform": "instagram", "name": "Instagram Account"},
        "tt_456": {"id": "tt_456", "platform": "tiktok", "name": "TikTok Account"},
    }
    accounts.get = lambda aid: accs.get(aid)
    creator = dict(creators.DEFAULTS, id="creator1", name="Streamer", privacy="public")
    creators.get = lambda cid: creator if cid == "creator1" else None
    events = []
    creators.log = lambda cid, msg: events.append(msg)
    posting._mirror = lambda post: None
    video_dir = Path(root) / "video"
    (video_dir / "clips").mkdir(parents=True)
    (video_dir / "clips" / "clip1.mp4").write_bytes(b"mock mp4")
    clip = {"id": "clip1", "file": "clip1.mp4", "title": "A clip", "hook": "Moment",
            "description": "A great clip", "hashtags": ["gaming"], "score": 97, "status": "done"}
    job = {"id": "job12345678", "creator": "creator1", "dir": str(video_dir), "clips": [clip]}
    jobs.get = lambda jid: job if jid == job["id"] else None
    calls = []
    def fake_yt_upload(acc, path, title, description, tags, privacy, **kw):
        calls.append(("youtube", acc["id"], kw.get("publish_at"), privacy))
        return "yt123", "https://www.youtube.com/shorts/yt123"
    def fake_ig_upload(acc, path, caption, jid):
        calls.append(("instagram", acc["id"], jid))
        return "ig123", "https://www.instagram.com/reel/ig123/"
    accounts.youtube_upload = fake_yt_upload
    accounts.instagram_upload = fake_ig_upload

    with ctx.as_user("schedtestuser123"):
        publishing_time = iso(180)
        instagram_time = iso(210)
        check("YouTube timezone-aware future date is normalized",
              accounts.youtube_publish_time(publishing_time) == publishing_time)
        check("Instagram future date is normalized",
              accounts.instagram_publish_time(instagram_time) == instagram_time)
        for validator in (accounts.youtube_publish_time, accounts.instagram_publish_time):
            for bad in ("2026-12-03T10:00:00", "not-a-date", iso(-10), iso(999999)):
                try:
                    validator(bad)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Accepted invalid or naive date " + bad)
        check("Both platforms reject past, naive and invalid dates", True)

        try:
            posting.enqueue(job, clip, ["yt_ABC"], now=True, youtube_publish_at=publishing_time)
        except ValueError:
            check("Post now cannot override a future schedule", True)
        else:
            raise AssertionError("Post now with future date allowed")

        try:
            posting.enqueue(job, clip, ["ig_123"], now=False, youtube_publish_at=publishing_time)
        except ValueError:
            check("YouTube scheduling requires selected YouTube destination", True)
        else:
            raise AssertionError("Scheduled YouTube with no YouTube account")

        try:
            posting.enqueue(job, clip, ["yt_ABC"], now=False, instagram_publish_at=instagram_time)
        except ValueError:
            check("Instagram scheduling requires selected Instagram destination", True)
        else:
            raise AssertionError("Scheduled Instagram with no Instagram account")

        made = posting.enqueue(job, clip, ["yt_ABC", "ig_123"], now=False,
                               youtube_publish_at=publishing_time, instagram_publish_at=instagram_time)
        check("Creates independent YouTube and Instagram posts", len(made) == 2)
        yt, ig = made
        check("YouTube schedules upload IMMEDIATELY without publishing publicly",
              yt["platform"] == "youtube" and yt["status"] == "scheduled"
              and yt["due_at"] < time.time() + 30 and yt["publish_at"] == publishing_time)
        check("Instagram stays in LOCAL waiting queue until its release time",
              ig["platform"] == "instagram" and ig["status"] == "scheduled"
              and abs(ig["due_at"] - posting._iso_time(instagram_time)) < 1 and ig["instagram_publish_at"] == instagram_time)
        check("A queued Instagram Reel has not uploaded yet", not calls)

        posting._post(yt)
        check("YouTube upload receives future publishAt metadata", calls[0][0] == "youtube"
              and calls[0][2] == publishing_time)
        check("YouTube is marked remotely scheduled, not already public",
              yt["status"] == posting.YOUTUBE_SCHEDULED and not yt.get("posted_at"))

        check("Second enqueue cannot duplicate remotely scheduled YouTube upload",
              posting.enqueue(job, clip, ["yt_ABC"], now=False, youtube_publish_at=publishing_time) == [])
        # Test the Instagram publishing dispatch directly, without waiting hours
        # and without running the persistent background worker.
        posting._post(ig)
        check("Instagram publishes through the local queue's ordinary Instagram API path",
              calls[-1][0] == "instagram" and ig["status"] == "posted" and ig.get("posted_at", 0) > 0)

        stale = dict(ig, id="stale", status="scheduled", remote_id="", tries=0,
                     instagram_publish_at=iso(-90), due_at=time.time()-5400)
        posting._posts.append(stale)
        before = len(calls)
        posting._post(stale)
        check("Missed Instagram post after server outage fails rather than publishing late",
              stale["status"] == "failed" and len(calls) == before and "missed" in stale.get("error","").lower())
        posting.retry("stale")
        check("Explicit Retry after missed Instagram time clears stale schedule and requeues now",
              stale["status"] == "scheduled" and stale["instagram_publish_at"] is None)

        # Existing non-scheduled queue behavior remains unchanged.
        normal_clip = dict(clip, id="clip_normal")
        normal = posting.enqueue(job, normal_clip, ["ig_123"], now=False)
        check("Ordinary Instagram queue is still supported",
              len(normal) == 1 and normal[0]["platform"] == "instagram"
              and normal[0].get("instagram_publish_at") is None)

    # Verify real YouTube API initialization metadata with stubbed responses.
    class Resp:
        def __init__(self, body=None, headers=None):
            self.status_code = 200
            self._body = body or {}
            self.headers = headers or {}
            self.text = ""
        def json(self):
            return self._body

    request_meta = {}
    accounts._yt_token = lambda acc: "fake-token"
    accounts.httpx.get = lambda *a, **kw: Resp({"items":[{"id":"ABC"}]})
    def fake_post(url, **kwargs):
        request_meta.update(kwargs["json"])
        return Resp(headers={"Location":"https://www.googleapis.com/upload/youtube/v3/videos/UPLOAD"})
    accounts.httpx.post = fake_post
    accounts._yt_resume_position = lambda location, token, size: (size, "yt_remote")
    accounts.youtube_upload = saved["yt_upload"]
    with ctx.as_user("schedtestuser123"):
        vid, url = accounts.youtube_upload(accs["yt_ABC"], video_dir/"clips"/"clip1.mp4",
                                           "Scheduled clip", "Description", [], "public",
                                           publish_at=iso(180))
    status = request_meta["status"]
    check("YouTube inserts PRIVATE video with status.publishAt",
          status.get("privacyStatus") == "private" and status.get("publishAt","").endswith("Z")
          and "selfDeclaredMadeForKids" in status)
    check("YouTube upload returns actual remote video id", vid == "yt_remote")

    print(f"ALL PASSED ({checks} platform scheduling tests)")
finally:
    accounts.get = saved["accounts_get"]
    creators.get = saved["creator_get"]
    jobs.get = saved["job_get"]
    creators.log = saved["logs"]
    posting._mirror = saved["mirror"]
    accounts.youtube_upload = saved["yt_upload"]
    accounts.instagram_upload = saved["ig_upload"]
    accounts._yt_token = saved["yt_token"]
    accounts._yt_resume_position = saved["yt_resume"]
    accounts.httpx.get = saved["http_get"]
    accounts.httpx.post = saved["http_post"]
    shutil.rmtree(root, ignore_errors=True)

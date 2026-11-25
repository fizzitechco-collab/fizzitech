"""Offline auto-posting diagnosis and regression checks; no real account uploads."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

root = tempfile.mkdtemp(prefix="legend-autopost-")
os.environ["PEAKCUT_DATA"] = root
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio import accounts, creators, ctx, jobs, posting

checks = 0
def check(label, ok):
    global checks
    assert ok, label
    checks += 1
    print("PASS " + label)


def sample(**overrides):
    item = {**creators.DEFAULTS, "id": "creator1", "name": "Streamer",
            "accounts": ["ig_good", "yt_old"], "autopost": True,
            "post_rights_confirmed": True, "post_min_score": 75}
    return {**item, **overrides}


original = {"acc": accounts.get, "creator": creators.get, "logs": creators.log,
            "enq": posting.enqueue, "mine": posting._mine, "list": jobs.list_jobs,
            "settings": accounts.settings}
try:
    accounts.get = lambda aid: {
        "ig_good": {"id":"ig_good", "name":"Instagram", "platform":"instagram"},
        "yt_old": {"id":"yt_old", "name":"YouTube A", "platform":"youtube"},
        "yt_new": {"id":"yt_new", "name":"YouTube B", "platform":"youtube"}}.get(aid)
    creator = sample()
    creators.get = lambda cid: creator if cid == "creator1" else None
    calls = []
    logs = []
    posting.enqueue = lambda job, clip, targets, now=False: (calls.append((targets, now)) or [{"id":"post1"}])
    creators.log = lambda cid, msg: logs.append((cid, msg))
    job = {"id":"job1", "creator":"creator1", "options":{"clip_mode":"gaming"}, "created":1000,
           "source":{"type":"url"}}
    clip = {"id":"clip01", "status":"done", "score":90, "title":"A good reaction"}

    with ctx.as_user("testautopost123"):
        ok, reason, dest = posting.auto_post_check(job, clip)
        check("Configured creator auto-post is eligible", ok and dest == ["ig_good", "yt_old"])
        posting.on_clip_ready(job, clip)
        check("Finished eligible clip is enqueued automatically", len(calls) == 1 and calls[-1][0] == dest)

        creator = sample(autopost=False)
        ok, reason, dest = posting.auto_post_check(job, clip)
        check("Auto-post OFF reports clear reason", not ok and "OFF" in reason)
        posting.on_clip_ready(job, clip)
        check("OFF state does not queue a clip", len(calls) == 1 and "skipped" in logs[-1][1].lower())

        creator = sample(post_rights_confirmed=False)
        ok, reason, _ = posting.auto_post_check(job, clip)
        check("Missing publish permission blocks unattended posting", not ok and "permission" in reason.lower())

        creator = sample(accounts=[])
        ok, reason, _ = posting.auto_post_check(job, clip)
        check("No destinations gives actionable reason", not ok and "destination" in reason)

        creator = sample(accounts=["ig_disconnected"])
        ok, reason, _ = posting.auto_post_check(job, clip)
        check("Disconnected destinations are not silently queued", not ok and "destination" in reason)

        creator = sample(post_min_score=95)
        ok, reason, _ = posting.auto_post_check(job, clip)
        check("Low score explains numeric posting threshold", not ok and "90" in reason and "95" in reason)

        creator = sample()
        manual = dict(job, custom_campaign={"id":"brand"})
        ok, reason, _ = posting.auto_post_check(manual, clip)
        check("Paid branded campaigns still require manual posting", not ok and "Campaign" in reason)

        approved = dict(job, options={"clip_mode":"expedia_ishowspeed"})
        ok, reason, _ = posting.auto_post_check(approved, clip)
        check("Expedia rules remain unchanged", not ok and "manual" in reason)

        ok, reason, _ = posting.auto_post_check(dict(job, creator=None), clip)
        check("No-creator videos explain why auto-post never fires", not ok and "creator" in reason)

        creator = sample(youtube_account="yt_new")
        ok, reason, dest = posting.auto_post_check(job, clip)
        check("Explicit YouTube upload channel replaces old YouTube but keeps Instagram",
              ok and dest == ["ig_good","yt_new"])
        creator = sample()
        accounts.settings = lambda: {"paused": True}
        jobs.list_jobs = lambda: [dict(job, clips=[dict(clip), dict(clip, id="clip02", score=50, title="Weak")])]
        posting._mine = lambda: [
            {"job":"job1","clip":"clip01","platform":"instagram","status":"failed","error":"access token expired"}]
        status = posting.diagnostics("creator1")
        check("Diagnostics surface global posting pause", status["paused"] and any("PAUSED" in s for s in status["notices"]))
        check("Diagnostics surface provider's previous error without any OAuth tokens",
              any(x["queued"] and "expired" in x["reason"] for x in status["recent"])
              and not any("access_token" in str(x) for x in status.values()))
        check("Diagnostics surface clips that miss the minimum score",
              any("below the auto-post minimum" in row["reason"] for row in status["recent"]))
        check("Diagnostics cover only the requested creator", status["creator"] == "creator1")
    print(f"ALL PASSED ({checks} auto-post diagnostics checks)")
finally:
    accounts.get = original["acc"]
    creators.get = original["creator"]
    creators.log = original["logs"]
    posting.enqueue = original["enq"]
    posting._mine = original["mine"]
    jobs.list_jobs = original["list"]
    accounts.settings = original["settings"]
    shutil.rmtree(root, ignore_errors=True)

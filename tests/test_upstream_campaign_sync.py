"""Offline regression for selectively synced upstream creator/campaign copy.

Run from project root:
    .venv\\Scripts\\python.exe tests\\test_upstream_campaign_sync.py
No network, external API, livestream, or real user files.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="legend-upstream-copy-")
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import account, creators, ctx, jobs, posting

checks = 0

def check(label, ok):
    global checks
    if not ok:
        raise AssertionError(label)
    checks += 1
    print("PASS " + label)

try:
    check("Creator Big text strips controls and is at most 60 chars",
          creators.clean_overlay_hook("  MY\n   BIG   TEXT  ") == "MY BIG TEXT"
          and len(creators.clean_overlay_hook("a" * 100)) == 60)
    copy = "This is my post!\n#Minecraft @creator https://example.com/clip"
    saved_copy = creators.clean_description_text(copy)
    check("Creator campaign description preserves hashtags, @mentions, URLs and line breaks",
          "#Minecraft" in saved_copy and "@creator" in saved_copy and "\n" in saved_copy
          and "https://example.com/clip" in saved_copy)
    creator_settings = creators._clean({"overlay_hook_text": "HI THERE",
                                       "description_text": saved_copy, "clip_quality": 0})
    check("Creator stores big text separately from the existing hook text COLOR",
          creator_settings["overlay_hook_text"] == "HI THERE"
          and "hook_text" not in creator_settings)
    job_opts = jobs.clean_options({"overlay_hook_text": "MY CAMPAIGN",
                                   "description_text": saved_copy, "hook_text": "FFFFFF"})
    check("Job options accept campaign copy and keep hook color independently",
          job_opts["overlay_hook_text"] == "MY CAMPAIGN"
          and job_opts["description_text"] == saved_copy
          and job_opts["hook_text"] == "FFFFFF")

    with tempfile.TemporaryDirectory(prefix="legend-posttext-") as folder:
        root = Path(folder)
        (root / "clips").mkdir()
        video = root / "clips" / "clip01.mp4"
        video.write_bytes(b"original encoded video bytes; must not be changed")
        clip = {"id": "clip01", "status": "done", "file": video.name,
                "title": "First", "hook": "Look", "description": "Original summary",
                "hashtags": ["minecraft"], "score": 90}
        job = {"id": "fake-job", "dir": str(root), "user": "testuser123",
               "source": {"type": "url", "url": "https://example.com/watch"},
               "options": {"clip_mode": "gaming"}, "status": "done", "clips": [clip]}
        sidecar = root / "clips" / "clip01.json"
        sidecar.write_text(json.dumps({"title": "First", "hook": "Look"}))
        with ctx.as_user("testuser123"):
            jobs.save_post_text(job, clip, {"title": "Renamed!","description": "My #custom words",
                                             "hashtags": "#minecraft funny #clutch"})
            check("Title, description and hashtags saved in job.json",
                  json.loads((root / "job.json").read_text())["clips"][0]["hashtags"] ==
                  ["minecraft", "funny", "clutch"])
            check("Clip publishing metadata sidecar stays in sync",
                  json.loads(sidecar.read_text())["title"] == "Renamed!")
            check("Post metadata editing does not rerender or overwrite video",
                  video.read_bytes() == b"original encoded video bytes; must not be changed")
            check("Individual downloads use a safe title-based filename",
                  account.clip_title_name(clip) == "Renamed"
                  and account.clip_title_name({"title": "../unsafe! name"}) == "unsafe name")
            clip["fixed_description"] = True
            cap = posting._caption(clip, {"name": "Tester", "post_footer": ""})
            check("An exact custom description is posted without duplicate auto tags",
                  cap.count("#minecraft") <= 1 and cap.count("#custom") == 1)
            job["options"]["clip_mode"] = "gta6"
            before = clip["title"]
            try:
                jobs.save_post_text(job, clip, {"title": "Forbidden override"})
            except ValueError:
                check("Protected GTA campaign metadata cannot be overwritten silently",
                      clip["title"] == before)
            else:
                raise AssertionError("Protected GTA metadata unexpectedly modified")

    print(f"ALL PASSED ({checks} upstream-copy checks)")
finally:
    import shutil
    shutil.rmtree(os.environ["PEAKCUT_DATA"], ignore_errors=True)

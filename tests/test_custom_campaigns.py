"""Offline Custom Campaigns tests.

Creates no live jobs or social posts. All data is temporary and never uses a
user's actual account, keys or existing recordings.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix="legend-campaign-check-"))
os.environ["PEAKCUT_DATA"] = str(root)
os.environ["DATABASE_URL"] = ""
os.environ["PEAKCUT_UPDATE_CHECK"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio import brain, ctx, custom_campaigns, jobs, creators, posting, accounts

checks = 0
def check(name, result):
    global checks
    assert result, name
    print("PASS " + name)
    checks += 1

try:
    with ctx.as_user("campaignuser1"):
        first = custom_campaigns.create({
            "name": "Launch Highlights", "brand": "Example Studios",
            "brief": "Only show actual livestream product reactions.",
            "hook_text": "THE REAL REACTION",
            "description_text": "The streamer reacts to the launch.",
            "hashtags": "#launch #Launch #gaming",
            "status": "active", "rate_per_1k": 2.5
        })
        cid = first["id"]
        check("Created a true custom campaign separate from legacy GTA clip mode",
              len(cid) == 16 and first["name"] == "Launch Highlights"
              and first["status"] == "active")
        check("Hashtag duplicates removed while preserving typed values",
              first["hashtags"] == ["launch", "gaming"])
        data_file = root / "users" / "campaignuser1" / "custom_campaigns.json"
        check("Campaign settings persisted in per-user data folder",
              json.loads(data_file.read_text())[0]["brief"] == first["brief"])
        check("Campaign list can read saved definitions",
              custom_campaigns.all_campaigns()[0]["id"] == cid)
        check("Selected campaign snapshot has the original brand/brief",
              custom_campaigns.snapshot(cid)["brand"] == "Example Studios")
        check("Job options independently preserve campaign IDs",
              jobs.clean_options({"custom_campaign_id":cid, "quality":0})["custom_campaign_id"] == cid)

        j = jobs.create({"type": "url", "url": "https://www.youtube.com/watch?v=abcde123456",
                         "name": "Sample video"}, {"custom_campaign_id": cid, "quality": 0},
                        enqueue=False)
        check("Campaign selection produces a job with a server-side snapshot",
              j["custom_campaign"]["id"] == cid
              and j["options"]["custom_campaign_id"] == cid)
        saved = json.loads((Path(j["dir"]) / "job.json").read_text())
        check("Campaign snapshot survives job file persistence",
              saved["custom_campaign"]["brief"] == first["brief"])

        changed = custom_campaigns.update(cid, {"name":"Updated launch", "hook_text":"AFTER THE LAUNCH"})
        check("Campaign editing works without destroying previous fields",
              changed["name"] == "Updated launch" and changed["brand"] == "Example Studios")
        check("Editing campaign does not modify an existing job snapshot",
              j["custom_campaign"]["name"] == "Launch Highlights")
        paused = custom_campaigns.update(cid, {"status":"paused"})
        check("Campaign can be paused", paused["status"] == "paused")
        try:
            custom_campaigns.snapshot(cid)
        except ValueError:
            check("Paused campaign refuses NEW clip jobs", True)
        else:
            raise AssertionError("Paused campaign was accepted")
        try:
            jobs.create({"type":"file", "name":"unused.mp4", "path":""},
                        {"custom_campaign_id": cid}, enqueue=False)
        except ValueError:
            check("Backend job creation enforces the paused state", True)
        else:
            raise AssertionError("Job ignored paused campaign")
        custom_campaigns.update(cid, {"status":"active"})
        try:
            jobs.create({"type":"file", "name":"unused.mp4", "path":""},
                        {"custom_campaign_id": cid, "clip_mode": "gta6"}, enqueue=False)
        except ValueError:
            check("GTA VI special clipping cannot be accidentally mixed into a custom campaign", True)
        else:
            raise AssertionError("GTA VI campaign collision")
        try:
            custom_campaigns.create({"name":"Bad tags", "hashtags":"#okay #bad-tag"})
        except ValueError:
            check("Invalid campaign hashtags are rejected", True)
        else:
            raise AssertionError("Invalid tags accepted")

        custom_campaigns.delete(cid)
        check("Campaign delete removes only the definition",
              custom_campaigns.get(cid) is None
              and json.loads((Path(j["dir"])/"job.json").read_text())["custom_campaign"]["id"] == cid)
        default = custom_campaigns.create({"name":"New default active"})
        check("New campaigns default to active", default["status"] == "active")

    with ctx.as_user("campaignuser2"):
        check("Campaigns from another user are not visible",
              custom_campaigns.all_campaigns() == []
              and custom_campaigns.get(default["id"]) is None)
        try:
            jobs.create({"type":"file", "name":"unused.mp4", "path":""},
                        {"custom_campaign_id": default["id"]}, enqueue=False)
        except ValueError:
            check("Cross-user campaign IDs cannot attach to jobs", True)
        else:
            raise AssertionError("Cross-user campaign accessed")

    with ctx.as_user("campaignuser1"):
        original_ask = brain.ask_ai
        captured = []
        words = [{"w": "Moment.", "s": float(i*2), "e": float(i*2)+.4} for i in range(14)]
        import numpy as np
        db = np.zeros(60)
        def fake_ai(prompt, schema=None, purpose=""):
            captured.append(prompt)
            return [], "fake-AI", 5
        brain.ask_ai = fake_ai
        try:
            clips, info = brain.find_clips(
                words, db, 40.0, "Livestream example", "Creator",
                max_clips=1, min_len=8, max_len=30,
                custom_campaign={"id": default["id"],"name":"New default active",
                                 "brand":"Example Studios","brief":"real product reaction"})
            check("Campaign brief influences AI selection instructions",
                  any("real product reaction" in prompt and "Example Studios" in prompt
                      for prompt in captured))
            check("No made-up clips when the AI returns no valid campaign moments",
                  clips == [] and info["model"] == "fake-AI")
        finally:
            brain.ask_ai = original_ask

        original_ask = brain.ask_ai
        brain.ask_ai = lambda *a,**kw: (_ for _ in ()).throw(RuntimeError("No AI available"))
        try:
            clips, info = brain.find_clips(
                words, db, 40.0, "Livestream", "Creator",
                max_clips=1, min_len=8, max_len=30,
                custom_campaign={"id": default["id"], "brand":"Test","brief":"brand moment"})
            check("AI outage does not create unrelated loudness-picked campaign clips",
                  clips == [] and "requires a working AI" in info["note"])
        finally:
            brain.ask_ai = original_ask

    # Paid/branded campaigns require manual publish review. Other creator
    # auto-post rules remain unchanged.
    original_creator_get, original_enqueue, original_account_get = creators.get, posting.enqueue, accounts.get
    sent = []
    try:
        creators.get = lambda _cid: {"autopost": True, "accounts": ["fake-destination"],
                                     "post_rights_confirmed": True, "post_min_score": 80}
        posting.enqueue = lambda *args, **kwargs: (sent.append((args, kwargs)) or [])
        accounts.get = lambda aid: {"id": aid, "platform": "instagram"} if aid == "fake-destination" else None
        post_job = {"creator": "fake-creator", "options": {"clip_mode": "gaming"},
                    "custom_campaign": {"id": "fakecampaign"}}
        posting.on_clip_ready(post_job, {"score": 95, "title": "Branded clip", "status": "done"})
        check("Branded campaign clips cannot inherit automatic posting",
              sent == [])
        normal_job = {"creator": "fake-creator", "options": {"clip_mode": "gaming"}}
        posting.on_clip_ready(normal_job, {"score": 95, "title": "Ordinary clip", "status": "done"})
        check("Normal creator automatic posting still follows existing preferences",
              len(sent) == 1)
    finally:
        creators.get, posting.enqueue, accounts.get = original_creator_get, original_enqueue, original_account_get

    ui = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
    page = (Path(__file__).resolve().parents[1] / "web" / "campaigns.js").read_text(encoding="utf-8")
    check("Frontend Campaigns page is wired into the navigation and URL",
          '"campaigns", navIc(' in ui and 'campaigns:"campaigns"' in ui
          and 'id="o_custom_campaign"' in ui)
    check("Campaign actions and safe HTML escaping are available",
          'data-campaign-action="new"' in page and 'data-campaign-action="toggle"' in page
          and 'esc(c.name)' in page and 'loadCampaigns' in page)
    print(f"ALL PASSED ({checks} Custom Campaigns checks)")
finally:
    shutil.rmtree(root, ignore_errors=True)

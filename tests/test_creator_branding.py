"""Offline normal clip branding and source platform CTA regression tests."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="legend-branding-")
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio import creator_branding, creators, jobs, render
from studio.gta_cta import add_cta, add_watch_more

checks = 0

def check(label, ok):
    global checks
    assert ok, label
    checks += 1
    print("PASS " + label)

check("Selected IShowSpeed creator is included in title exactly once",
      creator_branding.title_with_creator("Huge clutch!", "IShowSpeed") == "Huge clutch! IShowSpeed"
      and creator_branding.title_with_creator("Huge clutch! #ishowspeed", "IShowSpeed") == "Huge clutch! ishowspeed")
check("Creator names with spaces turn into plain labels",
      creator_branding.creator_label("Kai Cenat") == "KaiCenat")
check("Title cap stays at 100 chars after creator credit",
      len(creator_branding.title_with_creator("a" * 100, "IShowSpeed")) <= 100
      and creator_branding.title_with_creator("a" * 100, "IShowSpeed").endswith("IShowSpeed"))
check("No creator means no guessed name",
      creator_branding.title_with_creator("Great gaming!", "") == "Great gaming!")
check("Known video source domains determine on-screen platform",
      creator_branding.source_platform({"url":"https://www.youtube.com/watch?v=Kyv61l2vF6M"}) == "YouTube"
      and creator_branding.source_platform({"url":"https://www.twitch.tv/videos/12345"}) == "Twitch"
      and creator_branding.source_platform({"url":"https://kick.com/streamer/videos/abc"}) == "Kick")
check("A malicious lookalike domain cannot select platform",
      not creator_branding.source_platform({"url":"https://twitch.tv.evil.example/mystream"})
      and not creator_branding.source_platform({"url":"https://faketwitch.tv/123"}))

job = {"options":{"clip_mode":"gaming","watch_more_enabled":True},
       "source":{"type":"url","url":"https://www.twitch.tv/videos/12345"}}
clip = {"title":"An incredible moment","hook":"WOW"}
creator_branding.decorate_clip(clip, job, "IShowSpeed")
check("Normal clip title and end CTA come from selected creator and actual source",
      clip["title"].endswith("IShowSpeed") and clip["watch_more_enabled"]
      and clip["watch_more_name"] == "IShowSpeed" and clip["watch_more_platform"] == "Twitch")
ass = "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
decorated = add_watch_more(ass, clip, 23)
check("CTA appears only during the last three seconds and below center",
      "Watch more on" in decorated and "IShowSpeed  Twitch" in decorated
      and "0:00:20." in decorated and "\\pos(540,1130)" in decorated)
check("Titles and end CTA contain no hash prefix", 
      "#" not in clip["title"] and "#" not in decorated)
check("CTA OFF leaves existing ASS unchanged",
      add_watch_more(ass, {**clip, "watch_more_enabled":False}, 23) == ass)
check("No creator or short clip gives no misleading CTA",
      add_watch_more(ass, {**clip, "watch_more_name":""}, 23) == ass
      and add_watch_more(ass, clip, 1) == ass)
check("Unknown file-source platform is omitted without inventing a source",
      "IShowSpeed" in add_watch_more(ass, {**clip, "watch_more_platform":""}, 23)
      and "Twitch" not in add_watch_more(ass, {**clip, "watch_more_platform":""}, 23))
check("Existing GTA CTA behavior remains available",
      "Watch more on" in add_cta(ass, {"cta_enabled":True,"cta_creator_name":"IShowSpeed"}, 18))

protected = dict(clip, title="Brand-approved", watch_more_enabled=False)
creator_branding.decorate_clip(protected,
                              {"options":{"clip_mode":"gta6","watch_more_enabled":True}, "source":job["source"]},
                              "IShowSpeed")
check("Protected GTA campaign title is unchanged, optional normal CTA is blocked",
      protected["title"] == "Brand-approved" and not protected["watch_more_enabled"])
custom = dict(clip, title="Campaign-approved")
creator_branding.decorate_clip(custom, {**job, "custom_campaign":{"id":"test"}}, "IShowSpeed")
check("Protected custom campaign copy is unchanged",
      custom["title"] == "Campaign-approved" and not custom["watch_more_enabled"])

check("Normal and creator settings clean the toggle",
      jobs.clean_options({"watch_more_enabled": True})["watch_more_enabled"]
      and not jobs.clean_options({"watch_more_enabled":False})["watch_more_enabled"]
      and creators._clean({"watch_more_enabled":True})["watch_more_enabled"])
print(f"ALL PASSED ({checks} creator name/CTA checks)")

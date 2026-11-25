"""Source-grounded optional clip end CTA and creator-name post title attribution.

Do not infer streamer identity from AI output; only use an explicitly selected
creator workspace. Never change protected GTA/Expedia or custom campaign copy.
"""
import re
from urllib.parse import urlparse


def creator_hashtag(name: str) -> str:
    """A single readable hashtag suitable for a clip title."""
    value = "".join(re.findall(r"[^\W_]+", str(name or ""), flags=re.UNICODE))[:55]
    return "#" + value if value and not value.isdigit() else ""


def title_with_creator(title: str, creator_name: str, *, protected: bool = False) -> str:
    """Add the selected creator's hashtag once, inside YouTube's title limit."""
    title = str(title or "").strip()[:100]
    tag = creator_hashtag(creator_name)
    if protected or not tag:
        return title
    if re.search(r"(?<![\w])" + re.escape(tag) + r"(?![\w])", title, flags=re.IGNORECASE):
        return title
    return (title[:100-len(tag)-1].rstrip() + " " + tag).strip()


def source_platform(source: dict) -> str:
    """Only use a validated source domain, never guess from a video title."""
    url = str((source or {}).get("url") or "")
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"):
        return "YouTube"
    if host in ("twitch.tv", "www.twitch.tv", "clips.twitch.tv", "www.clips.twitch.tv"):
        return "Twitch"
    if host in ("kick.com", "www.kick.com"):
        return "Kick"
    return ""


def decorate_clip(clip: dict, job: dict, creator_name: str) -> dict:
    """Apply only to new ordinary clips, not a protected brand campaign."""
    mode = (job.get("options") or {}).get("clip_mode", "gaming")
    protected = mode not in ("gaming", "irl") or bool(job.get("custom_campaign")) or bool(clip.get("campaign_review_required"))
    if not protected and creator_name:
        clip["title"] = title_with_creator(clip.get("title"), creator_name)
    clip["watch_more_enabled"] = bool((job.get("options") or {}).get("watch_more_enabled")) and not protected
    clip["watch_more_name"] = creator_hashtag(creator_name) if not protected else ""
    clip["watch_more_platform"] = source_platform(job.get("source")) if not protected else ""
    return clip

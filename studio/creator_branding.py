"""Selected creator credit for ordinary clips, with no hashtag prefixes.

Creator identity is taken from a selected workspace, never guessed from AI text.
Protected brand and special campaigns retain their approved text.
"""
import re
from urllib.parse import urlparse


def creator_label(name: str) -> str:
    """Compact, readable creator handle without a social hashtag marker."""
    value = "".join(re.findall(r"[^\W_]+", str(name or ""), flags=re.UNICODE))[:55]
    return value if value and not value.isdigit() else ""


def title_with_creator(title: str, creator_name: str, *, protected: bool = False) -> str:
    """Credit selected creator once in a <=100-character title, without '#'."""
    title = str(title or "").strip()[:100]
    label = creator_label(creator_name)
    if protected or not label:
        return title
    # Convert a legacy auto-appended #Creator label to plain Creator.
    existing_tag = re.compile(r"(?<![\w])#" + re.escape(label) + r"(?![\w])", re.IGNORECASE)
    title = existing_tag.sub(label, title)
    if re.search(r"(?<![\w])" + re.escape(label) + r"(?![\w])", title, re.IGNORECASE):
        return title
    return (title[:100 - len(label) - 1].rstrip() + " " + label).strip()


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
    clip["watch_more_name"] = creator_label(creator_name) if not protected else ""
    clip["watch_more_platform"] = source_platform(job.get("source")) if not protected else ""
    return clip

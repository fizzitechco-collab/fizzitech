"""IRL clip selection and an optional *human-reviewed* Expedia campaign preset.

No synthetic video/voice, fake engagement, campaign submission, or payout automation.
The campaign preset accepts only the specific approved public recording linked
from ReachClipping. An automatic transcript-based filter cannot replace human
review of the visuals, branding, destination, or audience statistics.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

EXPEDIA_CAMPAIGN = "expedia_ishowspeed"
APPROVED_VIDEO_ID = "Kyv61l2vF6M"
APPROVED_VIDEO = f"https://www.youtube.com/watch?v={APPROVED_VIDEO_ID}"
EXPEDIA_START = 2 * 3600 + 56 * 60 + 29  # 02:56:29
RULES_URL = "https://reachclipping.com/Expedia-IShowSpeed"
MODES = {"gaming", "irl", "gta6"}  # Historical Expedia clips still load, but preset cannot be selected anew.


def youtube_video_id(url: str) -> str:
    try:
        p = urlparse(str(url))
        host = (p.hostname or "").lower()
        if host in {"youtu.be", "www.youtu.be"}:
            ident = p.path.strip("/").split("/")[0]
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            if p.path == "/watch":
                ident = parse_qs(p.query).get("v", [""])[0]
            elif p.path.startswith(("/live/", "/embed/", "/shorts/")):
                ident = p.path.strip("/").split("/")[1]
            else:
                ident = ""
        else:
            return ""
        return ident if re.fullmatch(r"[A-Za-z0-9_-]{11}", ident) else ""
    except (ValueError, IndexError):
        return ""


def validate_source(source: dict, options: dict) -> None:
    if options.get("clip_mode") != EXPEDIA_CAMPAIGN:
        return
    if source.get("type") != "url" or youtube_video_id(source.get("url", "")) != APPROVED_VIDEO_ID:
        raise ValueError("This Expedia preset accepts only the approved IShowSpeed stream linked in the campaign. Use the 'Use approved footage' button.")


def approved_range(options: dict) -> dict:
    if options.get("clip_mode") != EXPEDIA_CAMPAIGN:
        return options
    result = dict(options)
    result["range_start"] = max(float(result.get("range_start") or 0), EXPEDIA_START)
    if result.get("range_end") is not None and float(result["range_end"]) <= result["range_start"]:
        raise ValueError("Campaign clips must come from after 02:56:29 of the approved stream.")
    return result


def contains_expedia(words: list, start: float, end: float) -> bool:
    """Require the brand to actually be spoken near the selected moment.
    Transcript-derived requirement is intentionally conservative; manually
    review visuals before uploading because Expedia can appear on screen.
    """
    return any(start <= float(w.get("s", -1)) <= end and re.search(r"\bexpedia\b", str(w.get("w", "")), re.I)
               for w in words)


def prepare_clip(clip: dict, destination: str = "") -> dict:
    """Prepare brand-focused text without inventing destinations/claims.

    Human review is still required: clip can be used only if Expedia is the
    genuine focus, destination is correct and all external campaign rules hold.
    """
    c = dict(clip)
    c["campaign_id"] = EXPEDIA_CAMPAIGN
    c["campaign_review_required"] = True
    dest = re.sub(r"[^\w\- .,']", "", str(destination or ""))[:55].strip()
    c["campaign_destination"] = dest
    hook = str(c.get("hook") or "").strip()
    if "expedia" not in hook.lower():
        hook = ("EXPEDIA: " + hook).strip(" :")
    c["hook"] = hook[:60]
    title = str(c.get("title") or "IShowSpeed travel moment")
    if "expedia" not in title.lower():
        title = "IShowSpeed x Expedia: " + title
    c["title"] = title[:100]
    desc = str(c.get("description") or "").strip()
    if "expedia" not in desc.lower():
        desc = ("IShowSpeed and Expedia: " + desc).strip()
    if dest:
        desc = f"{desc}\nDestination: {dest}"
    c["description"] = desc[:300]
    tags = [str(t).lstrip("#") for t in c.get("hashtags", []) if str(t).strip()]
    tags = [t for t in tags if t.lower() != "ishowspeed"]
    c["hashtags"] = ["IShowSpeed", "Expedia"] + [t for t in tags if t.lower() != "expedia"][:6]
    return c

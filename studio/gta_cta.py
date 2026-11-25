"""Small 2.8-second centered end CTA, drawn in the existing ASS render pass."""
import re


def _time(t):
    t = max(0.0, float(t))
    hh = int(t // 3600)
    mm = int(t % 3600 // 60)
    ss = int(t % 60)
    cs = int((t - int(t)) * 100)
    return f"{hh}:{mm:02d}:{ss:02d}.{cs:02d}"


def add_cta(ass: str, clip: dict, seconds: float) -> str:
    if not clip.get("cta_enabled") or seconds <= 1.3:
        return ass
    # Do not allow user/title text to inject ASS formatting sequences.
    name = re.sub(r"[^A-Za-z0-9_@ .'-]", "", str(clip.get("cta_creator_name") or ""))[:42].strip()
    label = "Watch more on " + (name or "the creator's channel")
    start, end = max(0.0, seconds - 2.8), seconds - 0.04
    cmd = (r"{\an5\pos(540,1020)\fs44\b1\1c&H00FFFFFF&\3c&H00101010&"
           r"\bord6\shad2\fad(180,200)}")
    return ass.rstrip() + f"\nDialogue: 9,{_time(start)},{_time(end)},Hook,,0,0,0,,{cmd}{label}\n"

def add_watch_more(ass: str, clip: dict, seconds: float) -> str:
    """Optional two-line normal clip CTA: below center, final 3 seconds.

    The on-screen creator hashtag comes from the selected workspace, and the
    source platform is derived from the actual video URL, not an AI guess.
    No additional black frame or second encoding pass.
    """
    if not clip.get("watch_more_enabled") or seconds <= 1.3:
        return ass
    name = re.sub(r"[^A-Za-z0-9_#]", "", str(clip.get("watch_more_name") or ""))[:58]
    if not name or not name.startswith("#"):
        return ass  # no selected creator identity: no misleading promo
    platform = str(clip.get("watch_more_platform") or "")
    if platform not in ("YouTube", "Twitch", "Kick"):
        platform = ""
    second_line = name + ("  #" + platform if platform else "")
    start, end = max(0.0, seconds - 3.0), max(0.0, seconds - 0.06)
    if end <= start:
        return ass
    # 1080x1920 canvas: lower-middle (61–65% height), safely above UI bottom.
    # ASS escapes are literal, and user-provided text has no formatting braces.
    first = r"{\an5\pos(540,1130)\fs47\b1\1c&H00FFFFFF&\3c&H00101010&\bord5\shad2\fad(200,250)}"
    # Reduce font size for very long workspace names so text stays on screen.
    font_size = max(25, min(54, int(54 * 24 / max(24, len(second_line)))))
    second = (r"{\an5\pos(540,1210)\fs" + str(font_size) +
              r"\b1\1c&H00FFFFFF&\3c&H00101010&\bord6\shad2\fad(200,250)}")
    return (ass.rstrip() +
            f"\nDialogue: 9,{_time(start)},{_time(end)},Hook,,0,0,0,,{first}Watch more on" +
            f"\nDialogue: 9,{_time(start)},{_time(end)},Hook,,0,0,0,,{second}{second_line}\n")

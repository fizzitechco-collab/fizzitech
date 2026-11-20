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

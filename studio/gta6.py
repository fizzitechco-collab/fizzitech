"""GTA VI clip mode: conservative text evidence only, not a visual classifier.

A GTA title does not establish what is on-screen in a mixed-game broadcast. 
Content needs contextual GTA VI evidence near the selected clip; humans must verify.
"""
import re

GTA = re.compile(r"\b(?:gta\s*(?:6|vi|six)|grand\s+theft\s+auto\s*(?:6|vi|six)|vice\s+city|leonida|lucia\s+and\s+jason|jason\s+and\s+lucia)\b", re.I)
OTHERS = re.compile(r"\b(?:minecraft|roblox|fortnite|valorant|pubg|free\s*fire|red\s*dead|call\s+of\s+duty|warzone|apex\s+legends|counter\s*strike|cs2|gta\s*(?:5|v)(?!i)|gta\s*online)\b", re.I)
SWITCH = re.compile(r"\b(?:switch(?:ing)?\s+(?:to|games)|play(?:ing)?\s+(?:something\s+else|another\s+game)|moving\s+to)\b", re.I)


def _text(words, start=0, end=float('inf')):
    return ' '.join(str(w.get('w','')) for w in words if start <= float(w.get('s',-1)) <= end)


def stream_eligible(title, only_gta6_live=False):
    """If strict, require explicit GTA6 stream branding and no named competing title."""
    if not only_gta6_live:
        return True
    t = str(title or '')
    return bool(GTA.search(t)) and not bool(OTHERS.search(t))


def moment_eligible(words, start, end, title='', only_gta6_live=False):
    """Never accept only noise/reactions for a GTA-specific moment.

    This may reject good GTA VI moments when nobody says the game's name; false
    negatives are safer than uploading unrelated games as GTA VI.
    """
    spoken = _text(words, max(0, start - 25), end + 12)
    if OTHERS.search(spoken):
        return False
    if GTA.search(spoken):
        return True
    if only_gta6_live and stream_eligible(title, True) and not SWITCH.search(spoken):
        return True
    return False

GUIDANCE = '''
CLIP MODE: GRAND THEFT AUTO VI ONLY. The stream may contain other games.
Choose ONLY genuine GTA VI gameplay/discussion moments supported by what is said.
Prefer wanted-level chaos, police chases, unexpected NPC encounters, vehicle escapes,
funny streamer reactions to GTA VI, missions and surprising open-world moments.
DO NOT clip Minecraft, GTA V/Online, Roblox, Fortnite, menus unrelated to GTA VI,
or arbitrary yelling. If the transcript doesn't establish GTA VI, return [] instead
of guessing what video shows; you cannot see video frames. Never invent GTA 6 events.
'''

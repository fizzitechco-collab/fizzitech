"""Private per-user category preference learned from explicitly rated clips.

No external data leaves the app. No neural model, no surprise post automation:
a subtle bounded category adjustment starts only after 8 rated clips.
"""
from __future__ import annotations

from collections import defaultdict


def profile(jobs: list) -> dict:
    grouped = defaultdict(list)
    ratings = []
    for job in jobs:
        for clip in job.get("clips", []):
            category = str(clip.get("category") or "other").lower()
            try:
                value = int(clip.get("rating"))
            except (TypeError, ValueError):
                continue
            if 1 <= value <= 5 and clip.get("status") == "done":
                grouped[category].append(value)
                ratings.append(value)
    if len(ratings) < 8:
        return {}
    mean = sum(ratings) / len(ratings)
    # Shrink small categories toward neutral so a single 5-star rating does not
    # control the ranking. A modest 8-point ceiling preserves the Gemini score.
    return {cat: max(-8, min(8, round((sum(v) / len(v) - mean) * 5 * len(v) / (len(v) + 3))))
            for cat, v in grouped.items() if len(v) >= 2}


def score(candidate: dict, weights: dict | None) -> int:
    base = max(0, min(100, int(float(candidate.get("score") or 0))))
    return max(0, min(100, base + int((weights or {}).get(str(candidate.get("category") or "other").lower(), 0))))

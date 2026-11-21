"""Isolated checks for bounded audio scanning and source facecam preview policy.

Uses fake audio, never connects to YouTube or touches real videos.
"""
import tempfile
from pathlib import Path

import numpy as np

from studio import games, hashtags, jobs, server
from studio.progressive_audio import ProgressiveAudio, RATE

checks = 0


def check(label, condition):
    global checks
    assert condition, label
    checks += 1
    print("PASS " + label)


with tempfile.TemporaryDirectory(prefix="legend-smart-audio-") as folder:
    source = ProgressiveAudio("https://www.youtube.com/watch?v=sample", Path(folder), 75, section_seconds=30)
    calls = []

    def fake_section(index):
        calls.append(index)
        return np.full(min(source.section_samples, len(source) - index * source.section_samples),
                       index + 1, dtype=np.int16)

    source._read_section = fake_section
    check("source has complete logical duration without eager downloading", len(source) == 75 * RATE and calls == [])
    check("first section loads on demand", np.all(source[:RATE] == 1) and calls == [0])
    check("cached section is not downloaded again", np.all(source[5 * RATE:6 * RATE] == 1) and calls == [0])
    check("a slice across boundaries stitches audio", np.all(source[29 * RATE:30 * RATE] == 1) and
          np.all(source[30 * RATE:31 * RATE] == 2) and calls == [0, 1])
    check("remaining distant source is untouched", calls == [0, 1])
    check("last partial section loads correctly", np.all(source[60 * RATE:65 * RATE] == 3) and calls == [0, 1, 2])
    check("integer indexing works", source[-1] == 3)
    check("empty audio slice returns empty samples", len(source[:0]) == 0)

    fail = ProgressiveAudio("https://www.youtube.com/watch?v=sample", Path(folder), 45, section_seconds=30)

    def no_section(_):
        raise RuntimeError("Audio sections not available.")

    def good_fallback():
        fail._whole = np.full(len(fail), 7, dtype=np.int16)
        fail.fallback_used = True

    fail._read_section = no_section
    fail._load_full = good_fallback
    check("section errors fall back to working full downloader", np.all(fail[:2 * RATE] == 7)
          and fail.fallback_used)

    check("MAX analysis is a recognized boolean option",
          jobs.clean_options({"max_clips": 100, "scan_entire": True})["scan_entire"] is True)
    check("one-clip analysis is a recognized bounded option",
          jobs.clean_options({"max_clips": 1, "scan_entire": False})["max_clips"] == 1)

    game, tags = games.detect("Epic MINECRAFT survival stream")
    check("upstream game matching recognizes Minecraft", game == "Minecraft" and "Minecraft" in tags)
    taglist = hashtags.make("I found diamonds and diamonds again", "Minecraft speedrun", "Streamer", game)
    check("game tag appears in generated hashtag list", "minecraft" in taglist)
    check("game hashtags stay unique", len(taglist) == len(set(taglist)))

    check("browser policy allows in-memory blob preview images", "img-src 'self' data: blob:" in server.CSP)

print("ALL PASSED")

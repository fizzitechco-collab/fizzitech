"""Offline regression checks for Auto source resolution (up to genuine 4K)."""
from pathlib import Path
import sys
import tempfile
import os
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if not os.environ.get("PEAKCUT_DATA"):
    os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="legend-resolution-test-")

from studio import source_quality, jobs, creators, media, segment_download, render, live

def check(title, result):
    assert result, title
    print("PASS " + title)

check("1080p source outputs at most 1080p",
      source_quality.auto_export_height(1920, 1080) == 1080)
check("2160p source outputs genuine 4K",
      source_quality.auto_export_height(3840, 2160) == 2160)
check("1440p source stays at 1440p",
      source_quality.auto_export_height(2560, 1440) == 1440)
check("720p source stays 720p",
      source_quality.auto_export_height(1280, 720) == 720)
check("480p source is never upscaled to HD",
      source_quality.auto_export_height(854, 480) == 480)
check("portrait source uses its shorter dimension",
      source_quality.auto_export_height(1080, 1920) == 1080)
check("Auto job quality survives options validation",
      jobs.clean_options({"quality": 0})["quality"] == 0)
check("Explicit 4K quality survives options validation",
      jobs.clean_options({"quality": 2160})["quality"] == 2160)
check("Creator Auto preference is not replaced with 1080p",
      creators._clean({"clip_quality": 0})["clip_quality"] == 0)
check("Fixed-quality HLS downloads keep old verified 1080p source cap",
      segment_download._source_cap(1080) == min(1080, segment_download.FETCH_HEIGHT_CAP))
check("Auto download is capped at 4K",
      segment_download._source_cap(0) <= 2160)
check("4K download requires actual 4K if manually selected",
      segment_download._hd_min_height(2160) == 2160)
check("Auto download does not demand 4K from a 1080p source",
      segment_download._hd_min_height(0) == 0)
auto_cmd = segment_download._section_cmd(
    "https://www.youtube.com/watch?v=test", "clip.%(ext)s", 10, 20, 0)
check("Auto download asks for a capped source format",
      "-f" in auto_cmd and "height<=2160" in auto_cmd[auto_cmd.index("-f") + 1])
check("Whole-source Auto downloader is capped at 4K",
      "height<=2160" in media._video_format(0))
check("Native 4K crop uses a real 2160x3840 working canvas",
      "scale=2160:3840:" in render._filter("crop", 1920, canvas_w=2160))
check("1080p composition unchanged",
      "scale=1080:1920:" in render._filter("crop", 1920))
check("4K facecam composition uses matching large canvas",
      "scale=2160:" in render._filter("facecam", 1920, roi=(0.01, 0.01, 0.30, 0.30), canvas_w=2160))

import yt_dlp
original = yt_dlp.YoutubeDL
chosen = {}
class FakeDownloader:
    def __init__(self, options):
        chosen.update(options)
    def __enter__(self):
        return self
    def __exit__(self, typ, val, tb):
        return False
    def extract_info(self, url, download=False):
        return {"is_live": True, "title": "Test", "requested_formats": [
            {"url": "https://example.test/1080.mp4", "height": 1080},
            {"url": "https://example.test/audio.m4a"}]}
try:
    yt_dlp.YoutubeDL = FakeDownloader
    resolved = live.resolve("https://twitch.tv/example", quality=0)
    check("Auto livestream requests best available up to 4K",
          "height<=2160" in chosen["format"] and resolved["source_height"] == 1080)
finally:
    yt_dlp.YoutubeDL = original
print("ALL PASSED")

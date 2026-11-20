"""PeakCut standalone 144p diagnostic. Does not access user jobs or AI keys.

Usage:
  python -m studio.quickcheck
  python -m studio.quickcheck --url https://www.youtube.com/watch?v=... [--seconds 12]

No Youtube URL is stored. Downloads use the real PeakCut segment downloader.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def run(cmd, timeout=60):
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, errors="replace", timeout=timeout)


def probe_video(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
             "-show_entries", "format=duration", "-of", "json", str(path)], 15)
    if r.returncode:
        raise RuntimeError("ffprobe failed: " + r.stderr[-300:])
    o = json.loads(r.stdout)
    tracks = {x.get("codec_type") for x in o.get("streams", [])}
    if "video" not in tracks or "audio" not in tracks:
        raise RuntimeError("Output is missing video or audio stream")
    v = next(x for x in o["streams"] if x.get("codec_type") == "video")
    return (v.get("width"), v.get("height"), float(o["format"]["duration"]))


def main():
    p = argparse.ArgumentParser(description="PeakCut 144p segment test")
    p.add_argument("--url", help="Public video URL to test with 144p segment; never saved")
    p.add_argument("--seconds", type=int, default=12, help="Length of remote test, default 12 seconds")
    p.add_argument("--skip-offline", action="store_true")
    args = p.parse_args()
    print("PeakCut 144p diagnostics — no Gemini API key needed", flush=True)
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("FAIL: ffmpeg / ffprobe missing from PATH")
        return 2
    print("FFmpeg/ffprobe: OK", flush=True)
    try:
        import yt_dlp
        print("yt-dlp:", yt_dlp.version.__version__, flush=True)
    except ImportError:
        print("yt-dlp: missing. Run: .venv\\Scripts\\python.exe -m pip install -U 'yt-dlp[default]'", flush=True)
        if args.url:
            return 3
    if shutil.which("deno"):
        r = run(["deno", "--version"], 8)
        print("Deno:", r.stdout.splitlines()[0] if r.stdout else "found", flush=True)
    else:
        print("Deno: not installed/detected. YouTube EJS may require it; winget install DenoLand.Deno", flush=True)

    from . import segment_download as sd
    with tempfile.TemporaryDirectory(prefix="peakcut-144p-test-") as tmp:
        d = Path(tmp)
        if not args.skip_offline:
            src = d / "testsource.mp4"
            # Truly generate a 256x144 video/audio and exercise the actual local segment path.
            cmd = ["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "lavfi", "-i", "testsrc2=size=256x144:rate=24",
                   "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=44100",
                   "-t", "8", "-c:v", "mpeg4", "-q:v", "4", "-c:a", "aac", "-shortest", str(src)]
            r = run(cmd, 35)
            if r.returncode:
                print("FAIL: cannot encode 144p test video", r.stderr[-300:])
                return 4
            try:
                piece = sd._local_segment(src, d / "pieces", "test144", 1.0, 5.0, None)
                w, h, dur = probe_video(piece)
                if h != 144 or not 2 <= dur <= 5.5:
                    raise RuntimeError(f"Wrong output: {w}x{h}, {dur:.1f}s")
            except Exception as ex:
                print("FAIL: 144p local clip test:", ex)
                return 5
            output = Path.cwd() / "PEAKCUT-144P-LOCAL-TEST.mp4"
            shutil.copyfile(piece, output)
            print(f"PASS: actual 144p clip with sound rendered: {output} ({w}x{h}, {dur:.1f}s)", flush=True)
        if args.url:
            if not args.url.startswith(("https://", "http://")):
                print("FAIL: URL must begin with https:// or http://")
                return 6
            print("Testing REMOTE 144p segment (12 seconds by default). YouTube may return 403.", flush=True)
            # Remote test is segment-only no huge fallback; keeps current user's jobs untouched.
            old_cap = sd.FETCH_HEIGHT_CAP
            sd.FETCH_HEIGHT_CAP = 144
            try:
                part = sd.download_section(args.url, d / "online", "remote144", 2.0, float(max(5, min(args.seconds, 30)) + 2),
                                           height=144, cache_dir=None,
                                           stage=lambda x: print("  ", x, flush=True))
                w,h,duration=probe_video(part)
                output = Path.cwd() / "PEAKCUT-144P-ONLINE-TEST.mp4"
                shutil.copyfile(part, output)
                print(f"PASS: ONLINE segment downloaded {w}x{h} duration {duration:.1f}s -> {output}", flush=True)
            except Exception as ex:
                print("REMOTE TEST FAILED:", str(ex)[-500:], flush=True)
                print("This can be an upstream YouTube 403/token restriction; local render test is independent.", flush=True)
                return 7
            finally:
                sd.FETCH_HEIGHT_CAP = old_cap
    return 0

if __name__ == "__main__":
    sys.exit(main())

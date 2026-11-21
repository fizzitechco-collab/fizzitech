"""On-demand real video frames for the manual streamer webcam picker.

Unlike a YouTube thumbnail, the image comes from the footage that will be
clipped. A failed request never presents a misleading thumbnail as video.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from . import media, segment_download


def frame(url: str, at: float) -> bytes:
    """Return a JPEG frame around the selected time in the linked video."""
    if not media.site_allowed(url):
        raise ValueError("Unsupported video URL.")
    at = float(at)
    if not 0 <= at <= 12 * 3600:
        raise ValueError("Choose a valid preview timestamp.")

    media.check_youtube(url)
    with tempfile.TemporaryDirectory(prefix="legend-webcam-") as work:
        folder = Path(work)
        output = str(folder / "source.%(ext)s")
        if segment_download._is_youtube_url(url):
            fmt = (
                "312/bv[protocol^=m3u8][height<=1080]/"
                "bv[protocol^=https][height<=1080]"
            )
        else:
            fmt = "bv[height<=1080]/b[height<=1080]"
        cmd = segment_download._yt_dlp_base(url) + [
            "--download-sections", f"*{at:.3f}-{at + 2.5:.3f}",
            "--merge-output-format", "mp4",
            "-f", fmt, "-o", output, url,
        ]
        try:
            segment_download._run_bounded(
                cmd, folder, "source.*", 65, idle_seconds=40,
            )
            video = segment_download._result(folder, "source")
            out = subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-v", "error", "-ss", "0.4",
                    "-i", str(video), "-frames:v", "1",
                    "-vf", "scale=960:-2", "-q:v", "3",
                    "-f", "image2pipe", "-vcodec", "mjpeg", "-",
                ],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=18, check=False,
            )
            if out.returncode or len(out.stdout) < 1024:
                raise RuntimeError("Could not extract a frame from the downloaded video.")
            return out.stdout
        except (OSError, subprocess.TimeoutExpired, segment_download.DownloadFailure) as exc:
            raise RuntimeError(
                "Could not load a video frame from this link. Try another timestamp "
                "or select 'Choose facecam before rendering' for a clip preview."
            ) from exc

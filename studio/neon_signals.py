"""Optional, bounded motion / scene-change inspection for Legend Clipper.

We deliberately sample SHORT intervals using ffmpeg and decode 160x90 grayscale
frames, not whole livestream videos. This preserves the selected-section policy.
The numbers measure frame change, not recognition of a specific game or action.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np

FRAME_W, FRAME_H = 160, 90
FRAME_BYTES = FRAME_W * FRAME_H


def analyze(source: str | Path, start: float, end: float, *, timeout: int = 16) -> dict:
    """Return {motion, cuts, action_score, sampled_seconds} without decoding whole video.

    A maximum of ~9 seconds is sampled around the middle of an interval. If an
    external decoder fails, the result is unavailable rather than fabricated.
    """
    try:
        s, e = float(start), float(end)
        if not math.isfinite(s) or not math.isfinite(e) or s < 0 or e <= s:
            return {}
        source = Path(source)
        if not source.is_file():
            return {}
        length = min(9.0, e - s)
        mid = s + (e - s) / 2
        t0 = max(s, mid - length / 2)
        # Low resolution and 2 fps keeps Deep mode feasible without a GPU.
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-threads", "1", "-ss", f"{t0:.3f}",
               "-i", str(source), "-t", f"{length:.3f}", "-an", "-sn",
               "-vf", f"fps=2,scale={FRAME_W}:{FRAME_H}:flags=fast_bilinear,format=gray",
               "-f", "rawvideo", "-pix_fmt", "gray", "-"]
        run = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=timeout, check=False)
        if run.returncode != 0 or len(run.stdout) < FRAME_BYTES * 2:
            return {}
        frame_count = min(22, len(run.stdout) // FRAME_BYTES)
        arr = np.frombuffer(run.stdout[:frame_count * FRAME_BYTES], dtype=np.uint8).reshape(
            frame_count, FRAME_H, FRAME_W).astype(np.float32)
        diffs = np.mean(np.abs(np.diff(arr, axis=0)), axis=(1, 2)) / 255.0
        if diffs.size == 0:
            return {}
        # Robust trimmed mean prevents hard cuts from looking like constant action.
        trimmed = np.sort(diffs)[:max(1, int(math.ceil(diffs.size * .85)))]
        motion = float(np.mean(trimmed))
        cuts = int(np.count_nonzero(diffs >= .26))
        flash = float(np.max(np.abs(np.diff(np.mean(arr, axis=(1, 2))))) / 255.0)
        # Optional true optical flow. Farneback can distinguish moving objects
        # from uniform flashes; the fallback still works if cv2 is unavailable.
        optical_flow = None
        try:
            import cv2
            sampled = arr.astype(np.uint8)
            mags = []
            for idx in range(1, len(sampled)):
                flow = cv2.calcOpticalFlowFarneback(sampled[idx - 1], sampled[idx], None,
                                                    0.5, 2, 11, 2, 5, 1.1, 0)
                mag = cv2.magnitude(flow[..., 0], flow[..., 1])
                mags.append(float(np.median(mag)))
            if mags:
                optical_flow = min(1.0, float(np.mean(mags)) / 3.0)
        except (ImportError, ValueError, TypeError):
            pass
        score = motion / .095 * 72 + min(18, cuts * 7) + min(8, flash * 30)
        if optical_flow is not None:
            score += min(14, optical_flow * 14)
        action_score = int(round(min(100, score)))
        return {"motion": round(motion, 4), "optical_flow": round(optical_flow, 4) if optical_flow is not None else None,
                "cuts": cuts, "action_score": action_score,
                "sampled_seconds": round(length, 2), "frames": frame_count}
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        return {}


def boost(result: dict) -> int:
    """Small positive visual bonus. It must not overrule speech-context safety filters."""
    return max(0, min(10, int(round(float(result.get("action_score", 0)) / 10)))) if result else 0

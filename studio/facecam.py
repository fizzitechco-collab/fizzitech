"""Local streamer webcam *panel* detection (not identifying who the person is).

Samples frames from the selected segment, finds consistent faces in screen
corners, then expands to include the surrounding rectangular webcam overlay.
No heavy generative models, face recognition, biometric database or external
uploads. Always lets the user specify the webcam corner when auto fails.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

POSITIONS = ("auto", "top_left", "top_right", "bottom_left", "bottom_right")
SIZES = ("small", "medium", "large")


def _cascade(cv2):
    root = Path(cv2.data.haarcascades)
    models = []
    for filename in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
        detector = cv2.CascadeClassifier(str(root / filename))
        if not detector.empty():
            models.append((filename.startswith("haarcascade_profile"), detector))
    return models


def _frame(source: Path, position: float, cv2, np):
    result = subprocess.run([
        "ffmpeg", "-nostdin", "-loglevel", "error", "-ss", f"{position:.2f}",
        "-i", str(source), "-frames:v", "1", "-vf", "scale=720:-2",
        "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=13, check=False)
    if result.returncode or not result.stdout:
        return None
    return cv2.imdecode(np.frombuffer(result.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)


def _faces(frame, cv2, classifiers):
    height, width = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=1.7, tileGridSize=(8, 8)).apply(gray)
    results = []
    for profile, cascade in classifiers:
        for flip in ((False, True) if profile else (False,)):
            img = cv2.flip(gray, 1) if flip else gray
            faces = cascade.detectMultiScale(img, 1.09, 4, minSize=(25, 25),
                         maxSize=(int(width * .30), int(height * .55)))
            for x, y, w, h in faces:
                if flip:
                    x = width - x - w
                cx, cy = (x + w / 2) / width, (y + h / 2) / height
                # Minecraft characters/player HUD often occupy the centre.
                if .32 < cx < .68 or .18 < cx < .82 and .25 < cy < .75:
                    continue
                if w / width > .31 or h / height > .52:
                    continue
                results.append((cx, cy, w / width, h / height))
    return results


def _guess_panel(corner: str, size: str = "medium", face=None, source_ratio: float = 16/9):
    """Normalized x/y/w/h of the entire streamer webcam REGION incl. background.

    The region is substantially bigger than the face; its aspect approaches
    16:10 while maintaining corner anchoring. For overlays that do not match
    these assumptions users can try small/medium/large or crop elsewhere.
    """
    size = size if size in SIZES else "medium"
    w = {"small": .26, "medium": .35, "large": .45}[size]
    if face:
        # Ensure the face PLUS generous wall/background around it is included.
        w = max(w, min(.48, face[2] * 4.3))
    aspect = 1.58
    h = min(.65, w * max(1.0, source_ratio) / aspect)
    if corner not in POSITIONS or corner == "auto":
        corner = "top_left"
    x = 0.01 if corner.endswith("left") else 1 - w - .01
    y = .01 if corner.startswith("top") else 1 - h - .01
    # Some webcams are offset a little from the frame edge. Keep the detected
    # face away from the panel border without cropping the surrounding room.
    if face:
        cx, cy, _, _ = face
        x = max(0., min(1 - w, min(x + .11, max(x, cx - .58 * w)) if corner.endswith("left")
                                      else max(x - .11, min(x, cx - .42 * w))))
        y = max(0., min(1 - h, min(y + .10, max(y, cy - .48 * h)) if corner.startswith("top")
                                      else max(y - .10, min(y, cy - .52 * h))))
    return tuple(round(v, 4) for v in (x, y, w, h))


def detect_webcam_panel(video: Path, start: float, end: float, *, position="auto", size="medium"):
    """Return (ROI, metadata) or (None,metadata) if Smart detection is uncertain.

    Forced corner modes always yield a repeatable source crop, without any
    random face zoom. Smart requires a face at same place on multiple frames.
    """
    position = position if position in POSITIONS else "auto"
    size = size if size in SIZES else "medium"
    if position != "auto":
        return _guess_panel(position, size), {"method": "manual-corner", "position": position, "size": size}
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None, {"method": "unavailable", "reason": "OpenCV not installed"}
    classifiers = _cascade(cv2)
    if not classifiers:
        return None, {"method": "unavailable", "reason": "OpenCV face models missing"}
    duration = max(.25, end - start)
    offsets = (.5, 1.4, duration * .2, duration * .4, duration * .6, duration * .8)
    centers = []
    ratio = 16/9
    for idx, offset in enumerate(offsets):
        pos = max(0., start + min(max(0., duration - .2), offset))
        try:
            frame = _frame(Path(video), pos, cv2, np)
            if frame is None:
                continue
            ratio = frame.shape[1] / max(1, frame.shape[0])
            for face in _faces(frame, cv2, classifiers):
                centers.append((idx, face))
        except (OSError, ValueError, subprocess.TimeoutExpired, cv2.error):
            continue
    winner = []
    # Require distinct temporal samples, not duplicate cascades on one frame.
    for idx, f in centers:
        near = [(i, other) for i, other in centers
                if abs(other[0] - f[0]) < .10 and abs(other[1] - f[1]) < .13]
        if len(set(i for i, _ in near)) >= 2 and len(near) > len(winner):
            winner = near
    if not winner:
        return None, {"method": "not-detected", "samples": len(set(i for i, _ in centers))}
    f = tuple(sum(other[k] for _, other in winner) / len(winner) for k in range(4))
    horiz = "left" if f[0] < .5 else "right"
    vert = "top" if f[1] < .5 else "bottom"
    corner = f"{vert}_{horiz}"
    return _guess_panel(corner, size, face=f, source_ratio=ratio), {
        "method": "tracked-faces", "position": corner, "size": size,
        "samples": len(set(i for i, _ in winner)), "region_includes_background": True}


def facecam_roi(video: Path, start: float, end: float):
    """Backward-compatible API used by older versions of render.py."""
    return detect_webcam_panel(video, start, end)[0]


def parse_webcam_rect(value):
    """Optional exact panel crop, normalized source x,y,w,h (0..1)."""
    if not value:
        return None
    try:
        vals = [float(x.strip()) for x in str(value).split(",")]
        if len(vals) != 4:
            raise ValueError()
        x, y, w, h = vals
        if not (0 <= x < 1 and 0 <= y < 1 and .08 <= w <= .95 and .08 <= h <= .95 and x+w <= 1.0001 and y+h <= 1.0001):
            raise ValueError()
        return tuple(round(v, 4) for v in vals)
    except (TypeError, ValueError):
        raise ValueError("Webcam region must be source fractions x,y,width,height, e.g. 0.02,0.03,0.36,0.36") from None

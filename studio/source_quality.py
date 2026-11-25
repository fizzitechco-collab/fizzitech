"""Source-matched export sizes for the Auto (up to 4K) quality setting.

The smaller source dimension is the available vertical pixel budget. Never
request a larger output preset than the video actually contains.
"""
AUTO = 0
MAX_QUALITY = 2160
PRESETS = (2160, 1440, 1080, 720, 480, 360, 240, 144)
MANUAL = (360, 720, 1080, 2160)


def auto_export_height(width: int, height: int) -> int:
    """Best supported output width at or below actual source's short side."""
    short_side = min(int(width), int(height))
    for preset in PRESETS:
        if short_side >= preset:
            return preset
    raise ValueError("Source video is smaller than 144p, so it cannot make a usable clip.")

"""User-owned custom Campaigns for LegendClipper.

This is an organizational and clip-copy workflow, NOT the GTA VI / Expedia
hard-coded selection rules. No campaign posts or payouts run automatically.
Campaign definitions are stored per signed-in user under their existing data
folder. Jobs keep a snapshot so editing/deleting a campaign cannot silently
rewrite clips already created.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from . import config, ctx

_LOCK = threading.RLock()
_MAX_CAMPAIGNS = 50
_FIELDS = ("name", "brand", "brief", "hook_text", "description_text",
           "hashtags", "status", "rate_per_1k")
_LIMITS = {"name": 85, "brand": 90, "brief": 1500,
           "hook_text": 60, "description_text": 2000}


def _path() -> Path:
    return config.user_dir(ctx.uid()) / "custom_campaigns.json"


def _read() -> list[dict]:
    path = _path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except FileNotFoundError:
        return []
    except (OSError, ValueError, TypeError):
        raise ValueError("Could not read saved campaigns; check the campaign data file.")


def _write(rows: list[dict]) -> None:
    file = _path()
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_name(file.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as out:
            json.dump(rows, out, indent=2, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        tmp.replace(file)
    finally:
        tmp.unlink(missing_ok=True)
    ctx.bump()


def _tags(value) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[\s,]+", value)
    elif isinstance(value, list):
        parts = value
    else:
        raise ValueError("Hashtags must be a text string or a list.")
    tags, seen = [], set()
    for item in parts:
        tag = str(item).strip().lstrip("#")
        if not tag:
            continue
        if not re.fullmatch(r"[\w]{1,40}", tag, re.UNICODE):
            raise ValueError("Hashtags can contain letters, numbers and underscores only (max 40 each).")
        if tag.casefold() not in seen:
            tags.append(tag)
            seen.add(tag.casefold())
        if len(tags) > 10:
            raise ValueError("Maximum 10 unique hashtags per campaign.")
    return tags


def _clean(body: dict, previous: dict | None = None) -> dict:
    if not isinstance(body, dict):
        raise ValueError("Invalid campaign details.")
    item = dict(previous or {})
    for key in _FIELDS:
        if key not in body and previous is not None:
            continue
        value = body.get(key, "active" if key == "status" else ([] if key == "hashtags" else ""))
        if key in _LIMITS:
            value = str(value or "").strip()
            if len(value) > _LIMITS[key]:
                raise ValueError(f"{key.replace('_', ' ').title()} is too long.")
            item[key] = value
        elif key == "hashtags":
            item[key] = _tags(value)
        elif key == "status":
            if value not in ("active", "paused"):
                raise ValueError("Choose Active or Paused for this campaign.")
            item[key] = value
        elif key == "rate_per_1k":
            try:
                amount = float(value or 0)
            except (ValueError, TypeError):
                raise ValueError("Campaign rate must be a number.")
            if not 0 <= amount <= 100000 or amount != amount:
                raise ValueError("Campaign rate must be between 0 and 100000.")
            item[key] = round(amount, 2)
    if not item.get("name"):
        raise ValueError("Enter a campaign name.")
    return item


def all_campaigns() -> list[dict]:
    with _LOCK:
        return sorted(_read(), key=lambda c: (-c.get("updated", 0), c["id"]))


def get(campaign_id: str) -> dict | None:
    if not re.fullmatch(r"[0-9a-f]{12,32}", str(campaign_id or "")):
        return None
    with _LOCK:
        return next((c for c in _read() if c.get("id") == campaign_id), None)


def create(body: dict) -> dict:
    with _LOCK:
        rows = _read()
        if len(rows) >= _MAX_CAMPAIGNS:
            raise ValueError(f"Maximum {_MAX_CAMPAIGNS} campaigns per account.")
        item = _clean(body)
        now = time.time()
        item.update(id=uuid.uuid4().hex[:16], created=now, updated=now)
        rows.append(item)
        _write(rows)
        return item


def update(campaign_id: str, body: dict) -> dict:
    with _LOCK:
        rows = _read()
        for index, item in enumerate(rows):
            if item.get("id") == campaign_id:
                changed = _clean(body, item)
                changed["updated"] = time.time()
                rows[index] = changed
                _write(rows)
                return changed
        raise KeyError("Campaign not found.")


def delete(campaign_id: str) -> None:
    with _LOCK:
        rows = _read()
        kept = [c for c in rows if c.get("id") != campaign_id]
        if len(kept) == len(rows):
            raise KeyError("Campaign not found.")
        _write(kept)


def snapshot(campaign_id: str) -> dict:
    """Return immutable-by-convention campaign copy for one new clip job."""
    c = get(campaign_id)
    if c is None:
        raise ValueError("Custom campaign not found. Reload Campaigns and try again.")
    if c["status"] != "active":
        raise ValueError("This campaign is paused. Activate it to create new clips.")
    return {key: c[key] for key in ("id", "name", "brand", "brief",
                                   "hook_text", "description_text", "hashtags")}

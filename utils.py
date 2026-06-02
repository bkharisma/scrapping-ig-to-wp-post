import re
import json
from datetime import datetime
from pathlib import Path


def parse_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def validate_date(date_str: str) -> bool:
    if not date_str:
        return True
    return parse_date(date_str) is not None


def is_within_period(timestamp: str, date_from: str, date_to: str) -> bool:
    if not date_from and not date_to:
        return True
    try:
        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        ts = ts.replace(tzinfo=None)
        if date_from:
            fd = parse_date(date_from)
            if fd and ts < fd:
                return False
        if date_to:
            td = parse_date(date_to)
            if td and ts > td.replace(hour=23, minute=59, second=59):
                return False
        return True
    except (ValueError, AttributeError):
        return True


def save_metadata(posts: list[dict], path: Path):
    cleaned = []
    for p in posts:
        cleaned.append({
            "id": p.get("id"),
            "media_type": p.get("media_type"),
            "caption": p.get("caption"),
            "timestamp": p.get("timestamp"),
            "permalink": p.get("permalink"),
            "like_count": p.get("like_count", 0),
            "comments_count": p.get("comments_count", 0),
            "media_url": p.get("media_url"),
            "thumbnail_url": p.get("thumbnail_url"),
            "media_files": p.get("_media_files", []),
            "comments": p.get("_comments", []),
            "children": [
                {
                    "id": c.get("id"),
                    "media_type": c.get("media_type"),
                    "media_url": c.get("media_url"),
                    "thumbnail_url": c.get("thumbnail_url"),
                }
                for c in p.get("children", {}).get("data", [])
            ] if p.get("children") else [],
        })
    path.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False))


MIMETYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}

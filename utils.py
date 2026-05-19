from datetime import datetime


def parse_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


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


MIMETYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}

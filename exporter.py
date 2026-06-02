import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def export_captions_csv(posts: list[dict], output_path: Path):
    fieldnames = ["id", "date", "caption", "type", "likes", "comments", "permalink"]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in posts:
            date_str = ""
            if p.get("timestamp"):
                parts = p["timestamp"][:10].split("-")
                if len(parts) == 3:
                    date_str = f"{parts[2]}-{parts[1]}-{parts[0]}"

            writer.writerow({
                "id": p.get("id", ""),
                "date": date_str,
                "caption": p.get("caption", ""),
                "type": p.get("media_type", ""),
                "likes": p.get("like_count", 0),
                "comments": p.get("comments_count", 0),
                "permalink": p.get("permalink", ""),
            })

    logger.info(f"CSV exported: {output_path} ({len(posts)} rows)")

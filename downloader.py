import logging
from pathlib import Path
from urllib.parse import urlparse
import requests
from tqdm import tqdm
from config import OUTPUT_DIR

logger = logging.getLogger(__name__)


def _ext_guessed(url: str) -> str:
    path = urlparse(url).path
    guess = Path(path).suffix
    if guess and len(guess) <= 6:
        return guess
    return ".bin"


def download_media(posts: list[dict], subdir: str = "media") -> list[dict]:
    media_dir = OUTPUT_DIR / subdir
    media_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    downloaded: list[dict] = []

    all_items: list[tuple[int, str, str, str | None]] = []
    for idx, post in enumerate(posts):
        if post.get("media_type") in ("IMAGE", "VIDEO") and post.get("media_url"):
            all_items.append((idx, post["id"], post["media_type"], post.get("media_url")))
        elif post.get("media_type") == "CAROUSEL_ALBUM" and post.get("children", {}).get("data"):
            for child in post["children"]["data"]:
                url = child.get("media_url") or child.get("thumbnail_url")
                if url:
                    all_items.append((idx, f"{post['id']}_{child['id']}", child["media_type"], url))

    for post_idx, item_id, media_type, url in tqdm(all_items, desc="Download media"):
        try:
            ext = _ext_guessed(url)
            filename = f"{item_id}{ext}"
            filepath = media_dir / filename

            if filepath.exists():
                downloaded.append({"id": item_id, "path": str(filepath), "media_type": media_type})
                continue

            resp = session.get(url, timeout=60, stream=True)
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))

            with open(filepath, "wb") as f:
                with tqdm(total=total, unit="B", unit_scale=True, desc=f"  {item_id[:12]}...", leave=False) as pbar:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                        pbar.update(len(chunk))

            posts[post_idx].setdefault("_media_files", []).append(str(filepath))
            downloaded.append({"id": item_id, "path": str(filepath), "media_type": media_type})

        except Exception as e:
            logger.warning(f"Gagal download {item_id}: {e}")

    logger.info(f"Download selesai: {len(downloaded)} file ke {media_dir}")
    return downloaded


def download_media_organized(posts: list[dict], media_dir: Path, progress_callback=None):
    media_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    downloaded: list[dict] = []

    all_items: list[tuple[int, str, str, str | None, str]] = []
    for idx, post in enumerate(posts):
        date_str = ""
        if post.get("timestamp"):
            date_str = post["timestamp"][:10]
        if post.get("media_type") in ("IMAGE", "VIDEO") and post.get("media_url"):
            all_items.append((idx, post["id"], post["media_type"], post.get("media_url"), date_str))
        elif post.get("media_type") == "CAROUSEL_ALBUM" and post.get("children", {}).get("data"):
            for child in post["children"]["data"]:
                url = child.get("media_url") or child.get("thumbnail_url")
                if url:
                    all_items.append((idx, f"{post['id']}_{child['id']}", child["media_type"], url, date_str))

    total = len(all_items)
    iterator = tqdm(all_items, desc="Download media") if not progress_callback else all_items

    for i, (post_idx, item_id, media_type, url, date_str) in enumerate(iterator):
        try:
            ext = _ext_guessed(url)
            filename = f"{item_id}{ext}"

            date_dir = media_dir / date_str if date_str else media_dir
            date_dir.mkdir(parents=True, exist_ok=True)
            filepath = date_dir / filename

            if filepath.exists():
                downloaded.append({"id": item_id, "path": str(filepath), "media_type": media_type})
                posts[post_idx].setdefault("_media_files", []).append(str(filepath))
                if progress_callback:
                    progress_callback(i + 1, total, f"{item_id[:12]}... (exists)")
                continue

            resp = session.get(url, timeout=60, stream=True)
            resp.raise_for_status()
            cl = int(resp.headers.get("content-length", 0))

            with open(filepath, "wb") as f:
                with tqdm(total=cl, unit="B", unit_scale=True, desc=f"  {item_id[:12]}...", leave=False) as pbar:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                        pbar.update(len(chunk))

            posts[post_idx].setdefault("_media_files", []).append(str(filepath))
            downloaded.append({"id": item_id, "path": str(filepath), "media_type": media_type})

            if progress_callback:
                progress_callback(i + 1, total, f"{item_id[:12]}...")

        except Exception as e:
            logger.warning(f"Gagal download {item_id}: {e}")
            if progress_callback:
                progress_callback(i + 1, total, f"{item_id[:12]}... FAILED")

    logger.info(f"Download selesai: {len(downloaded)} file ke {media_dir}")
    return downloaded

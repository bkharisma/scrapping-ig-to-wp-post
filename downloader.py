import logging
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from tqdm import tqdm
from config import OUTPUT_DIR, MAX_CONCURRENT_DOWNLOADS

logger = logging.getLogger(__name__)


def _ext_guessed(url: str) -> str:
    path = urlparse(url).path
    guess = Path(path).suffix
    if guess and len(guess) <= 6:
        return guess
    return ".bin"


def _download_single(session: requests.Session, url: str, filepath: Path,
                     media_type: str, item_id: str) -> dict | None:
    try:
        resp = session.get(url, timeout=60, stream=True)
        resp.raise_for_status()

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        return {"id": item_id, "path": str(filepath), "media_type": media_type}
    except Exception as e:
        logger.warning(f"Gagal download {item_id}: {e}")
        return None


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
                media_files = posts[post_idx].setdefault("_media_files", [])
                if str(filepath) not in media_files:
                    media_files.append(str(filepath))
                downloaded.append({"id": item_id, "path": str(filepath), "media_type": media_type})
                continue

            result = _download_single(session, url, filepath, media_type, item_id)
            if result:
                media_files = posts[post_idx].setdefault("_media_files", [])
                if str(filepath) not in media_files:
                    media_files.append(str(filepath))
                downloaded.append(result)

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
            parts = post["timestamp"][:10].split("-")
            if len(parts) == 3:
                date_str = f"{parts[2]}{parts[1]}{parts[0]}"
        if post.get("media_type") in ("IMAGE", "VIDEO") and post.get("media_url"):
            all_items.append((idx, post["id"], post["media_type"], post.get("media_url"), date_str))
        elif post.get("media_type") == "CAROUSEL_ALBUM" and post.get("children", {}).get("data"):
            for child in post["children"]["data"]:
                url = child.get("media_url") or child.get("thumbnail_url")
                if url:
                    all_items.append((idx, f"{post['id']}_{child['id']}", child["media_type"], url, date_str))

    total = len(all_items)
    max_workers = min(MAX_CONCURRENT_DOWNLOADS, 8)

    def download_item(item_tuple):
        post_idx, item_id, media_type, url, date_str = item_tuple
        try:
            ext = _ext_guessed(url)
            filename = f"{item_id}{ext}"

            date_dir = media_dir / date_str if date_str else media_dir
            date_dir.mkdir(parents=True, exist_ok=True)
            filepath = date_dir / filename

            if filepath.exists():
                return post_idx, item_id, media_type, str(filepath), True, None

            result = _download_single(session, url, filepath, media_type, item_id)
            if result:
                return post_idx, item_id, media_type, str(filepath), False, None
            else:
                return post_idx, item_id, media_type, None, False, "FAILED"
        except Exception as e:
            return post_idx, item_id, media_type, None, False, str(e)

    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download_item, item): item for item in all_items}

        for future in as_completed(futures):
            completed += 1
            post_idx, item_id, media_type, filepath, existed, error = future.result()

            if filepath:
                media_files = posts[post_idx].setdefault("_media_files", [])
                if filepath not in media_files:
                    media_files.append(filepath)
                downloaded.append({"id": item_id, "path": filepath, "media_type": media_type})

            if progress_callback:
                status_msg = f"{item_id[:12]}... ({'exists' if existed else 'FAILED' if error else 'ok'})"
                progress_callback(completed, total, status_msg)

    logger.info(f"Download selesai: {len(downloaded)} file ke {media_dir}")
    return downloaded

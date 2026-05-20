import json
import logging
import sys
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from config import ACCESS_TOKEN, IG_USER_ID, DATE_FROM, DATE_TO, OUTPUT_DIR
from scrapper import InstagramScrapper
from downloader import download_media

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def validate_config():
    errors = []
    if not ACCESS_TOKEN:
        errors.append("ACCESS_TOKEN belum diisi di .env")
    if not IG_USER_ID:
        errors.append("IG_USER_ID belum diisi di .env")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


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
    logger.info(f"Metadata disimpan: {path} ({len(cleaned)} post)")


def main():
    validate_config()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    scraper = InstagramScrapper()

    logger.info("Mengambil info akun...")
    try:
        info = scraper.get_account_info()
        logger.info(f"Akun: @{info.get('username')} ({info.get('name')})")
        logger.info(f"Followers: {info.get('followers_count')} | Total post: {info.get('media_count')}")
    except Exception as e:
        logger.warning(f"Gagal ambil info akun: {e}")

    logger.info(f"Mengambil post (periode: {DATE_FROM or 'awal'} ~ {DATE_TO or 'sekarang'})...")
    try:
        posts = scraper.fetch_all_media(DATE_FROM, DATE_TO)
    except Exception as e:
        logger.error(f"Gagal mengambil media: {e}")
        sys.exit(1)

    if not posts:
        logger.warning("Tidak ada post dalam periode tersebut.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    meta_path = OUTPUT_DIR / f"metadata_{timestamp}.json"
    save_metadata(posts, meta_path)

    logger.info("Mendownload file media...")
    try:
        download_media(posts)
    except Exception as e:
        logger.warning(f"Download media gagal: {e}")

    # update metadata dengan path file lokal
    save_metadata(posts, meta_path)

    logger.info("Selesai!")
    logger.info(f"Metadata: {meta_path}")
    logger.info(f"Media   : {OUTPUT_DIR / 'media'}/")


if __name__ == "__main__":
    main()

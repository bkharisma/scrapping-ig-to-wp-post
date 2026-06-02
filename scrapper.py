import time
import logging
from typing import Any
import requests
from config import ACCESS_TOKEN, IG_USER_ID, GRAPH_API_BASE, REQUEST_DELAY, MAX_RETRIES
from utils import is_within_period

logger = logging.getLogger(__name__)


class InstagramScrapper:
    def __init__(self):
        self.session = requests.Session()
        self.session.params = {"access_token": ACCESS_TOKEN}
        self.user_id = IG_USER_ID

    def _request(self, url: str, params: dict | None = None) -> dict:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.session.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    raise Exception(f"API error: {data['error']}")
                return data
            except requests.RequestException as e:
                logger.warning(f"Request failed (attempt {attempt}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(2 ** attempt)
                else:
                    raise

    def get_media_fields(self) -> str:
        return (
            "id,caption,media_type,media_url,thumbnail_url,"
            "timestamp,permalink,like_count,comments_count,"
            "children{media_type,media_url,thumbnail_url}"
        )

    def fetch_all_media(self, date_from: str = "", date_to: str = "",
                        fetch_comments: bool = False, comments_limit: int = 25,
                        progress_callback=None) -> list[dict]:
        if not self.user_id:
            raise ValueError("IG_USER_ID belum diisi di .env")
        if not ACCESS_TOKEN:
            raise ValueError("ACCESS_TOKEN belum diisi di .env")

        url = f"{GRAPH_API_BASE}/{self.user_id}/media"
        params = {"fields": self.get_media_fields(), "limit": 100}
        all_posts: list[dict] = []
        page = 1

        while url:
            logger.info(f"Mengambil halaman {page}...")
            data = self._request(url, params if page == 1 else None)
            params = None

            raw_posts = data.get("data", [])
            if not raw_posts:
                break

            filtered = [
                p for p in raw_posts
                if is_within_period(p.get("timestamp", ""), date_from, date_to)
            ]
            all_posts.extend(filtered)

            logging.debug(
                f"  -> {len(raw_posts)} post, "
                f"{len(filtered)} dalam periode"
            )

            url = data.get("paging", {}).get("next", "")
            page += 1
            time.sleep(REQUEST_DELAY)

        logger.info(f"Total post dalam periode: {len(all_posts)}")

        if fetch_comments and all_posts:
            logger.info(f"Mengambil komentar untuk {len(all_posts)} post...")
            for idx, post in enumerate(all_posts, 1):
                try:
                    comments = self.fetch_comments(post["id"], comments_limit)
                    post["_comments"] = comments
                except Exception as e:
                    logger.warning(f"Gagal ambil komentar post {post['id']}: {e}")
                    post["_comments"] = []
                if progress_callback:
                    progress_callback(idx, len(all_posts),
                                      f"Komentar: {idx}/{len(all_posts)}")
                time.sleep(REQUEST_DELAY)

        return all_posts

    def fetch_comments(self, media_id: str, limit: int = 25) -> list[dict]:
        url = f"{GRAPH_API_BASE}/{media_id}/comments"
        params = {"fields": "text,timestamp,username", "limit": limit}
        data = self._request(url, params)
        raw = data.get("data", [])
        return [
            {"text": c.get("text", ""), "timestamp": c.get("timestamp", ""),
             "username": c.get("username", "")}
            for c in raw
        ]

    def get_account_info(self) -> dict[str, Any]:
        url = f"{GRAPH_API_BASE}/{self.user_id}"
        params = {"fields": "id,username,name,profile_picture_url,biography,followers_count,media_count"}
        return self._request(url, params)

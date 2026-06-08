import json
import logging
import threading
import tempfile
import re
import shutil
import time
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_file, send_from_directory

from config import (
    ACCESS_TOKEN, IG_USER_ID, FETCH_COMMENTS, COMMENTS_LIMIT,
    WP_ENABLED, WP_URL, WP_USER, WP_APP_PASS, WP_POST_STATUS,
    API_KEY, METADATA_CACHE_TTL,
)
from scrapper import InstagramScrapper
from downloader import download_media_organized
from exporter import export_captions_csv
from utils import save_metadata, validate_date
from analytics import (
    analyze_engagement, analyze_sentiment, analyze_target_market,
    get_post_sentiment, get_sentiment_words, add_sentiment_word,
    remove_sentiment_word, analyze_best_time_to_post,
    extract_word_frequencies, analyze_content_categories,
    analyze_followers_trend,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

DATA_DIR = Path("data")
CRAWLS_DIR = DATA_DIR / "crawls"
CRAWLS_DIR.mkdir(parents=True, exist_ok=True)

scrap_progress: dict = {}
scrap_lock = threading.Lock()
index_lock = threading.Lock()

_scraper_instance: InstagramScrapper | None = None
_scraper_lock = threading.Lock()

_metadata_cache: dict[str, tuple[float, list[dict]]] = {}
_metadata_cache_lock = threading.Lock()
_metadata_read_lock = threading.Lock()

_analytics_cache: dict[str, tuple[float, dict]] = {}
_analytics_cache_lock = threading.Lock()

PROGRESS_MAX_AGE = 3600


def _get_scraper() -> InstagramScrapper:
    global _scraper_instance
    with _scraper_lock:
        if _scraper_instance is None:
            _scraper_instance = InstagramScrapper()
        return _scraper_instance


def _invalidate_scraper():
    global _scraper_instance
    with _scraper_lock:
        _scraper_instance = None


def _cleanup_old_progress():
    now = time.time()
    to_delete = [
        key for key, val in scrap_progress.items()
        if val.get("status") in ("done", "error") and now - val.get("_completed_at", now) > PROGRESS_MAX_AGE
    ]
    for key in to_delete:
        del scrap_progress[key]


def get_session_index() -> list[dict]:
    idx_path = CRAWLS_DIR / "index.json"
    if idx_path.exists():
        return json.loads(idx_path.read_text(encoding="utf-8"))
    return []


def save_session_index(index: list[dict]):
    (CRAWLS_DIR / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False)
    )


def update_session_index(session_id: str, posts: list[dict],
                         date_from: str, date_to: str, media_types: list[str]):
    dates = []
    for p in posts:
        ts = p.get("timestamp", "")
        if ts:
            parts = ts[:10].split("-")
            if len(parts) == 3:
                dates.append(f"{parts[2]}-{parts[1]}-{parts[0]}")
    total_media = sum(len(p.get("_media_files", [])) for p in posts)

    entry = {
        "session_id": session_id,
        "date": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
        "total_posts": len(posts),
        "total_media": total_media,
        "filter_date_from": date_from or "",
        "filter_date_to": date_to or "",
        "filter_types": media_types,
        "data_from": min(dates) if dates else "",
        "data_to": max(dates) if dates else "",
    }

    with index_lock:
        index = get_session_index()
        index.insert(0, entry)
        save_session_index(index)


def _load_metadata(session_id: str) -> list[dict]:
    meta_path = CRAWLS_DIR / session_id / "metadata.json"
    if not meta_path.exists():
        return None

    mtime = meta_path.stat().st_mtime

    with _metadata_cache_lock:
        if session_id in _metadata_cache:
            cached_mtime, cached_data = _metadata_cache[session_id]
            if cached_mtime == mtime:
                return cached_data

    with _metadata_read_lock:
        with _metadata_cache_lock:
            if session_id in _metadata_cache:
                cached_mtime, cached_data = _metadata_cache[session_id]
                if cached_mtime == mtime:
                    return cached_data

        posts = json.loads(meta_path.read_text(encoding="utf-8"))

        with _metadata_cache_lock:
            _metadata_cache[session_id] = (mtime, posts)

        return posts


def _invalidate_metadata_cache(session_id: str):
    with _metadata_cache_lock:
        _metadata_cache.pop(session_id, None)
    with _analytics_cache_lock:
        keys_to_del = [k for k in _analytics_cache if k.startswith(f"{session_id}/")]
        for k in keys_to_del:
            del _analytics_cache[k]


def _load_wp_posted(session_id: str) -> dict[str, dict]:
    wp_path = CRAWLS_DIR / session_id / "wp_posted.json"
    if not wp_path.exists():
        return {}
    try:
        return json.loads(wp_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_wp_posted(session_id: str, data: dict[str, dict]):
    wp_path = CRAWLS_DIR / session_id / "wp_posted.json"
    wp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _get_posted_ig_ids(session_id: str) -> set[str]:
    data = _load_wp_posted(session_id)
    return set(data.keys())


def _get_cached_analytics(session_id: str, key: str) -> dict | None:
    cache_key = f"{session_id}/{key}"
    meta_path = CRAWLS_DIR / session_id / "metadata.json"
    if not meta_path.exists():
        return None
    meta_mtime = meta_path.stat().st_mtime
    info_path = CRAWLS_DIR / session_id / "session_info.json"
    info_mtime = info_path.stat().st_mtime if info_path.exists() else 0
    latest_mtime = max(meta_mtime, info_mtime)

    with _analytics_cache_lock:
        if cache_key in _analytics_cache:
            cached_mtime, cached_data = _analytics_cache[cache_key]
            if cached_mtime >= latest_mtime:
                return cached_data
    return None


def _set_cached_analytics(session_id: str, key: str, data: dict):
    if "error" in data:
        return
    cache_key = f"{session_id}/{key}"
    meta_path = CRAWLS_DIR / session_id / "metadata.json"
    if not meta_path.exists():
        return
    meta_mtime = meta_path.stat().st_mtime
    info_path = CRAWLS_DIR / session_id / "session_info.json"
    info_mtime = info_path.stat().st_mtime if info_path.exists() else 0
    latest_mtime = max(meta_mtime, info_mtime)
    with _analytics_cache_lock:
        _analytics_cache[cache_key] = (latest_mtime, data)


def _save_session_info(session_id: str, account_info: dict):
    info_path = CRAWLS_DIR / session_id / "session_info.json"
    info_path.write_text(json.dumps({
        "followers_count": account_info.get("followers_count", 0),
        "username": account_info.get("username", ""),
        "name": account_info.get("name", ""),
        "saved_at": datetime.now().isoformat(),
    }, ensure_ascii=False), encoding="utf-8")


def _load_session_info(session_id: str) -> dict:
    info_path = CRAWLS_DIR / session_id / "session_info.json"
    if info_path.exists():
        try:
            return json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _get_followers_count(session_id: str) -> tuple[int, str]:
    cached = _load_session_info(session_id)
    if cached.get("followers_count"):
        return cached["followers_count"], "cached"

    try:
        scraper = _get_scraper()
        account = scraper.get_account_info()
        followers = account.get("followers_count", 0)
        if followers > 0:
            _save_session_info(session_id, account)
            return followers, "cached"
        return 0, "api_returned_zero"
    except Exception as e:
        logger.warning(f"Gagal ambil followers count: {e}")
        return 0, "api_unavailable"


def scrap_task(date_from: str, date_to: str, media_types: list[str],
               progress_key: str, fetch_comments: bool = False,
               comments_limit: int = 25, auto_post: bool = False):
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    def update_prog(**kw):
        with scrap_lock:
            _cleanup_old_progress()
            scrap_progress[progress_key].update(kw)

    def download_cb(done, total, msg):
        pct = int(done / total * 100) if total else 0
        update_prog(total_downloaded=done, total_to_download=total,
                     download_pct=pct, message=f"Download media: {done}/{total} - {msg}")

    try:
        with scrap_lock:
            scrap_progress[progress_key] = {
                "status": "running", "session_id": session_id,
                "page": 0, "total_fetched": 0, "total_downloaded": 0,
                "download_pct": 0, "message": "Memulai scrapping...",
            }

        session_dir = CRAWLS_DIR / session_id
        session_dir.mkdir(parents=True)

        scraper = _get_scraper()

        try:
            account = scraper.get_account_info()
            _save_session_info(session_id, account)
        except Exception:
            logger.warning("Gagal ambil info akun saat scrap")

        def comments_cb(done, total, msg):
            update_prog(message=msg)
        update_prog(message="Mengambil data dari Instagram...")
        posts = scraper.fetch_all_media(
            date_from, date_to,
            fetch_comments=fetch_comments,
            comments_limit=comments_limit,
            progress_callback=comments_cb if fetch_comments else None,
        )

        update_prog(total_fetched=len(posts),
                     message=f"Ditemukan {len(posts)} post dalam periode")

        if media_types:
            filtered = [p for p in posts if p.get("media_type") in media_types]
            update_prog(message=f"Filter {media_types}: {len(filtered)} post tersisa")
            posts = filtered

        if not posts:
            save_metadata(posts, session_dir / "metadata.json")
            export_captions_csv(posts, session_dir / "captions.csv")
            update_session_index(session_id, posts, date_from, date_to, media_types)
            update_prog(status="done", _completed_at=time.time(),
                         message=f"Selesai! Tidak ada post untuk filter yang dipilih.",
                         session_id=session_id)
            return

        media_dir = session_dir / "media"
        update_prog(message=f"Mendownload {sum(
            1 for p in posts if p.get('media_type') in ('IMAGE', 'VIDEO')
            or (p.get('media_type') == 'CAROUSEL_ALBUM' and p.get('children', {}).get('data'))
        )} file media...")
        download_media_organized(posts, media_dir, progress_callback=download_cb)

        save_metadata(posts, session_dir / "metadata.json")
        export_captions_csv(posts, session_dir / "captions.csv")
        update_session_index(session_id, posts, date_from, date_to, media_types)

        total_media = sum(len(p.get("_media_files", [])) for p in posts)

        wp_results = []
        if auto_post and WP_ENABLED and WP_URL and WP_USER and WP_APP_PASS:
            try:
                from wordpress import WordPressClient
                wp = WordPressClient()

                posted_ids = _get_posted_ig_ids(session_id)
                posts_to_post = [p for p in posts if p.get("id") not in posted_ids]
                if len(posts_to_post) < len(posts):
                    logger.info(f"Auto-post: {len(posts) - len(posts_to_post)} post sudah diposting, di-skip")

                if posts_to_post:
                    update_prog(message=f"Mengupload {len(posts_to_post)} post ke WordPress...")

                    def wp_progress(done, total, msg):
                        update_prog(wp_posted=done, wp_total=total, message=msg)

                    wp_results = wp.post_all(posts_to_post, status=WP_POST_STATUS, progress_callback=wp_progress)

                    wp_posted_data = _load_wp_posted(session_id)
                    for r in wp_results:
                        ig_id = r.get("ig_post_id")
                        wp_id = r.get("wp_post_id")
                        if ig_id and (r.get("success") or r.get("skipped")):
                            wp_posted_data.setdefault("posts", {})[ig_id] = {
                                "wp_post_id": wp_id,
                                "wp_edit_url": r.get("wp_edit_url", ""),
                                "status": "skipped" if r.get("skipped") else "posted",
                                "posted_at": datetime.now().isoformat(),
                            }
                    _save_wp_posted(session_id, wp_posted_data)
                else:
                    wp_results = [{"skipped": True, "ig_post_id": pid} for pid in posted_ids]

                wp_ok = sum(1 for r in wp_results if r.get("success"))
                wp_skip = sum(1 for r in wp_results if r.get("skipped"))
                msg = f"Selesai! {len(posts)} post, {total_media} media, WP: {wp_ok}/{len(posts_to_post or [])} draft"
                if wp_skip:
                    msg += f", {wp_skip} skip"
                update_prog(
                    status="done", download_pct=100, _completed_at=time.time(),
                    message=msg,
                    session_id=session_id, wp_results=wp_results,
                )
                return
            except Exception as e:
                logger.exception("WordPress auto-post gagal")
                wp_error = str(e)
                wp_results = [{"success": False, "error": wp_error}]
                update_prog(
                    status="done", download_pct=100, _completed_at=time.time(),
                    message=f"Selesai! {len(posts)} post, {total_media} media — WP GAGAL: {wp_error}",
                    session_id=session_id, wp_results=wp_results,
                )
                return

        update_prog(status="done", download_pct=100, _completed_at=time.time(),
                     message=f"Selesai! {len(posts)} post, {total_media} file media"
                             + (" (WP tidak aktif)" if not WP_ENABLED else ""),
                     session_id=session_id, wp_results=wp_results)

    except Exception as e:
        logger.exception("Crawl gagal")
        with scrap_lock:
            scrap_progress[progress_key] = {
                "status": "error", "session_id": session_id,
                "message": f"Error: {str(e)}",
                "_completed_at": time.time(),
            }


@app.before_request
def check_api_key():
    if not API_KEY:
        return
    if request.path.startswith("/static"):
        return
    if request.path == "/":
        return
    key = request.headers.get("X-API-Key", "") or request.args.get("api_key", "")
    if key != API_KEY:
        return jsonify({"error": "Unauthorized: API key required"}), 401


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scrap", methods=["POST"])
def start_scrap():
    data = request.get_json()
    date_from = data.get("date_from", "")
    date_to = data.get("date_to", "")
    media_types = data.get("media_types", [])
    fetch_comments = data.get("fetch_comments", False)
    auto_post = data.get("auto_post", False)

    if not ACCESS_TOKEN or not IG_USER_ID:
        return jsonify({"error": "ACCESS_TOKEN atau IG_USER_ID belum diisi di .env"}), 400

    if not validate_date(date_from) or not validate_date(date_to):
        return jsonify({"error": "Format tanggal tidak valid (YYYY-MM-DD)"}), 400

    progress_key = datetime.now().isoformat()
    thread = threading.Thread(
        target=scrap_task,
        args=(date_from, date_to, media_types, progress_key),
        kwargs={"fetch_comments": fetch_comments, "comments_limit": COMMENTS_LIMIT, "auto_post": auto_post},
        daemon=True
    )
    thread.start()

    return jsonify({"progress_key": progress_key})


@app.route("/api/scrap/status")
def get_scrap_status():
    progress_key = request.args.get("key", "")
    with scrap_lock:
        _cleanup_old_progress()
        status = scrap_progress.get(
            progress_key,
            {"status": "idle", "message": "Tidak ada scrap aktif"}
        )
    return jsonify(status)


@app.route("/api/sessions")
def list_sessions():
    return jsonify(get_session_index())


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def delete_session(session_id):
    session_dir = CRAWLS_DIR / session_id
    if not session_dir.resolve().is_relative_to(CRAWLS_DIR.resolve()):
        return jsonify({"error": "Invalid session"}), 400

    deleted = False
    if session_dir.exists():
        try:
            shutil.rmtree(session_dir)
            _invalidate_metadata_cache(session_id)
            deleted = True
        except Exception as e:
            logger.exception(f"Gagal menghapus folder sesi {session_id}")
            return jsonify({"error": f"Gagal menghapus folder: {str(e)}"}), 500

    with index_lock:
        index = get_session_index()
        before = len(index)
        index = [e for e in index if e.get("session_id") != session_id]
        if len(index) == before and not deleted:
            return jsonify({"error": "Session tidak ditemukan"}), 404
        save_session_index(index)

    msg = "Sesi berhasil dihapus" if deleted else "Sesi dihapus dari index (data sudah tidak ada)"
    return jsonify({"ok": True, "message": msg})


@app.route("/api/sessions/<session_id>/posts")
def get_session_posts(session_id):
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 30, type=int)
    search = request.args.get("search", "")
    sort_by = request.args.get("sort_by", "timestamp")
    sort_order = request.args.get("sort_order", "desc")

    posts = _load_metadata(session_id)
    if posts is None:
        return jsonify({"error": MISSING_MSG}), 404

    for p in posts:
        sentiment = get_post_sentiment(p.get("caption", ""), p.get("comments", []))
        p["sentiment"] = sentiment["sentiment"]
        p["sentiment_score"] = sentiment["score"]

    ranked = sorted(posts, key=lambda p: p.get("like_count", 0) + p.get("comments_count", 0), reverse=True)
    rank_map = {p["id"]: i + 1 for i, p in enumerate(ranked)}
    for p in posts:
        p["rank"] = rank_map.get(p["id"], 0)

    if search:
        sl = search.lower()
        posts = [p for p in posts if sl in (p.get("caption", "") or "").lower()]

    reverse = sort_order == "desc"
    if sort_by == "likes":
        posts.sort(key=lambda p: p.get("like_count", 0), reverse=reverse)
    elif sort_by == "comments":
        posts.sort(key=lambda p: p.get("comments_count", 0), reverse=reverse)
    elif sort_by == "rank":
        posts.sort(key=lambda p: p.get("rank", 0), reverse=not reverse)
    else:
        posts.sort(key=lambda p: p.get("timestamp", ""), reverse=reverse)

    total = len(posts)
    start = (page - 1) * per_page
    end = start + per_page
    page_posts = posts[start:end]

    return jsonify({
        "posts": page_posts,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    })


@app.route("/api/sessions/<session_id>/posts/<post_id>")
def get_single_post(session_id, post_id):
    posts = _load_metadata(session_id)
    if posts is None:
        return jsonify({"error": MISSING_MSG}), 404
    post = next((p for p in posts if p["id"] == post_id), None)
    if not post:
        return jsonify({"error": "Post not found"}), 404
    return jsonify(post)


@app.route("/api/sessions/<session_id>/stats")
def get_session_stats(session_id):
    posts = _load_metadata(session_id)
    if posts is None:
        return jsonify({"error": MISSING_MSG}), 404

    total = len(posts)
    type_counts: dict[str, int] = {}
    total_likes = 0
    total_comments = 0
    max_likes = 0
    top_post = None
    dates: list[str] = []

    for p in posts:
        t = p.get("media_type", "UNKNOWN")
        type_counts[t] = type_counts.get(t, 0) + 1
        likes = p.get("like_count", 0)
        total_likes += likes
        total_comments += p.get("comments_count", 0)

        if likes > max_likes:
            max_likes = likes
            top_post = p

        if p.get("timestamp"):
            parts = p["timestamp"][:10].split("-")
            if len(parts) == 3:
                dates.append(f"{parts[2]}-{parts[1]}-{parts[0]}")

    return jsonify({
        "total_posts": total,
        "type_counts": type_counts,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "avg_likes": round(total_likes / total, 1) if total else 0,
        "avg_comments": round(total_comments / total, 1) if total else 0,
        "top_post": {
            "id": top_post.get("id"),
            "like_count": top_post.get("like_count"),
            "caption": (top_post.get("caption", "") or "")[:100],
        } if top_post else None,
        "date_range": {
            "from": min(dates) if dates else "",
            "to": max(dates) if dates else "",
        } if dates else None,
    })


MISSING_MSG = "Sesi ini tidak memiliki data metadata. Silakan scrap ulang."


@app.route("/api/sessions/<session_id>/analytics/engagement")
def session_engagement(session_id):
    cached = _get_cached_analytics(session_id, "engagement")
    if cached is not None:
        return jsonify(cached)

    posts = _load_metadata(session_id)
    if posts is None:
        return jsonify({"error": MISSING_MSG}), 404

    followers, reason = _get_followers_count(session_id)
    result = analyze_engagement(posts, followers)
    result["followers_reason"] = reason
    _set_cached_analytics(session_id, "engagement", result)
    return jsonify(result)


@app.route("/api/sessions/<session_id>/analytics/sentiment")
def session_sentiment(session_id):
    cached = _get_cached_analytics(session_id, "sentiment")
    if cached is not None:
        return jsonify(cached)

    posts = _load_metadata(session_id)
    if posts is None:
        return jsonify({"error": MISSING_MSG}), 404

    result = analyze_sentiment(posts)
    _set_cached_analytics(session_id, "sentiment", result)
    return jsonify(result)


@app.route("/api/sessions/<session_id>/analytics/insights")
def session_insights(session_id):
    cached = _get_cached_analytics(session_id, "insights")
    if cached is not None:
        return jsonify(cached)

    posts = _load_metadata(session_id)
    if posts is None:
        return jsonify({"error": MISSING_MSG}), 404

    followers, reason = _get_followers_count(session_id)
    result = analyze_target_market(posts, followers)
    result["followers_reason"] = reason
    _set_cached_analytics(session_id, "insights", result)
    return jsonify(result)


@app.route("/api/sessions/<session_id>/analytics/best-time")
def session_best_time(session_id):
    cached = _get_cached_analytics(session_id, "best-time")
    if cached is not None:
        return jsonify(cached)

    posts = _load_metadata(session_id)
    if posts is None:
        return jsonify({"error": MISSING_MSG}), 404
    result = analyze_best_time_to_post(posts)
    _set_cached_analytics(session_id, "best-time", result)
    return jsonify(result)


@app.route("/api/sessions/<session_id>/analytics/wordcloud")
def session_wordcloud(session_id):
    max_words = request.args.get("max", 80, type=int)
    cache_key = f"wordcloud_{max_words}"
    cached = _get_cached_analytics(session_id, cache_key)
    if cached is not None:
        return jsonify(cached)

    posts = _load_metadata(session_id)
    if posts is None:
        return jsonify({"error": MISSING_MSG}), 404
    result = extract_word_frequencies(posts, max_words)
    _set_cached_analytics(session_id, cache_key, result)
    return jsonify(result)


@app.route("/api/sessions/<session_id>/analytics/content-categories")
def session_content_categories(session_id):
    cached = _get_cached_analytics(session_id, "content-categories")
    if cached is not None:
        return jsonify(cached)

    posts = _load_metadata(session_id)
    if posts is None:
        return jsonify({"error": MISSING_MSG}), 404
    result = analyze_content_categories(posts)
    _set_cached_analytics(session_id, "content-categories", result)
    return jsonify(result)


@app.route("/api/sessions/<session_id>/analytics/followers-trend")
def session_followers_trend(session_id):
    cached = _get_cached_analytics(session_id, "followers-trend")
    if cached is not None:
        return jsonify(cached)

    try:
        scraper = _get_scraper()
        insights = scraper.get_account_insights("follower_count", "day")
        result = analyze_followers_trend(insights)
    except Exception as e:
        logger.warning(f"Followers trend gagal: {e}")
        return jsonify({"error": f"Gagal ambil data insights: {e}"}), 500

    _set_cached_analytics(session_id, "followers-trend", result)
    return jsonify(result)


@app.route("/api/sessions/<session_id>/csv")
def download_csv(session_id):
    csv_path = CRAWLS_DIR / session_id / "captions.csv"
    if not csv_path.exists():
        return jsonify({"error": "CSV not found"}), 404
    return send_file(
        csv_path,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"ig_captions_{session_id}.csv",
    )


@app.route("/api/sessions/<session_id>/images")
def download_images(session_id):
    media_dir = CRAWLS_DIR / session_id / "media"
    if not media_dir.exists():
        return jsonify({"error": "No media found"}), 404

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    try:
        import zipfile
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for date_folder in sorted(media_dir.iterdir()):
                if not date_folder.is_dir():
                    continue
                for file in sorted(date_folder.iterdir()):
                    zf.write(file, f"{date_folder.name}/{file.name}")

        tmp.close()
        return send_file(
            tmp.name,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"ig_images_{session_id}.zip",
        )
    except Exception:
        import os
        os.unlink(tmp.name)
        raise


@app.route("/api/media/<session_id>/<path:filepath>")
def serve_media(session_id, filepath):
    media_dir = CRAWLS_DIR / session_id / "media"
    resolved = (media_dir / filepath).resolve()

    if not resolved.is_relative_to(media_dir.resolve()):
        return jsonify({"error": "Forbidden"}), 403

    if not resolved.exists():
        return jsonify({"error": "Not found"}), 404

    return send_from_directory(media_dir, filepath)


@app.route("/api/wp/status")
def wp_status():
    from wordpress import WordPressClient
    return jsonify({
        "enabled": WP_ENABLED,
        "configured": WordPressClient.is_configured(),
        "url": WP_URL or "",
        "user": WP_USER or "",
        "post_status": WP_POST_STATUS,
    })


@app.route("/api/wp/test")
def wp_test():
    from wordpress import WordPressClient
    if not WordPressClient.is_configured():
        return jsonify({"ok": False, "error": "WordPress belum dikonfigurasi di .env"}), 400

    try:
        wp = WordPressClient()
        resp = wp.session.get(f"{wp._api_base}/posts", params={"per_page": 1}, timeout=15)
        if resp.status_code == 200:
            return jsonify({
                "ok": True,
                "url": WP_URL,
                "user": WP_USER,
                "api_reachable": True,
                "message": f"Koneksi berhasil! API WordPress dapat diakses.",
            })
        else:
            return jsonify({
                "ok": False,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def wp_post_task(session_id: str, post_ids: list[str], progress_key: str):
    from wordpress import WordPressClient

    def update_prog(**kw):
        with scrap_lock:
            _cleanup_old_progress()
            scrap_progress[progress_key].update(kw)

    try:
        with scrap_lock:
            scrap_progress[progress_key] = {
                "status": "running", "session_id": session_id,
                "wp_posted": 0, "wp_total": 0, "message": "Memulai upload ke WordPress...",
            }

        posts = _load_metadata(session_id)
        if posts is None:
            update_prog(status="error", _completed_at=time.time(), message="Session metadata tidak ditemukan")
            return

        if post_ids:
            posts = [p for p in posts if p.get("id") in post_ids]

        if not posts:
            update_prog(status="done", _completed_at=time.time(), message="Tidak ada post untuk dikirim", wp_posted=0, wp_total=0)
            return

        posted_ids = _get_posted_ig_ids(session_id)
        if posted_ids:
            skipped_count = sum(1 for p in posts if p.get("id") in posted_ids)
            posts = [p for p in posts if p.get("id") not in posted_ids]
            if skipped_count > 0:
                logger.info(f"WP post: {skipped_count} IG post sudah diposting sebelumnya, di-skip")

        if not posts:
            update_prog(
                status="done", _completed_at=time.time(),
                message="Semua post sudah diposting sebelumnya (skip)",
                wp_posted=0, wp_total=0,
            )
            return

        wp = WordPressClient()

        def wp_progress(done, total, msg):
            update_prog(wp_posted=done, wp_total=total, message=msg)

        results = wp.post_all(posts, status=WP_POST_STATUS, progress_callback=wp_progress)
        success = sum(1 for r in results if r.get("success"))
        skipped = sum(1 for r in results if r.get("skipped"))

        wp_posted_data = _load_wp_posted(session_id)
        for r in results:
            ig_id = r.get("ig_post_id")
            wp_id = r.get("wp_post_id")
            if ig_id and (r.get("success") or r.get("skipped")):
                wp_posted_data.setdefault("posts", {})[ig_id] = {
                    "wp_post_id": wp_id,
                    "wp_edit_url": r.get("wp_edit_url", ""),
                    "status": "skipped" if r.get("skipped") else "posted",
                    "posted_at": datetime.now().isoformat(),
                }
        _save_wp_posted(session_id, wp_posted_data)

        msg = f"WordPress: {success}/{len(posts)} post berhasil diupload"
        if skipped:
            msg += f", {skipped} skip"
        update_prog(
            status="done", _completed_at=time.time(),
            message=msg,
            wp_results=results,
        )

    except Exception as e:
        logger.exception("WP post task gagal")
        with scrap_lock:
            scrap_progress[progress_key] = {
                "status": "error", "session_id": session_id,
                "message": f"Error: {str(e)}",
                "_completed_at": time.time(),
            }


@app.route("/api/config/token", methods=["POST"])
def update_token():
    try:
        data = request.get_json(silent=True) or {}
        new_token = (data.get("access_token") or "").strip()

        if "\n" in new_token or "\r" in new_token:
            return jsonify({"error": "Token mengandung karakter tidak valid"}), 400

        if not new_token:
            return jsonify({"error": "Token tidak boleh kosong"}), 400

        env_path = Path(".env")
        if not env_path.exists():
            return jsonify({"error": "File .env tidak ditemukan"}), 500

        content = env_path.read_text(encoding="utf-8")
        if re.search(r"^ACCESS_TOKEN=", content, re.MULTILINE):
            content = re.sub(r"^ACCESS_TOKEN=.*", f"ACCESS_TOKEN={new_token}", content, flags=re.MULTILINE)
        else:
            content += f"\nACCESS_TOKEN={new_token}\n"
        env_path.write_text(content, encoding="utf-8")

        import config
        import scrapper
        config.ACCESS_TOKEN = new_token
        scrapper.ACCESS_TOKEN = new_token

        _invalidate_scraper()

        global ACCESS_TOKEN
        ACCESS_TOKEN = new_token

        return jsonify({"ok": True, "message": "Token berhasil diperbarui"})
    except Exception as e:
        logger.exception("Gagal memperbarui token")
        return jsonify({"error": f"Gagal memperbarui token: {str(e)}"}), 500


@app.route("/api/config/ig-test")
def test_ig_token():
    try:
        c = _get_scraper()
        info = c.get_account_info()
        return jsonify({
            "ok": True,
            "username": info.get("username", "?"),
            "name": info.get("name", "?"),
            "followers": info.get("followers_count", 0),
            "message": f"Token valid! Akun: @{info.get('username', '?')}",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/config/account")
def get_account_info():
    try:
        c = _get_scraper()
        info = c.get_account_info()
        return jsonify({"ok": True, "account": info})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "account": None})


@app.route("/api/config/sentiment-words")
def handle_get_sentiment_words():
    return jsonify(get_sentiment_words())


@app.route("/api/config/sentiment-words/add", methods=["POST"])
def handle_add_sentiment_word():
    data = request.get_json(silent=True) or {}
    word = data.get("word", "").strip()
    category = data.get("category", "")
    if not word:
        return jsonify({"error": "Kata tidak boleh kosong"}), 400
    if category not in ("positive", "negative"):
        return jsonify({"error": "Kategori harus 'positive' atau 'negative'"}), 400
    ok = add_sentiment_word(word, category)
    if not ok:
        return jsonify({"error": "Gagal menambah kata"}), 400
    return jsonify({"ok": True, "message": f"Kata '{word}' ditambahkan ke {category}", "words": get_sentiment_words()})


@app.route("/api/config/sentiment-words/remove", methods=["POST"])
def handle_remove_sentiment_word():
    data = request.get_json(silent=True) or {}
    word = data.get("word", "").strip()
    category = data.get("category", "")
    if not word:
        return jsonify({"error": "Kata tidak boleh kosong"}), 400
    if category not in ("positive", "negative"):
        return jsonify({"error": "Kategori harus 'positive' atau 'negative'"}), 400
    ok = remove_sentiment_word(word, category)
    if not ok:
        return jsonify({"error": "Gagal menghapus kata"}), 400
    return jsonify({"ok": True, "message": f"Kata '{word}' dihapus dari {category}", "words": get_sentiment_words()})


@app.route("/api/sessions/<session_id>/post-to-wp", methods=["POST"])
def post_session_to_wp(session_id):
    if not WP_URL or not WP_USER or not WP_APP_PASS:
        return jsonify({"error": "WordPress belum dikonfigurasi di .env"}), 400

    data = request.get_json() or {}
    post_ids = data.get("post_ids", [])

    progress_key = f"wp_{datetime.now().isoformat()}"
    thread = threading.Thread(
        target=wp_post_task,
        args=(session_id, post_ids, progress_key),
        daemon=True,
    )
    thread.start()

    return jsonify({"progress_key": progress_key})


if __name__ == "__main__":
    logger.info("IG Crawler Dashboard berjalan di http://localhost:5000")
    app.run(debug=False, host="0.0.0.0", port=5000)

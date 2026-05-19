import json
import logging
import threading
import io
import zipfile
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from dotenv import load_dotenv

load_dotenv()

from config import ACCESS_TOKEN, IG_USER_ID, WP_ENABLED, WP_URL, WP_USER, WP_APP_PASS, WP_POST_STATUS
from crawler import InstagramCrawler
from downloader import download_media_organized
from exporter import export_captions_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

CRAWLS_DIR = Path("data") / "crawls"
CRAWLS_DIR.mkdir(parents=True, exist_ok=True)

crawl_progress: dict = {}
crawl_lock = threading.Lock()


def get_session_index() -> list[dict]:
    idx_path = CRAWLS_DIR / "index.json"
    if idx_path.exists():
        return json.loads(idx_path.read_text(encoding="utf-8"))
    return []


def save_session_index(index: list[dict]):
    (CRAWLS_DIR / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False)
    )


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


def update_session_index(session_id: str, posts: list[dict],
                         date_from: str, date_to: str, media_types: list[str]):
    dates = [p["timestamp"][:10] for p in posts if p.get("timestamp")]
    total_media = sum(len(p.get("_media_files", [])) for p in posts)

    entry = {
        "session_id": session_id,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_posts": len(posts),
        "total_media": total_media,
        "filter_date_from": date_from or "",
        "filter_date_to": date_to or "",
        "filter_types": media_types,
        "data_from": min(dates) if dates else "",
        "data_to": max(dates) if dates else "",
    }

    index = get_session_index()
    index.insert(0, entry)
    save_session_index(index)


def crawl_task(date_from: str, date_to: str, media_types: list[str],
               progress_key: str):
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    def update_prog(**kw):
        with crawl_lock:
            crawl_progress[progress_key].update(kw)

    def download_cb(done, total, msg):
        pct = int(done / total * 100) if total else 0
        update_prog(total_downloaded=done, total_to_download=total,
                     download_pct=pct, message=f"Download media: {done}/{total} - {msg}")

    try:
        with crawl_lock:
            crawl_progress[progress_key] = {
                "status": "running", "session_id": session_id,
                "page": 0, "total_fetched": 0, "total_downloaded": 0,
                "download_pct": 0, "message": "Memulai crawling...",
            }

        session_dir = CRAWLS_DIR / session_id
        session_dir.mkdir(parents=True)

        crawler = InstagramCrawler()

        update_prog(message="Mengambil data dari Instagram...")
        posts = crawler.fetch_all_media(date_from, date_to)

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
            update_prog(status="done",
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
        if WP_ENABLED and WP_URL and WP_USER and WP_APP_PASS:
            try:
                from wordpress import WordPressClient
                wp = WordPressClient()
                update_prog(message=f"Mengupload {len(posts)} post ke WordPress...")

                def wp_progress(done, total, msg):
                    update_prog(wp_posted=done, wp_total=total, message=msg)

                wp_results = wp.post_all(posts, status=WP_POST_STATUS, progress_callback=wp_progress)
                wp_ok = sum(1 for r in wp_results if r.get("success"))
                update_prog(
                    status="done", download_pct=100,
                    message=f"Selesai! {len(posts)} post, {total_media} media, WP: {wp_ok}/{len(posts)} draft",
                    session_id=session_id, wp_results=wp_results,
                )
                return
            except Exception as e:
                logger.exception("WordPress auto-post gagal")
                wp_error = str(e)
                wp_results = [{"success": False, "error": wp_error}]
                update_prog(
                    status="done", download_pct=100,
                    message=f"Selesai! {len(posts)} post, {total_media} media — WP GAGAL: {wp_error}",
                    session_id=session_id, wp_results=wp_results,
                )
                return

        update_prog(status="done", download_pct=100,
                     message=f"Selesai! {len(posts)} post, {total_media} file media"
                             + (" (WP tidak aktif)" if not WP_ENABLED else ""),
                     session_id=session_id, wp_results=wp_results)

    except Exception as e:
        logger.exception("Crawl gagal")
        with crawl_lock:
            crawl_progress[progress_key] = {
                "status": "error", "session_id": session_id,
                "message": f"Error: {str(e)}",
            }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/crawl", methods=["POST"])
def start_crawl():
    data = request.get_json()
    date_from = data.get("date_from", "")
    date_to = data.get("date_to", "")
    media_types = data.get("media_types", [])

    if not ACCESS_TOKEN or not IG_USER_ID:
        return jsonify({"error": "ACCESS_TOKEN atau IG_USER_ID belum diisi di .env"}), 400

    progress_key = datetime.now().isoformat()
    thread = threading.Thread(
        target=crawl_task, args=(date_from, date_to, media_types, progress_key),
        daemon=True
    )
    thread.start()

    return jsonify({"progress_key": progress_key})


@app.route("/api/crawl/status")
def get_crawl_status():
    progress_key = request.args.get("key", "")
    with crawl_lock:
        status = crawl_progress.get(
            progress_key,
            {"status": "idle", "message": "Tidak ada crawl aktif"}
        )
    return jsonify(status)


@app.route("/api/sessions")
def list_sessions():
    return jsonify(get_session_index())


@app.route("/api/sessions/<session_id>/posts")
def get_session_posts(session_id):
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 30, type=int)
    search = request.args.get("search", "")
    sort_by = request.args.get("sort_by", "timestamp")
    sort_order = request.args.get("sort_order", "desc")

    meta_path = CRAWLS_DIR / session_id / "metadata.json"
    if not meta_path.exists():
        return jsonify({"error": "Session not found"}), 404

    posts = json.loads(meta_path.read_text(encoding="utf-8"))

    if search:
        sl = search.lower()
        posts = [p for p in posts if sl in (p.get("caption", "") or "").lower()]

    reverse = sort_order == "desc"
    if sort_by == "likes":
        posts.sort(key=lambda p: p.get("like_count", 0), reverse=reverse)
    elif sort_by == "comments":
        posts.sort(key=lambda p: p.get("comments_count", 0), reverse=reverse)
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
    meta_path = CRAWLS_DIR / session_id / "metadata.json"
    if not meta_path.exists():
        return jsonify({"error": "Session not found"}), 404
    posts = json.loads(meta_path.read_text(encoding="utf-8"))
    post = next((p for p in posts if p["id"] == post_id), None)
    if not post:
        return jsonify({"error": "Post not found"}), 404
    return jsonify(post)


@app.route("/api/sessions/<session_id>/stats")
def get_session_stats(session_id):
    meta_path = CRAWLS_DIR / session_id / "metadata.json"
    if not meta_path.exists():
        return jsonify({"error": "Session not found"}), 404

    posts = json.loads(meta_path.read_text(encoding="utf-8"))

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
        total_likes += p.get("like_count", 0)
        total_comments += p.get("comments_count", 0)

        lc = p.get("like_count", 0)
        if lc > max_likes:
            max_likes = lc
            top_post = p

        if p.get("timestamp"):
            dates.append(p["timestamp"][:10])

    return jsonify({
        "total_posts": total,
        "type_counts": type_counts,
        "total_likes": sum(p.get("like_count", 0) for p in posts),
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

    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as zf:
        for date_folder in sorted(media_dir.iterdir()):
            if not date_folder.is_dir():
                continue
            for file in sorted(date_folder.iterdir()):
                zf.write(file, f"{date_folder.name}/{file.name}")

    data.seek(0)
    return send_file(
        data,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"ig_images_{session_id}.zip",
    )


@app.route("/api/media/<session_id>/<path:filepath>")
def serve_media(session_id, filepath):
    media_dir = CRAWLS_DIR / session_id / "media"
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
        with crawl_lock:
            crawl_progress[progress_key].update(kw)

    try:
        with crawl_lock:
            crawl_progress[progress_key] = {
                "status": "running", "session_id": session_id,
                "wp_posted": 0, "wp_total": 0, "message": "Memulai upload ke WordPress...",
            }

        meta_path = CRAWLS_DIR / session_id / "metadata.json"
        if not meta_path.exists():
            update_prog(status="error", message="Session metadata tidak ditemukan")
            return

        posts = json.loads(meta_path.read_text(encoding="utf-8"))

        if post_ids:
            posts = [p for p in posts if p.get("id") in post_ids]

        if not posts:
            update_prog(status="done", message="Tidak ada post untuk dikirim", wp_posted=0, wp_total=0)
            return

        wp = WordPressClient()

        def wp_progress(done, total, msg):
            update_prog(wp_posted=done, wp_total=total, message=msg)

        results = wp.post_all(posts, status=WP_POST_STATUS, progress_callback=wp_progress)
        success = sum(1 for r in results if r.get("success"))
        update_prog(
            status="done",
            message=f"WordPress: {success}/{len(posts)} post berhasil diupload",
            wp_results=results,
        )

    except Exception as e:
        logger.exception("WP post task gagal")
        with crawl_lock:
            crawl_progress[progress_key] = {
                "status": "error", "session_id": session_id,
                "message": f"Error: {str(e)}",
            }


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
    app.run(debug=True, host="0.0.0.0", port=5000)

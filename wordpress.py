import json
import logging
import os
import random
import re
import string
import copy
import tempfile
import urllib.parse
from pathlib import Path
from typing import Callable

import requests

from config import WP_URL, WP_USER, WP_APP_PASS, WP_POST_STATUS, WP_TEMPLATE_POST_ID

logger = logging.getLogger(__name__)


def _new_id(length: int = 8) -> str:
    return "".join(random.choices(string.hexdigits[:16], k=length))


class WordPressClient:
    def __init__(self, wp_url: str = "", username: str = "", app_password: str = ""):
        self.wp_url = (wp_url or WP_URL).rstrip("/")
        self.username = username or WP_USER
        self.app_password = app_password or WP_APP_PASS

        self.session = requests.Session()
        self.session.auth = (self.username, self.app_password)
        self.session.headers.update({"Accept": "application/json"})

        self._api_base = f"{self.wp_url}/wp-json/wp/v2"
        self._template_cache: dict | None = None

    def _check_response(self, resp: requests.Response, context: str = "") -> dict:
        if resp.status_code >= 400:
            body = resp.text[:500]
            raise Exception(f"WP API error ({resp.status_code}) {context}: {body}")
        return resp.json()

    def upload_media(self, file_path: str | Path, title: str = "") -> tuple[int, str] | None:
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"File tidak ditemukan: {path}")
            return None

        filename = path.name
        mime_map = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".gif": "image/gif",
            ".webp": "image/webp",
            ".mp4": "video/mp4", ".webm": "video/webm",
        }
        ext = path.suffix.lower()
        content_type = mime_map.get(ext, "application/octet-stream")

        try:
            with open(path, "rb") as f:
                files = {"file": (filename, f, content_type)}
                headers = {
                    "Content-Disposition": f"attachment; filename={filename}",
                }
                if title:
                    headers["Content-Description"] = title
                resp = self.session.post(
                    f"{self._api_base}/media",
                    files=files,
                    headers=headers,
                    timeout=120,
                )
            data = self._check_response(resp, "upload_media")
            media_id = data.get("id")
            source_url = data.get("source_url", "")
            logger.info(f"Media uploaded: {filename} -> WP media #{media_id} ({source_url})")
            return (media_id, source_url)
        except Exception as e:
            logger.error(f"Gagal upload media {filename}: {e}")
            return None

    def create_post(
        self,
        title: str,
        content: str,
        date: str = "",
        featured_media: int | None = None,
        status: str = "draft",
        categories: list[int] | None = None,
        tags: list[int] | None = None,
        meta: dict | None = None,
        template: str = "",
    ) -> dict:
        payload: dict = {
            "title": title,
            "content": content,
            "status": status,
        }
        if date:
            payload["date"] = date
        if featured_media:
            payload["featured_media"] = featured_media
        if categories:
            payload["categories"] = categories
        if tags:
            payload["tags"] = tags
        if meta:
            payload["meta"] = meta
        if template:
            payload["template"] = template

        resp = self.session.post(
            f"{self._api_base}/posts",
            json=payload,
            timeout=60,
        )
        data = self._check_response(resp, "create_post")
        logger.info(f"WP post created: #{data.get('id')} - {title[:50]}")
        return data

    def _build_title(self, post: dict) -> str:
        caption = post.get("caption") or ""
        first_line = caption.split("\n")[0].strip()
        if first_line:
            return first_line[:60] + ("..." if len(first_line) > 60 else "")
        ts = post.get("timestamp", "")
        date_str = ts[:10] if ts else "Unknown"
        return f"[Instagram] {date_str}"

    @staticmethod
    def _format_date(timestamp: str) -> str:
        if not timestamp:
            return ""
        return timestamp[:19]

    def _build_html_content(self, post: dict, media_items: list[dict]) -> str:
        parts: list[str] = []

        caption = post.get("caption") or ""
        if caption:
            paragraphs = caption.split("\n")
            caption_html = "\n".join(f"<p>{line}</p>" for line in paragraphs if line.strip())
            parts.append(caption_html)

        for item in media_items:
            if item.get("type") == "VIDEO":
                src = item.get("source_url", "")
                parts.append(
                    f'<figure class="wp-block-video"><video controls src="{src}" type="video/mp4"></video></figure>'
                )
            else:
                src = item.get("source_url", "")
                alt = (caption[:80] if caption else "").replace('"', "&quot;")
                parts.append(
                    f'<figure class="wp-block-image"><img src="{src}" alt="{alt}" /></figure>'
                )

        permalink = post.get("permalink")
        if permalink:
            parts.append(
                f'<p><em>Sumber: <a href="{permalink}" target="_blank" rel="noopener">Instagram</a></em></p>'
            )

        return "\n\n".join(parts)

    def _build_elementor_editor_content(self, post: dict, media_items: list[dict]) -> str:
        parts: list[str] = []

        for item in media_items:
            if item.get("type") == "VIDEO":
                src = item.get("source_url", "")
                parts.append(f'<video controls src="{src}" style="max-width:100%"></video>')

        caption = post.get("caption") or ""
        if caption:
            paragraphs = caption.split("\n")
            parts.extend(f"<p>{line}</p>" for line in paragraphs if line.strip())

        permalink = post.get("permalink")
        if permalink:
            parts.append(
                f'<p><em>Sumber: <a href="{permalink}" target="_blank" rel="noopener">Instagram</a></em></p>'
            )

        return "\n".join(parts)

    def _get_media_files_for_post(self, post: dict) -> list[tuple[str, str]]:
        files: list[tuple[str, str]] = []
        media_type = post.get("media_type", "")

        if media_type in ("IMAGE", "VIDEO"):
            media_files = post.get("media_files") or []
            if media_files:
                files.append((media_files[0], media_type))
        elif media_type == "CAROUSEL_ALBUM":
            children = post.get("children") or []
            media_files = post.get("media_files") or []
            for child in children:
                child_id = child.get("id", "")
                child_type = child.get("media_type", "IMAGE")
                match = next(
                    (f for f in media_files if child_id and child_id in f),
                    None,
                )
                if match:
                    files.append((match, child_type))

        return files

    def _fetch_template(self) -> dict:
        if self._template_cache is not None:
            return self._template_cache

        if not WP_TEMPLATE_POST_ID:
            raise Exception("WP_TEMPLATE_POST_ID belum diisi di .env")

        resp = self.session.get(
            f"{self._api_base}/posts/{WP_TEMPLATE_POST_ID}",
            params={"context": "edit"},
            timeout=30,
        )
        data = self._check_response(resp, "fetch_template")

        meta = data.get("meta", {})
        el_data_str = meta.get("_elementor_data", "")
        if not el_data_str:
            raise Exception(f"Post {WP_TEMPLATE_POST_ID} tidak memiliki _elementor_data")

        self._template_cache = {
            "elementor_data": json.loads(el_data_str),
            "template": data.get("template", ""),
            "page_settings": meta.get("_elementor_page_settings", ""),
        }

        logger.info(f"Template fetched from post #{WP_TEMPLATE_POST_ID}")
        return self._template_cache

    def _regenerate_ids(self, data):
        data = copy.deepcopy(data)

        def _walk(elements):
            for el in elements:
                old_id = el.get("id", "")
                if old_id:
                    el["id"] = _new_id(len(old_id) if old_id else 8)
                children = el.get("elements", [])
                if children:
                    _walk(children)

        if isinstance(data, list):
            _walk(data)
        return data

    def _find_widgets(self, elements, widget_type: str = "") -> list[dict]:
        results: list[dict] = []

        def _walk(elems):
            for el in elems:
                if widget_type and el.get("widgetType") == widget_type:
                    results.append(el)
                elif not widget_type and el.get("elType") == "widget":
                    results.append(el)
                children = el.get("elements", [])
                if children:
                    _walk(children)

        _walk(elements)
        return results

    def _inject_into_template(
        self,
        template_data: list[dict],
        post: dict,
        wp_media_items: list[dict],
    ) -> str:
        cloned = self._regenerate_ids(template_data)

        gallery_images = [
            {"id": item["id"], "url": item.get("source_url", "")}
            for item in wp_media_items
        ]

        gallery_widgets = self._find_widgets(cloned, "bdt-advanced-image-gallery")
        if gallery_widgets and gallery_images:
            gallery_widgets[0]["settings"]["wp_gallery"] = gallery_images
            gallery_widgets[0]["settings"]["_skin"] = "bdt-carousel"
            logger.info(f"Injected {len(gallery_images)} images into bdt-advanced-image-gallery (carousel)")

        image_gallery_widgets = self._find_widgets(cloned, "image-gallery")
        if image_gallery_widgets and gallery_images:
            image_gallery_widgets[0]["settings"]["wp_gallery"] = gallery_images
            logger.info(f"Injected {len(gallery_images)} images into image-gallery (grid)")

        text_widgets = self._find_widgets(cloned, "text-editor")

        content_widget = None
        for w in text_widgets:
            editor_len = len(w.get("settings", {}).get("editor", ""))
            if editor_len > 50:
                content_widget = w
                break

        if not content_widget and text_widgets:
            content_widget = max(
                text_widgets,
                key=lambda w: len(w.get("settings", {}).get("editor", "")),
            )

        if content_widget:
            editor_html = self._build_elementor_editor_content(post, wp_media_items)
            content_widget["settings"]["editor"] = editor_html
            logger.info(f"Injected content into text-editor widget ({len(editor_html)} chars)")
        else:
            logger.warning("Tidak ada text-editor widget yang cocok untuk inject konten")

        fi_widgets = self._find_widgets(cloned, "theme-post-featured-image")
        if fi_widgets:
            dynamic = fi_widgets[0].get("settings", {}).get("__dynamic__", {})
            if "image" in dynamic:
                tag_str = dynamic["image"]
                match = re.search(r'settings="([^"]+)"', tag_str)
                if match:
                    encoded = match.group(1)
                    decoded = urllib.parse.unquote(encoded)
                    try:
                        settings_data = json.loads(decoded)
                        if "fallback" in settings_data:
                            del settings_data["fallback"]
                            re_encoded = urllib.parse.quote(json.dumps(settings_data, ensure_ascii=False))
                            dynamic["image"] = tag_str.replace(encoded, re_encoded)
                            logger.info("Cleared fallback image from theme-post-featured-image")
                    except json.JSONDecodeError:
                        logger.warning("Could not parse theme-post-featured-image settings")

        return json.dumps(cloned, ensure_ascii=False)

    def post_ig_post(self, post: dict, status: str = "") -> dict:
        result = {
            "ig_post_id": post.get("id"),
            "success": False,
            "wp_post_id": None,
            "wp_edit_url": None,
            "error": None,
        }

        try:
            media_files = self._get_media_files_for_post(post)

            wp_media_items: list[dict] = []
            featured_media_id = None

            for file_path, media_type in media_files:
                title = f"IG {post.get('id', '')} - {file_path.split('/')[-1]}"
                upload_result = self.upload_media(file_path, title=title)
                if upload_result:
                    media_id, source_url = upload_result
                    wp_media_items.append({
                        "id": media_id,
                        "type": media_type,
                        "source_url": source_url,
                    })
                    if featured_media_id is None:
                        featured_media_id = media_id

            if post.get("media_type") == "VIDEO":
                thumbnail_url = post.get("thumbnail_url", "")
                if thumbnail_url:
                    try:
                        resp = self.session.get(thumbnail_url, timeout=30)
                        resp.raise_for_status()
                        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                            f.write(resp.content)
                            temp_path = f.name
                        thumb_result = self.upload_media(
                            temp_path,
                            title=f"IG {post.get('id', '')} - thumbnail",
                        )
                        os.unlink(temp_path)
                        if thumb_result:
                            thumb_id, thumb_url = thumb_result
                            featured_media_id = thumb_id
                            logger.info(f"Video thumbnail uploaded as featured image: #{thumb_id}")
                    except Exception as e:
                        logger.warning(f"Gagal upload video thumbnail: {e}")
                elif featured_media_id:
                    featured_media_id = None

            title = self._build_title(post)
            post_status = status or WP_POST_STATUS

            use_elementor = bool(WP_TEMPLATE_POST_ID)

            if use_elementor:
                try:
                    template = self._fetch_template()
                    elementor_data_str = self._inject_into_template(
                        template["elementor_data"], post, wp_media_items,
                    )

                    wp_post = self.create_post(
                        title=title,
                        content="",
                        date=self._format_date(post.get("timestamp", "")),
                        featured_media=featured_media_id,
                        status=post_status,
                        template=template.get("template", "elementor_header_footer"),
                        meta={
                            "_elementor_edit_mode": "builder",
                            "_elementor_template_type": "wp-post",
                            "_elementor_data": elementor_data_str,
                            "_elementor_page_settings": template.get("page_settings", ""),
                        },
                    )
                except Exception as e:
                    logger.warning(f"Elementor template gagal, fallback ke HTML: {e}")
                    use_elementor = False

            if not use_elementor:
                content = self._build_html_content(post, wp_media_items)

                if not wp_media_items:
                    media_url = post.get("media_url") or post.get("thumbnail_url") or ""
                    if media_url:
                        if post.get("media_type") == "VIDEO":
                            content = f'<figure class="wp-block-video"><video controls src="{media_url}"></video></figure>\n\n' + content
                        else:
                            content = f'<figure class="wp-block-image"><img src="{media_url}" /></figure>\n\n' + content

                wp_post = self.create_post(
                    title=title,
                    content=content,
                    date=self._format_date(post.get("timestamp", "")),
                    featured_media=featured_media_id,
                    status=post_status,
                    meta={
                        "ig_post_id": post.get("id", ""),
                        "ig_timestamp": post.get("timestamp", ""),
                        "ig_permalink": post.get("permalink", ""),
                    },
                )

            result["success"] = True
            result["wp_post_id"] = wp_post.get("id")
            result["wp_edit_url"] = (
                f"{self.wp_url}/wp-admin/post.php?post={wp_post.get('id')}&action=edit"
            )

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Gagal post IG {post.get('id')}: {e}")

        return result

    def post_all(
        self,
        posts: list[dict],
        status: str = "",
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> list[dict]:
        results: list[dict] = []
        total = len(posts)

        for i, post in enumerate(posts):
            if progress_callback:
                caption = (post.get("caption") or "")[:30]
                progress_callback(
                    i + 1,
                    total,
                    f"WP: posting {i + 1}/{total} - {caption}...",
                )

            result = self.post_ig_post(post, status=status)
            results.append(result)

            status_str = "OK" if result["success"] else f"GAGAL: {result['error']}"
            logger.info(f"[{i + 1}/{total}] IG {post.get('id')} -> {status_str}")

        success_count = sum(1 for r in results if r["success"])
        logger.info(f"WP post selesai: {success_count}/{total} berhasil")

        if progress_callback:
            progress_callback(total, total, f"WordPress: {success_count}/{total} post berhasil")

        return results

    @staticmethod
    def is_configured() -> bool:
        return bool(WP_URL and WP_USER and WP_APP_PASS)

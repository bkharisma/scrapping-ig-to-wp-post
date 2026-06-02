import re
import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev

logger = logging.getLogger(__name__)

SENTIMENT_WORDS_FILE = Path("data/sentiment_words.json")

_DEFAULT_POSITIVE = {
    "baik", "bagus", "hebat", "keren", "mantap", "sukses", "indah", "cantik",
    "menarik", "nyaman", "senang", "bahagia", "puas", "bangga", "lucu",
    "imut", "gemas", "bersyukur", "terima kasih", "makasih", "love", "suka",
    "sempurna", "istimewa", "luar biasa", "recommended", "rekomendasi",
    "wow", "amazing", "beautiful", "great", "awesome", "fantastic",
    "terbaik", "terkeren", "terindah", "terlucu", "kreatif", "inovatif",
    "menginspirasi", "inspiratif", "motivasi", "semangat", "keren abis",
    "cakep", "kece", "sip", "top", "nice", "good", "perfect",
    "inspiring", "wonderful", "excellent", "brilliant", "stunning",
    "murah", "hemat", "untung", "berkah", "sehat", "segar", "cerah",
}

_DEFAULT_NEGATIVE = {
    "buruk", "jelek", "parah", "payah", "mengerikan", "menyedihkan",
    "kecewa", "gagal", "rugi", "susah", "sulit", "sedih", "marah",
    "benci", "muak", "jijik", "bosan", "membosankan", "capek", "lelah",
    "gak enak", "ga enak", "nggak enak", "tidak enak", "sampah",
    "mengecewakan", "menjijikkan", "horor", "mengerikan", "ngeri",
    "jahat", "kejam", "kasar", "buruk banget", "jelek banget",
    "worst", "bad", "terrible", "awful", "hate", "ugly", "boring",
    "horrible", "disappointed", "disappointing", "fail", "failed",
    "sakit", "pusing", "stress", "frustrasi", "kalut", "kacau",
    "mahal", "boros", "menyesal", "nyesel", "zonk", "gagal total",
    "tidak suka", "ga suka", "gak suka", "nggak suka", "ga mood",
    "berantakan", "amburadul", "sembarangan", "asalan",
}

POSITIVE_WORDS = set()
NEGATIVE_WORDS = set()


def _init_sentiment_words():
    global POSITIVE_WORDS, NEGATIVE_WORDS
    if SENTIMENT_WORDS_FILE.exists():
        try:
            data = json.loads(SENTIMENT_WORDS_FILE.read_text(encoding="utf-8"))
            POSITIVE_WORDS = set(data.get("positive", _DEFAULT_POSITIVE))
            NEGATIVE_WORDS = set(data.get("negative", _DEFAULT_NEGATIVE))
            return
        except Exception:
            logger.warning("Gagal membaca %s, pakai default", SENTIMENT_WORDS_FILE)
    POSITIVE_WORDS = set(_DEFAULT_POSITIVE)
    NEGATIVE_WORDS = set(_DEFAULT_NEGATIVE)


def _save_sentiment_words():
    SENTIMENT_WORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SENTIMENT_WORDS_FILE.write_text(
        json.dumps({
            "positive": sorted(POSITIVE_WORDS),
            "negative": sorted(NEGATIVE_WORDS),
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def add_sentiment_word(word: str, category: str) -> bool:
    word = word.strip().lower()
    if not word:
        return False
    if category == "positive":
        POSITIVE_WORDS.add(word)
    elif category == "negative":
        NEGATIVE_WORDS.add(word)
    else:
        return False
    _save_sentiment_words()
    return True


def remove_sentiment_word(word: str, category: str) -> bool:
    word = word.strip().lower()
    if not word:
        return False
    if category == "positive":
        POSITIVE_WORDS.discard(word)
    elif category == "negative":
        NEGATIVE_WORDS.discard(word)
    else:
        return False
    _save_sentiment_words()
    return True


def get_sentiment_words() -> dict:
    return {
        "positive": sorted(POSITIVE_WORDS),
        "negative": sorted(NEGATIVE_WORDS),
    }


_init_sentiment_words()


def _clean_caption(caption: str) -> str:
    if not caption:
        return ""
    text = re.sub(r"[#@]\w+", "", caption)
    text = re.sub(r"https?://\S+", "", text)
    return text.lower().strip()


def _comments_text(comments: list[dict]) -> str:
    if not comments:
        return ""
    return " ".join(c.get("text", "") for c in comments if c.get("text"))


def _compute_sentiment(text: str) -> dict:
    cleaned = _clean_caption(text)
    words = set(cleaned.split())

    pos_count = sum(1 for w in words if w in POSITIVE_WORDS)
    neg_count = sum(1 for w in words if w in NEGATIVE_WORDS)

    for phrase in POSITIVE_WORDS:
        if " " in phrase and phrase in cleaned:
            pos_count += 1
    for phrase in NEGATIVE_WORDS:
        if " " in phrase and phrase in cleaned:
            neg_count += 1

    net = pos_count - neg_count
    if net > 0:
        label = "positive"
    elif net < 0:
        label = "negative"
    else:
        label = "neutral"

    return {"sentiment": label, "score": net, "positive_words": pos_count, "negative_words": neg_count}


def get_post_sentiment(caption: str, comments: list | None = None) -> dict:
    text = caption or ""
    if comments:
        text += " " + _comments_text(comments)
    return _compute_sentiment(text)


def _extract_hashtags(caption: str) -> list[str]:
    if not caption:
        return []
    return re.findall(r"#(\w+)", caption)


def analyze_engagement(posts: list[dict], followers_count: int) -> dict:
    if not posts:
        return {"error": "No posts"}

    has_followers = followers_count and followers_count > 0
    per_post = []
    daily: dict[str, list[float]] = {}
    weekly: dict[str, list[float]] = {}
    monthly: dict[str, list[float]] = {}
    by_type: dict[str, list[float]] = {}

    for p in posts:
        likes = p.get("like_count", 0)
        comments = p.get("comments_count", 0)
        interactions = likes + comments
        er = round((interactions / followers_count) * 100, 3) if has_followers else 0

        entry = {
            "id": p.get("id"),
            "caption": (p.get("caption") or "")[:80],
            "media_type": p.get("media_type", "UNKNOWN"),
            "likes": likes,
            "comments": comments,
            "interactions": interactions,
            "engagement_rate": er,
        }
        per_post.append(entry)

        mt = p.get("media_type", "UNKNOWN")
        if has_followers:
            by_type.setdefault(mt, []).append(er)
        else:
            by_type.setdefault(mt, []).append(interactions)

        ts = p.get("timestamp", "")
        if ts:
            month_key = ts[:7]
            daily_key = ts[:10]
            if has_followers:
                monthly.setdefault(month_key, []).append(er)
                daily.setdefault(daily_key, []).append(er)
            else:
                monthly.setdefault(month_key, []).append(interactions)
                daily.setdefault(daily_key, []).append(interactions)
            try:
                dt = datetime.fromisoformat(ts)
                iso_year, iso_week, _ = dt.isocalendar()
                week_key = f"{iso_year}-W{iso_week:02d}"
                if has_followers:
                    weekly.setdefault(week_key, []).append(er)
                else:
                    weekly.setdefault(week_key, []).append(interactions)
            except (ValueError, TypeError):
                pass

    if has_followers:
        avg_er = round(mean([e["engagement_rate"] for e in per_post]), 3)
    else:
        avg_er = round(mean([e["interactions"] for e in per_post]), 1)

    sorted_by_er = sorted(per_post, key=lambda x: x["engagement_rate"] if has_followers else x["interactions"], reverse=True)
    top_5 = sorted_by_er[:5]

    rate_label = "avg_engagement_rate" if has_followers else "avg_interactions"
    type_summary = {}
    for t, rates in by_type.items():
        type_summary[t] = {
            rate_label: round(mean(rates), 3) if has_followers else round(mean(rates), 1),
            "count": len(rates),
        }

    daily_trend = {}
    for d, rates in sorted(daily.items()):
        display_d = f"{d[8:10]}-{d[5:7]}-{d[:4]}"
        daily_trend[display_d] = round(mean(rates), 3) if has_followers else round(mean(rates), 1)

    weekly_trend = {}
    for w, rates in sorted(weekly.items()):
        display_w = w if "-W" not in w else f"W{w.split('-W')[1]}-{w.split('-W')[0]}"
        weekly_trend[display_w] = round(mean(rates), 3) if has_followers else round(mean(rates), 1)

    monthly_trend = {}
    for m, rates in sorted(monthly.items()):
        display_m = f"{m[5:7]}-{m[:4]}"
        monthly_trend[display_m] = round(mean(rates), 3) if has_followers else round(mean(rates), 1)

    return {
        "average_engagement_rate": avg_er,
        "total_interactions": sum(e["interactions"] for e in per_post),
        "followers_count": followers_count if has_followers else None,
        "has_followers_data": has_followers,
        "top_5_posts": top_5,
        "by_media_type": type_summary,
        "daily_trend": daily_trend,
        "weekly_trend": weekly_trend,
        "monthly_trend": monthly_trend,
        "per_post": per_post,
    }


def analyze_sentiment(posts: list[dict]) -> dict:
    if not posts:
        return {"error": "No posts"}

    results = []
    distribution = {"positive": 0, "neutral": 0, "negative": 0}

    for p in posts:
        caption = p.get("caption") or ""
        comments = p.get("comments", [])
        text = caption
        if comments:
            text += " " + _comments_text(comments)

        sentiment = _compute_sentiment(text)
        pos_count = sentiment["positive_words"]
        neg_count = sentiment["negative_words"]
        net = sentiment["score"]
        label = sentiment["sentiment"]
        distribution[label] += 1

        results.append({
            "id": p.get("id"),
            "caption": (caption or "")[:100],
            "media_type": p.get("media_type", "UNKNOWN"),
            "positive_words": pos_count,
            "negative_words": neg_count,
            "score": net,
            "sentiment": label,
            "comments_count": len(comments),
        })

    positive_posts = [r for r in results if r["sentiment"] == "positive"]
    negative_posts = [r for r in results if r["sentiment"] == "negative"]

    total = len(results)
    return {
        "distribution": distribution,
        "distribution_pct": {
            "positive": round(distribution["positive"] / total * 100, 1) if total else 0,
            "neutral": round(distribution["neutral"] / total * 100, 1) if total else 0,
            "negative": round(distribution["negative"] / total * 100, 1) if total else 0,
        },
        "total_posts": total,
        "top_positive": sorted(positive_posts, key=lambda x: x["score"], reverse=True)[:5] if positive_posts else [],
        "top_negative": sorted(negative_posts, key=lambda x: x["score"])[:5] if negative_posts else [],
        "per_post": results,
    }


def analyze_target_market(posts: list[dict], followers_count: int) -> dict:
    if not posts:
        return {"error": "No posts"}

    has_followers = followers_count and followers_count > 0
    day_names = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    day_engagement: dict[int, list[float]] = {i: [] for i in range(7)}
    type_engagement: dict[str, list[float]] = {}
    hashtag_engagement: dict[str, list[int]] = {}
    caption_lengths: list[tuple[int, float]] = []

    for p in posts:
        likes = p.get("like_count", 0)
        comments = p.get("comments_count", 0)
        interactions = likes + comments
        er = (interactions / followers_count * 100) if has_followers else 0

        ts = p.get("timestamp", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                day_engagement[dt.weekday()].append(interactions)
            except (ValueError, TypeError):
                pass

        mt = p.get("media_type", "UNKNOWN")
        type_engagement.setdefault(mt, []).append(er if has_followers else interactions)

        caption = p.get("caption") or ""
        hashtags = _extract_hashtags(caption)
        for h in hashtags:
            hashtag_engagement.setdefault(h, []).append(interactions)

        caption_lengths.append((len(caption.strip()), interactions))

    day_avg = {}
    for day_idx, vals in day_engagement.items():
        if vals:
            day_avg[day_names[day_idx]] = {
                "avg_interactions": round(mean(vals), 1),
                "count": len(vals),
            }
    best_day = max(day_avg, key=lambda d: day_avg[d]["avg_interactions"]) if day_avg else None

    type_perf = {}
    perf_key = "avg_engagement_rate" if has_followers else "avg_interactions"
    for t, rates in type_engagement.items():
        type_perf[t] = {
            perf_key: round(mean(rates), 3) if has_followers else round(mean(rates), 1),
            "count": len(rates),
        }
    best_type = max(type_perf, key=lambda t: type_perf[t][perf_key]) if type_perf else None

    hashtag_summary = {}
    for h, vals in hashtag_engagement.items():
        hashtag_summary[h] = {
            "frequency": len(vals),
            "avg_interactions": round(mean(vals), 1),
        }
    sorted_hashtags = sorted(hashtag_summary.items(), key=lambda x: x[1]["frequency"], reverse=True)
    top_hashtags = [{"tag": h, **v} for h, v in sorted_hashtags[:20]]

    length_buckets = {"0-50": [], "51-100": [], "101-200": [], "201-500": [], "500+": []}
    for length, interactions in caption_lengths:
        if length <= 50:
            length_buckets["0-50"].append(interactions)
        elif length <= 100:
            length_buckets["51-100"].append(interactions)
        elif length <= 200:
            length_buckets["101-200"].append(interactions)
        elif length <= 500:
            length_buckets["201-500"].append(interactions)
        else:
            length_buckets["500+"].append(interactions)

    caption_insight = {}
    for bucket, vals in length_buckets.items():
        if vals:
            caption_insight[bucket] = {
                "count": len(vals),
                "avg_interactions": round(mean(vals), 1),
            }
        else:
            caption_insight[bucket] = {"count": 0, "avg_interactions": 0}

    all_interactions = [p.get("like_count", 0) + p.get("comments_count", 0) for p in posts]
    consistency = {}
    if len(all_interactions) > 1:
        avg_int = mean(all_interactions)
        sd = stdev(all_interactions)
        cv = round((sd / avg_int) * 100, 1) if avg_int else 0
        consistency = {
            "average_interactions": round(avg_int, 1),
            "std_dev": round(sd, 1),
            "coefficient_of_variation_pct": cv,
            "interpretation": "Stabil" if cv < 50 else "Variatif" if cv < 100 else "Tidak konsisten",
        }
    elif len(all_interactions) == 1:
        consistency = {
            "average_interactions": all_interactions[0],
            "std_dev": 0,
            "coefficient_of_variation_pct": 0,
            "interpretation": "Hanya 1 post",
        }

    return {
        "best_posting_day": best_day,
        "day_breakdown": day_avg,
        "best_media_type": best_type,
        "media_type_performance": type_perf,
        "top_hashtags": top_hashtags,
        "caption_length_insight": caption_insight,
        "engagement_consistency": consistency,
        "followers_count": followers_count if has_followers else None,
        "has_followers_data": has_followers,
    }


STOPWORDS = {
    "dan", "di", "ke", "dari", "yang", "ini", "itu", "dengan", "untuk",
    "pada", "adalah", "akan", "telah", "sudah", "bisa", "dapat", "tidak",
    "juga", "saya", "kami", "kita", "mereka", "dia", "anda", "kau",
    "aku", "kamu", "nya", "the", "and", "of", "to", "in", "is", "it",
    "you", "that", "was", "for", "are", "with", "this", "have", "from",
    "atau", "serta", "tetapi", "namun", "ada", "saat", "setelah",
    "sebagai", "oleh", "seperti", "lebih", "semua", "jika", "saya",
    "bisa", "ingin", "akan", "telah", "sudah", "tersebut", "sebuah",
}

CONTENT_CATEGORIES = {
    "produk": {
        "keywords": ["produk", "product", "beli", "order", "shop", "tersedia",
                      "ready stock", "pre-order", "best seller", "kualitas",
                      "original", "baru", "tersedia", "stok"],
    },
    "promo": {
        "keywords": ["diskon", "discount", "sale", "promo", "gratis", "free",
                      "giveaway", "give away", "hadiah", "prize", "kompetisi",
                      "competition", "flash sale", "bundling", "bonus",
                      "cashback", "voucher", "coupon", "promotion"],
    },
    "edukasi": {
        "keywords": ["tips", "tutorial", "cara", "how to", "panduan", "guide",
                      "belajar", "learn", "edukasi", "education", "info",
                      "informasi", "knowledge", "pengetahuan", "triks",
                      "rahasia", "secret", "wawasan", "step by step",
                      "langkah", "cara mudah"],
    },
    "lifestyle": {
        "keywords": ["daily", "life", "sehari-hari", "lifestyle", "routine",
                      "rutinitas", "hari ini", "today", "activity",
                      "aktivitas", "momen", "moment", "vibes", "vibe",
                      "ootd", "outfit", "style", "fashion"],
    },
    "inspirasi": {
        "keywords": ["inspirasi", "inspiration", "motivasi", "motivation",
                      "semangat", "quotes", "quote", "kata kata",
                      "kutipan", "sabar", "syukur", "bersyukur",
                      "positive", "positif", "mindset", "growth"],
    },
    "behind_scene": {
        "keywords": ["behind the scene", "bts", "proses", "process",
                      "making", "dibalik layar", "behind the scenes",
                      "pembuatan", "workshop", "shooting"],
    },
}

_compiled_categories = None


def _get_categories():
    global _compiled_categories
    if _compiled_categories is not None:
        return _compiled_categories
    _compiled_categories = {}
    for cat_name, cat_data in CONTENT_CATEGORIES.items():
        _compiled_categories[cat_name] = [
            re.compile(re.escape(kw), re.IGNORECASE) for kw in cat_data["keywords"]
        ]
    return _compiled_categories


def classify_content(caption: str) -> str:
    if not caption:
        return "uncategorized"
    categories = _get_categories()
    scores = {}
    for cat_name, patterns in categories.items():
        score = sum(1 for p in patterns if p.search(caption))
        if score > 0:
            scores[cat_name] = score
    if not scores:
        return "uncategorized"
    return max(scores, key=scores.get)


def analyze_content_categories(posts: list[dict]) -> dict:
    if not posts:
        return {"error": "No posts"}

    category_counts: dict[str, int] = {}
    category_engagement: dict[str, list[float]] = {}

    for p in posts:
        caption = p.get("caption") or ""
        cat = classify_content(caption)
        category_counts[cat] = category_counts.get(cat, 0) + 1
        interactions = p.get("like_count", 0) + p.get("comments_count", 0)
        category_engagement.setdefault(cat, []).append(interactions)

    cat_avg = {}
    for cat, vals in category_engagement.items():
        cat_avg[cat] = {
            "count": len(vals),
            "avg_interactions": round(mean(vals), 1) if vals else 0,
            "total_interactions": sum(vals),
        }

    best_category = max(cat_avg, key=lambda c: cat_avg[c]["avg_interactions"]) if cat_avg else None

    return {
        "category_distribution": category_counts,
        "category_performance": cat_avg,
        "best_category": best_category,
        "total_posts": len(posts),
    }


def extract_word_frequencies(posts: list[dict], max_words: int = 100) -> list[dict]:
    word_counts: dict[str, int] = Counter()

    def _count_text(text: str):
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"[#@]\w+", "", text)
        text = re.sub(r"[^\w\s]", " ", text)
        words = text.lower().split()
        for w in words:
            w = w.strip()
            if len(w) > 2 and w not in STOPWORDS:
                word_counts[w] += 1

    for p in posts:
        caption = p.get("caption") or ""
        _count_text(caption)
        for c in p.get("comments", []):
            _count_text(c.get("text", ""))

    most_common = word_counts.most_common(max_words)
    return [{"word": w, "count": c, "size": c} for w, c in most_common]


def analyze_best_time_to_post(posts: list[dict]) -> dict:
    if not posts:
        return {"error": "No posts"}

    day_names = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    heatmap: dict[str, dict[int, list[int]]] = {}
    for day in day_names:
        heatmap[day] = {h: [] for h in range(24)}

    for p in posts:
        ts = p.get("timestamp", "")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            day_name = day_names[dt.weekday()]
            hour = dt.hour
            interactions = p.get("like_count", 0) + p.get("comments_count", 0)
            heatmap[day_name][hour].append(interactions)
        except (ValueError, TypeError):
            pass

    matrix = []
    for day in day_names:
        row = []
        for h in range(24):
            vals = heatmap[day][h]
            avg = round(mean(vals), 1) if vals else 0
            count = len(vals)
            row.append({"hour": h, "avg_interactions": avg, "count": count})
        matrix.append({"day": day, "hours": row})

    all_hour_day = []
    for day in day_names:
        for h in range(24):
            vals = heatmap[day][h]
            if vals:
                all_hour_day.append((day, h, mean(vals)))

    best_time = None
    if all_hour_day:
        best = max(all_hour_day, key=lambda x: x[2])
        best_time = {
            "day": best[0],
            "hour": best[1],
            "avg_interactions": round(best[2], 1),
        }

    return {
        "heatmap": matrix,
        "best_time": best_time,
        "day_names": day_names,
    }


def analyze_followers_trend(insights_data: dict) -> dict:
    if not insights_data:
        return {"error": "No insights data"}

    raw_data = insights_data.get("data", [])
    if not raw_data:
        return {"error": "Empty insights response"}

    metric = raw_data[0]
    values = metric.get("values", [])
    if not values:
        return {"error": "No values in insights data"}

    parsed = []
    for v in values:
        val = v.get("value")
        end_time = v.get("end_time", "")
        if val is None or not end_time:
            continue
        try:
            dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        parsed.append({"date": dt.strftime("%d-%m-%Y"), "followers": val})

    if not parsed:
        return {"error": "Failed to parse insights values"}

    parsed.sort(key=lambda x: x["date"])

    for i, entry in enumerate(parsed):
        prev = parsed[i - 1]["followers"] if i > 0 else entry["followers"]
        entry["change"] = entry["followers"] - prev

    current = parsed[-1]["followers"]
    oldest = parsed[0]["followers"]
    total_change = current - oldest
    avg_daily_change = round(total_change / (len(parsed) - 1), 1) if len(parsed) > 1 else 0

    weekly: dict[str, list[int]] = {}
    monthly: dict[str, list[int]] = {}
    for entry in parsed:
        dt = datetime.strptime(entry["date"], "%d-%m-%Y")
        iso_year, iso_week, _ = dt.isocalendar()
        week_key = f"{iso_year}-W{iso_week:02d}"
        month_key = dt.strftime("%Y-%m")
        weekly.setdefault(week_key, []).append(entry["followers"])
        monthly.setdefault(month_key, []).append(entry["followers"])

    weekly_agg = []
    for wk, vals in sorted(weekly.items()):
        weekly_agg.append({
            "week": wk,
            "avg_followers": round(mean(vals)),
            "change": vals[-1] - vals[0],
        })

    monthly_agg = []
    for mn, vals in sorted(monthly.items()):
        display_mn = f"{mn[5:7]}-{mn[:4]}"
        monthly_agg.append({
            "month": display_mn,
            "avg_followers": round(mean(vals)),
            "change": vals[-1] - vals[0],
        })

    return {
        "current_followers": current,
        "total_change": total_change,
        "avg_daily_change": avg_daily_change,
        "data_points": len(parsed),
        "daily": parsed,
        "weekly": weekly_agg,
        "monthly": monthly_agg,
    }

import re
import logging
from collections import Counter
from datetime import datetime
from statistics import mean, stdev

logger = logging.getLogger(__name__)

POSITIVE_WORDS = {
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

NEGATIVE_WORDS = {
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


def _extract_hashtags(caption: str) -> list[str]:
    if not caption:
        return []
    return re.findall(r"#(\w+)", caption)


def _clean_caption(caption: str) -> str:
    if not caption:
        return ""
    text = re.sub(r"[#@]\w+", "", caption)
    text = re.sub(r"https?://\S+", "", text)
    return text.lower().strip()


def analyze_engagement(posts: list[dict], followers_count: int) -> dict:
    if not posts or not followers_count:
        return {"error": "No posts or followers_count is 0"}

    per_post = []
    monthly: dict[str, list[float]] = {}
    by_type: dict[str, list[float]] = {}

    for p in posts:
        likes = p.get("like_count", 0)
        comments = p.get("comments_count", 0)
        interactions = likes + comments
        er = round((interactions / followers_count) * 100, 3)

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
        by_type.setdefault(mt, []).append(er)

        ts = p.get("timestamp", "")
        if ts:
            month_key = ts[:7]
            monthly.setdefault(month_key, []).append(er)

    avg_er = round(mean([e["engagement_rate"] for e in per_post]), 3)
    sorted_by_er = sorted(per_post, key=lambda x: x["engagement_rate"], reverse=True)
    top_5 = sorted_by_er[:5]

    type_summary = {}
    for t, rates in by_type.items():
        type_summary[t] = {
            "avg_engagement_rate": round(mean(rates), 3),
            "count": len(rates),
        }

    monthly_trend = {}
    for m, rates in sorted(monthly.items()):
        monthly_trend[m] = round(mean(rates), 3)

    return {
        "average_engagement_rate": avg_er,
        "total_interactions": sum(e["interactions"] for e in per_post),
        "followers_count": followers_count,
        "top_5_posts": top_5,
        "by_media_type": type_summary,
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
        cleaned = _clean_caption(caption)
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
            distribution["positive"] += 1
        elif net < 0:
            label = "negative"
            distribution["negative"] += 1
        else:
            label = "neutral"
            distribution["neutral"] += 1

        results.append({
            "id": p.get("id"),
            "caption": (caption or "")[:100],
            "media_type": p.get("media_type", "UNKNOWN"),
            "positive_words": pos_count,
            "negative_words": neg_count,
            "score": net,
            "sentiment": label,
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

    day_names = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    day_engagement: dict[int, list[float]] = {i: [] for i in range(7)}
    type_engagement: dict[str, list[float]] = {}
    hashtag_engagement: dict[str, list[int]] = {}
    caption_lengths: list[tuple[int, float]] = []

    for p in posts:
        likes = p.get("like_count", 0)
        comments = p.get("comments_count", 0)
        interactions = likes + comments
        er = ((interactions) / followers_count * 100) if followers_count else 0

        ts = p.get("timestamp", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                day_engagement[dt.weekday()].append(interactions)
            except (ValueError, TypeError):
                pass

        mt = p.get("media_type", "UNKNOWN")
        type_engagement.setdefault(mt, []).append(er)

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
    for t, rates in type_engagement.items():
        type_perf[t] = {
            "avg_engagement_rate": round(mean(rates), 3),
            "count": len(rates),
        }
    best_type = max(type_perf, key=lambda t: type_perf[t]["avg_engagement_rate"]) if type_perf else None

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
    }

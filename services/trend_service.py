"""
Model 2 – Trend Analysis Engine
Consumes Model 1 output from MongoDB and produces trend intelligence.

Architecture:
  - All heavy lifting is done via MongoDB aggregation pipelines (fast, scalable)
  - AI (Groq) is called ONCE per trend report for the executive summary only
  - Emerging issue detection uses Counter-based NLP on review summaries
  - Results are optionally cached in the trend_reports collection
  - Supports 50,000+ reviews through pipeline-level filtering and projection

Performance strategy:
  - Never load raw review text into Python for aggregation work
  - Use $match as the first pipeline stage to filter at DB level
  - Project only the fields each pipeline needs
  - AI summary is generated from pre-aggregated stats, not raw reviews
"""

import logging
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from groq import Groq, RateLimitError

from database.mongo import get_db

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Groq client (reused from env – one client for the whole service)
# ---------------------------------------------------------------------------

_groq = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
_TREND_MODEL = "llama-3.3-70b-versatile"

# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------

_PERIOD_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}


def _period_to_days(period: str) -> int:
    return _PERIOD_DAYS.get(period, 30)


def _date_range(
    period: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple[datetime, datetime]:
    """
    Return (start, end) as naive UTC datetimes (no timezone suffix).
    Custom start/end take priority over period shorthand.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if start_date and end_date:
        try:
            start = datetime.fromisoformat(start_date).replace(tzinfo=None)
            end   = datetime.fromisoformat(end_date).replace(tzinfo=None)
            return start, end
        except ValueError:
            pass  # fall through to period logic

    days  = _period_to_days(period or "30d")
    start = now - timedelta(days=days)
    return start, now


def _previous_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """Return the equivalent previous period immediately before (start, end)."""
    delta = end - start
    return start - delta, start


# ---------------------------------------------------------------------------
# MongoDB match stage builder
# ---------------------------------------------------------------------------

def _build_match(
    start: datetime,
    end: datetime,
    package_name: Optional[str],
) -> dict:
    """
    Build the $match stage used across all pipelines.
    Dates are stored as plain ISO strings without timezone suffix,
    so we strip the offset here to keep string comparison consistent.
    """
    # Remove timezone info so the string matches what scraper_service stores
    start_str = start.replace(tzinfo=None).isoformat()
    end_str   = end.replace(tzinfo=None).isoformat()

    match: dict[str, Any] = {
        "date": {
            "$gte": start_str,
            "$lte": end_str,
        }
    }
    if package_name:
        match["packageName"] = package_name
    return match


# ---------------------------------------------------------------------------
# 1. Sentiment aggregation
# ---------------------------------------------------------------------------

async def get_sentiment_counts(
    start: datetime,
    end: datetime,
    package_name: Optional[str] = None,
) -> dict[str, int]:
    """Return {Positive: n, Negative: n, Neutral: n} for the given window."""
    collection = get_db()["reviews"]
    pipeline = [
        {"$match": _build_match(start, end, package_name)},
        {"$group": {"_id": "$sentiment", "count": {"$sum": 1}}},
    ]
    cursor = collection.aggregate(pipeline)
    result = {"Positive": 0, "Negative": 0, "Neutral": 0}
    async for doc in cursor:
        if doc["_id"] in result:
            result[doc["_id"]] = doc["count"]
    return result


def _to_percentages(counts: dict[str, int]) -> dict[str, float]:
    """Convert raw counts to rounded percentages."""
    total = sum(counts.values())
    if total == 0:
        return {"Positive": 0.0, "Negative": 0.0, "Neutral": 0.0}
    return {k: round(v / total * 100, 1) for k, v in counts.items()}


# ---------------------------------------------------------------------------
# 2. Feedback type aggregation
# ---------------------------------------------------------------------------

async def get_feedback_type_counts(
    start: datetime,
    end: datetime,
    package_name: Optional[str] = None,
) -> dict[str, int]:
    """Return counts per feedbackType for the given window."""
    collection = get_db()["reviews"]
    pipeline = [
        {"$match": _build_match(start, end, package_name)},
        {"$group": {"_id": "$feedbackType", "count": {"$sum": 1}}},
    ]
    cursor = collection.aggregate(pipeline)

    _key_map = {
        "Bug Report":       "bugReports",
        "Complaint":        "complaints",
        "Suggestion":       "suggestions",
        "Positive Feedback":"positiveFeedback",
        "General Feedback": "generalFeedback",
    }
    result = {v: 0 for v in _key_map.values()}
    async for doc in cursor:
        key = _key_map.get(doc["_id"])
        if key:
            result[key] = doc["count"]
    return result


# ---------------------------------------------------------------------------
# 3. Top issues  – AI-powered extraction (replaces n-gram approach)
# ---------------------------------------------------------------------------

# Stopwords kept for the feature-request path in priority_service
_STOPWORDS = {
    "the","a","an","is","in","of","to","and","or","for","with","that",
    "this","it","not","after","has","been","app","update","user","users",
    "use","using","when","but","are","was","have","from","on","at","be",
    "very","please","i","my","me","we","they","he","she","its","your",
    "can","cannot","cant","dont","do","get","getting","got","keep","still",
    "always","every","time","times","since","new","now","latest","even",
    "also","just","would","will","about","issue","problem","error","fix",
    "issues","problems",
}


def _extract_issues_with_llm(summaries: list[str], top_n: int) -> dict[str, Any]:
    """
    Group review summaries into issue clusters and positive highlights.
    Uses simple heuristic grouping — no extra Groq call here.
    Groq is reserved for the final recommendations step only.
    """
    if not summaries:
        return {"issues": [], "positiveHighlights": []}

    issues: list[dict] = []
    highlights: list[dict] = []
    seen_issues: dict[str, int] = {}
    seen_highlights: dict[str, int] = {}

    for s in summaries:
        s = s.strip()
        if not s:
            continue
        if _is_positive_phrase(s):
            # Normalise key
            key = s.lower()[:80]
            seen_highlights[key] = seen_highlights.get(key, 0) + 1
        else:
            key = s.lower()[:80]
            seen_issues[key] = seen_issues.get(key, 0) + 1

    # Sort by frequency, take top N
    top_issues = sorted(seen_issues.items(), key=lambda x: x[1], reverse=True)
    top_highlights = sorted(seen_highlights.items(), key=lambda x: x[1], reverse=True)

    # Deduplicate: drop shorter entries that are substrings of longer ones
    def _dedup(items: list[tuple[str, int]], n: int) -> list[dict]:
        result = []
        for phrase, count in items:
            if not any(phrase in kept for kept, _ in result):
                result.append((phrase, count))
            if len(result) >= n:
                break
        return [{"issue": p.title(), "count": c} for p, c in result]

    def _dedup_highlights(items: list[tuple[str, int]], n: int) -> list[dict]:
        result = []
        for phrase, count in items:
            if not any(phrase in kept for kept, _ in result):
                result.append((phrase, count))
            if len(result) >= n:
                break
        return [{"highlight": p.title(), "count": c} for p, c in result]

    return {
        "issues":            _dedup(top_issues, top_n),
        "positiveHighlights":_dedup_highlights(top_highlights, 5),
    }


# Positive-phrase guard — last-resort filter before any issue enters the pipeline
_POSITIVE_WORDS = {
    "great","excellent","amazing","awesome","love","loved","best","perfect",
    "wonderful","fantastic","superb","good","nice","brilliant","outstanding",
    "beautiful","smooth","easy","helpful","fast","quick","enjoy","enjoyed",
    "happy","satisfied","pleased","impressed","appreciate","recommended",
    "flawless","seamless","intuitive","clean","simple","works well","works great",
}

def _is_positive_phrase(title: str) -> bool:
    """Return True if the phrase is clearly positive praise, not an issue."""
    lower = title.lower()
    tokens = set(re.findall(r"\w+", lower))
    positive_hits = tokens & _POSITIVE_WORDS
    negative_words = {
        "crash","fail","failed","error","bug","slow","broken","not","cannot",
        "cant","issue","problem","missing","fix","delay","stuck","freeze",
        "wrong","bad","poor","terrible","awful","hate","annoying","frustrating",
        "unable","refused","declined","charged","lost","deleted","disappeared",
    }
    negative_hits = tokens & negative_words
    # Positive if has positive words and NO negative words
    return len(positive_hits) > 0 and len(negative_hits) == 0


async def get_top_issues(
    start: datetime,
    end: datetime,
    package_name: Optional[str] = None,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """
    Returns only actionable issues.
    Fetches summaries from non-positive reviews only (Bug Report, Complaint, Suggestion).
    Positive Feedback is excluded at the MongoDB query level.
    """
    collection = get_db()["reviews"]
    pipeline = [
        {"$match": {
            **_build_match(start, end, package_name),
            "feedbackType": {"$in": ["Bug Report", "Complaint", "Suggestion", "General Feedback"]},
        }},
        {"$project": {"_id": 0, "summary": 1}},
    ]

    summaries: list[str] = []
    async for doc in collection.aggregate(pipeline):
        s = doc.get("summary", "").strip()
        if s and not _is_positive_phrase(s):
            summaries.append(s)

    if not summaries:
        return []

    result = _extract_issues_with_llm(summaries, top_n)
    return result.get("issues", [])


async def get_top_issues_and_highlights(
    start: datetime,
    end: datetime,
    package_name: Optional[str] = None,
    top_n: int = 10,
) -> dict[str, Any]:
    """
    Returns both issues (from non-positive reviews) and positiveHighlights
    (from Positive Feedback reviews) in one call. No extra Groq API calls.
    """
    collection = get_db()["reviews"]

    # Issues: from complaints, bugs, suggestions
    issue_pipeline = [
        {"$match": {
            **_build_match(start, end, package_name),
            "feedbackType": {"$in": ["Bug Report", "Complaint", "Suggestion", "General Feedback"]},
        }},
        {"$project": {"_id": 0, "summary": 1}},
    ]

    # Highlights: from positive feedback
    highlight_pipeline = [
        {"$match": {
            **_build_match(start, end, package_name),
            "feedbackType": "Positive Feedback",
        }},
        {"$project": {"_id": 0, "summary": 1}},
    ]

    issue_summaries: list[str] = []
    async for doc in collection.aggregate(issue_pipeline):
        s = doc.get("summary", "").strip()
        if s and not _is_positive_phrase(s):
            issue_summaries.append(s)

    highlight_summaries: list[str] = []
    async for doc in collection.aggregate(highlight_pipeline):
        s = doc.get("summary", "").strip()
        if s:
            highlight_summaries.append(s)

    if not issue_summaries and not highlight_summaries:
        return {"issues": [], "positiveHighlights": []}

    # Build issues from non-positive summaries
    issues_result = _extract_issues_with_llm(issue_summaries, top_n)
    issues = issues_result.get("issues", [])

    # Build highlights from positive summaries (separate clean list)
    highlights: list[dict] = []
    seen: dict[str, int] = {}
    for s in highlight_summaries:
        key = s.strip().lower()[:80]
        seen[key] = seen.get(key, 0) + 1
    top_pos = sorted(seen.items(), key=lambda x: x[1], reverse=True)[:5]
    highlights = [{"highlight": p.title(), "count": c} for p, c in top_pos]

    return {"issues": issues, "positiveHighlights": highlights}


# ---------------------------------------------------------------------------
# 4. Emerging issue detection
# ---------------------------------------------------------------------------

async def get_emerging_issues(
    period: str = "30d",
    package_name: Optional[str] = None,
    min_recent_count: int = 3,
    growth_threshold: float = 1.5,
) -> list[dict[str, Any]]:
    """
    Detect issues that have grown significantly in the recent half of the period
    compared to the earlier half.

    Strategy:
    - Split the period into two equal halves
    - Count phrase frequencies in each half
    - Flag as Emerging if recent_count >= min_recent_count AND
      recent_count / max(previous_count, 1) >= growth_threshold
    - Flag as Declining if the inverse is true
    """
    days = _period_to_days(period)
    now = datetime.now(timezone.utc)
    mid = now - timedelta(days=days // 2)
    start = now - timedelta(days=days)

    # Recent half
    recent_issues = await get_top_issues(mid, now, package_name, top_n=50)
    # Previous half
    prev_issues = await get_top_issues(start, mid, package_name, top_n=50)

    prev_map = {item["issue"]: item["count"] for item in prev_issues}
    recent_map = {item["issue"]: item["count"] for item in recent_issues}

    results: list[dict[str, Any]] = []

    for issue, recent_count in recent_map.items():
        if recent_count < min_recent_count:
            continue

        prev_count = prev_map.get(issue, 0)
        ratio = recent_count / max(prev_count, 1)

        if ratio >= growth_threshold:
            trend = "Emerging"
        elif ratio <= (1 / growth_threshold):
            trend = "Declining"
        else:
            trend = "Stable"

        if trend in ("Emerging", "Declining"):
            results.append({
                "issue": issue,
                "trend": trend,
                "recentCount": recent_count,
                "previousCount": prev_count,
            })

    # Sort: Emerging first, then by recent count
    results.sort(key=lambda x: (x["trend"] != "Emerging", -x["recentCount"]))
    return results[:20]


# ---------------------------------------------------------------------------
# 5. Total review count
# ---------------------------------------------------------------------------

async def get_total_count(
    start: datetime,
    end: datetime,
    package_name: Optional[str] = None,
) -> int:
    collection = get_db()["reviews"]
    return await collection.count_documents(_build_match(start, end, package_name))


# ---------------------------------------------------------------------------
# 6. Groq-powered trend summary  (one AI call per report)
# ---------------------------------------------------------------------------

def generate_trend_summary(
    total: int,
    sentiment_pct: dict[str, float],
    sentiment_change: Optional[dict[str, float]],
    top_issues: list[dict],
    feedback_counts: dict[str, int],
    period: str,
) -> str:
    """
    Ask Groq to write a concise business-friendly executive summary
    based on pre-aggregated statistics. Only the stats are sent – no raw reviews.
    """
    issue_lines = "\n".join(
        f"  - {item['issue']}: {item['count']} mentions"
        for item in top_issues[:5]
    )

    change_text = ""
    if sentiment_change:
        change_text = (
            f"\nSentiment change vs previous period: "
            f"Positive {sentiment_change['positive']:+.1f}%, "
            f"Negative {sentiment_change['negative']:+.1f}%, "
            f"Neutral {sentiment_change['neutral']:+.1f}%"
        )

    prompt = (
        f"You are a product analytics expert. Write a concise 3-4 sentence "
        f"business-friendly summary of this app review trend data.\n\n"
        f"Period: last {period}\n"
        f"Total reviews analysed: {total}\n"
        f"Sentiment: Positive {sentiment_pct.get('Positive', 0)}%, "
        f"Negative {sentiment_pct.get('Negative', 0)}%, "
        f"Neutral {sentiment_pct.get('Neutral', 0)}%"
        f"{change_text}\n"
        f"Feedback breakdown: Bug Reports={feedback_counts.get('bugReports', 0)}, "
        f"Complaints={feedback_counts.get('complaints', 0)}, "
        f"Suggestions={feedback_counts.get('suggestions', 0)}, "
        f"Positive Feedback={feedback_counts.get('positiveFeedback', 0)}\n"
        f"Top issues:\n{issue_lines}\n\n"
        f"Write only the summary. No bullet points, no headers."
    )

    try:
        response = _groq.chat.completions.create(
            model=_TREND_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200,
        )
        return response.choices[0].message.content.strip()
    except RateLimitError:
        logger.warning("Groq rate limit hit during trend summary generation.")
        return _fallback_summary(sentiment_pct, top_issues, period)
    except Exception as exc:
        logger.error("Trend summary generation failed: %s", exc)
        return _fallback_summary(sentiment_pct, top_issues, period)


def _fallback_summary(
    sentiment_pct: dict[str, float],
    top_issues: list[dict],
    period: str,
) -> str:
    """Rule-based fallback when Groq is unavailable."""
    neg = sentiment_pct.get("Negative", 0)
    pos = sentiment_pct.get("Positive", 0)
    top = top_issues[0]["issue"] if top_issues else "various issues"
    tone = "predominantly negative" if neg > 50 else ("predominantly positive" if pos > 50 else "mixed")
    return (
        f"User sentiment over the last {period} is {tone} "
        f"({pos}% positive, {neg}% negative). "
        f"The most discussed issue is '{top}'."
    )


# ---------------------------------------------------------------------------
# 7. Comparison engine
# ---------------------------------------------------------------------------

async def compare_periods(
    current_start: datetime,
    current_end: datetime,
    prev_start: datetime,
    prev_end: datetime,
    package_name: Optional[str] = None,
) -> dict[str, Any]:
    """
    Compare sentiment and feedback type counts between two time windows.
    Returns percentage-point changes for sentiment and absolute+percent changes
    for feedback types.
    """
    # Run all four aggregations concurrently via gather
    import asyncio

    curr_sentiment, prev_sentiment, curr_fb, prev_fb = await asyncio.gather(
        get_sentiment_counts(current_start, current_end, package_name),
        get_sentiment_counts(prev_start, prev_end, package_name),
        get_feedback_type_counts(current_start, current_end, package_name),
        get_feedback_type_counts(prev_start, prev_end, package_name),
    )

    curr_pct = _to_percentages(curr_sentiment)
    prev_pct = _to_percentages(prev_sentiment)

    sentiment_changes = {
        "positive": round(curr_pct["Positive"] - prev_pct["Positive"], 1),
        "negative": round(curr_pct["Negative"] - prev_pct["Negative"], 1),
        "neutral":  round(curr_pct["Neutral"]  - prev_pct["Neutral"],  1),
    }

    fb_changes: dict[str, Any] = {}
    for key in curr_fb:
        curr_val = curr_fb[key]
        prev_val = prev_fb.get(key, 0)
        change_pct = (
            round((curr_val - prev_val) / prev_val * 100, 1)
            if prev_val > 0
            else (100.0 if curr_val > 0 else 0.0)
        )
        fb_changes[key] = {
            "metric": key,
            "current": curr_val,
            "previous": prev_val,
            "changePercent": change_pct,
        }

    neg_change = sentiment_changes["negative"]
    if neg_change > 5:
        shift = f"Negative sentiment increased by {neg_change}pp — user satisfaction declined."
    elif neg_change < -5:
        shift = f"Negative sentiment decreased by {abs(neg_change)}pp — user satisfaction improved."
    else:
        shift = "Overall sentiment remained relatively stable."

    return {
        "sentimentChanges": sentiment_changes,
        "feedbackTypeChanges": fb_changes,
        "overallSentimentShift": shift,
    }


# ---------------------------------------------------------------------------
# 8. Cache trend report in MongoDB
# ---------------------------------------------------------------------------

async def cache_trend_report(report: dict[str, Any]) -> None:
    """Upsert a trend report into the trend_reports collection."""
    try:
        collection = get_db()["trend_reports"]
        key = {
            "packageName": report.get("packageName"),
            "period": report.get("period"),
        }
        report["cachedAt"] = datetime.utcnow().isoformat()
        await collection.update_one(key, {"$set": report}, upsert=True)
    except Exception as exc:
        logger.warning("Failed to cache trend report: %s", exc)


async def get_cached_report(
    package_name: Optional[str],
    period: str,
    max_age_minutes: int = 30,
) -> Optional[dict[str, Any]]:
    """
    Return a cached trend report if it exists and is younger than max_age_minutes.
    Returns None if no valid cache entry exists.
    """
    try:
        collection = get_db()["trend_reports"]
        doc = await collection.find_one(
            {"packageName": package_name, "period": period},
            sort=[("cachedAt", -1)],
        )
        if not doc:
            return None

        cached_at = datetime.fromisoformat(doc["cachedAt"]).replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - cached_at).total_seconds() / 60
        if age > max_age_minutes:
            return None

        doc.pop("_id", None)
        return doc
    except Exception as exc:
        logger.warning("Cache lookup failed: %s", exc)
        return None

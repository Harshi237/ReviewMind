"""
Model 3 – Priority Intelligence Engine

Consumes Model 1 (reviews collection) and Model 2 (trend data) outputs to
determine exactly what product and engineering teams should act on next.

Architecture & performance:
  ─ All volume/distribution data comes from MongoDB aggregation pipelines
  ─ Issue clustering uses LLM-assisted grouping via Groq (one call, batched)
  ─ Growth data reuses Model 2's period-comparison logic directly
  ─ Priority score is a configurable weighted formula (0–100)
  ─ Groq is called TWICE per full report:
      1. Issue clustering (batch – one prompt for all top issues)
      2. Recommendations (one prompt per final ranked list)
  ─ Reports are cached in priority_reports collection for 30 minutes
  ─ Supports 50,000+ reviews via pipeline-first strategy
"""

import asyncio
import logging
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from groq import Groq, RateLimitError

from database.mongo import get_db
from services.trend_service import (
    _build_match,
    _period_to_days,
    _STOPWORDS,
    _to_percentages,
    _is_positive_phrase,
    get_sentiment_counts,
    get_top_issues,
    get_top_issues_and_highlights,
    get_total_count,
)

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Groq client
# ---------------------------------------------------------------------------

_groq  = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
_MODEL = "llama-3.3-70b-versatile"

# ---------------------------------------------------------------------------
# Scoring weights (default – overridden by request params)
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS = {
    "impact":    0.40,
    "growth":    0.30,
    "severity":  0.20,
    "sentiment": 0.10,
}

# ---------------------------------------------------------------------------
# Severity keyword rules (deterministic fast-path before LLM clustering)
# ---------------------------------------------------------------------------

_CRITICAL_KEYWORDS = {
    "crash","crashes","crashing","not opening","force close","black screen",
    "white screen","data loss","account deleted","payment deducted","charged twice",
    "money deducted","fraud","hacked","security",
}
_HIGH_KEYWORDS = {
    "login","sign in","sign up","register","payment","transaction","otp",
    "verification","unable to","cannot","not working","broken","failed","failure",
    "error","bug","stuck","freeze","freezing","hangs","hanging",
}
_MEDIUM_KEYWORDS = {
    "slow","lag","lagging","delay","loading","battery","drain","notification",
    "missing","incorrect","wrong","outdated","search","filter",
}
# Everything else is Low


def _assign_severity(
    issue: str,
    growth_percent: float,
    negative_pct: float,
) -> str:
    """
    Rule-based severity assignment.
    Escalates automatically if growth is extreme or sentiment is very negative.
    """
    lowered = issue.lower()
    tokens  = set(re.findall(r"\w+", lowered))

    if tokens & _CRITICAL_KEYWORDS:
        base = "Critical"
    elif tokens & _HIGH_KEYWORDS:
        base = "High"
    elif tokens & _MEDIUM_KEYWORDS:
        base = "Medium"
    else:
        base = "Low"

    # Escalation rules
    _order = ["Low", "Medium", "High", "Critical"]
    idx = _order.index(base)

    if growth_percent > 200 and idx < 3:
        idx += 1          # escalate one level for explosive growth
    if negative_pct > 80 and idx < 3:
        idx += 1          # escalate if overwhelming negative sentiment

    return _order[min(idx, 3)]


def _severity_score(severity: str) -> float:
    """Map severity label → normalised 0-100 score for the priority formula."""
    return {"Critical": 100.0, "High": 75.0, "Medium": 40.0, "Low": 15.0}.get(severity, 15.0)


# ---------------------------------------------------------------------------
# 1. Growth analysis per issue
# ---------------------------------------------------------------------------

async def _get_issue_growth(
    issue: str,
    curr_start: datetime,
    curr_end: datetime,
    prev_start: datetime,
    prev_end: datetime,
    package_name: Optional[str],
) -> tuple[int, int, float]:
    """
    Return (current_count, previous_count, growth_percent) for a specific issue phrase.
    Counts reviews whose summary contains the issue phrase in each window.
    """
    collection = get_db()["reviews"]

    regex = {"$regex": re.escape(issue), "$options": "i"}

    async def _count(start: datetime, end: datetime) -> int:
        match = _build_match(start, end, package_name)
        match["summary"] = regex
        return await collection.count_documents(match)

    curr, prev = await asyncio.gather(
        _count(curr_start, curr_end),
        _count(prev_start, prev_end),
    )

    if prev == 0:
        growth = 100.0 if curr > 0 else 0.0
    else:
        growth = round((curr - prev) / prev * 100, 1)

    return curr, prev, growth


# ---------------------------------------------------------------------------
# 2. Sentiment breakdown per issue
# ---------------------------------------------------------------------------

async def _get_issue_sentiment(
    issue: str,
    start: datetime,
    end: datetime,
    package_name: Optional[str],
) -> dict[str, Any]:
    """
    Return sentiment distribution and dominant feedbackType for a specific issue.
    """
    collection = get_db()["reviews"]
    match = _build_match(start, end, package_name)
    match["summary"] = {"$regex": re.escape(issue), "$options": "i"}

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {
                "sentiment":    "$sentiment",
                "feedbackType": "$feedbackType",
            },
            "count": {"$sum": 1},
        }},
    ]

    sentiment_counts: dict[str, int] = {"Positive": 0, "Negative": 0, "Neutral": 0}
    fb_counts: Counter = Counter()

    async for doc in collection.aggregate(pipeline):
        s  = doc["_id"].get("sentiment", "")
        ft = doc["_id"].get("feedbackType", "")
        n  = doc["count"]
        if s in sentiment_counts:
            sentiment_counts[s] += n
        fb_counts[ft] += n

    pct = _to_percentages(sentiment_counts)
    dominant_sentiment = max(pct, key=pct.get)  # type: ignore[arg-type]
    dominant_fb = fb_counts.most_common(1)[0][0] if fb_counts else "General Feedback"

    return {
        "dominantSentiment": dominant_sentiment,
        "negativePct":       pct.get("Negative", 0.0),
        "feedbackType":      dominant_fb,
    }


# ---------------------------------------------------------------------------
# 3. Feature request extraction – AI-powered
# ---------------------------------------------------------------------------

async def get_feature_requests(
    start: datetime,
    end: datetime,
    package_name: Optional[str],
    total_reviews: int,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """
    Extract top feature requests from Suggestion reviews using Groq.
    Returns complete, human-readable feature titles with counts and priority scores.
    """
    collection = get_db()["reviews"]
    pipeline = [
        {"$match": {**_build_match(start, end, package_name), "feedbackType": "Suggestion"}},
        {"$project": {"_id": 0, "summary": 1}},
    ]

    summaries: list[str] = []
    async for doc in collection.aggregate(pipeline):
        s = doc.get("summary", "").strip()
        if s:
            summaries.append(s)

    if not summaries:
        return []

    total_suggestions = len(summaries) or 1
    sample = summaries[:200]
    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sample))

    prompt = (
        "You are a product analyst reviewing feature requests from app users.\n"
        "Below are summaries of user suggestions.\n\n"
        "Your task:\n"
        f"1. Identify the top {top_n} distinct feature requests.\n"
        "2. Write a COMPLETE, human-readable feature title (3–6 words) for each.\n"
        "3. Count how many summaries relate to each feature request.\n\n"
        "Rules:\n"
        "- Titles must be complete (e.g. 'Add Dark Mode Option', "
        "'Offline Playback Support', 'Improve Search Functionality').\n"
        "- Never use single words or fragments.\n"
        "- Merge similar requests.\n"
        "- Sort by count descending.\n\n"
        f"Suggestion summaries:\n{numbered}\n\n"
        'Reply ONLY as JSON: {"features": [{"feature": "...", "count": N}, ...]}'
    )

    features_raw = []
    try:
        response = _groq.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        import json
        data = json.loads(response.choices[0].message.content)
        features_raw = data.get("features", [])
    except RateLimitError:
        logger.warning("Groq rate limit hit during feature extraction.")
    except Exception as exc:
        logger.warning("Feature extraction failed: %s", exc)

    # Fallback: use full summary sentences
    if not features_raw:
        counter: Counter = Counter(s.strip() for s in summaries if len(s.strip()) > 5)
        features_raw = [
            {"feature": k.title(), "count": v}
            for k, v in counter.most_common(top_n)
        ]

    results = []
    for rank, item in enumerate(features_raw[:top_n], start=1):
        title   = str(item.get("feature", "")).strip()
        count   = int(item.get("count", 1))
        req_pct = round(count / total_suggestions * 100, 1)
        p_score = round(min(count / total_suggestions * 100 * 2, 100), 1)
        if title:
            results.append({
                "rank":           rank,
                "feature":        title,
                "requests":       count,
                "requestPercent": req_pct,
                "priorityScore":  p_score,
            })

    return results


# ---------------------------------------------------------------------------
# 4. LLM-assisted issue clustering  (one Groq call for all top issues)
# ---------------------------------------------------------------------------

def cluster_issues_with_llm(issues: list[str]) -> dict[str, str]:
    """
    Send the list of top issue phrases to Groq and ask it to group them
    into human-readable cluster names.

    Returns a mapping: {original_phrase → cluster_name}
    Falls back to identity mapping on any failure.
    """
    if not issues:
        return {}

    issue_list = "\n".join(f"- {issue}" for issue in issues)
    prompt = (
        "You are a product analyst. Group the following app issue phrases into "
        "concise cluster names (e.g. 'Payment Failure', 'Login Error', 'OTP Issue').\n\n"
        "Rules:\n"
        "1. Merge semantically similar phrases into one cluster.\n"
        "2. Use short, business-friendly cluster names (2–4 words).\n"
        "3. Reply ONLY as a JSON object mapping each original phrase to its cluster name.\n"
        "4. Every input phrase must appear as a key.\n\n"
        f"Phrases:\n{issue_list}\n\n"
        "Reply with ONLY the JSON object."
    )

    try:
        response = _groq.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=800,
            response_format={"type": "json_object"},
        )
        import json
        raw = response.choices[0].message.content.strip()
        mapping = json.loads(raw)
        # Ensure all keys exist
        return {issue: mapping.get(issue, issue) for issue in issues}
    except RateLimitError:
        logger.warning("Groq rate limit hit during clustering. Using identity mapping.")
    except Exception as exc:
        logger.warning("Clustering LLM call failed: %s. Using identity mapping.", exc)

    return {issue: issue for issue in issues}


# ---------------------------------------------------------------------------
# 5. Priority score calculation
# ---------------------------------------------------------------------------

def calculate_priority_score(
    impact_pct:      float,   # % of total reviews affected
    growth_percent:  float,   # period-over-period growth %
    severity:        str,     # Critical / High / Medium / Low
    negative_pct:    float,   # % negative sentiment for this issue
    weights: Optional[dict[str, float]] = None,
) -> float:
    """
    Weighted priority score in range 0–100.

    Default weights: impact=40%, growth=30%, severity=20%, sentiment=10%
    All inputs are normalised to 0–100 before weighting.
    """
    w = weights or DEFAULT_WEIGHTS

    # Normalise each dimension to 0–100
    impact_score    = min(impact_pct * 2, 100.0)          # 50% affected = 100 pts
    growth_score    = min(max(growth_percent, 0) / 3, 100.0)  # 300% growth = 100 pts
    severity_score  = _severity_score(severity)
    sentiment_score = negative_pct                         # already 0–100

    score = (
        w.get("impact",    0.40) * impact_score    +
        w.get("growth",    0.30) * growth_score    +
        w.get("severity",  0.20) * severity_score  +
        w.get("sentiment", 0.10) * sentiment_score
    )
    return round(min(score, 100.0), 1)


# ---------------------------------------------------------------------------
# 6. Full ranked issue list
# ---------------------------------------------------------------------------

async def get_ranked_issues(
    period:       str,
    package_name: Optional[str],
    top_n:        int,
    weights:      dict[str, float],
) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    """
    Build a fully scored and ranked list of ACTIONABLE issues for the given period.
    Positive feedback is excluded at the extraction level.

    Returns (ranked_issues, total_review_count, positive_highlights).
    """
    days      = _period_to_days(period)
    now       = datetime.now(timezone.utc).replace(tzinfo=None)
    curr_end  = now
    curr_start= now - timedelta(days=days)
    prev_end  = curr_start
    prev_start= prev_end - timedelta(days=days)

    # ── Step 1: get issues + highlights + total count in parallel ─────────
    issues_result, total = await asyncio.gather(
        get_top_issues_and_highlights(curr_start, curr_end, package_name, top_n=top_n * 2),
        get_total_count(curr_start, curr_end, package_name),
    )

    raw_issues         = issues_result.get("issues", [])
    positive_highlights= issues_result.get("positiveHighlights", [])

    # Extra guard: remove any positive items that slipped through
    raw_issues = [i for i in raw_issues if not _is_positive_phrase(i["issue"])]

    if not raw_issues or total == 0:
        return [], total, positive_highlights

    # ── Step 2: LLM clustering (one call) ─────────────────────────────────
    issue_names = [item["issue"] for item in raw_issues]
    cluster_map = cluster_issues_with_llm(issue_names)

    # ── Step 3: per-issue growth + sentiment (parallelised) ───────────────
    growth_tasks = [
        _get_issue_growth(
            item["issue"], curr_start, curr_end,
            prev_start, prev_end, package_name,
        )
        for item in raw_issues
    ]
    sentiment_tasks = [
        _get_issue_sentiment(item["issue"], curr_start, curr_end, package_name)
        for item in raw_issues
    ]

    growth_results, sentiment_results = await asyncio.gather(
        asyncio.gather(*growth_tasks),
        asyncio.gather(*sentiment_tasks),
    )

    # ── Step 4: score every issue ─────────────────────────────────────────
    scored: list[dict[str, Any]] = []
    for item, (curr_cnt, prev_cnt, growth_pct), sent in zip(
        raw_issues, growth_results, sentiment_results
    ):
        issue        = item["issue"]
        cluster      = cluster_map.get(issue, issue)
        affected_pct = round(curr_cnt / total * 100, 1)
        neg_pct      = sent["negativePct"]
        severity     = _assign_severity(issue, growth_pct, neg_pct)

        p_score = calculate_priority_score(
            impact_pct    = affected_pct,
            growth_percent= growth_pct,
            severity      = severity,
            negative_pct  = neg_pct,
            weights       = weights,
        )

        scored.append({
            "issue":            issue,
            "cluster":          cluster,
            "severity":         severity,
            "priorityScore":    p_score,
            "affectedUsers":    curr_cnt,
            "affectedPercent":  affected_pct,
            "currentCount":     curr_cnt,
            "previousCount":    prev_cnt,
            "growthPercent":    growth_pct,
            "dominantSentiment":sent["dominantSentiment"],
            "feedbackType":     sent["feedbackType"],
        })

    # ── Step 5: sort and rank ─────────────────────────────────────────────
    scored.sort(key=lambda x: x["priorityScore"], reverse=True)
    for rank, item in enumerate(scored[:top_n], start=1):
        item["rank"] = rank

    return scored[:top_n], total, positive_highlights


# ---------------------------------------------------------------------------
# 7. Groq-powered recommendations  (one call, pre-aggregated data only)
# ---------------------------------------------------------------------------

def generate_recommendations(
    ranked_issues:   list[dict[str, Any]],
    ranked_features: list[dict[str, Any]],
    period:          str,
) -> tuple[list[dict[str, Any]], str]:
    """
    Ask Groq to generate structured recommendations and an executive summary.
    Returns (recommendations_list, executive_summary_string).
    Falls back to rule-based output if Groq is unavailable.
    """
    issue_lines   = "\n".join(
        f"  {i['rank']}. {i['issue']} | score={i['priorityScore']} "
        f"severity={i['severity']} growth={i['growthPercent']}% "
        f"affected={i['affectedPercent']}%"
        for i in ranked_issues[:5]
    )
    feature_lines = "\n".join(
        f"  {f['rank']}. {f['feature']} | requests={f['requests']} score={f['priorityScore']}"
        for f in ranked_features[:3]
    )

    prompt = (
        f"You are a senior product manager reviewing app store feedback intelligence.\n"
        f"Period: last {period}\n\n"
        f"Top priority issues:\n{issue_lines}\n\n"
        f"Top feature requests:\n{feature_lines}\n\n"
        f"Generate:\n"
        f"1. A JSON array called 'recommendations' with objects:\n"
        f'   {{"issue":"...","action":"...","urgency":"Immediate|Soon|Monitor|Backlog","reason":"..."}}\n'
        f"   One entry per issue/feature (max 8 total).\n"
        f"2. A key 'executiveSummary' with a 3-4 sentence plain-English business summary.\n\n"
        f"Reply ONLY as a JSON object with keys 'recommendations' and 'executiveSummary'."
    )

    try:
        response = _groq.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=900,
            response_format={"type": "json_object"},
        )
        import json
        data = json.loads(response.choices[0].message.content)
        recs    = data.get("recommendations", [])
        summary = data.get("executiveSummary", "")
        return recs, summary
    except RateLimitError:
        logger.warning("Groq rate limit hit during recommendations generation.")
    except Exception as exc:
        logger.error("Recommendations generation failed: %s", exc)

    return _fallback_recommendations(ranked_issues, ranked_features), _fallback_summary(ranked_issues, period)


def _fallback_recommendations(
    issues:   list[dict],
    features: list[dict],
) -> list[dict]:
    recs = []
    urgency_map = {"Critical": "Immediate", "High": "Soon", "Medium": "Monitor", "Low": "Backlog"}
    for i in issues[:5]:
        recs.append({
            "issue":   i["issue"],
            "action":  f"Investigate and resolve {i['issue']}",
            "urgency": urgency_map.get(i["severity"], "Monitor"),
            "reason":  f"Affects {i['affectedPercent']}% of users with {i['growthPercent']}% growth.",
        })
    for f in features[:3]:
        recs.append({
            "issue":   f["feature"],
            "action":  f"Evaluate {f['feature']} for roadmap",
            "urgency": "Backlog",
            "reason":  f"Requested by {f['requests']} users.",
        })
    return recs


def _fallback_summary(issues: list[dict], period: str) -> str:
    top = issues[0]["issue"] if issues else "various issues"
    return (
        f"Over the last {period}, '{top}' is the highest-priority issue "
        f"requiring immediate attention. Review the ranked issue list for "
        f"a complete action plan."
    )


# ---------------------------------------------------------------------------
# 8. Cache priority report
# ---------------------------------------------------------------------------

async def cache_priority_report(report: dict[str, Any]) -> None:
    try:
        collection = get_db()["priority_reports"]
        key = {
            "packageName": report.get("packageName"),
            "period":      report.get("period"),
        }
        report["cachedAt"] = datetime.utcnow().isoformat()
        await collection.update_one(key, {"$set": report}, upsert=True)
    except Exception as exc:
        logger.warning("Failed to cache priority report: %s", exc)


async def get_cached_priority_report(
    package_name:      Optional[str],
    period:            str,
    max_age_minutes:   int = 30,
) -> Optional[dict[str, Any]]:
    try:
        collection = get_db()["priority_reports"]
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
        logger.warning("Priority cache lookup failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 9. Master report builder
# ---------------------------------------------------------------------------

async def build_priority_report(
    period:       str,
    package_name: Optional[str],
    top_n:        int,
    weights:      dict[str, float],
) -> dict[str, Any]:
    """Orchestrate all Model 3 functions and return the complete priority report dict."""
    days      = _period_to_days(period)
    now       = datetime.now(timezone.utc).replace(tzinfo=None)
    curr_end  = now
    curr_start= now - timedelta(days=days)

    # ── Ranked issues + highlights + total ────────────────────────────────
    ranked_issues, total, positive_highlights = await get_ranked_issues(
        period, package_name, top_n, weights
    )

    # ── Feature requests ──────────────────────────────────────────────────
    ranked_features = await get_feature_requests(
        curr_start, curr_end, package_name, total or 1, top_n=10
    )

    # ── AI recommendations + executive summary ────────────────────────────
    recs, exec_summary = generate_recommendations(ranked_issues, ranked_features, period)

    return {
        "packageName":        package_name,
        "period":             period,
        "totalReviews":       total,
        "generatedAt":        datetime.utcnow().isoformat(),
        "topPriorityIssues":  ranked_issues,
        "topFeatureRequests": ranked_features,
        "positiveHighlights": positive_highlights,
        "recommendations":    recs,
        "executiveSummary":   exec_summary,
    }

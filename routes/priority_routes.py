"""
Priority Routes – Model 3: Priority Intelligence Engine
Exposes actionable decision-making endpoints built on Model 1 + Model 2 output.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from models.priority_model import (
    FeatureRankingResponse,
    IssueRankingResponse,
    PriorityReport,
    PriorityRequest,
    RankedFeature,
    RankedIssue,
    Recommendation,
)
from services.priority_service import (
    DEFAULT_WEIGHTS,
    build_priority_report,
    cache_priority_report,
    get_cached_priority_report,
    get_feature_requests,
    get_ranked_issues,
)
from services.trend_service import _period_to_days, _date_range

from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Priorities"])


# ---------------------------------------------------------------------------
# Shared weight builder
# ---------------------------------------------------------------------------

def _build_weights(req: PriorityRequest) -> dict[str, float]:
    """
    Extract scoring weights from the request, normalising them so they sum to 1.
    If weights don't sum to 1, they are proportionally rescaled.
    """
    raw = {
        "impact":    req.weightImpact    or DEFAULT_WEIGHTS["impact"],
        "growth":    req.weightGrowth    or DEFAULT_WEIGHTS["growth"],
        "severity":  req.weightSeverity  or DEFAULT_WEIGHTS["severity"],
        "sentiment": req.weightSentiment or DEFAULT_WEIGHTS["sentiment"],
    }
    total = sum(raw.values())
    if total == 0:
        return DEFAULT_WEIGHTS.copy()
    return {k: round(v / total, 4) for k, v in raw.items()}


# ---------------------------------------------------------------------------
# POST /api/priorities  –  Full priority report
# ---------------------------------------------------------------------------

@router.post(
    "/priorities",
    response_model=PriorityReport,
    summary="Generate a complete priority intelligence report",
    status_code=status.HTTP_200_OK,
)
async def get_priorities(body: PriorityRequest):
    """
    Runs the full Model 3 pipeline:

    1. Extracts top issues from review summaries (MongoDB aggregation)
    2. Groups similar issues into clusters (Groq LLM – one call)
    3. Calculates impact, growth, severity, and priority score per issue
    4. Extracts and ranks feature requests
    5. Generates AI recommendations and executive summary (Groq – one call)
    6. Caches and returns the complete priority report

    Reports are cached for 30 minutes. Use the same request to get a
    cached result instantly on repeat calls.
    """
    period       = body.period or "30d"
    package_name = body.packageName
    top_n        = body.topN or 10
    weights      = _build_weights(body)

    # ── Cache check ────────────────────────────────────────────────────────
    cached = await get_cached_priority_report(package_name, period)
    if cached:
        logger.info("Returning cached priority report for %s / %s", package_name, period)
        return _deserialise_report(cached)

    # ── Build fresh report ─────────────────────────────────────────────────
    try:
        report_dict = await build_priority_report(period, package_name, top_n, weights)
    except Exception as exc:
        logger.error("Priority report generation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Priority analysis failed: {exc}",
        )

    if report_dict["totalReviews"] == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No reviews found for the selected period and package.",
        )

    # ── Cache it ───────────────────────────────────────────────────────────
    await cache_priority_report(report_dict)

    return _deserialise_report(report_dict)


# ---------------------------------------------------------------------------
# GET /api/priorities/issues  –  Ranked issue list only
# ---------------------------------------------------------------------------

@router.get(
    "/priorities/issues",
    response_model=IssueRankingResponse,
    summary="Get ranked priority issues",
    status_code=status.HTTP_200_OK,
)
async def get_issue_ranking(
    period:      str           = Query(default="30d", description="7d | 30d | 90d"),
    packageName: Optional[str] = Query(default=None),
    topN:        int           = Query(default=10, ge=1, le=50),
):
    """
    Returns only the ranked issue list without AI recommendations.
    Faster than the full report — useful for dashboards that need just the ranking.
    """
    ranked, _ = await get_ranked_issues(
        period, packageName, topN, DEFAULT_WEIGHTS
    )

    if not ranked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No issues found for the selected period.",
        )

    return IssueRankingResponse(
        packageName=packageName,
        period=period,
        issues=[RankedIssue(**i) for i in ranked],
    )


# ---------------------------------------------------------------------------
# GET /api/priorities/features  –  Ranked feature requests only
# ---------------------------------------------------------------------------

@router.get(
    "/priorities/features",
    response_model=FeatureRankingResponse,
    summary="Get ranked feature requests",
    status_code=status.HTTP_200_OK,
)
async def get_feature_ranking(
    period:      str           = Query(default="30d", description="7d | 30d | 90d"),
    packageName: Optional[str] = Query(default=None),
    topN:        int           = Query(default=10, ge=1, le=50),
):
    """
    Returns only the ranked feature requests extracted from Suggestion reviews.
    """
    days      = _period_to_days(period)
    now       = datetime.now(timezone.utc).replace(tzinfo=None)
    curr_end  = now
    curr_start= now - timedelta(days=days)

    from services.trend_service import get_total_count
    total = await get_total_count(curr_start, curr_end, packageName)

    features = await get_feature_requests(
        curr_start, curr_end, packageName, total or 1, top_n=topN
    )

    if not features:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No feature requests found for the selected period.",
        )

    return FeatureRankingResponse(
        packageName=packageName,
        period=period,
        features=[RankedFeature(**f) for f in features],
    )


# ---------------------------------------------------------------------------
# GET /api/priorities/report  –  Full executive report (cached-first)
# ---------------------------------------------------------------------------

@router.get(
    "/priorities/report",
    response_model=PriorityReport,
    summary="Get or generate the full AI-powered executive priority report",
    status_code=status.HTTP_200_OK,
)
async def get_executive_report(
    period:      str           = Query(default="30d", description="7d | 30d | 90d"),
    packageName: Optional[str] = Query(default=None),
    topN:        int           = Query(default=10, ge=1, le=50),
):
    """
    Returns the complete priority report including:
    - Ranked issues with severity, impact, and growth
    - Ranked feature requests
    - AI-generated recommendations with urgency levels
    - Executive summary

    Hits the cache first (30 min TTL). Generates fresh if no cache exists.
    """
    # Try cache first
    cached = await get_cached_priority_report(packageName, period)
    if cached:
        logger.info("Returning cached executive report for %s / %s", packageName, period)
        return _deserialise_report(cached)

    # Generate fresh
    try:
        report_dict = await build_priority_report(
            period, packageName, topN, DEFAULT_WEIGHTS
        )
    except Exception as exc:
        logger.error("Executive report generation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Report generation failed: {exc}",
        )

    if report_dict["totalReviews"] == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No reviews found for the selected period and package.",
        )

    await cache_priority_report(report_dict)
    return _deserialise_report(report_dict)


# ---------------------------------------------------------------------------
# Helper – deserialise cached dict → Pydantic model
# ---------------------------------------------------------------------------

def _deserialise_report(d: dict) -> PriorityReport:
    """Convert a raw dict (from MongoDB cache or fresh build) to PriorityReport."""
    return PriorityReport(
        packageName     = d.get("packageName"),
        period          = d.get("period", "30d"),
        totalReviews    = d.get("totalReviews", 0),
        generatedAt     = d.get("generatedAt", ""),
        topPriorityIssues = [
            RankedIssue(**i) for i in d.get("topPriorityIssues", [])
        ],
        topFeatureRequests = [
            RankedFeature(**f) for f in d.get("topFeatureRequests", [])
        ],
        recommendations = [
            Recommendation(**r) for r in d.get("recommendations", [])
        ],
        executiveSummary = d.get("executiveSummary", ""),
    )

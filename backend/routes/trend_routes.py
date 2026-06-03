"""
Trend Routes – Model 2: Trend Analysis Engine
API endpoints that expose trend intelligence built on top of Model 1 output.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from models.trend_model import (
    CompareRequest,
    CompareResponse,
    EmergingIssue,
    EmergingIssuesResponse,
    FeedbackTypeCounts,
    PeriodComparison,
    SentimentChange,
    SentimentTrend,
    TopIssue,
    TrendRequest,
    TrendResponse,
)
from services.trend_service import (
    _date_range,
    _previous_range,
    _period_to_days,
    cache_trend_report,
    compare_periods,
    generate_trend_summary,
    get_cached_report,
    get_emerging_issues,
    get_feedback_type_counts,
    get_sentiment_counts,
    get_top_issues,
    get_total_count,
    _to_percentages,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Trends"])


# ---------------------------------------------------------------------------
# POST /api/trends   –  Main trend dashboard
# ---------------------------------------------------------------------------

@router.post(
    "/trends",
    response_model=TrendResponse,
    summary="Get trend intelligence for a time period",
    status_code=status.HTTP_200_OK,
)
async def get_trends(body: TrendRequest):
    """
    Returns a full trend report for the selected period including:
    - Sentiment breakdown with period-over-period change
    - Feedback type counts
    - Top issues (keyword frequency on review summaries)
    - AI-generated executive trend summary

    Results are cached for 30 minutes in MongoDB to avoid re-computation.
    """
    period_label = body.period or "30d"

    # ── Cache check ────────────────────────────────────────────────────────
    if not body.startDate and not body.endDate:
        cached = await get_cached_report(body.packageName, period_label)
        if cached:
            logger.info("Returning cached trend report for %s / %s", body.packageName, period_label)
            return cached

    # ── Date ranges ────────────────────────────────────────────────────────
    start, end = _date_range(body.period, body.startDate, body.endDate)
    prev_start, prev_end = _previous_range(start, end)

    # ── Aggregations (all hit MongoDB, no raw review loading) ──────────────
    import asyncio
    total, curr_sentiment, prev_sentiment, feedback_counts, top_issues = (
        await asyncio.gather(
            get_total_count(start, end, body.packageName),
            get_sentiment_counts(start, end, body.packageName),
            get_sentiment_counts(prev_start, prev_end, body.packageName),
            get_feedback_type_counts(start, end, body.packageName),
            get_top_issues(start, end, body.packageName, top_n=10),
        )
    )

    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No reviews found for the selected period and package.",
        )

    # ── Sentiment percentages + change ─────────────────────────────────────
    curr_pct = _to_percentages(curr_sentiment)
    prev_pct = _to_percentages(prev_sentiment)

    sentiment_change = SentimentChange(
        positive=round(curr_pct["Positive"] - prev_pct["Positive"], 1),
        negative=round(curr_pct["Negative"] - prev_pct["Negative"], 1),
        neutral=round(curr_pct["Neutral"]  - prev_pct["Neutral"],  1),
    )

    sentiment = SentimentTrend(
        positive=curr_pct["Positive"],
        negative=curr_pct["Negative"],
        neutral=curr_pct["Neutral"],
        change=sentiment_change,
    )

    # ── AI trend summary (one Groq call per report) ────────────────────────
    summary = generate_trend_summary(
        total=total,
        sentiment_pct=curr_pct,
        sentiment_change={
            "positive": sentiment_change.positive,
            "negative": sentiment_change.negative,
            "neutral":  sentiment_change.neutral,
        },
        top_issues=top_issues,
        feedback_counts=feedback_counts,
        period=period_label,
    )

    # ── Build response ─────────────────────────────────────────────────────
    response = TrendResponse(
        packageName=body.packageName,
        period=period_label,
        totalReviews=total,
        sentiment=sentiment,
        feedbackTypes=FeedbackTypeCounts(**feedback_counts),
        topIssues=[TopIssue(**item) for item in top_issues],
        trendSummary=summary,
    )

    # ── Cache the result ───────────────────────────────────────────────────
    if not body.startDate and not body.endDate:
        await cache_trend_report(response.model_dump())

    return response


# ---------------------------------------------------------------------------
# GET /api/trends/emerging  –  Emerging issue detection
# ---------------------------------------------------------------------------

@router.get(
    "/trends/emerging",
    response_model=EmergingIssuesResponse,
    summary="Detect emerging and declining issues",
    status_code=status.HTTP_200_OK,
)
async def get_emerging(
    period: str = Query(default="30d", description="7d | 30d | 90d"),
    packageName: Optional[str] = Query(default=None, description="Filter by package name"),
):
    """
    Splits the selected period into two equal halves and identifies issues
    that are growing (Emerging) or shrinking (Declining) in the recent half.

    Useful for catching new bugs or complaints before they become widespread.
    """
    issues = await get_emerging_issues(
        period=period,
        package_name=packageName,
    )

    return EmergingIssuesResponse(
        packageName=packageName,
        period=period,
        issues=[EmergingIssue(**item) for item in issues],
    )


# ---------------------------------------------------------------------------
# POST /api/trends/compare  –  Period comparison
# ---------------------------------------------------------------------------

@router.post(
    "/trends/compare",
    response_model=CompareResponse,
    summary="Compare sentiment and feedback types across two periods",
    status_code=status.HTTP_200_OK,
)
async def compare_trend_periods(body: CompareRequest):
    """
    Compares the current period against the previous equivalent period.

    Returns:
    - Percentage-point sentiment changes
    - Absolute and % changes per feedback type
    - Plain-English sentiment shift description
    """
    # Parse current period
    days = _period_to_days(body.currentPeriod)
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    curr_end  = now
    curr_start= now - timedelta(days=days)

    # Parse compare period
    compare_days_str = body.compareWith.replace("previous_", "")
    compare_days  = _period_to_days(compare_days_str)
    prev_end      = curr_start
    prev_start    = prev_end - timedelta(days=compare_days)

    result = await compare_periods(
        current_start=curr_start,
        current_end=curr_end,
        prev_start=prev_start,
        prev_end=prev_end,
        package_name=body.packageName,
    )

    sc = result["sentimentChanges"]
    fb_raw = result["feedbackTypeChanges"]

    return CompareResponse(
        packageName=body.packageName,
        currentPeriod=body.currentPeriod,
        comparePeriod=body.compareWith,
        sentimentChanges=SentimentChange(
            positive=sc["positive"],
            negative=sc["negative"],
            neutral=sc["neutral"],
        ),
        feedbackTypeChanges={
            k: PeriodComparison(**v) for k, v in fb_raw.items()
        },
        overallSentimentShift=result["overallSentimentShift"],
    )

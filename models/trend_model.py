"""
Pydantic models for Model 2 – Trend Analysis Engine.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared period type
# ---------------------------------------------------------------------------

PeriodStr = Literal["7d", "30d", "90d"]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class TrendRequest(BaseModel):
    """Request body for POST /api/trends"""

    period: Optional[PeriodStr] = Field(
        default="30d",
        description="Time window: 7d | 30d | 90d",
    )
    packageName: Optional[str] = Field(
        default=None,
        description="Filter by app package name. Omit to analyse all apps.",
    )
    startDate: Optional[str] = Field(
        default=None,
        description="Custom range start date (ISO-8601). Overrides period.",
    )
    endDate: Optional[str] = Field(
        default=None,
        description="Custom range end date (ISO-8601). Overrides period.",
    )


class CompareRequest(BaseModel):
    """Request body for POST /api/trends/compare"""

    currentPeriod: PeriodStr = Field(default="30d")
    compareWith: Literal["previous_7d", "previous_30d", "previous_90d"] = Field(
        default="previous_30d"
    )
    packageName: Optional[str] = Field(default=None)


# ---------------------------------------------------------------------------
# Response sub-models
# ---------------------------------------------------------------------------


class SentimentChange(BaseModel):
    positive: float
    negative: float
    neutral: float


class SentimentTrend(BaseModel):
    positive: float = Field(description="% of reviews that are Positive")
    negative: float = Field(description="% of reviews that are Negative")
    neutral: float = Field(description="% of reviews that are Neutral")
    change: Optional[SentimentChange] = Field(
        default=None,
        description="Percentage-point change vs previous equivalent period",
    )


class FeedbackTypeCounts(BaseModel):
    bugReports: int = 0
    complaints: int = 0
    suggestions: int = 0
    positiveFeedback: int = 0
    generalFeedback: int = 0


class TopIssue(BaseModel):
    issue: str
    count: int


class EmergingIssue(BaseModel):
    issue: str
    trend: Literal["Emerging", "Stable", "Declining"] = "Emerging"
    recentCount: int = 0
    previousCount: int = 0


class PeriodComparison(BaseModel):
    metric: str
    current: int
    previous: int
    changePercent: float


# ---------------------------------------------------------------------------
# Top-level response models
# ---------------------------------------------------------------------------


class TrendResponse(BaseModel):
    packageName: Optional[str]
    period: str
    totalReviews: int
    sentiment: SentimentTrend
    feedbackTypes: FeedbackTypeCounts
    topIssues: list[TopIssue]
    trendSummary: str


class EmergingIssuesResponse(BaseModel):
    packageName: Optional[str]
    period: str
    issues: list[EmergingIssue]


class CompareResponse(BaseModel):
    packageName: Optional[str]
    currentPeriod: str
    comparePeriod: str
    sentimentChanges: SentimentChange
    feedbackTypeChanges: dict[str, PeriodComparison]
    overallSentimentShift: str

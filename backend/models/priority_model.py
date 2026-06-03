"""
Pydantic models for Model 3 – Priority Intelligence Engine.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------

SeverityLevel = Literal["Critical", "High", "Medium", "Low"]
PeriodStr     = Literal["7d", "30d", "90d"]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class PriorityRequest(BaseModel):
    """Request body for POST /api/priorities"""

    period: Optional[PeriodStr] = Field(
        default="30d",
        description="Time window: 7d | 30d | 90d",
    )
    packageName: Optional[str] = Field(
        default=None,
        description="Filter by Google Play package name.",
    )
    topN: Optional[int] = Field(
        default=10,
        ge=1,
        le=50,
        description="Number of top issues/features to return.",
    )
    # Configurable scoring weights (must sum to 1.0 — validated in service)
    weightImpact: Optional[float]   = Field(default=0.40, ge=0.0, le=1.0)
    weightGrowth: Optional[float]   = Field(default=0.30, ge=0.0, le=1.0)
    weightSeverity: Optional[float] = Field(default=0.20, ge=0.0, le=1.0)
    weightSentiment: Optional[float]= Field(default=0.10, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Issue cluster
# ---------------------------------------------------------------------------


class IssueCluster(BaseModel):
    """A group of semantically similar review summaries."""
    cluster: str
    representativePhrases: list[str] = Field(
        default_factory=list,
        description="Top phrases that belong to this cluster.",
    )
    count: int


# ---------------------------------------------------------------------------
# Scored & ranked issue
# ---------------------------------------------------------------------------


class RankedIssue(BaseModel):
    rank: int
    issue: str
    cluster: Optional[str] = None
    severity: SeverityLevel
    priorityScore: float = Field(..., ge=0.0, le=100.0)
    affectedUsers: int
    affectedPercent: float
    currentCount: int
    previousCount: int
    growthPercent: float
    dominantSentiment: str
    feedbackType: str


# ---------------------------------------------------------------------------
# Feature request
# ---------------------------------------------------------------------------


class RankedFeature(BaseModel):
    rank: int
    feature: str
    requests: int
    requestPercent: float
    priorityScore: float = Field(..., ge=0.0, le=100.0)


# ---------------------------------------------------------------------------
# AI recommendation
# ---------------------------------------------------------------------------


class Recommendation(BaseModel):
    issue: str
    action: str
    urgency: Literal["Immediate", "Soon", "Monitor", "Backlog"]
    reason: str


class PositiveHighlight(BaseModel):
    highlight: str
    count: int


# ---------------------------------------------------------------------------
# Full priority report
# ---------------------------------------------------------------------------


class PriorityReport(BaseModel):
    packageName: Optional[str]
    period: str
    totalReviews: int
    generatedAt: str
    topPriorityIssues: list[RankedIssue]
    topFeatureRequests: list[RankedFeature]
    positiveHighlights: list[PositiveHighlight] = []
    recommendations: list[Recommendation]
    executiveSummary: str


# ---------------------------------------------------------------------------
# Lightweight response models for individual endpoints
# ---------------------------------------------------------------------------


class IssueRankingResponse(BaseModel):
    packageName: Optional[str]
    period: str
    issues: list[RankedIssue]


class FeatureRankingResponse(BaseModel):
    packageName: Optional[str]
    period: str
    features: list[RankedFeature]

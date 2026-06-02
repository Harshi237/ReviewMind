"""
Pydantic models for Review Mind AI – Model 1.
These models define the shape of requests, responses, and MongoDB documents.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations (as Literal types for strict validation)
# ---------------------------------------------------------------------------

SentimentType = Literal["Positive", "Negative", "Neutral"]

FeedbackType = Literal[
    "Bug Report",
    "Complaint",
    "Suggestion",
    "Positive Feedback",
    "General Feedback",
]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class TestReviewRequest(BaseModel):
    """Request body for POST /api/test-review"""

    review: str = Field(..., min_length=1, description="Raw review text to analyse")


class AnalyzeAppRequest(BaseModel):
    """Request body for POST /api/analyze-app"""

    packageName: str = Field(
        ...,
        min_length=3,
        description="Google Play package name, e.g. com.spotify.music",
    )
    maxReviews: Optional[int] = Field(
        default=200,
        ge=1,
        le=5000,
        description="Maximum number of reviews to fetch (default 200)",
    )


# ---------------------------------------------------------------------------
# AI output model (what Gemini must return per review)
# ---------------------------------------------------------------------------


class ReviewIntelligence(BaseModel):
    """Structured intelligence extracted by Model 1 for a single review."""

    sentiment: SentimentType
    feedbackType: FeedbackType
    summary: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Full review document (stored in MongoDB)
# ---------------------------------------------------------------------------


class ReviewDocument(BaseModel):
    """Complete review record stored in the database."""

    reviewId: str
    packageName: str
    review: str
    score: int = Field(..., ge=1, le=5)
    date: str
    sentiment: SentimentType
    feedbackType: FeedbackType
    summary: str
    analysedAt: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class TestReviewResponse(BaseModel):
    sentiment: SentimentType
    feedbackType: FeedbackType
    summary: str


class AnalyzeAppResponse(BaseModel):
    packageName: str
    totalFetched: int
    totalAnalysed: int
    totalStored: int
    reviews: list[ReviewDocument]

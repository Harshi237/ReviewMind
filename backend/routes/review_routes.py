"""
Review Routes – API endpoints for Review Mind AI Model 1.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from models.review_model import (
    AnalyzeAppRequest,
    AnalyzeAppResponse,
    ReviewDocument,
    TestReviewRequest,
    TestReviewResponse,
)
from services.ai_service import analyse_single_review
from services.batch_service import process_and_store
from services.scraper_service import fetch_reviews

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Reviews"])


# ---------------------------------------------------------------------------
# POST /api/test-review
# ---------------------------------------------------------------------------


@router.post(
    "/test-review",
    response_model=TestReviewResponse,
    summary="Test Model 1 with a single review",
    status_code=status.HTTP_200_OK,
)
async def test_review(body: TestReviewRequest):
    """
    Analyse a single review text with Model 1.

    Use this endpoint to verify that the AI integration is working correctly
    before connecting it to live Google Play reviews.
    """
    result = analyse_single_review(body.review)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="AI analysis failed. The review could not be processed.",
        )

    return TestReviewResponse(**result)


# ---------------------------------------------------------------------------
# POST /api/analyze-app
# ---------------------------------------------------------------------------


@router.post(
    "/analyze-app",
    response_model=AnalyzeAppResponse,
    summary="Fetch, analyse, and store reviews for a Google Play app",
    status_code=status.HTTP_200_OK,
)
async def analyze_app(body: AnalyzeAppRequest):
    """
    Full pipeline for a given package name:

    1. Fetch reviews from Google Play Store.
    2. Analyse each review with Model 1 (batched).
    3. Store results in MongoDB.
    4. Return structured review intelligence.
    """
    package_name = body.packageName.strip()
    max_reviews = body.maxReviews or 200

    # ── Step 1: Fetch reviews ──────────────────────────────────────────────
    logger.info("Fetching reviews for '%s' (max=%d)…", package_name, max_reviews)
    try:
        raw_reviews = fetch_reviews(package_name, max_reviews=max_reviews)
    except Exception as exc:
        logger.error("Scraper failed for '%s': %s", package_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch reviews for '{package_name}': {exc}",
        )

    if not raw_reviews:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No reviews found for package '{package_name}'. "
                   "Check the package name and try again.",
        )

    total_fetched = len(raw_reviews)
    logger.info("Fetched %d reviews. Starting analysis…", total_fetched)

    # ── Step 2 & 3: Analyse + Store ────────────────────────────────────────
    try:
        analysed = await process_and_store(package_name, raw_reviews)
    except Exception as exc:
        logger.error("Batch processing failed for '%s': %s", package_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Review analysis failed: {exc}",
        )

    # ── Step 4: Build response ─────────────────────────────────────────────
    review_docs = [
        ReviewDocument(
            reviewId=r.get("reviewId", ""),
            packageName=package_name,
            review=r.get("review", ""),
            score=r.get("score", 0),
            date=r.get("date", ""),
            sentiment=r["sentiment"],
            feedbackType=r["feedbackType"],
            summary=r["summary"],
        )
        for r in analysed
    ]

    return AnalyzeAppResponse(
        packageName=package_name,
        totalFetched=total_fetched,
        totalAnalysed=len(analysed),
        totalStored=len(analysed),
        reviews=review_docs,
    )

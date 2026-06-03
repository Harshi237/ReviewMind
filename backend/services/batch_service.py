"""
Batch Service
Orchestrates chunked processing of reviews through the AI service
and persists results to MongoDB.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from database.mongo import get_reviews_collection
from services.ai_service import analyse_reviews_batch

logger = logging.getLogger(__name__)

# Number of reviews sent to the AI service per chunk
_BATCH_SIZE = int(os.getenv("BATCH_SIZE", 10))


async def process_and_store(
    package_name: str,
    reviews: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Split *reviews* into batches, analyse each batch with Gemini,
    upsert results into MongoDB, and return all analysed documents.

    Args:
        package_name: The Google Play package identifier.
        reviews:      Normalised review dicts from the scraper service.

    Returns:
        List of fully enriched review documents that were stored.
    """
    if not reviews:
        logger.warning("process_and_store called with empty review list.")
        return []

    all_analysed: list[dict[str, Any]] = []
    total = len(reviews)
    batches = _chunk(reviews, _BATCH_SIZE)

    logger.info(
        "Starting batch processing: %d reviews in %d batches (size=%d) for '%s'",
        total,
        len(batches),
        _BATCH_SIZE,
        package_name,
    )

    for batch_idx, batch in enumerate(batches, start=1):
        logger.info(
            "Processing batch %d/%d (%d reviews)…",
            batch_idx,
            len(batches),
            len(batch),
        )

        # Run the synchronous Gemini calls in a thread pool so we don't
        # block the FastAPI event loop.
        analysed = await asyncio.get_event_loop().run_in_executor(
            None, analyse_reviews_batch, batch
        )

        if analysed:
            await _upsert_reviews(package_name, analysed)
            all_analysed.extend(analysed)

        # Small courtesy delay between batches to respect rate limits
        if batch_idx < len(batches):
            await asyncio.sleep(1)

    logger.info(
        "Batch processing complete: %d/%d reviews stored for '%s'.",
        len(all_analysed),
        total,
        package_name,
    )
    return all_analysed


async def _upsert_reviews(
    package_name: str,
    analysed: list[dict[str, Any]],
) -> None:
    """
    Upsert analysed reviews into MongoDB.
    Uses reviewId as the unique key to avoid duplicates on re-runs.
    """
    collection = get_reviews_collection()
    now = datetime.utcnow().isoformat()

    for doc in analysed:
        document = {
            "reviewId": doc.get("reviewId", ""),
            "packageName": package_name,
            "review": doc.get("review", ""),
            "score": doc.get("score", 0),
            "date": doc.get("date", ""),
            "sentiment": doc.get("sentiment", ""),
            "feedbackType": doc.get("feedbackType", ""),
            "summary": doc.get("summary", ""),
            "analysedAt": now,
        }

        await collection.update_one(
            {"reviewId": document["reviewId"]},
            {"$set": document},
            upsert=True,
        )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _chunk(lst: list, size: int) -> list[list]:
    """Split *lst* into sub-lists of at most *size* elements."""
    return [lst[i : i + size] for i in range(0, len(lst), size)]

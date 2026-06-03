"""
Google Play Scraper Service
Fetches reviews for a given package name using google-play-scraper.
"""

import logging
from datetime import datetime
from typing import Any

import pandas as pd
from google_play_scraper import Sort, reviews

logger = logging.getLogger(__name__)

# Maximum reviews per scraper call (library limit per request is ~200)
_SCRAPER_CHUNK = 200


def fetch_reviews(package_name: str, max_reviews: int = 200) -> list[dict[str, Any]]:
    """
    Fetch up to *max_reviews* reviews for *package_name* from Google Play.

    Returns a list of normalised review dicts:
    {
        "reviewId": str,
        "review":   str,
        "score":    int,   # 1-5
        "date":     str,   # ISO-8601
    }
    """
    logger.info("Fetching up to %d reviews for '%s'", max_reviews, package_name)

    all_reviews: list[dict] = []
    continuation_token = None

    while len(all_reviews) < max_reviews:
        fetch_count = min(_SCRAPER_CHUNK, max_reviews - len(all_reviews))

        try:
            result, continuation_token = reviews(
                package_name,
                lang="en",
                country="us",
                sort=Sort.NEWEST,
                count=fetch_count,
                continuation_token=continuation_token,
            )
        except Exception as exc:
            logger.error(
                "Scraper error for '%s' after %d reviews: %s",
                package_name,
                len(all_reviews),
                exc,
            )
            break

        if not result:
            logger.info("No more reviews returned by scraper.")
            break

        all_reviews.extend(result)

        # Stop if the library has no more pages
        if continuation_token is None:
            break

    logger.info("Fetched %d raw reviews for '%s'", len(all_reviews), package_name)
    return _normalise(all_reviews)


def _normalise(raw: list[dict]) -> list[dict[str, Any]]:
    """
    Convert raw google-play-scraper dicts to our internal schema.
    Drops reviews with missing/empty content.
    """
    if not raw:
        return []

    df = pd.DataFrame(raw)

    # Keep only the columns we need
    keep = ["reviewId", "content", "score", "at"]
    df = df[[c for c in keep if c in df.columns]]

    # Drop rows with no review text
    df = df.dropna(subset=["content"])
    df = df[df["content"].str.strip() != ""]

    # Rename to our schema
    df = df.rename(columns={"content": "review", "at": "date"})

    # Ensure reviewId is a string
    df["reviewId"] = df["reviewId"].astype(str)

    # Normalise score to int (default 0 if missing)
    df["score"] = pd.to_numeric(df["score"], errors="coerce").fillna(0).astype(int)

    # Normalise date to ISO-8601 string
    df["date"] = df["date"].apply(_format_date)

    return df.to_dict(orient="records")


def _format_date(value: Any) -> str:
    """Convert various date representations to a clean UTC ISO-8601 string (no timezone suffix)."""
    if isinstance(value, datetime):
        # Strip timezone info and store as plain UTC string for consistent string comparison
        return value.replace(tzinfo=None).isoformat()
    if isinstance(value, str):
        # Normalise existing strings – strip any timezone suffix
        try:
            dt = datetime.fromisoformat(value)
            return dt.replace(tzinfo=None).isoformat()
        except ValueError:
            return value
    try:
        ts = pd.Timestamp(value)
        return ts.tz_localize(None).isoformat() if ts.tzinfo else ts.isoformat()
    except Exception:
        return ""

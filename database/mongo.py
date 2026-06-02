"""
MongoDB connection management using Motor (async driver).
"""

import os
import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect_db() -> None:
    """Open the MongoDB connection. Called once at application startup."""
    global _client, _db

    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB_NAME", "reviewmind")

    _client = AsyncIOMotorClient(mongo_uri)
    _db = _client[db_name]

    # Verify connectivity
    await _client.admin.command("ping")
    logger.info("Connected to MongoDB at %s / database: %s", mongo_uri, db_name)

    # Ensure indexes for performance (idempotent – safe to call on every startup)
    await _ensure_indexes()


async def _ensure_indexes() -> None:
    """Create indexes required by Model 1 and Model 2."""
    reviews = _db["reviews"]
    await reviews.create_index("reviewId", unique=True)
    await reviews.create_index("packageName")
    await reviews.create_index("date")
    await reviews.create_index("sentiment")
    await reviews.create_index("feedbackType")
    # Compound index used by Model 2 aggregation pipelines
    await reviews.create_index([("packageName", 1), ("date", 1)])
    await reviews.create_index([("packageName", 1), ("sentiment", 1)])
    await reviews.create_index([("packageName", 1), ("feedbackType", 1)])

    trend_reports = _db["trend_reports"]
    await trend_reports.create_index(
        [("packageName", 1), ("period", 1)], unique=True
    )

    priority_reports = _db["priority_reports"]
    await priority_reports.create_index(
        [("packageName", 1), ("period", 1)], unique=True
    )

    logger.info("MongoDB indexes ensured.")


async def disconnect_db() -> None:
    """Close the MongoDB connection. Called once at application shutdown."""
    global _client
    if _client:
        _client.close()
        logger.info("MongoDB connection closed.")


def get_db() -> AsyncIOMotorDatabase:
    """Return the active database instance."""
    if _db is None:
        raise RuntimeError("Database is not connected. Call connect_db() first.")
    return _db


def get_reviews_collection():
    """Return the 'reviews' collection."""
    return get_db()["reviews"]


def get_trend_reports_collection():
    """Return the 'trend_reports' collection."""
    return get_db()["trend_reports"]

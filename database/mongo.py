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

"""Clears cached trend and priority reports from MongoDB."""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def clear():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["reviewmind"]
    r1 = await db["trend_reports"].delete_many({})
    r2 = await db["priority_reports"].delete_many({})
    print(f"Deleted trend_reports:    {r1.deleted_count}")
    print(f"Deleted priority_reports: {r2.deleted_count}")
    print("Cache cleared. Restart the server and refresh the dashboard.")
    client.close()

asyncio.run(clear())

"""Quick diagnostic test – run with: python test_trend.py"""
import asyncio
from dotenv import load_dotenv
load_dotenv()

from database.mongo import connect_db
from services.trend_service import get_top_issues_and_highlights, _date_range
from services.priority_service import build_priority_report

async def test():
    print("Connecting to MongoDB...")
    await connect_db()

    start, end = _date_range("30d")
    print(f"Date range: {start} → {end}")

    print("\n--- Testing get_top_issues_and_highlights ---")
    result = await get_top_issues_and_highlights(start, end, "com.spotify.music", 5)
    print("Issues found:", len(result.get("issues", [])))
    for i in result.get("issues", []):
        print(f"  - {i}")
    print("Highlights found:", len(result.get("positiveHighlights", [])))
    for h in result.get("positiveHighlights", []):
        print(f"  + {h}")

    print("\n--- Testing build_priority_report ---")
    from services.priority_service import DEFAULT_WEIGHTS
    report = await build_priority_report("30d", "com.spotify.music", 5, DEFAULT_WEIGHTS)
    print("Total reviews:", report["totalReviews"])
    print("Top issues:", len(report["topPriorityIssues"]))
    print("Positive highlights:", len(report["positiveHighlights"]))
    for i in report["topPriorityIssues"][:3]:
        print(f"  [{i.get('severity')}] {i.get('issue')} — score {i.get('priorityScore')}")

asyncio.run(test())

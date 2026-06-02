"""
Review Mind AI – FastAPI Application Entry Point
Model 1: Review Intelligence Model
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.mongo import connect_db, disconnect_db
from routes.review_routes import router as review_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown events."""
    await connect_db()
    yield
    await disconnect_db()


app = FastAPI(
    title="Review Mind AI",
    description="AI-powered review intelligence platform – Model 1: Review Intelligence",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS – allow all origins in development; tighten in production
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(review_router, prefix="/api")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Run directly with: python app.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import os

    import uvicorn
    from dotenv import load_dotenv

    load_dotenv()

    uvicorn.run(
        "app:app",
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", 8000)),
        reload=os.getenv("APP_ENV", "development") == "development",
    )

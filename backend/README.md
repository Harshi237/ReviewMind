# Review Mind AI – Backend

> **Model 1 – Review Intelligence**  
> AI-powered platform that fetches Google Play reviews and turns them into structured intelligence using Google Gemini.

---

## Table of Contents

1. [Project Structure](#project-structure)
2. [Tech Stack](#tech-stack)
3. [Prerequisites](#prerequisites)
4. [Setup](#setup)
5. [Environment Variables](#environment-variables)
6. [Running the Server](#running-the-server)
7. [API Reference](#api-reference)
8. [How It Works](#how-it-works)
9. [MongoDB Schema](#mongodb-schema)
10. [Extending the Platform](#extending-the-platform)

---

## Project Structure

```
backend/
├── app.py                      # FastAPI application entry point
├── routes/
│   └── review_routes.py        # API route handlers
├── services/
│   ├── scraper_service.py      # Google Play review fetcher
│   ├── ai_service.py           # Gemini AI integration (Model 1)
│   └── batch_service.py        # Batch orchestration + MongoDB storage
├── models/
│   └── review_model.py         # Pydantic request/response models
├── database/
│   └── mongo.py                # Async MongoDB connection (Motor)
├── utils/
│   └── validators.py           # AI response parsing & validation
├── requirements.txt
├── .env                        # Environment variables (never commit this)
└── README.md
```

---

## Tech Stack

| Layer        | Technology                  |
|--------------|-----------------------------|
| Backend      | Python 3.11+, FastAPI       |
| AI           | Google Gemini 1.5 Flash     |
| Database     | MongoDB (Motor async driver)|
| Scraping     | google-play-scraper         |
| Data         | Pandas                      |
| Retries      | Tenacity                    |
| Config       | python-dotenv               |

---

## Prerequisites

- Python 3.11 or higher
- MongoDB running locally or a MongoDB Atlas URI
- A Google Gemini API key ([get one here](https://aistudio.google.com/app/apikey))

---

## Setup

### 1. Clone / navigate to the project

```bash
cd backend
```

### 2. Create a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy `.env` and fill in your values:

```bash
# .env
GEMINI_API_KEY=your_gemini_api_key_here
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=reviewmind
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
BATCH_SIZE=10
MAX_RETRIES=3
```

---

## Environment Variables

| Variable        | Description                                      | Default                      |
|-----------------|--------------------------------------------------|------------------------------|
| `GEMINI_API_KEY`| Google Gemini API key                            | *(required)*                 |
| `MONGO_URI`     | MongoDB connection string                        | `mongodb://localhost:27017`  |
| `MONGO_DB_NAME` | MongoDB database name                            | `reviewmind`                 |
| `APP_ENV`       | `development` enables hot-reload                 | `development`                |
| `APP_HOST`      | Host to bind the server                          | `0.0.0.0`                    |
| `APP_PORT`      | Port to bind the server                          | `8000`                       |
| `BATCH_SIZE`    | Reviews per Gemini batch                         | `10`                         |
| `MAX_RETRIES`   | Gemini API retry attempts on failure             | `3`                          |

---

## Running the Server

```bash
# From the backend/ directory with venv activated
python app.py
```

Or with uvicorn directly:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

The server starts at: **http://localhost:8000**  
Interactive API docs: **http://localhost:8000/docs**

---

## API Reference

### `GET /health`

Health check.

**Response:**
```json
{ "status": "ok" }
```

---

### `POST /api/test-review`

Test Model 1 with a single review. Use this to verify the AI integration before running a full app analysis.

**Request:**
```json
{
  "review": "Payment failed after update."
}
```

**Response:**
```json
{
  "sentiment": "Negative",
  "feedbackType": "Complaint",
  "summary": "Payment failure after recent update."
}
```

---

### `POST /api/analyze-app`

Fetch all reviews for a Google Play app, analyse them with Model 1, store results in MongoDB, and return structured intelligence.

**Request:**
```json
{
  "packageName": "com.spotify.music",
  "maxReviews": 200
}
```

**Response:**
```json
{
  "packageName": "com.spotify.music",
  "totalFetched": 200,
  "totalAnalysed": 198,
  "totalStored": 198,
  "reviews": [
    {
      "reviewId": "abc123",
      "packageName": "com.spotify.music",
      "review": "App crashes every time I open it.",
      "score": 1,
      "date": "2024-05-01T10:00:00",
      "sentiment": "Negative",
      "feedbackType": "Bug Report",
      "summary": "App crashes on launch.",
      "analysedAt": "2024-05-10T12:00:00"
    }
  ]
}
```

---

## How It Works

```
POST /api/analyze-app
        │
        ▼
scraper_service.py
  └─ Fetches reviews from Google Play (paginated)
  └─ Normalises with Pandas → list of {reviewId, review, score, date}
        │
        ▼
batch_service.py
  └─ Splits reviews into batches (BATCH_SIZE)
  └─ For each batch → ai_service.py
        │
        ▼
ai_service.py
  └─ Builds prompt with multilingual instructions
  └─ Calls Gemini 1.5 Flash (with retry via Tenacity)
  └─ Parses + validates JSON response
        │
        ▼
batch_service.py
  └─ Upserts results into MongoDB (reviewId as unique key)
        │
        ▼
review_routes.py
  └─ Returns AnalyzeAppResponse to caller
```

---

## MongoDB Schema

Collection: `reviews`

```json
{
  "reviewId":    "string  – unique Google Play review ID",
  "packageName": "string  – app package name",
  "review":      "string  – original review text",
  "score":       "int     – star rating (1–5)",
  "date":        "string  – ISO-8601 review date",
  "sentiment":   "string  – Positive | Negative | Neutral",
  "feedbackType":"string  – Bug Report | Complaint | Suggestion | Positive Feedback | General Feedback",
  "summary":     "string  – concise English summary",
  "analysedAt":  "string  – ISO-8601 analysis timestamp"
}
```

An index on `reviewId` prevents duplicate documents on re-runs.

---

## Extending the Platform

The platform is designed for incremental growth:

| Future Model          | Description                                      |
|-----------------------|--------------------------------------------------|
| Model 2 – Trends      | Identify recurring themes across reviews over time |
| Model 3 – Priorities  | Rank issues by frequency and severity            |
| Dashboard Analytics   | Visualise sentiment trends and feedback breakdown |
| Competitor Analysis   | Compare review intelligence across similar apps  |

Each model can be added as a new service under `services/` and wired up via a new router in `routes/`.

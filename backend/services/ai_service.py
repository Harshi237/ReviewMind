"""
AI Service – Groq Integration (Model 1: Review Intelligence)

Optimisations applied:
  1. Groq llama-3.3-70b-versatile – extremely fast inference, generous free tier
     (30 req/min, 14,400 req/day on free plan vs Gemini's 15 req/min)
  2. Minimal prompt – only what the model needs, reduces input tokens
  3. JSON mode (response_format) – forces valid JSON output, no parsing hacks needed
  4. Low max_tokens (120) – summaries are short, no need to pay for unused tokens
  5. temperature=0 – deterministic output, no creative drift
  6. Configurable inter-request delay – stays within rate limits without over-waiting
  7. In-memory result cache – identical review text is never sent twice in a session
  8. Retry with exponential backoff – handles transient 429s gracefully
"""

import logging
import os
import time
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv
from groq import Groq, RateLimitError, APIStatusError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from utils.validators import extract_json_from_text, validate_ai_response

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Groq client
# ---------------------------------------------------------------------------

_client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))

# llama-3.3-70b-versatile: best accuracy on Groq free tier
# fallback: llama-3.1-8b-instant (faster, lower accuracy)
_MODEL = "llama-3.3-70b-versatile"

_MAX_TOKENS   = 120   # summaries are ≤20 words; 120 tokens is plenty
_TEMPERATURE  = 0     # fully deterministic – consistent structured output
_INTER_DELAY  = float(os.getenv("INTER_REQUEST_DELAY", 2))   # seconds between calls
_MAX_RETRIES  = int(os.getenv("MAX_RETRIES", 3))

# ---------------------------------------------------------------------------
# Minimal system prompt  (fewer tokens = faster + cheaper)
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are a multilingual review classifier. "
    "Analyse the user review (any language) and reply with ONLY a JSON object "
    "with exactly three keys:\n"
    '  "sentiment": "Positive" | "Negative" | "Neutral"\n'
    '  "feedbackType": "Bug Report" | "Complaint" | "Suggestion" | '
    '"Positive Feedback" | "General Feedback"\n'
    '  "summary": one concise English sentence (max 20 words)\n'
    "No markdown, no extra text, no explanation."
)

# ---------------------------------------------------------------------------
# Retry decorator  (only retry on rate-limit errors)
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception_type(RateLimitError),
    stop=stop_after_attempt(_MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=10, max=60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _call_groq(review_text: str) -> str:
    """
    Send a single review to Groq and return the raw response text.
    Uses JSON mode to guarantee parseable output.
    """
    response = _client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": review_text.strip()},
        ],
        temperature=_TEMPERATURE,
        max_tokens=_MAX_TOKENS,
        response_format={"type": "json_object"},  # enforces valid JSON output
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# In-memory cache  (avoids duplicate API calls within the same session)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=512)
def _cached_analyse(review_text: str) -> tuple | None:
    """
    Cached wrapper around _call_groq.
    Returns (sentiment, feedbackType, summary) tuple or None on failure.
    lru_cache requires hashable args and a hashable return type.
    """
    try:
        raw = _call_groq(review_text)
    except RateLimitError as exc:
        logger.error("Groq rate limit exceeded after retries: %s", exc)
        return None
    except APIStatusError as exc:
        logger.error("Groq API error: %s", exc)
        return None
    except Exception as exc:
        logger.error("Groq call failed: %s", exc)
        return None

    parsed = extract_json_from_text(raw)
    if parsed is None:
        logger.warning("Could not parse JSON from Groq response: %s", raw[:200])
        return None

    validated = validate_ai_response(parsed)
    if validated is None:
        logger.warning("Groq response failed validation: %s", parsed)
        return None

    return (validated["sentiment"], validated["feedbackType"], validated["summary"])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyse_single_review(review_text: str) -> dict[str, Any] | None:
    """
    Analyse a single review.

    Returns {"sentiment": ..., "feedbackType": ..., "summary": ...} or None.
    """
    result = _cached_analyse(review_text.strip())
    if result is None:
        return None
    sentiment, feedback_type, summary = result
    return {"sentiment": sentiment, "feedbackType": feedback_type, "summary": summary}


def analyse_reviews_batch(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Analyse a list of review dicts in sequence.

    Each input dict must contain at least: reviewId, review, score, date.
    Returns enriched dicts with sentiment, feedbackType, summary added.
    Reviews that fail analysis are skipped with a warning log.

    Optimisations:
    - Cached results skip the API entirely for duplicate review text
    - Configurable inter-request delay keeps usage within free-tier rate limits
    """
    results: list[dict[str, Any]] = []
    total = len(reviews)

    for idx, review in enumerate(reviews):
        review_text = review.get("review", "").strip()

        if not review_text:
            logger.warning("[%d/%d] Skipping – empty review text.", idx + 1, total)
            continue

        # Check if this text was already seen (lru_cache hit = no API call)
        cache_info = _cached_analyse.cache_info()
        intelligence = analyse_single_review(review_text)
        new_cache_info = _cached_analyse.cache_info()
        cache_hit = new_cache_info.hits > cache_info.hits

        if intelligence is None:
            logger.warning(
                "[%d/%d] Skipping reviewId=%s – analysis failed.",
                idx + 1, total, review.get("reviewId", "?"),
            )
            continue

        results.append({**review, **intelligence})

        log_msg = "cache hit" if cache_hit else "API call"
        logger.info(
            "[%d/%d] reviewId=%s → %s | %s (%s)",
            idx + 1, total,
            review.get("reviewId", "?"),
            intelligence["sentiment"],
            intelligence["feedbackType"],
            log_msg,
        )

        # Only sleep after real API calls, not cache hits
        if not cache_hit and _INTER_DELAY > 0 and idx < total - 1:
            time.sleep(_INTER_DELAY)

    logger.info(
        "Batch complete: %d/%d analysed | cache stats: %s",
        len(results), total, _cached_analyse.cache_info(),
    )
    return results

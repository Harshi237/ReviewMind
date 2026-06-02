"""
Validation helpers for Review Mind AI.
Responsible for validating and sanitising AI responses before they are
stored or returned to the caller.
"""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed values
# ---------------------------------------------------------------------------

VALID_SENTIMENTS = {"Positive", "Negative", "Neutral"}

VALID_FEEDBACK_TYPES = {
    "Bug Report",
    "Complaint",
    "Suggestion",
    "Positive Feedback",
    "General Feedback",
}


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


def extract_json_from_text(text: str) -> dict[str, Any] | None:
    """
    Attempt to extract a JSON object from a raw string.

    Gemini sometimes wraps JSON in markdown code fences or adds extra prose.
    This function strips that noise and returns a parsed dict, or None on failure.
    """
    if not text:
        return None

    # 1. Try direct parse first (happy path)
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown code fences  ```json … ``` or ``` … ```
    fence_pattern = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
    match = fence_pattern.search(text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Find the first { … } block in the text
    brace_pattern = re.compile(r"\{[\s\S]*?\}", re.DOTALL)
    match = brace_pattern.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("Could not extract JSON from AI response: %s", text[:200])
    return None


# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------


def validate_ai_response(data: dict[str, Any]) -> dict[str, Any] | None:
    """
    Validate that the AI response contains the required fields with allowed values.

    Returns the cleaned dict on success, or None if validation fails.
    """
    if not isinstance(data, dict):
        return None

    sentiment = data.get("sentiment", "").strip()
    feedback_type = data.get("feedbackType", "").strip()
    summary = data.get("summary", "").strip()

    # Normalise common casing mistakes from the model
    sentiment = _normalise_sentiment(sentiment)
    feedback_type = _normalise_feedback_type(feedback_type)

    if sentiment not in VALID_SENTIMENTS:
        logger.warning("Invalid sentiment value: '%s'", sentiment)
        return None

    if feedback_type not in VALID_FEEDBACK_TYPES:
        logger.warning("Invalid feedbackType value: '%s'", feedback_type)
        return None

    if not summary:
        logger.warning("Empty summary in AI response")
        return None

    return {
        "sentiment": sentiment,
        "feedbackType": feedback_type,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _normalise_sentiment(value: str) -> str:
    """Case-insensitive normalisation for sentiment values."""
    mapping = {
        "positive": "Positive",
        "negative": "Negative",
        "neutral": "Neutral",
    }
    return mapping.get(value.lower(), value)


def _normalise_feedback_type(value: str) -> str:
    """Case-insensitive normalisation for feedbackType values."""
    mapping = {
        "bug report": "Bug Report",
        "complaint": "Complaint",
        "suggestion": "Suggestion",
        "positive feedback": "Positive Feedback",
        "general feedback": "General Feedback",
    }
    return mapping.get(value.lower(), value)

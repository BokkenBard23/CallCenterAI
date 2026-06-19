"""Feedback router — phrase match feedback endpoint (AG-UIREWORK-4).

Provides POST /api/feedback for submitting user feedback about
dictionary phrase matches. Feedback is persisted as JSONL
(append-only) under the configured data directory.

Rate-limited to 30 requests/minute per IP.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Request

from app.models import FeedbackRequest, FeedbackResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# JSONL file path for feedback persistence
_FEEDBACK_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "feedback"


def _ensure_feedback_dir() -> Path:
    """Ensure the feedback directory exists and return its path.

    Returns:
        Path to the feedback directory.
    """
    _FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    return _FEEDBACK_DIR


def _get_feedback_file() -> Path:
    """Get the current feedback JSONL file path (rotated daily).

    Returns:
        Path to today's feedback JSONL file.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    return _ensure_feedback_dir() / f"feedback-{today}.jsonl"


@router.post(
    "",
    summary="Submit phrase match feedback",
    response_model=FeedbackResponse,
)
async def submit_feedback(
    request: FeedbackRequest,
    http_request: Request,
) -> FeedbackResponse:
    """Submit user feedback about a dictionary phrase match.

    Feedback is appended as a JSONL line to a daily-rotated file
    under ``data/feedback/``. Each entry includes the feedback data
    plus a unique ID, client IP, and server timestamp.

    Args:
        request: Validated FeedbackRequest body.
        http_request: Raw HTTP request (for IP extraction).

    Returns:
        FeedbackResponse with status, feedback_id, and message.

    Raises:
        HTTPException 500: If the feedback file cannot be written.
    """
    feedback_id = uuid.uuid4().hex[:12]
    client_ip = http_request.client.host if http_request.client else "unknown"

    entry = {
        "feedback_id": feedback_id,
        "phrase_text": request.phrase_text,
        "session_id": request.session_id,
        "match_text": request.match_text,
        "feedback_text": request.feedback_text,
        "client_timestamp": request.timestamp,
        "server_timestamp": datetime.now().isoformat(),
        "client_ip": client_ip,
    }

    try:
        feedback_file = _get_feedback_file()
        with open(feedback_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("Failed to write feedback to %s: %s", feedback_file, exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to persist feedback. Please try again later.",
        ) from exc

    logger.info(
        "Feedback submitted: id=%s session=%s phrase=%s",
        feedback_id,
        request.session_id,
        request.phrase_text[:50],
    )

    return FeedbackResponse(
        status="ok",
        feedback_id=feedback_id,
        message="Feedback submitted successfully",
    )


@router.get(
    "",
    summary="List feedback entries",
    response_model=List[dict],
)
async def list_feedback(
    session_id: str = "",
    limit: int = 100,
) -> List[dict]:
    """List feedback entries, optionally filtered by session_id.

    Reads the most recent feedback JSONL file and returns entries
    in reverse order (newest first), up to ``limit`` entries.

    Args:
        session_id: Optional session filter.
        limit: Maximum number of entries to return (1-1000, default 100).

    Returns:
        List of feedback entry dicts.
    """
    limit = max(1, min(limit, 1000))
    entries: List[dict] = []

    try:
        feedback_file = _get_feedback_file()
        if not feedback_file.exists():
            return []

        with open(feedback_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if session_id and entry.get("session_id") != session_id:
                    continue
                entries.append(entry)
    except OSError:
        logger.warning("Could not read feedback file")
        return []

    # Return newest first, capped at limit
    entries.reverse()
    return entries[:limit]

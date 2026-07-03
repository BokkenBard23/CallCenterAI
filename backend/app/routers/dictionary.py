"""Dictionary router — SpeechLab display token endpoints.

Endpoints:
  GET /{session_id}/tokens — Get display tokens for a dictionary in a session
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.models import DisplayToken
from app.services.xml_parser import group_into_display_tokens
from app.utils.session import session_store

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/{session_id}/tokens",
    response_model=List[DisplayToken],
    summary="Get display tokens for a dictionary",
)
async def get_display_tokens(
    session_id: str,
    dict_name: Optional[str] = Query(
        None,
        description="Dictionary name (omit to use first dictionary in session)",
    ),
) -> List[DisplayToken]:
    """Get pre-grouped display tokens for a dictionary in a session.

    Converts the raw TokenSection from the stored DictionaryNode
    into DisplayToken[] suitable for frontend rendering with
    channel color mapping.

    Args:
        session_id: Session identifier from a previous upload.
        dict_name: Optional dictionary name to select. If omitted,
            the first dictionary in the session is used.

    Returns:
        List of DisplayToken instances.

    Raises:
        404: Session not found or dictionary not found in session.
        422: Dictionary has no token section available.
    """
    # ── Validate session ──────────────────────────────────────────
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found.",
        )

    # ── Find dictionary ──────────────────────────────────────────
    if not session.dictionaries:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' has no dictionaries.",
        )

    dictionary = None
    if dict_name:
        dictionary = session.dictionaries.get(dict_name)
        if dictionary is None:
            available = list(session.dictionaries.keys())
            raise HTTPException(
                status_code=404,
                detail=f"Dictionary '{dict_name}' not found in session. "
                       f"Available: {available}",
            )
    else:
        # Use the first dictionary in the session
        dictionary = next(iter(session.dictionaries.values()))

    # ── Get token section ────────────────────────────────────────
    token_section = dictionary.token_section
    if token_section is None or not token_section.tokens:
        raise HTTPException(
            status_code=422,
            detail=f"Dictionary '{dictionary.name}' has no token section "
                   "available for display token conversion.",
        )

    # ── Convert to display tokens ────────────────────────────────
    display_tokens = group_into_display_tokens(token_section)

    return display_tokens

"""Upload router — RTF and XML dictionary upload endpoints.

Endpoints:
  POST /rtf        — Upload and parse an RTF dialog file
  POST /dictionary — Upload and parse an XML phrase dictionary

Both endpoints accept an optional `session_id` form field to add
data to an existing session instead of creating a new one.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import settings
from app.models import UploadDictionaryResponse, UploadRtfResponse
from app.services.rtf_parser import parse_rtf_bytes
from app.services.xml_parser import parse_xml_bytes
from app.utils.session import session_store

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/rtf", response_model=UploadRtfResponse, summary="Upload RTF dialog file")
async def upload_rtf(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
) -> UploadRtfResponse:
    """Upload and parse an RTF dialog transcript.

    Accepts .rtf files containing call center dialogues.
    Returns parsed dialogue with speaker-labeled turns.

    If `session_id` is provided, adds the dialogue to an existing session.
    Otherwise, creates a new session.
    """
    # ── Validate file extension ──────────────────────────────────
    filename = file.filename or "unknown.rtf"
    if not filename.lower().endswith(".rtf"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file extension. Expected .rtf, got '{filename}'",
        )

    # ── Validate file size ───────────────────────────────────────
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum {settings.max_upload_size_mb}MB, "
                   f"got {len(content) / (1024 * 1024):.1f}MB",
        )

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    # ── Parse RTF ─────────────────────────────────────────────────
    try:
        parsed = await parse_rtf_bytes(content, filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Could not parse RTF file: {exc}",
        )
    except Exception as exc:
        logger.error("Unexpected error parsing RTF '%s': %s", filename, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Internal error parsing RTF file: {exc}",
        )

    # ── Validate dialogue was extracted ──────────────────────────
    if not parsed.turns:
        raise HTTPException(
            status_code=422,
            detail="No dialogue could be extracted from the RTF file. "
                   "The file may not contain valid RTF dialogue content.",
        )

    # ── Store in session ──────────────────────────────────────────
    if session_id:
        session = session_store.get(session_id)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{session_id}' not found.",
            )
    else:
        session = session_store.create()

    session.dialog = parsed
    session_store.update(session)

    # ── Build response ────────────────────────────────────────────
    raw_text_length = sum(len(turn.text) for turn in parsed.turns)

    return UploadRtfResponse(
        session_id=session.id,
        dialogue=parsed.turns,
        turn_count=parsed.total_turns,
        raw_text_length=raw_text_length,
    )


@router.post("/dictionary", response_model=UploadDictionaryResponse, summary="Upload XML dictionary")
async def upload_dictionary(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
) -> UploadDictionaryResponse:
    """Upload and parse an XML phrase dictionary.

    Accepts .xml files with SpeechLabRequest phrase dictionaries.
    Supports hierarchical dictionaries with nested SpeechLabRequest elements.

    If `session_id` is provided, adds the dictionary to an existing session.
    Otherwise, creates a new session.
    """
    # ── Validate file extension ──────────────────────────────────
    filename = file.filename or "unknown.xml"
    if not filename.lower().endswith(".xml"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file extension. Expected .xml, got '{filename}'",
        )

    # ── Validate file size ───────────────────────────────────────
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum {settings.max_upload_size_mb}MB",
        )

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    # ── Parse XML ─────────────────────────────────────────────────
    try:
        dictionary, validation = await parse_xml_bytes(content, filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid XML: {exc}",
        )
    except Exception as exc:
        logger.error("Unexpected error parsing XML '%s': %s", filename, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Internal error parsing XML file: {exc}",
        )

    # ── Validate dictionary content ──────────────────────────────
    if dictionary.condition_count == 0 and not dictionary.has_children:
        raise HTTPException(
            status_code=422,
            detail="No search phrases found in the dictionary XML. "
                   "The file must contain at least one WORD token or child dictionary.",
        )

    # ── Check for hierarchy cycles ────────────────────────────────
    if validation.errors:
        for error in validation.errors:
            if "cycle" in error.lower():
                raise HTTPException(
                    status_code=422,
                    detail=f"Dictionary hierarchy error: {error}",
                )

    # ── Store in session ──────────────────────────────────────────
    if session_id:
        session = session_store.get(session_id)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{session_id}' not found.",
            )
    else:
        session = session_store.create()

    session_store.add_dictionary(session.id, dictionary)

    # ── Build response ────────────────────────────────────────────
    return UploadDictionaryResponse(
        session_id=session.id,
        dictionary=dictionary,
        validation=validation,
    )

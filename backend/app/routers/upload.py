"""Upload router — RTF and XML dictionary upload endpoints.

Endpoints:
  POST /rtf            — Upload and parse an RTF dialog file
  POST /rtf/batch      — Upload and parse multiple RTF files (batch)
  POST /dictionary     — Upload and parse an XML phrase dictionary

Both single and batch upload endpoints accept an optional `session_id`
form field to add data to an existing session instead of creating a new one.
"""

from __future__ import annotations

import logging
import os
import re
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import settings
from app.models import (
    BatchUploadRtfResponse,
    DisplayToken,
    UploadDictionaryResponse,
    UploadRtfResponse,
)
from app.services.rtf_parser import parse_rtf_bytes
from app.services.xml_parser import group_into_display_tokens, parse_xml_bytes
from app.utils.session import session_store

logger = logging.getLogger(__name__)


def _sanitize_filename(filename: str) -> str:
    """Sanitize uploaded filename to prevent path traversal attacks.
    
    - Strips directory components (handles both / and \\)
    - Removes path traversal sequences (..)
    - Validates filename is not empty after sanitization
    - Only allows alphanumeric, dots, hyphens, underscores, and spaces
    
    Args:
        filename: Raw filename from upload.
        
    Returns:
        Sanitized filename.
        
    Raises:
        ValueError: If filename is empty or contains only invalid characters.
    """
    # Strip directory components
    name = os.path.basename(filename)
    
    # Remove any remaining path traversal sequences
    name = name.replace("..", "")
    
    # Validate filename is not empty
    if not name or name.strip() == "":
        raise ValueError("Invalid filename: empty after sanitization")
    
    # Validate filename doesn't contain suspicious characters
    # Allow: alphanumeric, dots, hyphens, underscores, spaces, Cyrillic
    if not re.match(r'^[\w\s.\-а-яА-ЯёЁ]+$', name):
        raise ValueError(f"Invalid filename: contains disallowed characters")
    
    return name


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
    # ── Sanitize filename ────────────────────────────────────────
    try:
        filename = _sanitize_filename(file.filename or "unknown.rtf")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # ── Validate file extension ──────────────────────────────────
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


# ═══════════════════════════════════════════════════════════
# POST /rtf/batch — Batch RTF upload
# ═══════════════════════════════════════════════════════════

# Maximum number of files in a single batch request
BATCH_MAX_FILES = 10


@router.post(
    "/rtf/batch",
    response_model=BatchUploadRtfResponse,
    summary="Batch upload multiple RTF dialog files",
)
async def upload_rtf_batch(
    files: List[UploadFile] = File(..., description="RTF files to upload (1-10)"),
    session_id: Optional[str] = Form(None, description="Optional session to add dialogues to"),
) -> BatchUploadRtfResponse:
    """Upload and parse multiple RTF dialog files in one request.

    Accepts 1-10 .rtf files. Each file is processed independently —
    if one file fails, others still succeed (partial success pattern).

    Each successful file creates its own session (unless a shared
    `session_id` is provided, in which case each dialogue is stored
    as a separate session linked to the provided one).

    Returns BatchUploadRtfResponse with per-file results, counts,
    and any errors for failed files.
    """
    # ── Validate file count ──────────────────────────────────────
    if len(files) < 1:
        raise HTTPException(
            status_code=400,
            detail="At least 1 file must be provided.",
        )
    if len(files) > BATCH_MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {BATCH_MAX_FILES} files per batch. Got {len(files)}.",
        )

    # ── Validate session (if provided) ──────────────────────────
    if session_id:
        existing = session_store.get(session_id)
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{session_id}' not found.",
            )

    # ── Process each file independently ──────────────────────────
    results: list[UploadRtfResponse] = []
    errors: list[dict] = []
    successful = 0
    failed = 0

    for file in files:
        try:
            filename = _sanitize_filename(file.filename or "unknown.rtf")
        except ValueError as exc:
            raise ValueError(str(exc))  # Will be caught by batch error handler

        try:
            # ── Validate file extension ─────────────────────────
            if not filename.lower().endswith(".rtf"):
                raise ValueError(f"Invalid file extension. Expected .rtf, got '{filename}'")

            # ── Validate file size ──────────────────────────────
            content = await file.read()
            if len(content) == 0:
                raise ValueError("Empty file uploaded")
            if len(content) > settings.max_upload_bytes:
                raise ValueError(
                    f"File too large. Maximum {settings.max_upload_size_mb}MB, "
                    f"got {len(content) / (1024 * 1024):.1f}MB"
                )

            # ── Parse RTF ───────────────────────────────────────
            try:
                parsed = await parse_rtf_bytes(content, filename)
            except ValueError as exc:
                raise ValueError(f"Could not parse RTF file: {exc}")
            except Exception as exc:
                logger.error("Unexpected error parsing RTF '%s': %s", filename, exc)
                raise ValueError(f"Internal error parsing RTF file: {exc}")

            # ── Validate dialogue was extracted ──────────────────
            if not parsed.turns:
                raise ValueError(
                    "No dialogue could be extracted from the RTF file. "
                    "The file may not contain valid RTF dialogue content."
                )

            # ── Store in session ────────────────────────────────
            if session_id:
                # For batch with shared session_id, each file gets its own session
                # but is conceptually linked to the provided session_id
                session = session_store.create()
                session.metadata["parent_session_id"] = session_id
            else:
                session = session_store.create()

            session.dialog = parsed
            session_store.update(session)

            # ── Build per-file response ─────────────────────────
            raw_text_length = sum(len(turn.text) for turn in parsed.turns)
            results.append(
                UploadRtfResponse(
                    session_id=session.id,
                    dialogue=parsed.turns,
                    turn_count=parsed.total_turns,
                    raw_text_length=raw_text_length,
                )
            )
            successful += 1

        except ValueError as exc:
            logger.warning("Batch upload failed for '%s': %s", filename, exc)
            failed += 1
            errors.append({"filename": filename, "error": str(exc)})
            results.append(
                UploadRtfResponse(
                    session_id="",
                    error=str(exc),
                )
            )
        except Exception as exc:
            logger.error("Unexpected batch upload error for '%s': %s", filename, exc)
            failed += 1
            errors.append({"filename": filename, "error": f"Unexpected error: {exc}"})
            results.append(
                UploadRtfResponse(
                    session_id="",
                    error=f"Unexpected error: {exc}",
                )
            )

    return BatchUploadRtfResponse(
        results=results,
        total=len(files),
        successful=successful,
        failed=failed,
        errors=errors,
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
    # ── Sanitize filename ────────────────────────────────────────
    try:
        filename = _sanitize_filename(file.filename or "unknown.xml")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # ── Validate file extension ──────────────────────────────────
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

    # ── Build display tokens for root dictionary ─────────────────
    display_tokens: list[DisplayToken] | None = None
    if dictionary.token_section and dictionary.token_section.tokens:
        display_tokens = group_into_display_tokens(dictionary.token_section)

    # ── Build response ────────────────────────────────────────────
    return UploadDictionaryResponse(
        session_id=session.id,
        dictionary=dictionary,
        validation=validation,
        display_tokens=display_tokens,
    )

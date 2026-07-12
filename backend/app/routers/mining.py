"""Mining router — offline corpus mining endpoints (Track B Quick Win).

Endpoints:
  POST   /mining/index              — start corpus indexing job (202 Accepted)
  GET    /mining/status/{job_id}     — polling for job status
  POST   /mining/cancel/{job_id}     — cancel a long-running job
  POST   /mining/find_similar        — top-k similar dialogues to a phrase group
  POST   /mining/find_fn             — find false-negative candidates (202 + polling)
  POST   /mining/audit               — LLM audit dictionary (202 + polling)

Pattern: ``routers/dictionary.py`` (FastAPI APIRouter + Pydantic request/response
DTOs). Long-running jobs (``index``, ``find_fn``, ``audit``) return ``job_id``
immediately; FE polls ``GET /mining/status/{job_id}``.

Service access
--------------
The :class:`DictionaryMiningService` singleton is attached to ``app.state``
during startup (see :func:`app.main._init_services`). When missing (e.g. in
unit tests) a service can be injected via ``app.state.mining_service`` before
the test client is constructed.

NEВ modifies existing routers.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status

from app.models import (
    AuditRequest,
    AuditResponse,
    FindFNRequest,
    FindFNResponse,
    FindSimilarRequest,
    FindSimilarResponse,
    IndexCorpusRequest,
    IndexCorpusResponse,
    MiningJobStatus,
)
from app.services.dict_mining import DictionaryMiningService
from app.utils.session import session_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mining", tags=["mining"])


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _get_service(request: Request) -> DictionaryMiningService:
    """Resolve the mining service from ``app.state``.

    Raises:
        HTTPException(503): service not initialised.
    """
    service: Optional[DictionaryMiningService] = getattr(
        request.app.state, "mining_service", None
    )
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mining service not initialised.",
        )
    return service


def _resolve_dictionary(session_id: str, dictionary_id: str):
    """Resolve a session + dictionary. Raises 404 / 400 on failure."""
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    node = session.dictionaries.get(dictionary_id)
    if node is None:
        available = list(session.dictionaries.keys())
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dictionary '{dictionary_id}' not found in session. "
                   f"Available: {available}",
        )
    return session, node


def _spawn_background(
    request: Request,
    job_id: str,
    coro,
) -> None:
    """Spawn a background asyncio task and register it with the mining service."""
    service: Optional[DictionaryMiningService] = getattr(
        request.app.state, "mining_service", None
    )
    task = asyncio.create_task(coro, name=f"mining-{job_id}")
    if service is not None:
        service._register_task(job_id, task)  # noqa: SLF001 — internal hook


# ═══════════════════════════════════════════════════════════
# POST /mining/index
# ═══════════════════════════════════════════════════════════


@router.post(
    "/index",
    response_model=IndexCorpusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start corpus indexing job (long-running)",
)
async def index_corpus(
    request: Request,
    body: IndexCorpusRequest,
) -> IndexCorpusResponse:
    """Start indexing all RTF files in ``directory_path``.

    Returns ``job_id`` immediately (202 Accepted). Poll ``GET /mining/status``.

    Errors:
        400: ``directory_path`` does not exist or contains no RTF.
        404: ``session_id`` or ``dictionary_id`` not found.
        409: A pending/running job already exists for this session+dictionary.
    """
    service = _get_service(request)
    _resolve_dictionary(body.session_id, body.dictionary_id)

    directory = Path(body.directory_path)
    if not directory.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"directory_path does not exist: {body.directory_path}",
        )
    if not any(directory.glob("*.rtf")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"no .rtf files found in {body.directory_path}",
        )

    existing = service._mining_store.find_running_job(  # noqa: SLF001
        body.session_id, body.dictionary_id
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A mining job {existing['job_type']} is already running "
                f"for session '{body.session_id}' + dictionary "
                f"'{body.dictionary_id}' (job_id={existing['job_id']}, "
                f"status={existing['status']})."
            ),
        )

    # Create the job synchronously so the response always carries job_id.
    # index_corpus() also creates the job row internally — so we delegate.
    try:
        response = await service.index_corpus(
            directory_path=body.directory_path,
            dictionary_id=body.dictionary_id,
            session_id=body.session_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return response


# ═══════════════════════════════════════════════════════════
# GET /mining/status/{job_id}
# ═══════════════════════════════════════════════════════════


@router.get(
    "/status/{job_id}",
    response_model=MiningJobStatus,
    summary="Poll mining job status",
)
async def get_job_status(
    request: Request,
    job_id: str,
) -> MiningJobStatus:
    """Return the current status + progress of a mining job.

    When ``status`` is ``completed`` / ``partial``, ``result`` carries the
    job-type-specific payload (FindFNJobResult / AuditJobResult).

    Errors:
        404: ``job_id`` not found.
    """
    service = _get_service(request)
    result = await service.get_job_status(job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mining job '{job_id}' not found.",
        )
    return result


# ═══════════════════════════════════════════════════════════
# POST /mining/cancel/{job_id}
# ═══════════════════════════════════════════════════════════


@router.post(
    "/cancel/{job_id}",
    summary="Cancel a long-running mining job",
)
async def cancel_job(
    request: Request,
    job_id: str,
):
    """Cancel a mining job. Stops at the next checkpoint.

    Errors:
        404: ``job_id`` not found.
        400: job is not running (already completed / cancelled / failed).
    """
    service = _get_service(request)
    status_obj = await service.get_job_status(job_id)
    if status_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mining job '{job_id}' not found.",
        )
    if status_obj.status not in ("pending", "running"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job '{job_id}' is not running (status={status_obj.status}).",
        )
    await service.cancel_job(job_id)
    return {"status": "cancelled", "job_id": job_id}


# ═══════════════════════════════════════════════════════════
# POST /mining/find_similar
# ═══════════════════════════════════════════════════════════


@router.post(
    "/find_similar",
    response_model=FindSimilarResponse,
    summary="Find similar dialogues to a phrase group (synchronous)",
)
async def find_similar(
    request: Request,
    body: FindSimilarRequest,
) -> FindSimilarResponse:
    """Find ``top_k`` dialogues similar to ``phrase_group_id``.

    Synchronous (fast — vector search only, no LLM). Requires a completed
    indexing job.

    Errors:
        400: invalid request (empty phrase_group_id).
        404: ``job_id`` or ``session_id`` not found.
    """
    service = _get_service(request)
    # find_similar only needs a valid session — no dictionary resolution.
    if session_store.get(body.session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{body.session_id}' not found.",
        )

    job_status = await service.get_job_status(body.job_id)
    if job_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mining job '{body.job_id}' not found.",
        )
    if job_status.status not in ("completed", "partial"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Indexing job '{body.job_id}' is not completed "
                f"(status={job_status.status})."
            ),
        )

    # The phrase_group_id doubles as the phrase text for the demo profile
    # (FE sends either the PhraseGroup id or its visible phrase text).
    phrase_text = body.phrase_group_id
    if not phrase_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="phrase_group_id must not be empty.",
        )

    return await service.find_similar_to_phrase(
        phrase_group_id=body.phrase_group_id,
        phrase_text=phrase_text,
        top_k=body.top_k,
    )


# ═══════════════════════════════════════════════════════════
# POST /mining/find_fn
# ═══════════════════════════════════════════════════════════


@router.post(
    "/find_fn",
    response_model=FindFNResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Find false-negative candidates (long-running, LLM verify)",
)
async def find_false_negatives(
    request: Request,
    body: FindFNRequest,
) -> FindFNResponse:
    """Start FN discovery. Returns ``job_id`` immediately (202 Accepted).

    FE polls ``GET /mining/status/{job_id}``; when ``status=completed`` the
    ``result`` field carries :class:`FindFNJobResult`.

    Errors:
        404: ``session_id`` / ``dictionary_id`` / ``job_id`` not found.
        400: indexing job not completed.
    """
    service = _get_service(request)
    _resolve_dictionary(body.session_id, body.dictionary_id)

    index_status = await service.get_job_status(body.job_id)
    if index_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mining job '{body.job_id}' not found.",
        )
    if index_status.status not in ("completed", "partial"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Indexing job '{body.job_id}' is not completed "
                f"(status={index_status.status})."
            ),
        )

    # Create the FN job row synchronously so the response carries a job_id.
    fn_job_id = service._make_job_id("find_fn")  # noqa: SLF001
    service._mining_store.create_job(  # noqa: SLF001
        job_id=fn_job_id,
        session_id=body.session_id,
        dictionary_id=body.dictionary_id,
        directory_path="",  # informational — find_fn does not read FS
        job_type="find_fn",
    )
    service._mining_store.update_job(fn_job_id, status="running", total_dialogues=0)  # noqa: SLF001

    _session, node = _resolve_dictionary(body.session_id, body.dictionary_id)

    async def _runner() -> None:
        try:
            await service.find_false_negatives(
                dictionary_node=node,
                job_id=fn_job_id,
                threshold=body.threshold,
            )
        except Exception:  # noqa: BLE001 — background task must not bubble
            logger.exception("mining.find_fn background task failed job=%s", fn_job_id)

    _spawn_background(request, fn_job_id, _runner())

    return FindFNResponse(
        job_id=fn_job_id,
        dictionary_id=body.dictionary_id,
        total=0,
        candidates=[],
        partial=False,
    )


# ═══════════════════════════════════════════════════════════
# POST /mining/audit
# ═══════════════════════════════════════════════════════════


@router.post(
    "/audit",
    response_model=AuditResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="LLM audit dictionary (long-running, per-PhraseGroup)",
)
async def audit_dictionary(
    request: Request,
    body: AuditRequest,
) -> AuditResponse:
    """Start a full LLM audit of the dictionary. Returns ``job_id`` (202).

    FE polls ``GET /mining/status/{job_id}``; when ``status=completed`` the
    ``result`` field carries :class:`AuditJobResult`.

    Errors:
        404: ``session_id`` / ``dictionary_id`` / ``job_id`` not found.
        400: indexing job not completed.
    """
    service = _get_service(request)
    _session, node = _resolve_dictionary(body.session_id, body.dictionary_id)

    index_status = await service.get_job_status(body.job_id)
    if index_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mining job '{body.job_id}' not found.",
        )
    if index_status.status not in ("completed", "partial"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Indexing job '{body.job_id}' is not completed "
                f"(status={index_status.status})."
            ),
        )

    audit_job_id = service._make_job_id("audit")  # noqa: SLF001
    service._mining_store.create_job(  # noqa: SLF001
        job_id=audit_job_id,
        session_id=body.session_id,
        dictionary_id=body.dictionary_id,
        directory_path="",  # informational — audit does not read FS
        job_type="audit",
    )
    service._mining_store.update_job(audit_job_id, status="running", total_dialogues=0)  # noqa: SLF001

    async def _runner() -> None:
        try:
            await service.audit_full_dictionary(
                dictionary_node=node,
                job_id=audit_job_id,
            )
        except Exception:  # noqa: BLE001 — background task must not bubble
            logger.exception("mining.audit background task failed job=%s", audit_job_id)

    _spawn_background(request, audit_job_id, _runner())

    return AuditResponse(
        job_id=audit_job_id,
        dictionary_id=body.dictionary_id,
        phrase_groups=[],
        partial=False,
    )

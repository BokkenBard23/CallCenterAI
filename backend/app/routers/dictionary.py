"""Dictionary router — SpeechLab display tokens + editing, AI, validation,
duplicates, statistics, and XML export endpoints.

Endpoints:
  GET   /{session_id}/tokens                              — display tokens (legacy)
  POST  /{session_id}/nodes                               — add a node
  PATCH /{session_id}/nodes/{node_id}                     — update node metadata
  DELETE /{session_id}/nodes/{node_id}                     — remove node + subtree
  POST  /{session_id}/nodes/{node_id}/conditions           — add a condition
  PATCH /{session_id}/nodes/{node_id}/conditions/{idx}     — update a condition
  DELETE /{session_id}/nodes/{node_id}/conditions/{idx}     — remove a condition
  POST  /{session_id}/nodes/{node_id}/conditions/reorder   — reorder conditions
  POST  /{session_id}/analyze-ai                          — LLM dictionary analysis
  POST  /{session_id}/suggest-phrases                     — LLM phrase suggestions
  POST  /{session_id}/duplicates                           — duplicate detection
  POST  /{session_id}/statistics                          — dictionary statistics
  POST  /{session_id}/validate                            — dictionary validation
  POST  /{session_id}/export-xml                          — canonical XML export

Note on identifiers:
  ``DictionaryNode`` has no separate ``id`` field for routing purposes —
  ``node.name`` IS the lookup key within ``session.dictionaries`` (a
  ``Dict[str, DictionaryNode]``). For nested nodes (children), the
  ``node_id`` path parameter is matched against ``node.name`` via a
  recursive tree search (``_find_node_recursive``). Names are expected to
  be unique within a single dictionary tree — SmartLogger enforces this
  at the XML level.
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.models import (
    AttributeSection,
    DisplayToken,
    DictionaryCondition,
    DictionaryNode,
    PhraseGroupVisual,
    SavedState,
)
from app.services.dict_utils import (
    DictionaryStats,
    DuplicateReport,
    ValidationResult,
    dictionary_stats,
    find_duplicates,
    validate_dictionary,
)
from app.services.dictionary_ai import (
    DictionaryAnalysisResult,
    DictionarySuggestion,
    analyze_dictionary,
    suggest_phrases,
)
from app.services.xml_parser import group_into_display_tokens
from app.services.xml_serializer import serialize_dictionary_to_xml
from app.utils.session import session_store

logger = logging.getLogger(__name__)

router = APIRouter()


# ═══════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════

_VALID_CHANNELS = {"CLIENT", "OPERATOR", "ANY"}
_VALID_LOGIC_OPERATORS = {"", "И", "ИЛИ", "НЕ", "И НЕ", "ИЛИ НЕ"}


# ═══════════════════════════════════════════════════════════
# Request DTOs
# ═══════════════════════════════════════════════════════════


class NodeCreateRequest(BaseModel):
    """Body for POST /nodes."""

    name: str = Field(..., min_length=1, description="New node name (unique within tree)")
    parent_name: Optional[str] = Field(
        None,
        description="Parent node name. If omitted, the node is added as a root "
        "dictionary on the session.",
    )


class NodeUpdateRequest(BaseModel):
    """Body for PATCH /nodes/{node_id}."""

    name: Optional[str] = Field(None, min_length=1)
    saved_state: Optional[SavedState] = None
    attributes: Optional[AttributeSection] = None


class ConditionCreateRequest(BaseModel):
    """Body for POST /nodes/{node_id}/conditions.

    The endpoint stores ``phrase_groups`` (the FE contract) as-is. The
    internal ``node.phrase_groups`` (used by search) is rebuilt by
    ``logic_builder.build_phrase_groups`` during search, so it does not
    need to be kept in sync on every edit.

    ``logic_operator`` is the operator that PRECEDES this condition in
    the visual expression ("" for the first condition). It is preserved
    for the editor UI; the search pipeline derives operator/negation
    semantics from the token stream / phrase_groups during search.
    """

    text: str = Field(..., min_length=1)
    word_distance: int = Field(2, ge=0, le=10)
    channel_constraint: str = Field("ANY")
    is_exact: bool = False
    is_exception: bool = False
    phrase_groups: List[PhraseGroupVisual] = Field(default_factory=list)
    open_brackets: int = Field(0, ge=0, le=10)
    close_brackets: int = Field(0, ge=0, le=10)
    logic_operator: str = Field(
        "",
        description='Operator preceding this condition: "" | "И" | "ИЛИ" | "НЕ" | '
        '"И НЕ" | "ИЛИ НЕ". The first condition must use "".',
    )


class ConditionUpdateRequest(BaseModel):
    """Body for PATCH /nodes/{node_id}/conditions/{idx}. All fields optional."""

    text: Optional[str] = Field(None, min_length=1)
    word_distance: Optional[int] = Field(None, ge=0, le=10)
    channel_constraint: Optional[str] = None
    is_exact: Optional[bool] = None
    is_exception: Optional[bool] = None
    phrase_groups: Optional[List[PhraseGroupVisual]] = None
    open_brackets: Optional[int] = Field(None, ge=0, le=10)
    close_brackets: Optional[int] = Field(None, ge=0, le=10)
    logic_operator: Optional[str] = None


class ReorderRequest(BaseModel):
    """Body for POST /nodes/{node_id}/conditions/reorder."""

    new_order: List[int] = Field(
        ...,
        description="Old condition indices in the desired new order. Must be a "
        "permutation of range(len(conditions)).",
    )


class AnalyzeAiRequest(BaseModel):
    """Body for POST /analyze-ai."""

    dict_name: Optional[str] = None
    provider_id: Optional[str] = None


class SuggestPhrasesRequest(BaseModel):
    """Body for POST /suggest-phrases."""

    dict_name: Optional[str] = None
    provider_id: Optional[str] = None
    count: int = Field(25, ge=1, le=200)


class DictNameRequest(BaseModel):
    """Body for endpoints that only need a dict_name (duplicates/stats/validate)."""

    dict_name: Optional[str] = None


class ExportXmlRequest(BaseModel):
    """Body for POST /export-xml."""

    dict_name: Optional[str] = None
    pretty: bool = True


class SuggestPhrasesResponse(BaseModel):
    suggestions: List[DictionarySuggestion] = Field(default_factory=list)


class ConditionCreateResponse(BaseModel):
    """Response for POST /conditions."""

    condition: DictionaryCondition
    index: int


class DeleteResponse(BaseModel):
    deleted: bool = True
    node_name: Optional[str] = None
    condition_idx: Optional[int] = None


class ReorderResponse(BaseModel):
    conditions: List[DictionaryCondition]


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _resolve_session(session_id: str):
    """Return the session or raise 404."""
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found.",
        )
    return session


def _resolve_root_dictionary(session, dict_name: Optional[str]) -> DictionaryNode:
    """Resolve the root dictionary on a session.

    If ``dict_name`` is provided, look it up; otherwise use the first
    dictionary in the session. Raises 404 on missing.
    """
    if not session.dictionaries:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session.id}' has no dictionaries.",
        )
    if dict_name:
        node = session.dictionaries.get(dict_name)
        if node is None:
            available = list(session.dictionaries.keys())
            raise HTTPException(
                status_code=404,
                detail=f"Dictionary '{dict_name}' not found in session. "
                       f"Available: {available}",
            )
        return node
    return next(iter(session.dictionaries.values()))


def _find_node_recursive(
    node: DictionaryNode,
    node_id: str,
) -> Optional[DictionaryNode]:
    """Search the dictionary tree by ``node.name`` (DFS).

    Returns the matching node, or None if not found.
    """
    if node.name == node_id:
        return node
    for child in node.children:
        found = _find_node_recursive(child, node_id)
        if found is not None:
            return found
    return None


def _find_node_in_session(session, dict_name: Optional[str], node_id: str):
    """Resolve a node by id (name) within a (optionally selected) dictionary tree.

    Returns (root_node, target_node). Raises 404 if not found.
    """
    root = _resolve_root_dictionary(session, dict_name)
    target = _find_node_recursive(root, node_id)
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=f"Node '{node_id}' not found in dictionary '{root.name}'.",
        )
    return root, target


def _find_parent_of(
    root: DictionaryNode,
    target: DictionaryNode,
) -> Optional[DictionaryNode]:
    """Return the parent of ``target`` within the tree rooted at ``root``.

    Returns None if ``target`` IS the root (no parent).
    """
    for child in root.children:
        if child is target or child.name == target.name:
            return root
        deeper = _find_parent_of(child, target)
        if deeper is not None:
            return deeper
    return None


def _validate_channel(channel: str) -> str:
    """Normalise + validate a channel value. Raises 422 on invalid."""
    if channel is None:
        return "ANY"
    ch = channel.strip().upper() or "ANY"
    if ch not in _VALID_CHANNELS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid channel '{channel}'. Must be one of {sorted(_VALID_CHANNELS)}.",
        )
    return ch


def _validate_logic_operator(op: Optional[str]) -> str:
    """Normalise + validate a logic operator string. Raises 422 on invalid."""
    if op is None:
        return ""
    normalised = op.strip()
    if normalised not in _VALID_LOGIC_OPERATORS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid logic_operator '{op}'. Must be one of "
                   f"{sorted(_VALID_LOGIC_OPERATORS)}.",
        )
    return normalised


def _compute_word_count(text: str) -> int:
    """Compute word count from text via simple whitespace split."""
    return len(text.split()) if text else 0


def _persist(session) -> None:
    """Persist the session via the store."""
    session_store.update(session)


# ═══════════════════════════════════════════════════════════
# GET /{session_id}/tokens — unchanged legacy endpoint
# ═══════════════════════════════════════════════════════════


@router.get(
    "/{session_id}",
    response_model=List[DictionaryNode],
    summary="Get all dictionary trees in a session",
)
async def get_session_dictionaries(
    session_id: str,
) -> List[DictionaryNode]:
    """Return all root dictionaries (with full subtrees) stored in a session.

    Used by the FE dictionary editor to render the navigation tree on mount.
    Additive endpoint — does not alter any of the 14 frozen editing endpoints.

    Raises:
        404: Session not found.
    """
    session = _resolve_session(session_id)
    return list(session.dictionaries.values())


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
    session = _resolve_session(session_id)
    dictionary = _resolve_root_dictionary(session, dict_name)

    token_section = dictionary.token_section
    if token_section is None or not token_section.tokens:
        raise HTTPException(
            status_code=422,
            detail=f"Dictionary '{dictionary.name}' has no token section "
                   "available for display token conversion.",
        )

    return group_into_display_tokens(token_section)


# ═══════════════════════════════════════════════════════════
# Editing — Nodes
# ═══════════════════════════════════════════════════════════


@router.post(
    "/{session_id}/nodes",
    response_model=DictionaryNode,
    summary="Add a new dictionary node",
)
async def add_node(
    session_id: str,
    body: NodeCreateRequest,
) -> DictionaryNode:
    """Add a new DictionaryNode — either as a root dictionary on the session
    (when ``parent_name`` is omitted) or as a child of an existing node.

    Returns the created node. Persists the session.
    """
    session = _resolve_session(session_id)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Node name must not be empty.")

    new_node = DictionaryNode(
        id=uuid.uuid4().hex[:12],
        name=name,
        parent_name=body.parent_name,
        conditions=[],
        condition_count=0,
        has_children=False,
        children_count=0,
    )

    if body.parent_name is None or body.parent_name == "":
        # Root-level: add to session.dictionaries
        if name in session.dictionaries:
            raise HTTPException(
                status_code=422,
                detail=f"Root dictionary '{name}' already exists in session "
                       f"'{session_id}'.",
            )
        session.dictionaries[name] = new_node
    else:
        # Child: find parent in any root dictionary
        parent_name = body.parent_name.strip()
        parent_node: Optional[DictionaryNode] = None
        for root in session.dictionaries.values():
            found = _find_node_recursive(root, parent_name)
            if found is not None:
                parent_node = found
                break
        if parent_node is None:
            raise HTTPException(
                status_code=404,
                detail=f"Parent node '{parent_name}' not found in session "
                       f"'{session_id}'.",
            )
        # Ensure name uniqueness within the parent's children list
        existing_names = {c.name for c in parent_node.children}
        if name in existing_names:
            raise HTTPException(
                status_code=422,
                detail=f"Child node '{name}' already exists under parent "
                       f"'{parent_name}'.",
            )
        parent_node.children.append(new_node)
        parent_node.has_children = True
        parent_node.children_count = len(parent_node.children)

    _persist(session)
    logger.info(
        "dictionary.add_node session=%s parent=%s name=%s",
        session_id, body.parent_name or "<root>", name,
    )
    return new_node


@router.patch(
    "/{session_id}/nodes/{node_id}",
    response_model=DictionaryNode,
    summary="Update node metadata",
)
async def update_node(
    session_id: str,
    node_id: str,
    body: NodeUpdateRequest,
) -> DictionaryNode:
    """Update a node's name / saved_state / attributes.

    ``node_id`` is matched against ``node.name``. If the name is changed,
    the session.dictionaries key (for root nodes) is updated too.
    """
    session = _resolve_session(session_id)

    # Search across all root dictionaries for the node
    target: Optional[DictionaryNode] = None
    owning_root_name: Optional[str] = None
    for root_name, root in session.dictionaries.items():
        found = _find_node_recursive(root, node_id)
        if found is not None:
            target = found
            owning_root_name = root_name
            break

    if target is None:
        raise HTTPException(
            status_code=404,
            detail=f"Node '{node_id}' not found in session '{session_id}'.",
        )

    if body.name is not None:
        new_name = body.name.strip()
        if not new_name:
            raise HTTPException(status_code=422, detail="name must not be empty.")
        # If this is a root node and the name changes, update the dict key
        if target.name == owning_root_name and new_name != owning_root_name:
            if new_name in session.dictionaries:
                raise HTTPException(
                    status_code=422,
                    detail=f"Root dictionary '{new_name}' already exists.",
                )
            session.dictionaries[new_name] = session.dictionaries.pop(owning_root_name)
        target.name = new_name

    if body.saved_state is not None:
        target.saved_state = body.saved_state
    if body.attributes is not None:
        target.attributes = body.attributes

    _persist(session)
    logger.info(
        "dictionary.update_node session=%s node_id=%s name=%s",
        session_id, node_id, target.name,
    )
    return target


@router.delete(
    "/{session_id}/nodes/{node_id}",
    response_model=DeleteResponse,
    summary="Remove a node (and its subtree)",
)
async def delete_node(
    session_id: str,
    node_id: str,
    dict_name: Optional[str] = Query(
        None,
        description="Restrict the search to this root dictionary.",
    ),
) -> DeleteResponse:
    """Remove a node and its subtree from the session.

    If the node is a root dictionary, the entire entry is removed from
    ``session.dictionaries``.
    """
    session = _resolve_session(session_id)

    # Direct root-dictionary match first
    if dict_name is None and node_id in session.dictionaries:
        del session.dictionaries[node_id]
        _persist(session)
        logger.info("dictionary.delete_node session=%s root=%s", session_id, node_id)
        return DeleteResponse(deleted=True, node_name=node_id)

    # Otherwise, search inside one (or all) root dictionaries
    roots_to_search: List[DictionaryNode]
    if dict_name:
        root = session.dictionaries.get(dict_name)
        if root is None:
            raise HTTPException(
                status_code=404,
                detail=f"Dictionary '{dict_name}' not found in session.",
            )
        roots_to_search = [root]
    else:
        roots_to_search = list(session.dictionaries.values())

    for root in roots_to_search:
        if root.name == node_id:
            # Root-level deletion (when dict_name was provided)
            if root.name in session.dictionaries:
                del session.dictionaries[root.name]
                _persist(session)
                logger.info("dictionary.delete_node session=%s root=%s", session_id, node_id)
                return DeleteResponse(deleted=True, node_name=node_id)
        # Search children
        for i, child in enumerate(root.children):
            if child.name == node_id:
                removed = root.children.pop(i)
                root.has_children = len(root.children) > 0
                root.children_count = len(root.children)
                _persist(session)
                logger.info(
                    "dictionary.delete_node session=%s parent=%s node=%s",
                    session_id, root.name, removed.name,
                )
                return DeleteResponse(deleted=True, node_name=removed.name)

    raise HTTPException(
        status_code=404,
        detail=f"Node '{node_id}' not found in session '{session_id}'.",
    )


# ═══════════════════════════════════════════════════════════
# Editing — Conditions
# ═══════════════════════════════════════════════════════════


def _build_condition_from_create(body: ConditionCreateRequest) -> DictionaryCondition:
    """Build a DictionaryCondition from a ConditionCreateRequest."""
    channel = _validate_channel(body.channel_constraint)
    _validate_logic_operator(body.logic_operator)
    text = body.text.strip()
    return DictionaryCondition(
        text=text,
        word_distance=body.word_distance,
        word_count=_compute_word_count(text),
        channel_constraint=channel,
        without_list=[],
        is_exact=body.is_exact,
        phrase_groups=list(body.phrase_groups),
        nested_phrases=[],
        exception_phrases=[],
        extra_limitations=[],
        is_exception=body.is_exception,
    )


@router.post(
    "/{session_id}/nodes/{node_id}/conditions",
    response_model=ConditionCreateResponse,
    summary="Add a condition to a node",
)
async def add_condition(
    session_id: str,
    node_id: str,
    body: ConditionCreateRequest,
    dict_name: Optional[str] = Query(None),
) -> ConditionCreateResponse:
    """Add a new condition to a node. Returns the created condition + its index."""
    session = _resolve_session(session_id)
    _root, target = _find_node_in_session(session, dict_name, node_id)

    condition = _build_condition_from_create(body)
    target.conditions.append(condition)
    target.condition_count = len(target.conditions)

    _persist(session)
    logger.info(
        "dictionary.add_condition session=%s node=%s idx=%d text=%r",
        session_id, node_id, len(target.conditions) - 1, condition.text,
    )
    return ConditionCreateResponse(condition=condition, index=len(target.conditions) - 1)


@router.patch(
    "/{session_id}/nodes/{node_id}/conditions/{condition_idx}",
    response_model=DictionaryCondition,
    summary="Update an existing condition",
)
async def update_condition(
    session_id: str,
    node_id: str,
    condition_idx: int,
    body: ConditionUpdateRequest,
    dict_name: Optional[str] = Query(None),
) -> DictionaryCondition:
    """Update an existing condition (partial merge). Recomputes word_count."""
    session = _resolve_session(session_id)
    _root, target = _find_node_in_session(session, dict_name, node_id)

    if condition_idx < 0 or condition_idx >= len(target.conditions):
        raise HTTPException(
            status_code=404,
            detail=f"Condition index {condition_idx} out of range "
                   f"(0..{len(target.conditions) - 1}).",
        )

    cond = target.conditions[condition_idx]

    if body.text is not None:
        cond.text = body.text.strip()
        cond.word_count = _compute_word_count(cond.text)
    if body.word_distance is not None:
        cond.word_distance = body.word_distance
    if body.channel_constraint is not None:
        cond.channel_constraint = _validate_channel(body.channel_constraint)
    if body.is_exact is not None:
        cond.is_exact = body.is_exact
    if body.is_exception is not None:
        cond.is_exception = body.is_exception
    if body.phrase_groups is not None:
        cond.phrase_groups = list(body.phrase_groups)
    if body.logic_operator is not None:
        _validate_logic_operator(body.logic_operator)
        # logic_operator is preserved for the editor UI; not stored as a
        # separate field on DictionaryCondition — it is encoded in the
        # token stream / phrase_groups during serialisation.
    # open_brackets / close_brackets are part of the visual contract; the
    # canonical serialiser derives brackets from the token_section, which
    # is regenerated on re-parse, so we do not persist them here.

    _persist(session)
    logger.info(
        "dictionary.update_condition session=%s node=%s idx=%d",
        session_id, node_id, condition_idx,
    )
    return cond


@router.delete(
    "/{session_id}/nodes/{node_id}/conditions/{condition_idx}",
    response_model=DeleteResponse,
    summary="Remove a condition by index",
)
async def delete_condition(
    session_id: str,
    node_id: str,
    condition_idx: int,
    dict_name: Optional[str] = Query(None),
) -> DeleteResponse:
    """Remove a condition by index. Persists the session."""
    session = _resolve_session(session_id)
    _root, target = _find_node_in_session(session, dict_name, node_id)

    if condition_idx < 0 or condition_idx >= len(target.conditions):
        raise HTTPException(
            status_code=404,
            detail=f"Condition index {condition_idx} out of range "
                   f"(0..{len(target.conditions) - 1}).",
        )

    target.conditions.pop(condition_idx)
    target.condition_count = len(target.conditions)
    _persist(session)
    logger.info(
        "dictionary.delete_condition session=%s node=%s idx=%d",
        session_id, node_id, condition_idx,
    )
    return DeleteResponse(deleted=True, condition_idx=condition_idx)


@router.post(
    "/{session_id}/nodes/{node_id}/conditions/reorder",
    response_model=ReorderResponse,
    summary="Reorder conditions",
)
async def reorder_conditions(
    session_id: str,
    node_id: str,
    body: ReorderRequest,
    dict_name: Optional[str] = Query(None),
) -> ReorderResponse:
    """Reorder conditions. ``new_order`` is a list of old indices in new order.

    Validates that ``new_order`` is a permutation of ``range(len(conditions))``.
    """
    session = _resolve_session(session_id)
    _root, target = _find_node_in_session(session, dict_name, node_id)

    n = len(target.conditions)
    if len(body.new_order) != n:
        raise HTTPException(
            status_code=422,
            detail=f"new_order length {len(body.new_order)} does not match "
                   f"condition count {n}.",
        )
    if any(idx < 0 or idx >= n for idx in body.new_order):
        raise HTTPException(
            status_code=422,
            detail=f"new_order contains an out-of-range index (0..{n - 1}).",
        )
    if len(set(body.new_order)) != n:
        raise HTTPException(
            status_code=422,
            detail="new_order must be a permutation of range(0..n) without duplicates.",
        )

    target.conditions = [target.conditions[i] for i in body.new_order]
    _persist(session)
    logger.info(
        "dictionary.reorder_conditions session=%s node=%s order=%s",
        session_id, node_id, body.new_order,
    )
    return ReorderResponse(conditions=target.conditions)


# ═══════════════════════════════════════════════════════════
# Analysis endpoints
# ═══════════════════════════════════════════════════════════


@router.post(
    "/{session_id}/analyze-ai",
    response_model=DictionaryAnalysisResult,
    summary="Run LLM dictionary analysis",
)
async def analyze_ai(
    session_id: str,
    body: AnalyzeAiRequest,
) -> DictionaryAnalysisResult:
    """Run an LLM analysis of the dictionary (summary / examples / recommendations)."""
    session = _resolve_session(session_id)
    node = _resolve_root_dictionary(session, body.dict_name)
    try:
        result = await analyze_dictionary(node, provider_id=body.provider_id)
    except Exception as exc:
        logger.error("analyze_dictionary failed for session=%s: %s", session_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"LLM analysis failed: {exc}",
        ) from exc
    logger.info(
        "dictionary.analyze_ai session=%s dict=%s provider=%s",
        session_id, node.name, body.provider_id,
    )
    return result


@router.post(
    "/{session_id}/suggest-phrases",
    response_model=SuggestPhrasesResponse,
    summary="LLM phrase suggestions",
)
async def suggest_phrases_endpoint(
    session_id: str,
    body: SuggestPhrasesRequest,
) -> SuggestPhrasesResponse:
    """Generate phrase suggestions via the LLM."""
    session = _resolve_session(session_id)
    node = _resolve_root_dictionary(session, body.dict_name)
    try:
        suggestions = await suggest_phrases(
            node,
            provider_id=body.provider_id,
            count=body.count,
        )
    except Exception as exc:
        logger.error("suggest_phrases failed for session=%s: %s", session_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"LLM phrase suggestions failed: {exc}",
        ) from exc
    logger.info(
        "dictionary.suggest_phrases session=%s dict=%s count=%d",
        session_id, node.name, len(suggestions),
    )
    return SuggestPhrasesResponse(suggestions=suggestions)


@router.post(
    "/{session_id}/duplicates",
    response_model=DuplicateReport,
    summary="Find duplicate conditions",
)
async def find_duplicates_endpoint(
    session_id: str,
    body: DictNameRequest,
) -> DuplicateReport:
    """Detect full and soft duplicates among the dictionary's conditions."""
    session = _resolve_session(session_id)
    node = _resolve_root_dictionary(session, body.dict_name)
    report = find_duplicates(node.conditions)
    logger.info(
        "dictionary.duplicates session=%s dict=%s full=%d soft=%d",
        session_id, node.name, len(report.full), len(report.soft),
    )
    return report


@router.post(
    "/{session_id}/statistics",
    response_model=DictionaryStats,
    summary="Compute dictionary statistics",
)
async def statistics_endpoint(
    session_id: str,
    body: DictNameRequest,
) -> DictionaryStats:
    """Compute aggregate statistics for the dictionary tree."""
    session = _resolve_session(session_id)
    node = _resolve_root_dictionary(session, body.dict_name)
    stats = dictionary_stats(node)
    logger.info(
        "dictionary.statistics session=%s dict=%s conditions=%d",
        session_id, node.name, stats.total_conditions,
    )
    return stats


@router.post(
    "/{session_id}/validate",
    response_model=ValidationResult,
    summary="Validate dictionary structure",
)
async def validate_endpoint(
    session_id: str,
    body: DictNameRequest,
) -> ValidationResult:
    """Run structural validation on the dictionary."""
    session = _resolve_session(session_id)
    node = _resolve_root_dictionary(session, body.dict_name)
    result = validate_dictionary(node)
    logger.info(
        "dictionary.validate session=%s dict=%s errors=%d warnings=%d",
        session_id, node.name, len(result.errors), len(result.warnings),
    )
    return result


# ═══════════════════════════════════════════════════════════
# XML export
# ═══════════════════════════════════════════════════════════


@router.post(
    "/{session_id}/export-xml",
    summary="Export dictionary to canonical XML",
    response_class=StreamingResponse,
)
async def export_xml(
    session_id: str,
    body: ExportXmlRequest,
) -> StreamingResponse:
    """Export the dictionary to canonical SmartLogger XML bytes.

    Returns a ``StreamingResponse`` with ``Content-Disposition: attachment``
    and ``media_type="application/xml"``.
    """
    session = _resolve_session(session_id)
    node = _resolve_root_dictionary(session, body.dict_name)
    try:
        xml_bytes = serialize_dictionary_to_xml(node, pretty=body.pretty)
    except Exception as exc:
        logger.error(
            "serialize_dictionary_to_xml failed session=%s dict=%s: %s",
            session_id, node.name, exc,
        )
        raise HTTPException(
            status_code=500,
            detail=f"XML serialisation failed: {exc}",
        ) from exc

    filename = f"{node.name}.xml"
    logger.info(
        "dictionary.export_xml session=%s dict=%s bytes=%d",
        session_id, node.name, len(xml_bytes),
    )
    return StreamingResponse(
        iter([xml_bytes]),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

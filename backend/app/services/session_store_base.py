"""Abstract base class and shared types for session storage backends.

Provides:
  - Session dataclass — holds all data for a single analysis session
  - SessionStoreBase — abstract interface that all backends must implement
  - JSON serialization helpers — shared between SQLite and future PostgreSQL backends

Backends must implement all abstract methods. The interface is synchronous
because all current consumers (FastAPI route handlers) call these methods
without ``await``. A future async interface can be added alongside.
"""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models import AnalysisResponse, BatchAnalysisResponse, DictionaryNode, ParsedDialog

# Default session TTL in seconds (2 hours)
DEFAULT_TTL_SECONDS = 7200

# Maximum number of sessions before cleanup triggers
MAX_SESSIONS = 1000


# ═══════════════════════════════════════════════════════════
# Session dataclass
# ═══════════════════════════════════════════════════════════


@dataclass
class Session:
    """Holds all data for a single analysis session."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)
    dialog: Optional[ParsedDialog] = None
    dictionaries: Dict[str, DictionaryNode] = field(default_factory=dict)
    analyses: Dict[str, AnalysisResponse] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """Update last_accessed timestamp."""
        self.last_accessed = datetime.now()

    def is_expired(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
        """Check if session has exceeded TTL."""
        if ttl_seconds <= 0:
            return False
        return datetime.now() - self.last_accessed > timedelta(seconds=ttl_seconds)


# ═══════════════════════════════════════════════════════════
# JSON serialization helpers
# ═══════════════════════════════════════════════════════════


class _SessionEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime and Pydantic models."""

    def default(self, o: Any) -> Any:
        if isinstance(o, datetime):
            return o.isoformat()
        if hasattr(o, "model_dump"):
            return o.model_dump(mode="json")
        if isinstance(o, Path):
            return str(o)
        return super().default(o)


def serialize_session(session: Session) -> str:
    """Serialize a Session dataclass to JSON string."""
    data = {
        "id": session.id,
        "created_at": session.created_at.isoformat(),
        "last_accessed": session.last_accessed.isoformat(),
        "dialog": session.dialog.model_dump(mode="json") if session.dialog else None,
        "dictionaries": {
            k: v.model_dump(mode="json") for k, v in session.dictionaries.items()
        },
        "analyses": {
            k: v.model_dump(mode="json") for k, v in session.analyses.items()
        },
        "metadata": session.metadata,
    }
    return json.dumps(data, ensure_ascii=False)


def deserialize_session(data: str) -> Session:
    """Deserialize a JSON string back to a Session dataclass."""
    raw = json.loads(data)
    dialog = ParsedDialog(**raw["dialog"]) if raw.get("dialog") else None
    dictionaries = {
        k: DictionaryNode(**v) for k, v in raw.get("dictionaries", {}).items()
    }
    analyses = {
        k: AnalysisResponse(**v) for k, v in raw.get("analyses", {}).items()
    }
    return Session(
        id=raw["id"],
        created_at=datetime.fromisoformat(raw["created_at"]),
        last_accessed=datetime.fromisoformat(raw["last_accessed"]),
        dialog=dialog,
        dictionaries=dictionaries,
        analyses=analyses,
        metadata=raw.get("metadata", {}),
    )


# ═══════════════════════════════════════════════════════════
# SessionStoreBase — Abstract interface
# ═══════════════════════════════════════════════════════════


class SessionStoreBase(ABC):
    """Abstract base for session storage backends.

    All methods are synchronous because current consumers (FastAPI route
    handlers) call them without ``await``. A future async variant can be
    added alongside when needed.

    Subclasses must implement every abstract method. The ``close()`` method
    has a no-op default implementation for backends that don't hold resources.
    """

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds

    # ── Lifecycle ──────────────────────────────────────────────

    def close(self) -> None:
        """Release backend resources (connections, file handles, etc.).

        Default no-op; backends with resources should override.
        """

    # ── CRUD operations ────────────────────────────────────────

    @abstractmethod
    def create(self, session_id: Optional[str] = None) -> Session:
        """Create a new empty session.

        Args:
            session_id: Optional explicit session ID. If None, auto-generated.

        Returns:
            The newly created Session.
        """

    @abstractmethod
    def get(self, session_id: str) -> Optional[Session]:
        """Retrieve a session by ID.

        Returns None if not found or expired.
        """

    @abstractmethod
    def get_or_create(self, session_id: Optional[str] = None) -> Session:
        """Get an existing session or create a new one."""

    @abstractmethod
    def update(self, session: Session) -> None:
        """Update a session in the store."""

    @abstractmethod
    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if found."""

    @abstractmethod
    def list_sessions(self) -> List[str]:
        """List all session IDs."""

    # ── Domain helpers ────────────────────────────────────────

    @abstractmethod
    def add_dictionary(self, session_id: str, dictionary: DictionaryNode) -> Optional[Session]:
        """Add a dictionary to a session. Returns updated session or None."""

    @abstractmethod
    def get_dictionary(self, session_id: str, dict_name: str) -> Optional[DictionaryNode]:
        """Get a specific dictionary from a session."""

    @abstractmethod
    def add_analysis(self, session_id: str, analysis: AnalysisResponse) -> Optional[Session]:
        """Add an analysis result to a session. Returns updated session or None."""

    @abstractmethod
    def get_analysis(self, analysis_id: str) -> Optional[AnalysisResponse]:
        """Find an analysis across all sessions by its ID."""

    # ── Cleanup ────────────────────────────────────────────────

    @abstractmethod
    def cleanup_expired(self) -> int:
        """Force cleanup of all expired sessions. Returns count removed."""

"""In-memory session storage for dialogues, dictionaries, and analysis results.

NOTE: This is a simple in-memory store suitable for single-process development.
For production, replace with Redis, database, or similar persistent storage.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.models import AnalysisResponse, BatchAnalysisResponse, ParsedDialog, DictionaryNode


# Default session TTL in seconds (2 hours)
_DEFAULT_TTL_SECONDS = 7200

# Maximum number of sessions before cleanup triggers
_MAX_SESSIONS = 1000


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

    def is_expired(self, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> bool:
        """Check if session has exceeded TTL."""
        if ttl_seconds <= 0:
            return False
        return datetime.now() - self.last_accessed > timedelta(seconds=ttl_seconds)


class SessionStore:
    """Thread-safe in-memory session store with TTL cleanup."""

    def __init__(self, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_seconds

    def create(self) -> Session:
        """Create a new empty session."""
        session = Session()
        with self._lock:
            self._maybe_cleanup()
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        """Retrieve a session by ID. Returns None if not found or expired."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if session.is_expired(self._ttl_seconds):
                del self._sessions[session_id]
                return None
            session.touch()
            return session

    def get_or_create(self, session_id: Optional[str] = None) -> Session:
        """Get an existing session or create a new one."""
        if session_id:
            existing = self.get(session_id)
            if existing is not None:
                return existing
        return self.create()

    def update(self, session: Session) -> None:
        """Update a session in the store."""
        session.touch()
        with self._lock:
            self._sessions[session.id] = session

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if found."""
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def list_sessions(self) -> List[str]:
        """List all session IDs."""
        with self._lock:
            return list(self._sessions.keys())

    def add_dictionary(self, session_id: str, dictionary: DictionaryNode) -> Optional[Session]:
        """Add a dictionary to a session. Returns updated session or None."""
        session = self.get(session_id)
        if session is None:
            return None
        session.dictionaries[dictionary.name] = dictionary
        self.update(session)
        return session

    def get_dictionary(self, session_id: str, dict_name: str) -> Optional[DictionaryNode]:
        """Get a specific dictionary from a session."""
        session = self.get(session_id)
        if session is None:
            return None
        return session.dictionaries.get(dict_name)

    def add_analysis(self, session_id: str, analysis: AnalysisResponse) -> Optional[Session]:
        """Add an analysis result to a session. Returns updated session or None."""
        session = self.get(session_id)
        if session is None:
            return None
        session.analyses[analysis.analysis_id] = analysis
        self.update(session)
        return session

    def get_analysis(self, analysis_id: str) -> Optional[AnalysisResponse]:
        """Find an analysis across all sessions by its ID."""
        with self._lock:
            for session in self._sessions.values():
                if not session.is_expired(self._ttl_seconds):
                    analysis = session.analyses.get(analysis_id)
                    if analysis is not None:
                        return analysis
        return None

    def _maybe_cleanup(self) -> None:
        """Remove expired sessions if above threshold. Must be called under lock."""
        if len(self._sessions) < _MAX_SESSIONS:
            return
        expired_ids = [
            sid for sid, s in self._sessions.items()
            if s.is_expired(self._ttl_seconds)
        ]
        for sid in expired_ids:
            del self._sessions[sid]

    def cleanup_expired(self) -> int:
        """Force cleanup of all expired sessions. Returns count removed."""
        with self._lock:
            expired_ids = [
                sid for sid, s in self._sessions.items()
                if s.is_expired(self._ttl_seconds)
            ]
            for sid in expired_ids:
                del self._sessions[sid]
            return len(expired_ids)


# Singleton instance
session_store = SessionStore()


# ═══════════════════════════════════════════════════════════
# Batch Store — in-memory storage for batch processing status
# ═══════════════════════════════════════════════════════════

class BatchStore:
    """Thread-safe in-memory store for batch analysis status.

    Stores BatchAnalysisResponse objects keyed by batch_id.
    Lifecycle: batches are created on POST /batch, updated during
    background processing, and read via GET /batch/{id}/status.
    Cleanup: batches are cleaned up together with their parent sessions.
    """

    def __init__(self) -> None:
        self._batches: Dict[str, BatchAnalysisResponse] = {}
        self._lock = threading.Lock()

    def create(self, batch: BatchAnalysisResponse) -> None:
        """Store a new batch."""
        with self._lock:
            self._batches[batch.batch_id] = batch

    def get(self, batch_id: str) -> Optional[BatchAnalysisResponse]:
        """Retrieve a batch by ID. Returns None if not found."""
        with self._lock:
            return self._batches.get(batch_id)

    def update(self, batch: BatchAnalysisResponse) -> None:
        """Update an existing batch in the store."""
        with self._lock:
            self._batches[batch.batch_id] = batch

    def delete(self, batch_id: str) -> bool:
        """Delete a batch. Returns True if found."""
        with self._lock:
            return self._batches.pop(batch_id, None) is not None

    def cleanup_for_session(self, session_id: str) -> int:
        """Remove all batches associated with a session. Returns count removed."""
        with self._lock:
            to_remove = [
                bid for bid, batch in self._batches.items()
                if batch.session_id == session_id
            ]
            for bid in to_remove:
                del self._batches[bid]
            return len(to_remove)


# Singleton instance
batch_store = BatchStore()

"""In-memory session storage implementation (fallback backend).

Used when SQLite is unavailable (e.g., filesystem permissions) or when
explicitly selected via ``SESSION_BACKEND=memory``. Sessions are lost on
server restart.

Thread safety: all public methods acquire ``self._lock``.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

from app.models import AnalysisResponse, DictionaryNode
from app.services.session_store_base import Session, SessionStoreBase

logger = logging.getLogger(__name__)


class MemorySessionStore(SessionStoreBase):
    """Thread-safe in-memory session store with TTL cleanup.

    Sessions are stored in a plain dict and lost on process restart.
    Suitable for development or as a fallback when SQLite is unavailable.
    """

    def __init__(self, ttl_seconds: int = 7200, max_sessions: int = 100) -> None:
        super().__init__(ttl_seconds=ttl_seconds, max_sessions=max_sessions)
        self._lock = threading.Lock()
        self._sessions: Dict[str, Session] = {}

    # ── CRUD operations ────────────────────────────────────────

    def create(self, session_id: Optional[str] = None) -> Session:
        """Create a new empty session."""
        session = Session(id=session_id) if session_id else Session()
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
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    def list_sessions(self) -> List[str]:
        """List all session IDs."""
        with self._lock:
            return list(self._sessions.keys())

    # ── Domain helpers ────────────────────────────────────────

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

    # ── Cleanup ────────────────────────────────────────────────

    def _maybe_cleanup(self) -> None:
        """Remove expired sessions if above threshold. Must be called under lock."""
        if len(self._sessions) < self._max_sessions:
            return
        expired_ids = [
            sid
            for sid, session in self._sessions.items()
            if session.is_expired(self._ttl_seconds)
        ]
        for sid in expired_ids:
            del self._sessions[sid]

    def cleanup_expired(self) -> int:
        """Force cleanup of all expired sessions. Returns count removed."""
        with self._lock:
            expired_ids = [
                sid
                for sid, session in self._sessions.items()
                if session.is_expired(self._ttl_seconds)
            ]
            for sid in expired_ids:
                del self._sessions[sid]
            removed = len(expired_ids)
            if removed > 0:
                logger.info("Cleaned up %d expired sessions (memory backend)", removed)
            return removed

"""In-memory session storage for dialogues, dictionaries, and analysis results.

NOTE: This is a simple in-memory store suitable for single-process development.
For production, replace with Redis, database, or similar persistent storage.

TODO (coder stage):
  - Consider adding TTL/expiry for sessions
  - Consider adding max session limit
  - Consider thread-safety for concurrent access
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from app.models import AnalysisResponse, ParsedDialog, XmlDictionary


@dataclass
class Session:
    """Holds all data for a single analysis session."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = field(default_factory=datetime.now)
    dialog: Optional[ParsedDialog] = None
    dictionary: Optional[XmlDictionary] = None
    analysis: Optional[AnalysisResponse] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class SessionStore:
    """Simple in-memory session store."""

    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}

    def create(self) -> Session:
        """Create a new empty session."""
        session = Session()
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        """Retrieve a session by ID."""
        return self._sessions.get(session_id)

    def get_or_create(self, session_id: Optional[str] = None) -> Session:
        """Get an existing session or create a new one."""
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        return self.create()

    def update(self, session: Session) -> None:
        """Update a session in the store."""
        self._sessions[session.id] = session

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if found."""
        return self._sessions.pop(session_id, None) is not None

    def list_sessions(self) -> list[str]:
        """List all session IDs."""
        return list(self._sessions.keys())


# Singleton instance
session_store = SessionStore()

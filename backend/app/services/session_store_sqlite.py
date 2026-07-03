"""SQLite-backed session storage implementation.

Sessions are persisted in a single SQLite database file, surviving server
restarts.  Each session is stored as a JSON-serialized blob in the
``sessions`` table.

Thread safety: all public methods acquire ``self._lock`` before DB access.

The schema uses standard SQL types compatible with PostgreSQL:
  - TEXT  →  PostgreSQL TEXT / VARCHAR
  - REAL  →  PostgreSQL DOUBLE PRECISION
  No SQLite-specific features are used that would break on PostgreSQL.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from app.models import AnalysisResponse, BatchAnalysisResponse, DictionaryNode
from app.services.session_store_base import (
    MAX_SESSIONS,
    Session,
    SessionStoreBase,
    deserialize_session,
    serialize_session,
)

logger = logging.getLogger(__name__)


class SqliteSessionStore(SessionStoreBase):
    """Thread-safe SQLite-backed session store with TTL cleanup.

    Each session is stored as a JSON blob in the ``sessions`` table.
    Columns: id (TEXT PK), data (TEXT JSON), created_at (TEXT ISO-8601),
    last_accessed (TEXT ISO-8601).

    The database file and tables are auto-created on first use.
    WAL mode is enabled for better concurrent read performance.
    """

    def __init__(
        self,
        db_path: str = "data/sessions.db",
        ttl_seconds: int = 7200,
    ) -> None:
        super().__init__(ttl_seconds=ttl_seconds)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._local = threading.local()
        self._init_db()

    # ── Connection management ─────────────────────────────────

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local SQLite connection.

        Each thread gets its own connection (SQLite requirement).
        WAL mode is enabled for better concurrent read performance.
        """
        if not hasattr(self._local, "conn") or self._local.conn is None:
            path = Path(self._db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_accessed TEXT NOT NULL
            )
        """)
        conn.commit()

    def close(self) -> None:
        """Close the thread-local database connection."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    # ── CRUD operations ────────────────────────────────────────

    def create(self, session_id: Optional[str] = None) -> Session:
        """Create a new empty session."""
        session = Session(id=session_id) if session_id else Session()
        with self._lock:
            self._maybe_cleanup()
            conn = self._get_connection()
            conn.execute(
                "INSERT OR REPLACE INTO sessions (id, data, created_at, last_accessed) VALUES (?, ?, ?, ?)",
                (
                    session.id,
                    serialize_session(session),
                    session.created_at.isoformat(),
                    session.last_accessed.isoformat(),
                ),
            )
            conn.commit()
        return session

    def get(self, session_id: str) -> Optional[Session]:
        """Retrieve a session by ID. Returns None if not found or expired."""
        with self._lock:
            conn = self._get_connection()
            row = conn.execute(
                "SELECT data FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            session = deserialize_session(row[0])
            if session.is_expired(self._ttl_seconds):
                conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                conn.commit()
                return None
            session.touch()
            conn.execute(
                "UPDATE sessions SET data = ?, last_accessed = ? WHERE id = ?",
                (serialize_session(session), session.last_accessed.isoformat(), session_id),
            )
            conn.commit()
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
            conn = self._get_connection()
            conn.execute(
                "UPDATE sessions SET data = ?, last_accessed = ? WHERE id = ?",
                (serialize_session(session), session.last_accessed.isoformat(), session.id),
            )
            conn.commit()

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if found."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
            return cursor.rowcount > 0

    def list_sessions(self) -> List[str]:
        """List all session IDs."""
        with self._lock:
            conn = self._get_connection()
            rows = conn.execute("SELECT id FROM sessions").fetchall()
            return [row[0] for row in rows]

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
            conn = self._get_connection()
            rows = conn.execute("SELECT data FROM sessions").fetchall()
            for (data_str,) in rows:
                try:
                    session = deserialize_session(data_str)
                except Exception:
                    continue
                if not session.is_expired(self._ttl_seconds):
                    analysis = session.analyses.get(analysis_id)
                    if analysis is not None:
                        return analysis
        return None

    # ── Cleanup ────────────────────────────────────────────────

    def _maybe_cleanup(self) -> None:
        """Remove expired sessions if above threshold. Must be called under lock."""
        conn = self._get_connection()
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        if count < MAX_SESSIONS:
            return
        self._delete_expired(conn)

    def _delete_expired(self, conn: sqlite3.Connection) -> List[str]:
        """Delete expired sessions from DB. Returns list of deleted IDs."""
        cutoff = (datetime.now() - timedelta(seconds=self._ttl_seconds)).isoformat()
        cursor = conn.execute(
            "DELETE FROM sessions WHERE last_accessed < ?", (cutoff,)
        )
        conn.commit()
        deleted_count = cursor.rowcount
        if deleted_count > 0:
            logger.info("Cleaned up %d expired sessions", deleted_count)
        return []

    def cleanup_expired(self) -> int:
        """Force cleanup of all expired sessions. Returns count removed."""
        with self._lock:
            conn = self._get_connection()
            cutoff = (datetime.now() - timedelta(seconds=self._ttl_seconds)).isoformat()
            cursor = conn.execute(
                "DELETE FROM sessions WHERE last_accessed < ?", (cutoff,)
            )
            conn.commit()
            return cursor.rowcount


# ═══════════════════════════════════════════════════════════
# BatchStore — SQLite-backed
# ═══════════════════════════════════════════════════════════


class BatchStore:
    """Thread-safe SQLite-backed store for batch analysis status.

    Batches are stored as JSON-serialized blobs in the ``batches`` table.
    """

    def __init__(self, db_path: str = "data/sessions.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local SQLite connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            path = Path(self._db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        """Create batches table if it doesn't exist."""
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batches (
                batch_id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        conn.commit()

    def close(self) -> None:
        """Close the thread-local database connection."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    def create(self, batch: BatchAnalysisResponse) -> None:
        """Store a new batch."""
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                "INSERT INTO batches (batch_id, data) VALUES (?, ?)",
                (batch.batch_id, batch.model_dump_json()),
            )
            conn.commit()

    def get(self, batch_id: str) -> Optional[BatchAnalysisResponse]:
        """Retrieve a batch by ID. Returns None if not found."""
        with self._lock:
            conn = self._get_connection()
            row = conn.execute(
                "SELECT data FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if row is None:
                return None
            return BatchAnalysisResponse.model_validate_json(row[0])

    def update(self, batch: BatchAnalysisResponse) -> None:
        """Update an existing batch in the store."""
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                "UPDATE batches SET data = ? WHERE batch_id = ?",
                (batch.model_dump_json(), batch.batch_id),
            )
            conn.commit()

    def delete(self, batch_id: str) -> bool:
        """Delete a batch. Returns True if found."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute("DELETE FROM batches WHERE batch_id = ?", (batch_id,))
            conn.commit()
            return cursor.rowcount > 0

    def cleanup_for_session(self, session_id: str) -> int:
        """Remove all batches associated with a session. Returns count removed."""
        with self._lock:
            conn = self._get_connection()
            rows = conn.execute("SELECT batch_id, data FROM batches").fetchall()
            to_remove: list[str] = []
            for batch_id, data_str in rows:
                try:
                    batch = BatchAnalysisResponse.model_validate_json(data_str)
                    if batch.session_id == session_id:
                        to_remove.append(batch_id)
                except Exception:
                    continue
            for bid in to_remove:
                conn.execute("DELETE FROM batches WHERE batch_id = ?", (bid,))
            conn.commit()
            return len(to_remove)

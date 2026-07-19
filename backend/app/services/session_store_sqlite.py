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

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models import AnalysisResponse, BatchAnalysisResponse, DictionaryNode
from app.services.session_store_base import (
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
        max_sessions: int = 100,
        cache_size_kb: int = 524288,  # 512 MB default
    ) -> None:
        super().__init__(ttl_seconds=ttl_seconds, max_sessions=max_sessions)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._local = threading.local()
        self._write_count = 0
        self._auto_vacuum_ensured = False
        self._cache_size_kb = cache_size_kb
        self._init_db()

    # ── Connection management ─────────────────────────────────

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local SQLite connection.

        Each thread gets its own connection (SQLite requirement).
        WAL mode is enabled for better concurrent read performance.
        Connection-level pragmas (mmap_size, cache_size, synchronous,
        temp_store, journal_size_limit) are set on every new connection.
        """
        if not hasattr(self._local, "conn") or self._local.conn is None:
            path = Path(self._db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), check_same_thread=False)
            # page_size MUST be set BEFORE journal_mode or any other statement
            # that touches the database — otherwise SQLite creates the file
            # with the default page_size (4096) and subsequent PRAGMA is ignored.
            conn.execute("PRAGMA page_size = 16384")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys = ON")  # required for CASCADE deletes
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA mmap_size=268435456")       # 256 MB memory-mapped I/O
            conn.execute(f"PRAGMA cache_size={-self._cache_size_kb}")  # configurable (default 512 MB)
            conn.execute("PRAGMA temp_store=MEMORY")          # temp tables in RAM
            conn.execute("PRAGMA journal_size_limit=67108864")  # 64 MB WAL cap
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        """Create tables if they don't exist.

        Sets persistent PRAGMAs (auto_vacuum, page_size) BEFORE any tables
        are created so they take effect immediately for new databases.
        For existing databases, runs a one-time VACUUM migration to enable
        auto_vacuum=INCREMENTAL (see :meth:`_ensure_auto_vacuum`).

        Creates the ``sessions`` table (primary session storage) plus the
        Track B mining tables (``mining_jobs``, ``mining_corpus``,
        ``mining_fn_candidates``, ``mining_audit_results``,
        ``mining_checkpoints``). The mining tables are managed by the
        sibling :class:`MiningStore` class but are created here to keep a
        single source of truth for schema migrations on first connect.
        """
        conn = self._get_connection()
        # Persistent PRAGMAs — must be set BEFORE any tables are created
        # so they take effect for a newly created database file.
        conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
        conn.execute("PRAGMA page_size = 16384")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_accessed TEXT NOT NULL
            )
        """)
        # P4 Level 2 — normalized dictionaries table (foreign-key CASCADE).
        # Each dictionary root is stored as a separate row keyed by (session_id, name).
        # This keeps the sessions.data JSON small (no 62 MB blob) and enables:
        #   - fast GET /api/sessions (list) without parsing dictionaries
        #   - fast GET /api/dictionary/{session_id}/{name} without loading all dicts
        #   - ON DELETE CASCADE so session deletion cleans up dictionaries
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dictionaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                name TEXT NOT NULL,
                node_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (session_id, name),
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dictionaries_session ON dictionaries(session_id)"
        )
        # Track B mining schema (additive — sessions table NOT modified).
        _create_mining_tables(conn)
        conn.commit()
        # One-time auto_vacuum migration for existing databases.
        # (Runs VACUUM only once per store lifetime.)
        if not self._auto_vacuum_ensured:
            self._ensure_auto_vacuum()
            self._auto_vacuum_ensured = True

    def _ensure_auto_vacuum(self) -> None:
        """Migrate an existing database to auto_vacuum=INCREMENTAL and page_size=16384.

        Checks ``PRAGMA auto_vacuum`` on the current database.  If it is not
        already 2 (INCREMENTAL), sets the pragma and runs a full VACUUM so
        that the new setting takes effect.  Also re-applies ``page_size``
        so that an existing database with the default 4096-byte pages is
        migrated to 16384 during the VACUUM.  Truncates the WAL.

        Graceful on failure: logs a warning but does **not** prevent the
        store from operating (the DB continues without auto_vacuum).
        The VACUUM will be attempted again on the next server start.
        """
        conn = self._get_connection()
        try:
            current = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
            if current == 2:
                return
            logger.warning(
                "DB auto_vacuum=%d (expected 2=INCREMENTAL). "
                "Running one-time VACUUM to migrate.",
                current,
            )
            # Both PRAGMAs must be set BEFORE VACUUM so that the
            # VACUUM rebuilds the database with the new settings.
            conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
            conn.execute("PRAGMA page_size = 16384")
            conn.execute("VACUUM")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.commit()
            logger.info(
                "VACUUM migration complete. auto_vacuum is now INCREMENTAL, "
                "page_size is 16384."
            )
        except sqlite3.OperationalError as exc:
            logger.error(
                "VACUUM migration failed (%s). "
                "DB continues without auto_vacuum. "
                "Will retry on next server start.",
                exc,
            )

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
                    serialize_session(session, include_dictionaries=False),
                    session.created_at.isoformat(),
                    session.last_accessed.isoformat(),
                ),
            )
            conn.commit()
            self._write_count += 1
            if self._write_count % 100 == 0:
                self._maybe_incremental_vacuum(conn)
        return session

    def get(self, session_id: str, include_dictionaries: bool = True) -> Optional[Session]:
        """Retrieve a session by ID. Returns None if not found or expired.

        Args:
            session_id: Session identifier.
            include_dictionaries: When True (default), loads dictionaries from
                the ``dictionaries`` table and attaches them to the returned
                Session. When False, returns Session with empty
                ``dictionaries={}`` — used by :meth:`get_analysis` and
                :meth:`update_analysis_llm` which do not need dictionary data.
        """
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
                self._write_count += 1
                self._maybe_incremental_vacuum(conn)
                return None
            session.touch()
            conn.execute(
                "UPDATE sessions SET data = ?, last_accessed = ? WHERE id = ?",
                (
                    serialize_session(session, include_dictionaries=False),
                    session.last_accessed.isoformat(),
                    session_id,
                ),
            )
            conn.commit()
            self._write_count += 1
            if self._write_count % 100 == 0:
                self._maybe_incremental_vacuum(conn)
            # Load dictionaries from the normalized table (unless caller
            # explicitly asked to skip — e.g. get_analysis / update_analysis_llm).
            if include_dictionaries:
                session.dictionaries = self._load_dictionaries(session_id)
            return session

    def get_or_create(self, session_id: Optional[str] = None) -> Session:
        """Get an existing session or create a new one."""
        if session_id:
            existing = self.get(session_id)
            if existing is not None:
                return existing
        return self.create()

    def update(self, session: Session) -> None:
        """Update a session in the store.

        Saves the session metadata (id, created_at, last_accessed, dialog,
        analyses, metadata) as a compact JSON blob in ``sessions.data``
        and separately persists all dictionaries into the ``dictionaries``
        table (P4 Level 2 normalization).
        """
        session.touch()
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                "UPDATE sessions SET data = ?, last_accessed = ? WHERE id = ?",
                (
                    serialize_session(session, include_dictionaries=False),
                    session.last_accessed.isoformat(),
                    session.id,
                ),
            )
            # Persist dictionaries into the normalized table. This is an
            # upsert: existing rows for this session are replaced so that
            # dictionary edits (rename, delete, condition changes) are
            # reflected. For very large dictionaries this is O(N) but runs
            # in a single transaction.
            self._save_dictionaries(conn, session.id, session.dictionaries)
            conn.commit()
            self._write_count += 1
            if self._write_count % 100 == 0:
                self._maybe_incremental_vacuum(conn)

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if found."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
            self._write_count += 1
            if self._write_count % 100 == 0:
                self._maybe_incremental_vacuum(conn)
            return cursor.rowcount > 0

    def list_sessions(self) -> List[str]:
        """List all session IDs."""
        with self._lock:
            conn = self._get_connection()
            rows = conn.execute("SELECT id FROM sessions").fetchall()
            return [row[0] for row in rows]

    def list_sessions_summary(self) -> List[Dict[str, Any]]:
        """Return lightweight summaries for all sessions (read-only).

        Unlike :meth:`get`, this does NOT update ``last_accessed`` and does
        not trigger TTL refresh — safe for listing/discovery endpoints.

        P4 Level 2: dictionary count is fetched via a SQL LEFT JOIN on the
        ``dictionaries`` table instead of parsing the session JSON blob.
        This avoids loading multi-megabyte dictionary payloads just to
        count them.

        Each entry: ``{session_id, created_at, turn_count, has_dictionary,
        dictionary_count}``.
        """
        with self._lock:
            conn = self._get_connection()
            rows = conn.execute(
                """
                SELECT s.id, s.created_at, s.data,
                       (SELECT COUNT(*) FROM dictionaries d WHERE d.session_id = s.id) AS dict_count
                FROM sessions s
                """
            ).fetchall()
        summaries: List[Dict[str, Any]] = []
        for sid, created_at, data_str, dict_count in rows:
            turn_count = 0
            try:
                blob = json.loads(data_str)
                dialog = blob.get("dialog")
                if dialog is not None:
                    turns = dialog.get("turns")
                    if isinstance(turns, list):
                        turn_count = len(turns)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "list_sessions_summary: failed to parse session '%s': %s",
                    sid, exc,
                )
            summaries.append(
                {
                    "session_id": sid,
                    "created_at": created_at,
                    "turn_count": turn_count,
                    "has_dictionary": dict_count > 0,
                    "dictionary_count": dict_count,
                }
            )
        return summaries

    def add_dictionary(self, session_id: str, dictionary: DictionaryNode) -> Optional[Session]:
        """Add a dictionary to a session. Returns updated session or None.

        P4 Level 2: dictionaries are stored in the normalized
        ``dictionaries`` table. This method performs a direct INSERT OR
        REPLACE on that table without rewriting the session JSON blob,
        which is O(1) for a single dictionary regardless of how many
        other dictionaries the session has.
        """
        with self._lock:
            conn = self._get_connection()
            # Verify the session exists
            row = conn.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            now = datetime.now().isoformat()
            node_json = dictionary.model_dump_json(
                exclude_defaults=True, exclude_none=True
            )
            conn.execute(
                """
                INSERT INTO dictionaries (session_id, name, node_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id, name) DO UPDATE SET node_json = excluded.node_json
                """,
                (session_id, dictionary.name, node_json, now),
            )
            conn.commit()
            self._write_count += 1
            if self._write_count % 100 == 0:
                self._maybe_incremental_vacuum(conn)
        # Return the session with dictionaries loaded so callers see the new dict
        return self.get(session_id)

    def get_dictionary(self, session_id: str, dict_name: str) -> Optional[DictionaryNode]:
        """Get a specific dictionary from a session.

        P4 Level 2: performs a direct SELECT on the ``dictionaries`` table
        keyed by (session_id, name). This is O(log N) via the UNIQUE index
        instead of O(N) deserialization of the entire session JSON blob.
        """
        with self._lock:
            conn = self._get_connection()
            row = conn.execute(
                "SELECT node_json FROM dictionaries WHERE session_id = ? AND name = ?",
                (session_id, dict_name),
            ).fetchone()
        if row is None:
            return None
        return DictionaryNode.model_validate_json(row[0])

    # ── Dictionary table helpers (P4 Level 2) ─────────────────

    def _save_dictionaries(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        dictionaries: Dict[str, DictionaryNode],
    ) -> None:
        """Replace all dictionaries for a session in a single transaction.

        Used by :meth:`update` to persist the full set of dictionaries after
        edits (rename, delete, condition changes). Deletes existing rows for
        the session and re-inserts the current set. Runs in the caller's
        transaction — does NOT commit.
        """
        conn.execute(
            "DELETE FROM dictionaries WHERE session_id = ?", (session_id,)
        )
        now = datetime.now().isoformat()
        for name, node in dictionaries.items():
            node_json = node.model_dump_json(
                exclude_defaults=True, exclude_none=True
            )
            conn.execute(
                """
                INSERT INTO dictionaries (session_id, name, node_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, name, node_json, now),
            )

    def _load_dictionaries(self, session_id: str) -> Dict[str, DictionaryNode]:
        """Load all dictionaries for a session from the normalized table.

        Used by :meth:`get` when ``include_dictionaries=True``. Returns
        an empty dict if the session has no dictionaries or does not exist.
        """
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT name, node_json FROM dictionaries WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        result: Dict[str, DictionaryNode] = {}
        for name, node_json in rows:
            try:
                result[name] = DictionaryNode.model_validate_json(node_json)
            except Exception as exc:
                logger.warning(
                    "Failed to deserialize dictionary '%s' for session '%s': %s",
                    name, session_id, exc,
                )
        return result

    def add_analysis(self, session_id: str, analysis: AnalysisResponse) -> Optional[Session]:
        """Add an analysis result to a session. Returns updated session or None."""
        session = self.get(session_id)
        if session is None:
            return None
        session.analyses[analysis.analysis_id] = analysis
        self.update(session)
        return session

    def get_analysis(self, analysis_id: str) -> Optional[AnalysisResponse]:
        """Find an analysis across all sessions by its ID.

        P4 Level 2: iterates over session JSON blobs WITHOUT loading
        dictionaries (they live in a separate table). This makes
        get_analysis O(sessions) instead of O(sessions × dictionaries)
        — a major speedup when searching for an analysis ID across
        100 sessions each with multi-megabyte dictionaries.
        """
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
        if count < self._max_sessions:
            return
        self._delete_expired(conn)

    def _delete_expired(self, conn: sqlite3.Connection) -> List[str]:
        """Delete expired sessions from DB. Returns list of deleted IDs."""
        cutoff = (datetime.now() - timedelta(seconds=self._ttl_seconds)).isoformat()
        cursor = conn.execute(
            "DELETE FROM sessions WHERE last_accessed < ? "
            "RETURNING id",
            (cutoff,),
        )
        deleted_ids = [row[0] for row in cursor.fetchall()]
        conn.commit()
        deleted_count = len(deleted_ids)
        self._write_count += 1
        if deleted_count > 0:
            logger.info("Cleaned up %d expired sessions", deleted_count)
            self._maybe_incremental_vacuum(conn)
        return deleted_ids

    def cleanup_expired(self) -> int:
        """Force cleanup of all expired sessions. Returns count removed."""
        with self._lock:
            conn = self._get_connection()
            cutoff = (datetime.now() - timedelta(seconds=self._ttl_seconds)).isoformat()
            cursor = conn.execute(
                "DELETE FROM sessions WHERE last_accessed < ?", (cutoff,)
            )
            conn.commit()
            removed = cursor.rowcount
            self._write_count += 1
            if removed > 0:
                self._maybe_incremental_vacuum(conn)
            return removed

    def vacuum(self) -> None:
        """Full VACUUM of the database + WAL checkpoint truncation.

        Safe to call on an empty or dormant database — VACUUM on a
        freshly-created DB with no deleted pages is nearly instant.

        This method is **not** intended for hot-path use (it blocks all
        writes for the duration).  Designed for:
          - Application shutdown (see ``backend/app/main.py`` lifespan)
          - Scheduled maintenance windows
          - One-time migration after schema changes
        """
        with self._lock:
            try:
                conn = self._get_connection()
                conn.execute("VACUUM")
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.commit()
                self._write_count = 0
                logger.info("Session DB vacuumed successfully")
            except sqlite3.OperationalError as exc:
                logger.warning("Session DB vacuum failed: %s", exc)

    def _maybe_incremental_vacuum(self, conn: sqlite3.Connection) -> None:
        """Reclaim free pages via incremental_vacuum when threshold is reached.

        Checks ``PRAGMA freelist_count`` and runs ``PRAGMA
        incremental_vacuum(N)`` if there are more than 50 free pages.
        Up to 100 pages are reclaimed per call.

        The check is cheap — ``freelist_count`` is a header read — and
        ``incremental_vacuum`` is a no-op when the freelist is empty.
        """
        try:
            freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
            if freelist > 50:
                conn.execute("PRAGMA incremental_vacuum(100)")
                logger.debug(
                    "Incremental vacuum: freelist=%d → reclaimed up to 100 pages",
                    freelist,
                )
        except sqlite3.OperationalError as exc:
            logger.warning("Incremental vacuum failed: %s", exc)


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



# ═══════════════════════════════════════════════════════════
# Mining schema (Track B — additive extension of SqliteSessionStore._init_db)
# ═══════════════════════════════════════════════════════════


_MINING_SCHEMA_SQL: List[str] = [
    """
    CREATE TABLE IF NOT EXISTS mining_jobs (
        job_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        dictionary_id TEXT NOT NULL,
        directory_path TEXT NOT NULL,
        job_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        started_at TEXT NOT NULL,
        completed_at TEXT,
        checkpoint_at TEXT,
        total_dialogues INTEGER DEFAULT 0,
        processed_dialogues INTEGER DEFAULT 0,
        error TEXT,
        warning TEXT,
        result_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mining_corpus (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        dialogue_id TEXT NOT NULL,
        file_path TEXT NOT NULL,
        channel TEXT,
        text TEXT NOT NULL,
        embedding_id INTEGER,
        turn_count INTEGER DEFAULT 0,
        llm_summary TEXT,
        llm_label TEXT,
        llm_score REAL,
        llm_reason TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mining_fn_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        dialogue_id TEXT NOT NULL,
        phrase_group_id TEXT,
        score REAL NOT NULL,
        llm_label TEXT NOT NULL,
        llm_score REAL,
        llm_reason TEXT,
        proposed_phrase TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mining_audit_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        phrase_group_id TEXT NOT NULL,
        phrase_text TEXT,
        recall REAL,
        missed_count INTEGER DEFAULT 0,
        recommendations_json TEXT,
        llm_explanation TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mining_checkpoints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        checkpoint_at TEXT NOT NULL,
        processed_count INTEGER NOT NULL,
        last_dialogue_id TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mining_corpus_job ON mining_corpus(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_mining_fn_job ON mining_fn_candidates(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_mining_audit_job ON mining_audit_results(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_mining_checkpoints_job ON mining_checkpoints(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_mining_jobs_session_dict ON mining_jobs(session_id, dictionary_id)",
]


def _create_mining_tables(conn: sqlite3.Connection) -> None:
    """Create the Track B mining tables if they don't exist. Additive only.

    Called by :meth:SqliteSessionStore._init_db (and by :class:MiningStore
    on its own connection). Idempotent: uses `IF NOT EXISTS`.
    """
    for stmt in _MINING_SCHEMA_SQL:
        conn.execute(stmt)


# ═══════════════════════════════════════════════════════════
# MiningStore — SQLite-backed store for offline corpus mining jobs
# ═══════════════════════════════════════════════════════════


class MiningStore:
    """Thread-safe SQLite-backed store for Track B mining jobs + corpus + results.

    Shares the same db_path as :class:SqliteSessionStore (single WAL-mode DB
    file, separate thread-local connections per store instance). Schema is
    created by :func:_create_mining_tables on first connect.

    Stores:
      - `mining_jobs`         — job lifecycle (pending|running|completed|failed|partial|cancelled)
      - `mining_corpus`       — parsed RTF dialogues indexed per job
      - `mining_fn_candidates` — FN discovery results (LLM-verified)
      - `mining_audit_results` — per-PhraseGroup audit results
      - `mining_checkpoints`  — checkpoint/resume log (every 25 dialogues)
    """

    def __init__(self, db_path: str = "data/sessions.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._local = threading.local()
        self._init_db()

    # ── Connection management ─────────────────────────────────

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local SQLite connection (WAL mode, 5s busy timeout)."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            path = Path(self._db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        """Create mining tables on this connection's thread."""
        conn = self._get_connection()
        _create_mining_tables(conn)
        conn.commit()

    def close(self) -> None:
        """Close the thread-local database connection."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    # ── Jobs ──────────────────────────────────────────────────

    def create_job(
        self,
        job_id: str,
        session_id: str,
        dictionary_id: str,
        directory_path: str,
        job_type: str,
    ) -> Dict[str, Any]:
        """Insert a new mining job row with status='pending'."""
        now = datetime.now().isoformat()
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                """
                INSERT INTO mining_jobs
                    (job_id, session_id, dictionary_id, directory_path,
                     job_type, status, started_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (job_id, session_id, dictionary_id, directory_path, job_type, now),
            )
            conn.commit()
        return {
            "job_id": job_id,
            "session_id": session_id,
            "dictionary_id": dictionary_id,
            "directory_path": directory_path,
            "job_type": job_type,
            "status": "pending",
            "started_at": now,
            "completed_at": None,
            "checkpoint_at": None,
            "total_dialogues": 0,
            "processed_dialogues": 0,
            "error": None,
            "warning": None,
            "result_json": None,
        }

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a job row by job_id (or None if not found)."""
        with self._lock:
            conn = self._get_connection()
            row = conn.execute(
                """
                SELECT job_id, session_id, dictionary_id, directory_path,
                       job_type, status, started_at, completed_at, checkpoint_at,
                       total_dialogues, processed_dialogues, error, warning,
                       result_json
                FROM mining_jobs WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "job_id": row[0],
            "session_id": row[1],
            "dictionary_id": row[2],
            "directory_path": row[3],
            "job_type": row[4],
            "status": row[5],
            "started_at": row[6],
            "completed_at": row[7],
            "checkpoint_at": row[8],
            "total_dialogues": row[9],
            "processed_dialogues": row[10],
            "error": row[11],
            "warning": row[12],
            "result_json": row[13],
        }

    def find_running_job(
        self,
        session_id: str,
        dictionary_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return any pending/running job for (session_id, dictionary_id).

        Used to detect duplicate indexing (409 Conflict in router).
        """
        with self._lock:
            conn = self._get_connection()
            row = conn.execute(
                """
                SELECT job_id, session_id, dictionary_id, directory_path,
                       job_type, status, started_at, completed_at, checkpoint_at,
                       total_dialogues, processed_dialogues, error, warning,
                       result_json
                FROM mining_jobs
                WHERE session_id = ? AND dictionary_id = ?
                  AND status IN ('pending', 'running')
                LIMIT 1
                """,
                (session_id, dictionary_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "job_id": row[0],
            "session_id": row[1],
            "dictionary_id": row[2],
            "directory_path": row[3],
            "job_type": row[4],
            "status": row[5],
            "started_at": row[6],
            "completed_at": row[7],
            "checkpoint_at": row[8],
            "total_dialogues": row[9],
            "processed_dialogues": row[10],
            "error": row[11],
            "warning": row[12],
            "result_json": row[13],
        }

    def update_job(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        total_dialogues: Optional[int] = None,
        processed_dialogues: Optional[int] = None,
        checkpoint_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        error: Optional[str] = None,
        warning: Optional[str] = None,
        result_json: Optional[str] = None,
    ) -> bool:
        """Update one or more fields on a job row. Returns True if updated."""
        sets: List[str] = []
        params: List[Any] = []
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if total_dialogues is not None:
            sets.append("total_dialogues = ?")
            params.append(total_dialogues)
        if processed_dialogues is not None:
            sets.append("processed_dialogues = ?")
            params.append(processed_dialogues)
        if checkpoint_at is not None:
            sets.append("checkpoint_at = ?")
            params.append(checkpoint_at)
        if completed_at is not None:
            sets.append("completed_at = ?")
            params.append(completed_at)
        if error is not None:
            sets.append("error = ?")
            params.append(error)
        if warning is not None:
            sets.append("warning = ?")
            params.append(warning)
        if result_json is not None:
            sets.append("result_json = ?")
            params.append(result_json)
        if not sets:
            return False
        params.append(job_id)
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                f"UPDATE mining_jobs SET {', '.join(sets)} WHERE job_id = ?",
                params,
            )
            conn.commit()
            return cursor.rowcount > 0

    def cancel_job(self, job_id: str) -> bool:
        """Mark a job as cancelled. Returns True if the job existed."""
        return self.update_job(job_id, status="cancelled")

    # ── Corpus ────────────────────────────────────────────────

    def add_corpus_entry(
        self,
        job_id: str,
        dialogue_id: str,
        file_path: str,
        text: str,
        channel: str = "ANY",
        turn_count: int = 0,
        embedding_id: Optional[int] = None,
        llm_summary: Optional[str] = None,
        llm_label: Optional[str] = None,
        llm_score: Optional[float] = None,
        llm_reason: Optional[str] = None,
    ) -> int:
        """Insert a corpus dialogue row. Returns the new row id."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                """
                INSERT INTO mining_corpus
                    (job_id, dialogue_id, file_path, channel, text,
                     embedding_id, turn_count, llm_summary, llm_label,
                     llm_score, llm_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id, dialogue_id, file_path, channel, text,
                    embedding_id, turn_count, llm_summary, llm_label,
                    llm_score, llm_reason,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)

    def list_corpus(self, job_id: str) -> List[Dict[str, Any]]:
        """List all corpus dialogues for a job."""
        with self._lock:
            conn = self._get_connection()
            rows = conn.execute(
                """
                SELECT id, job_id, dialogue_id, file_path, channel, text,
                       embedding_id, turn_count, llm_summary, llm_label,
                       llm_score, llm_reason
                FROM mining_corpus WHERE job_id = ?
                """,
                (job_id,),
            ).fetchall()
        return [
            {
                "id": r[0], "job_id": r[1], "dialogue_id": r[2],
                "file_path": r[3], "channel": r[4], "text": r[5],
                "embedding_id": r[6], "turn_count": r[7],
                "llm_summary": r[8], "llm_label": r[9],
                "llm_score": r[10], "llm_reason": r[11],
            }
            for r in rows
        ]

    # ── FN candidates ─────────────────────────────────────────

    def add_fn_candidate(
        self,
        job_id: str,
        dialogue_id: str,
        score: float,
        llm_label: str,
        phrase_group_id: Optional[str] = None,
        llm_score: Optional[float] = None,
        llm_reason: Optional[str] = None,
        proposed_phrase: Optional[str] = None,
    ) -> int:
        """Insert a false-negative candidate row. Returns the new row id."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                """
                INSERT INTO mining_fn_candidates
                    (job_id, dialogue_id, phrase_group_id, score, llm_label,
                     llm_score, llm_reason, proposed_phrase)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id, dialogue_id, phrase_group_id, score, llm_label,
                    llm_score, llm_reason, proposed_phrase,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)

    def list_fn_candidates(self, job_id: str) -> List[Dict[str, Any]]:
        """List all FN candidates for a job."""
        with self._lock:
            conn = self._get_connection()
            rows = conn.execute(
                """
                SELECT id, job_id, dialogue_id, phrase_group_id, score,
                       llm_label, llm_score, llm_reason, proposed_phrase
                FROM mining_fn_candidates WHERE job_id = ?
                """,
                (job_id,),
            ).fetchall()
        return [
            {
                "id": r[0], "job_id": r[1], "dialogue_id": r[2],
                "phrase_group_id": r[3], "score": r[4], "llm_label": r[5],
                "llm_score": r[6], "llm_reason": r[7],
                "proposed_phrase": r[8],
            }
            for r in rows
        ]

    # ── Audit results ─────────────────────────────────────────

    def add_audit_result(
        self,
        job_id: str,
        phrase_group_id: str,
        phrase_text: str,
        recall: float,
        missed_count: int,
        recommendations_json: str,
        llm_explanation: str,
    ) -> int:
        """Insert a per-PhraseGroup audit result row."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                """
                INSERT INTO mining_audit_results
                    (job_id, phrase_group_id, phrase_text, recall, missed_count,
                     recommendations_json, llm_explanation)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id, phrase_group_id, phrase_text, recall, missed_count,
                    recommendations_json, llm_explanation,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)

    def list_audit_results(self, job_id: str) -> List[Dict[str, Any]]:
        """List all audit results for a job."""
        with self._lock:
            conn = self._get_connection()
            rows = conn.execute(
                """
                SELECT id, job_id, phrase_group_id, phrase_text, recall,
                       missed_count, recommendations_json, llm_explanation
                FROM mining_audit_results WHERE job_id = ?
                """,
                (job_id,),
            ).fetchall()
        return [
            {
                "id": r[0], "job_id": r[1], "phrase_group_id": r[2],
                "phrase_text": r[3], "recall": r[4], "missed_count": r[5],
                "recommendations_json": r[6], "llm_explanation": r[7],
            }
            for r in rows
        ]

    # ── Checkpoints ───────────────────────────────────────────

    def add_checkpoint(
        self,
        job_id: str,
        processed_count: int,
        last_dialogue_id: Optional[str],
    ) -> None:
        """Insert a checkpoint row + update the job's checkpoint_at/processed_dialogues."""
        now = datetime.now().isoformat()
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                """
                INSERT INTO mining_checkpoints
                    (job_id, checkpoint_at, processed_count, last_dialogue_id)
                VALUES (?, ?, ?, ?)
                """,
                (job_id, now, processed_count, last_dialogue_id),
            )
            conn.execute(
                """
                UPDATE mining_jobs
                SET checkpoint_at = ?, processed_dialogues = ?
                WHERE job_id = ?
                """,
                (now, processed_count, job_id),
            )
            conn.commit()

    def get_last_checkpoint(self, job_id: str) -> Optional[int]:
        """Return last checkpoint's processed_count, or None if no checkpoint exists."""
        with self._lock:
            conn = self._get_connection()
            row = conn.execute(
                """
                SELECT MAX(processed_count) FROM mining_checkpoints WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])

    def get_progress(self, job_id: str) -> Optional[int]:
        """Return current processed_dialogues for a job (None if job missing)."""
        with self._lock:
            conn = self._get_connection()
            row = conn.execute(
                "SELECT processed_dialogues FROM mining_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return int(row[0])

    # ── JSON helpers ──────────────────────────────────────────

    def verify_tables_exist(self, table_names: List[str]) -> Dict[str, bool]:
        """Check existence of named tables in the mining DB (read-only).

        Returns a mapping ``{table_name: exists_bool}``. Used by the health
        check to detect a missing mining schema (e.g. after DB recreation).
        """
        if not table_names:
            return {}
        placeholders = ", ".join("?" for _ in table_names)
        with self._lock:
            conn = self._get_connection()
            rows = conn.execute(
                f"SELECT name FROM sqlite_master WHERE type='table' "
                f"AND name IN ({placeholders})",
                table_names,
            ).fetchall()
        existing = {r[0] for r in rows}
        return {name: (name in existing) for name in table_names}

    @staticmethod
    def dump_json(value: Any) -> str:
        """Serialise any JSON-compatible value to a string."""
        return json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def load_json(text: Optional[str]) -> Any:
        """Parse a JSON string. Returns None for empty/None input."""
        if not text:
            return None
        try:
            return json.loads(text)
        except (ValueError, TypeError) as exc:
            logger.warning("MiningStore.load_json: failed to parse: %s", exc)
            return None

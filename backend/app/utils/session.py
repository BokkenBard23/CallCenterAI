"""Session storage factory and singleton instances.

Provides:
  - ``session_store`` — singleton SessionStoreBase instance (SQLite or memory)
  - ``batch_store``   — singleton BatchStore instance (always SQLite)
  - Re-exports of Session dataclass and serialization helpers

The backend is selected via ``settings.session_backend``:
  - ``"sqlite"``  (default) — persistent, survives restarts
  - ``"memory"`` — volatile, lost on restart (dev / fallback)

If SQLite fails to initialize (permissions, disk full, etc.), the factory
automatically falls back to the memory backend with a WARNING log.
All existing imports from ``app.utils.session`` continue to work unchanged.
"""

from __future__ import annotations

import logging

from app.services.session_store_base import (
    Session,
    SessionStoreBase,
    deserialize_session,
    serialize_session,
)
from app.services.session_store_sqlite import SqliteSessionStore as SessionStore
from app.services.session_store_sqlite import BatchStore

logger = logging.getLogger(__name__)


def _get_db_path() -> str:
    """Get the database path from config, with fallback."""
    try:
        from app.config import settings
        return str(settings.session_db_path)
    except Exception:
        return "data/sessions.db"


def _get_ttl_seconds() -> int:
    """Get session TTL from config, with fallback."""
    try:
        from app.config import settings
        return settings.session_ttl_seconds
    except Exception:
        return 7200


def _get_max_sessions() -> int:
    """Get max sessions from config, with fallback."""
    try:
        from app.config import settings
        return settings.max_sessions
    except Exception:
        return 100


def _get_cache_size_kb() -> int:
    """Get SQLite cache size (KB) from config, with fallback."""
    try:
        from app.config import settings
        return settings.sqlite_cache_size_kb
    except Exception:
        return 524288  # 512 MB default


def create_session_store() -> SessionStoreBase:
    """Factory: create the configured session store backend.

    - ``"sqlite"``  → SqliteSessionStore (persistent)
    - ``"memory"``  → MemorySessionStore (volatile)

    On SQLite initialization failure, falls back to memory with WARNING.
    """
    try:
        from app.config import settings
        backend = settings.session_backend
    except Exception:
        backend = "sqlite"

    db_path = _get_db_path()
    ttl = _get_ttl_seconds()
    max_sessions = _get_max_sessions()
    cache_size_kb = _get_cache_size_kb()

    if backend == "memory":
        from app.services.session_store_memory import MemorySessionStore
        logger.info("Session backend: memory (configured)")
        return MemorySessionStore(ttl_seconds=ttl, max_sessions=max_sessions)

    # Default: sqlite
    try:
        from app.services.session_store_sqlite import SqliteSessionStore
        store = SqliteSessionStore(
            db_path=db_path, ttl_seconds=ttl, max_sessions=max_sessions,
            cache_size_kb=cache_size_kb,
        )
        logger.info(
            "Session backend: SQLite (db_path=%s, cache=%d KB)",
            db_path, cache_size_kb,
        )
        return store
    except Exception as exc:
        from app.services.session_store_memory import MemorySessionStore
        logger.warning(
            "SQLite session store failed to initialize (%s). "
            "Falling back to in-memory store. Sessions will NOT survive restarts.",
            exc,
        )
        return MemorySessionStore(ttl_seconds=ttl, max_sessions=max_sessions)


# ═══════════════════════════════════════════════════════════
# Singleton instances
# ═══════════════════════════════════════════════════════════

session_store = create_session_store()

# BatchStore always uses SQLite (separate concern from session backend)
try:
    from app.services.session_store_sqlite import BatchStore
    batch_store = BatchStore(db_path=_get_db_path())
except Exception:
    # If SQLite BatchStore fails, create a minimal in-memory shim
    # to avoid import-time crashes. Batch functionality will be degraded.
    logger.warning("BatchStore SQLite init failed — batch functionality may be degraded")
    batch_store = None  # type: ignore[assignment]

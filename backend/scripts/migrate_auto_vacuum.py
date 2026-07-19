#!/usr/bin/env python3
"""One-shot migration script: convert an existing sessions.db to P3-optimised settings.

**What this script does:**

1. Takes a backup of the original SQLite database file (``{db_path}.backup-{timestamp}``).
2. Validates that the file is a valid SQLite database with the expected schema.
3. Reports current database state (size, page count, page size, auto_vacuum mode, WAL size).
4. Sets new persistent PRAGMAs (auto_vacuum=INCREMENTAL, page_size=16384).
5. Runs VACUUM to apply the new settings to the on-disk structure.
6. Applies connection-level PRAGMAs (journal_size_limit, mmap_size, cache_size).
7. Truncates the WAL checkpoint.
8. Verifies the migration was successful.

**Usage:**

    # Dry-run (read-only, no changes):
    python scripts/migrate_auto_vacuum.py --dry-run

    # Full migration with default path (backend/data/sessions.db):
    python scripts/migrate_auto_vacuum.py

    # Custom DB path:
    python scripts/migrate_auto_vacuum.py --db-path /path/to/sessions.db

    # Skip backup:
    python scripts/migrate_auto_vacuum.py --no-backup

**Rollback:**

If the migration fails or causes issues, restore from backup:

    cp data/sessions.db.backup-{timestamp} data/sessions.db
    rm -f data/sessions.db-wal data/sessions.db-shm

The script itself never deletes or overwrites existing backups.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Logging ──────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("migrate_auto_vacuum")


# ── Configuration ──────────────────────────────────────────

DESIRED_PAGE_SIZE = 16384
DESIRED_AUTO_VACUUM = 2          # INCREMENTAL
DESIRED_MMAP_SIZE = 268435456    # 256 MB
DESIRED_CACHE_SIZE = -64000      # 64 MB
DESIRED_JOURNAL_SIZE_LIMIT = 67108864  # 64 MB
DESIRED_TEMP_STORE = 2           # MEMORY


# ═══════════════════════════════════════════════════════════
# Report helpers
# ═══════════════════════════════════════════════════════════


def _fmt_bytes(size: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _db_stats(db_path: str) -> dict:
    """Read current SQLite database stats via PRAGMAs."""
    stats: dict = {}
    try:
        conn = sqlite3.connect(db_path)
        stats["file_exists"] = True
        stats["file_size"] = os.path.getsize(db_path)
        stats["page_size"] = conn.execute("PRAGMA page_size").fetchone()[0]
        stats["page_count"] = conn.execute("PRAGMA page_count").fetchone()[0]
        stats["auto_vacuum"] = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        stats["freelist_count"] = conn.execute("PRAGMA freelist_count").fetchone()[0]
        stats["journal_mode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
        stats["synchronous"] = conn.execute("PRAGMA synchronous").fetchone()[0]
        stats["mmap_size"] = conn.execute("PRAGMA mmap_size").fetchone()[0]
        stats["cache_size"] = conn.execute("PRAGMA cache_size").fetchone()[0]
        stats["temp_store"] = conn.execute("PRAGMA temp_store").fetchone()[0]
        stats["journal_size_limit"] = conn.execute("PRAGMA journal_size_limit").fetchone()[0]

        # Database size accounting
        total_bytes = stats["page_count"] * stats["page_size"]
        free_bytes = stats["freelist_count"] * stats["page_size"]
        used_bytes = total_bytes - free_bytes
        stats["total_bytes"] = total_bytes
        stats["free_bytes"] = free_bytes
        stats["used_bytes"] = used_bytes

        # WAL file
        wal_path = db_path + "-wal"
        if os.path.exists(wal_path):
            stats["wal_size"] = os.path.getsize(wal_path)
        else:
            stats["wal_size"] = 0

        # Check sessions table
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchall()
        stats["has_sessions_table"] = len(tables) == 1
        if stats["has_sessions_table"]:
            count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            stats["session_count"] = count

        conn.close()
    except sqlite3.DatabaseError as exc:
        logger.error("Cannot open database '%s': %s", db_path, exc)
        stats["file_exists"] = False
        stats["error"] = str(exc)
    except FileNotFoundError:
        stats["file_exists"] = False
        stats["error"] = "File not found"

    return stats


def _print_stats(stats: dict, label: str) -> None:
    """Pretty-print database stats."""
    logger.info("─── %s ───", label)
    if not stats.get("file_exists"):
        logger.info("  Database file: %s", stats.get("error", "N/A"))
        return
    logger.info("  File size:      %s", _fmt_bytes(stats.get("file_size", 0)))
    logger.info("  Page size:      %d", stats.get("page_size", 0))
    logger.info("  Page count:     %d", stats.get("page_count", 0))
    logger.info("  Total DB size:  %s", _fmt_bytes(stats.get("total_bytes", 0)))
    logger.info("  Used pages:     %s", _fmt_bytes(stats.get("used_bytes", 0)))
    logger.info("  Free pages:     %s (%d pages)", _fmt_bytes(stats.get("free_bytes", 0)),
                 stats.get("freelist_count", 0))
    logger.info("  auto_vacuum:    %s", {0: "NONE", 1: "FULL", 2: "INCREMENTAL"}.get(stats.get("auto_vacuum", -1), "unknown"))
    logger.info("  Journal mode:   %s", stats.get("journal_mode", "?"))
    logger.info("  Synchronous:    %s", {0: "OFF", 1: "NORMAL", 2: "FULL", 3: "EXTRA"}.get(stats.get("synchronous", -1), "?"))
    logger.info("  mmap_size:      %s", _fmt_bytes(stats.get("mmap_size", 0)))
    logger.info("  cache_size:     %d KB", abs(stats.get("cache_size", 0)))
    logger.info("  temp_store:     %s", {0: "DEFAULT", 1: "FILE", 2: "MEMORY"}.get(stats.get("temp_store", -1), "?"))
    logger.info("  journal_limit:  %s", _fmt_bytes(stats.get("journal_size_limit", 0)))
    logger.info("  WAL size:       %s", _fmt_bytes(stats.get("wal_size", 0)))
    logger.info("  Sessions:       %d", stats.get("session_count", 0))


# ═══════════════════════════════════════════════════════════
# Migration logic
# ═══════════════════════════════════════════════════════════


def _validate_db(stats: dict) -> bool:
    """Validate that the DB file is suitable for migration."""
    if not stats.get("file_exists"):
        logger.error("Database file does not exist or cannot be opened.")
        return False
    if not stats.get("has_sessions_table"):
        logger.error("Database does not contain a 'sessions' table.")
        return False
    return True


def _create_backup(db_path: str) -> str | None:
    """Create a timestamped backup of the database file.

    Also backs up WAL and SHM files if they exist.
    Returns the backup path (without -wal/-shm suffix) or None on failure.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup-{timestamp}"

    try:
        logger.info("Creating backup: %s", backup_path)
        shutil.copy2(db_path, backup_path)

        # Backup WAL and SHM if they exist
        for ext in ("-wal", "-shm"):
            src = db_path + ext
            if os.path.exists(src):
                dst = backup_path + ext
                shutil.copy2(src, dst)
                logger.info("  Also backed up: %s", dst)

        logger.info("Backup created: %s (%s)", backup_path, _fmt_bytes(os.path.getsize(backup_path)))
        return backup_path
    except (IOError, OSError) as exc:
        logger.error("Backup failed: %s", exc)
        return None


def _run_migration(db_path: str, dry_run: bool = False) -> bool:
    """Execute the migration: VACUUM + pragmas. Returns True on success."""
    if dry_run:
        logger.info("DRY RUN: Would proceed with VACUUM + PRAGMA migration.")
        return True

    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA busy_timeout = 10000")  # 10s for safety

        # Step 1: Set persistent PRAGMAs (must be BEFORE VACUUM)
        logger.info("Setting PRAGMA auto_vacuum = INCREMENTAL (2)")
        conn.execute("PRAGMA auto_vacuum = 2")

        logger.info("Setting PRAGMA page_size = %d", DESIRED_PAGE_SIZE)
        conn.execute(f"PRAGMA page_size = {DESIRED_PAGE_SIZE}")

        # Step 2: VACUUM — applies page_size and auto_vacuum changes
        logger.info("Running VACUUM (this may take a while for large databases)...")
        t0 = time.time()
        conn.execute("VACUUM")
        elapsed = time.time() - t0
        logger.info("VACUUM completed in %.1f seconds", elapsed)

        # Step 3: Set connection-level PRAGMAs
        logger.info("Setting synchronous = NORMAL (1)")
        conn.execute("PRAGMA synchronous = 1")

        logger.info("Setting mmap_size = %d (%s)", DESIRED_MMAP_SIZE, _fmt_bytes(DESIRED_MMAP_SIZE))
        conn.execute(f"PRAGMA mmap_size = {DESIRED_MMAP_SIZE}")

        logger.info("Setting cache_size = %d (%d KB)", DESIRED_CACHE_SIZE, abs(DESIRED_CACHE_SIZE))
        conn.execute(f"PRAGMA cache_size = {DESIRED_CACHE_SIZE}")

        logger.info("Setting temp_store = MEMORY (2)")
        conn.execute("PRAGMA temp_store = 2")

        logger.info("Setting journal_size_limit = %d (%s)",
                     DESIRED_JOURNAL_SIZE_LIMIT, _fmt_bytes(DESIRED_JOURNAL_SIZE_LIMIT))
        conn.execute(f"PRAGMA journal_size_limit = {DESIRED_JOURNAL_SIZE_LIMIT}")

        # Step 4: WAL checkpoint
        logger.info("Running WAL checkpoint (TRUNCATE)...")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()

        conn.close()
        logger.info("Migration PRAGMAs applied successfully.")
        return True

    except sqlite3.OperationalError as exc:
        logger.error("Migration failed: %s", exc)
        logger.error("Your database is unchanged. Restore from backup if needed.")
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected migration error: %s", exc)
        return False


def _verify_migration(before: dict, after: dict) -> bool:
    """Verify that the migration produced the expected changes."""
    issues: list[str] = []

    if after.get("auto_vacuum") != 2:
        issues.append(f"auto_vacuum is {after.get('auto_vacuum')}, expected 2 (INCREMENTAL)")

    if after.get("page_size") != DESIRED_PAGE_SIZE:
        issues.append(f"page_size is {after.get('page_size')}, expected {DESIRED_PAGE_SIZE}")

    if after.get("freelist_count", 0) > 0:
        issues.append(f"freelist_count is {after.get('freelist_count')}, expected 0 after VACUUM")

    # Connection-level PRAGMAs (may differ from before if they were 0/unset)
    if after.get("mmap_size", 0) < DESIRED_MMAP_SIZE:
        issues.append(f"mmap_size is {after.get('mmap_size')}, expected ≥{DESIRED_MMAP_SIZE}")

    if after.get("synchronous", 0) != 1:
        issues.append(f"synchronous is {after.get('synchronous')}, expected 1 (NORMAL)")

    if after.get("journal_size_limit", 0) < DESIRED_JOURNAL_SIZE_LIMIT:
        issues.append(f"journal_size_limit is {after.get('journal_size_limit')}, expected ≥{DESIRED_JOURNAL_SIZE_LIMIT}")

    if issues:
        logger.warning("Verification found %d issue(s):", len(issues))
        for issue in issues:
            logger.warning("  ✗ %s", issue)
        return False

    logger.info("All PRAGMAs verified successfully.")
    return True


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate an existing SQLite sessions.db to P3-optimised settings "
                    "(auto_vacuum=INCREMENTAL, page_size=16384, WAL cap, etc.).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--db-path", "-d",
        default="data/sessions.db",
        help="Path to the SQLite database file (default: data/sessions.db)",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Read-only mode: report current state without making changes",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip backup creation (not recommended)",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )
    args = parser.parse_args()

    db_path = str(Path(args.db_path).resolve())
    if not os.path.exists(db_path):
        logger.error("Database file not found: %s", db_path)
        return 1

    # ── Phase 1: Report current state ──
    logger.info("Starting migration for: %s", db_path)
    before = _db_stats(db_path)
    _print_stats(before, "BEFORE")

    if not _validate_db(before):
        return 1

    # ── Phase 2: Dry-run or confirm ──
    already_optimized = (
        before.get("auto_vacuum") == 2
        and before.get("page_size") == DESIRED_PAGE_SIZE
    )
    if already_optimized:
        logger.info("Database already has auto_vacuum=INCREMENTAL and page_size=%d. "
                     "Nothing to do.", DESIRED_PAGE_SIZE)
        return 0

    if args.dry_run:
        logger.info("Dry-run: database is NOT optimized (auto_vacuum=%d, page_size=%d).",
                     before.get("auto_vacuum"), before.get("page_size"))
        estimated_saving = _fmt_bytes(before.get("free_bytes", 0))
        logger.info("Estimated reclaimable space after VACUUM: %s", estimated_saving)
        logger.info("Dry-run complete. Use without --dry-run to apply changes.")
        return 0

    if not args.yes:
        response = input(
            f"This will modify {db_path} and run VACUUM. "
            f"A backup will be created at {db_path}.backup-{{timestamp}}.\n"
            f"Proceed? [y/N]: "
        ).strip().lower()
        if response not in ("y", "yes"):
            logger.info("Migration cancelled by user.")
            return 0

    # ── Phase 3: Backup ──
    if not args.no_backup:
        backup_path = _create_backup(db_path)
        if backup_path is None:
            logger.error("Backup failed. Aborting migration to protect data.")
            return 1
        logger.info("To restore: cp %s %s && rm -f %s-wal %s-shm",
                     backup_path, db_path, db_path, db_path)
    else:
        logger.warning("Skipping backup (--no-backup). This is not recommended.")
        backup_path = None

    # ── Phase 4: Execute migration ──
    success = _run_migration(db_path, dry_run=False)
    if not success:
        logger.error("Migration FAILED. Database may be in an inconsistent state.")
        if backup_path:
            logger.info("Restore from backup: cp %s %s", backup_path, db_path)
        return 1

    # ── Phase 5: Verify ──
    after = _db_stats(db_path)
    _print_stats(after, "AFTER")
    verified = _verify_migration(before, after)

    # ── Summary ──
    size_before = before.get("file_size", 0)
    size_after = after.get("file_size", 0)
    saved = size_before - size_after

    logger.info("─── SUMMARY ───")
    logger.info("  File size:  %s → %s (%s reclaimed)",
                 _fmt_bytes(size_before), _fmt_bytes(size_after),
                 _fmt_bytes(saved) if saved > 0 else "0 B")
    logger.info("  Pages:      %d → %d (%d reclaimed)",
                 before.get("page_count", 0), after.get("page_count", 0),
                 before.get("page_count", 0) - after.get("page_count", 0))
    logger.info("  Free pages: %d → %d",
                 before.get("freelist_count", 0), after.get("freelist_count", 0))
    logger.info("  Status:     %s", "✅ VERIFIED" if verified else "⚠️  VERIFICATION FAILED")

    if backup_path:
        logger.info("  Backup:     %s", backup_path)

    return 0 if verified else 1


if __name__ == "__main__":
    sys.exit(main())

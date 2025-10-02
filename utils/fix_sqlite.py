"""
SQLite repair and health utility tailored for this project.

- Creates a timestamped backup in backups/
- Applies safe PRAGMAs (WAL, busy timeout, etc.)
- Ensures expected tables/columns exist for both legacy and current schemas
- Adds useful indexes
- Prints a health report

Run:
  python -m utils.fix_sqlite
"""
from __future__ import annotations

import os
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

try:
    from config import settings
    DB_PATH = settings.db_config.get("path", "bot.db")
except Exception:
    DB_PATH = "bot.db"

BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE_DIR / "backups"


def _connect(db_path: str) -> sqlite3.Connection:
    cx = sqlite3.connect(db_path, timeout=30)
    cx.row_factory = sqlite3.Row
    # Connection-level PRAGMAs
    try:
        cx.execute("PRAGMA journal_mode=WAL")
        cx.execute("PRAGMA synchronous=NORMAL")
        cx.execute("PRAGMA foreign_keys=ON")
        cx.execute("PRAGMA busy_timeout=10000")
        cx.execute("PRAGMA cache_size=10000")
    except Exception:
        pass
    return cx


def backup_database(db_path: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"bot_backup_{ts}.db"
    shutil.copy2(db_path, dst)
    return dst


def _has_table(cx: sqlite3.Connection, table: str) -> bool:
    cur = cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None


def _columns(cx: sqlite3.Connection, table: str) -> list[str]:
    try:
        cur = cx.execute(f"PRAGMA table_info({table})")
        return [r[1] for r in cur.fetchall()]
    except Exception:
        return []


def migrate() -> None:
    print("🔧 Starting SQLite migration (non-destructive)…")
    # Ensure DB file exists
    db_path = DB_PATH
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    # Backup first
    if os.path.exists(db_path):
        backup = backup_database(db_path)
        print(f"✅ Backup created: {backup}")
    else:
        print(f"ℹ️ Database file not found, it will be created: {db_path}")

    with _connect(db_path) as cx:
        cur = cx.cursor()

        # --- Ensure channels table exists in at least one supported form ---
        if not _has_table(cx, "channels"):
            # Create minimal compatible schema used by DatabaseManager
            cur.execute(
                """
                CREATE TABLE channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    username TEXT,
                    user_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    thumbnail TEXT,
                    tag TEXT
                )
                """
            )
        # Add missing columns used across code paths
        ch_cols = _columns(cx, "channels")
        for col, ddl in [
            ("name", "ALTER TABLE channels ADD COLUMN name TEXT"),
            ("title", "ALTER TABLE channels ADD COLUMN title TEXT"),
            ("username", "ALTER TABLE channels ADD COLUMN username TEXT"),
            ("user_id", "ALTER TABLE channels ADD COLUMN user_id INTEGER"),
            ("created_at", "ALTER TABLE channels ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("thumbnail", "ALTER TABLE channels ADD COLUMN thumbnail TEXT"),
            ("tag", "ALTER TABLE channels ADD COLUMN tag TEXT"),
        ]:
            if col not in ch_cols:
                try:
                    cur.execute(ddl)
                except sqlite3.OperationalError:
                    pass
        # Backfill name/title if one is missing
        ch_cols = _columns(cx, "channels")
        if "name" in ch_cols and "title" not in ch_cols:
            try:
                cur.execute("ALTER TABLE channels ADD COLUMN title TEXT")
                cur.execute("UPDATE channels SET title = name WHERE title IS NULL")
            except sqlite3.OperationalError:
                pass
        if "title" in ch_cols and "name" not in ch_cols:
            try:
                cur.execute("ALTER TABLE channels ADD COLUMN name TEXT")
                cur.execute("UPDATE channels SET name = title WHERE name IS NULL")
            except sqlite3.OperationalError:
                pass

        # Optional tg_chat_id (legacy from channel_repo)
        ch_cols = _columns(cx, "channels")
        if "tg_chat_id" not in ch_cols:
            try:
                cur.execute("ALTER TABLE channels ADD COLUMN tg_chat_id INTEGER")
            except sqlite3.OperationalError:
                pass

        # --- channel_members (for legacy membership mapping) ---
        if not _has_table(cx, "channel_members"):
            cur.execute(
                """
                CREATE TABLE channel_members (
                    channel_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel_id, user_id),
                    FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE CASCADE
                )
                """
            )

        # --- posts table and columns ---
        if not _has_table(cx, "posts"):
            cur.execute(
                """
                CREATE TABLE posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    post_type TEXT,
                    content TEXT NOT NULL,
                    caption TEXT,
                    buttons TEXT,
                    reactions TEXT,
                    scheduled_time TIMESTAMP,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (channel_id) REFERENCES channels (id)
                )
                """
            )
        # Add missing columns (and try to migrate from legacy 'type')
        po_cols = _columns(cx, "posts")
        if "post_type" not in po_cols:
            try:
                cur.execute("ALTER TABLE posts ADD COLUMN post_type TEXT")
                if "type" in po_cols:
                    cur.execute("UPDATE posts SET post_type = COALESCE(NULLIF(post_type,''), type)")
                else:
                    cur.execute("UPDATE posts SET post_type = COALESCE(post_type, 'text')")
            except sqlite3.OperationalError:
                pass
        for col in ("buttons", "reactions", "status"):
            if col not in po_cols:
                try:
                    if col == "status":
                        cur.execute("ALTER TABLE posts ADD COLUMN status TEXT DEFAULT 'pending'")
                    else:
                        cur.execute(f"ALTER TABLE posts ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass

        # --- other auxiliary tables used by DatabaseManager ---
        if not _has_table(cx, "user_timezones"):
            cur.execute(
                """
                CREATE TABLE user_timezones (
                    user_id INTEGER PRIMARY KEY,
                    timezone TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        if not _has_table(cx, "channel_thumbnails"):
            cur.execute(
                """
                CREATE TABLE channel_thumbnails (
                    channel_username TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    thumbnail_file_id TEXT NOT NULL,
                    local_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (channel_username, user_id)
                )
                """
            )
        if not _has_table(cx, "user_usage"):
            cur.execute(
                """
                CREATE TABLE user_usage (
                    user_id INTEGER PRIMARY KEY,
                    daily_bytes INTEGER DEFAULT 0,
                    last_reset TEXT,
                    last_post_time TEXT
                )
                """
            )

        # --- indexes ---
        indexes = [
            ("idx_channels_username", "channels", "username"),
            ("idx_channels_tg_chat_id", "channels", "tg_chat_id"),
            ("idx_channels_user_id", "channels", "user_id"),
            ("idx_posts_scheduled", "posts", "scheduled_time"),
            ("idx_posts_status", "posts", "status"),
            ("idx_posts_channel", "posts", "channel_id"),
            ("idx_cm_user", "channel_members", "user_id"),
            ("idx_cm_channel", "channel_members", "channel_id"),
            ("idx_usage_user", "user_usage", "user_id"),
        ]
        for name, table, cols in indexes:
            try:
                # Skip index if column(s) not present
                tcols = _columns(cx, table)
                needed = [c.strip() for c in cols.split(",")]
                if all(c in tcols for c in needed):
                    cur.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table}({cols})")
            except sqlite3.OperationalError:
                pass

        # Optimize
        try:
            cur.execute("VACUUM")
            cur.execute("ANALYZE")
        except Exception:
            pass

        cx.commit()
        print("✅ Migration finished successfully")


def health() -> Dict[str, Any]:
    out: Dict[str, Any] = {"status": "healthy", "issues": [], "stats": {}}
    try:
        with _connect(DB_PATH) as cx:
            cur = cx.cursor()
            # integrity
            try:
                r = cur.execute("PRAGMA integrity_check").fetchone()
                if r and r[0] != "ok":
                    out["status"] = "corrupted"
                    out["issues"].append(f"Integrity check failed: {r[0]}")
            except Exception as e:
                out["issues"].append(f"integrity_check error: {e}")

            # counts (if tables exist)
            for table in ("channels", "posts", "channel_members", "user_timezones", "user_usage"):
                try:
                    if _has_table(cx, table):
                        cnt = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        out["stats"][table] = int(cnt)
                except Exception:
                    pass

            # db size
            try:
                r = cur.execute("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()").fetchone()
                if r and r[0]:
                    out["stats"]["db_size_mb"] = float(r[0]) / 1024.0 / 1024.0
            except Exception:
                pass

            # journal_mode
            try:
                r = cur.execute("PRAGMA journal_mode").fetchone()
                if r and r[0]:
                    out["stats"]["journal_mode"] = r[0]
            except Exception:
                pass
    except Exception as e:
        out["status"] = "error"
        out["issues"].append(str(e))
    return out


if __name__ == "__main__":
    print("=" * 60)
    print("SQLite Repair & Health (project-tailored)")
    print("=" * 60)
    migrate()
    print("\n📊 Health check…")
    h = health()
    print(f"Status: {h['status']}")
    for k, v in h.get("stats", {}).items():
        print(f" - {k}: {v}")
    if h.get("issues"):
        print("\n⚠️ Issues:")
        for i in h["issues"]:
            print(f"  - {i}")
    else:
        print("\n✅ No issues detected")

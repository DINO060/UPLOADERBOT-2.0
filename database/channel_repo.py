import sqlite3
from typing import Optional, Dict, Any, Iterable

try:
    from config import settings as app_settings  # preferred
    DB_PATH = app_settings.db_config.get("path", "bot.db")
except Exception:
    DB_PATH = "bot.db"

DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS channels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_chat_id INTEGER NOT NULL UNIQUE,
  title TEXT,
  username TEXT,
  bot_is_admin INTEGER NOT NULL DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS channel_members (
  channel_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(channel_id, user_id),
  FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE CASCADE
);
"""


def db():
    return sqlite3.connect(DB_PATH, isolation_level=None)


def init_db():
    with db() as cx:
        cx.executescript(DDL)


def upsert_channel(tg_chat_id: int, title: Optional[str], username: Optional[str], bot_is_admin: bool) -> Dict[str, Any]:
    with db() as cx:
        cx.execute(
            """
      INSERT INTO channels (tg_chat_id,title,username,bot_is_admin)
      VALUES (?,?,?,?)
      ON CONFLICT(tg_chat_id) DO UPDATE SET
        title=excluded.title,
        username=excluded.username,
        bot_is_admin=excluded.bot_is_admin
    """,
            (tg_chat_id, title, username, 1 if bot_is_admin else 0),
        )
        r = cx.execute(
            "SELECT id,tg_chat_id,title,username,bot_is_admin FROM channels WHERE tg_chat_id=?",
            (tg_chat_id,),
        ).fetchone()
        return dict(zip(["id", "tg_chat_id", "title", "username", "bot_is_admin"], r))


def get_channel_by_tg_id(tg_chat_id: int) -> Optional[Dict[str, Any]]:
    with db() as cx:
        r = cx.execute(
            "SELECT id,tg_chat_id,title,username,bot_is_admin FROM channels WHERE tg_chat_id=?",
            (tg_chat_id,),
        ).fetchone()
        return (
            dict(zip(["id", "tg_chat_id", "title", "username", "bot_is_admin"], r))
            if r
            else None
        )


def add_member_if_missing(channel_id: int, user_id: int):
    with db() as cx:
        cx.execute(
            """
      INSERT OR IGNORE INTO channel_members (channel_id,user_id) VALUES (?,?)
    """,
            (channel_id, user_id),
        )


def list_user_channels(user_id: int) -> Iterable[Dict[str, Any]]:
    with db() as cx:
        rows = cx.execute(
            """
      SELECT c.id,c.name,c.username,c.user_id,c.created_at
      FROM channels c
      WHERE c.user_id = ?
    """,
            (user_id,),
        ).fetchall()
        cols = ["id", "name", "username", "user_id", "created_at"]
        return [dict(zip(cols, r)) for r in rows]


def get_channel_by_username(username: str, user_id: int) -> Optional[Dict[str, Any]]:
    """Gets a channel by its username for a specific user"""
    with db() as cx:
        # Nettoyer le username
        clean_username = username.lstrip('@')
        with_at = f"@{clean_username}" if not username.startswith('@') else username
        
        # Essayer d'abord avec le format exact
        r = cx.execute(
            """
            SELECT c.id, c.name, c.username, c.user_id, c.created_at
            FROM channels c
            WHERE c.username = ? AND c.user_id = ?
            """,
            (username, user_id)
        ).fetchone()
        
        # Si pas trouvé, essayer sans @
        if not r:
            r = cx.execute(
                """
                SELECT c.id, c.name, c.username, c.user_id, c.created_at
                FROM channels c
                WHERE c.username = ? AND c.user_id = ?
                """,
                (clean_username, user_id)
            ).fetchone()
        
        # Si pas trouvé, essayer avec @
        if not r:
            r = cx.execute(
                """
                SELECT c.id, c.name, c.username, c.user_id, c.created_at
                FROM channels c
                WHERE c.username = ? AND c.user_id = ?
                """,
                (with_at, user_id)
            ).fetchone()
        
        if r:
            cols = ["id", "name", "username", "user_id", "created_at"]
            result = dict(zip(cols, r))
            return result
        
        return None


def add_channel(name: str, username: str, user_id: int) -> int:
    """Add a new channel for a user"""
    with db() as cx:
        # Insérer le canal avec la structure simple
        cursor = cx.execute(
            """
            INSERT INTO channels (name, username, user_id)
            VALUES (?, ?, ?)
            """,
            (name, username, user_id)
        )
        channel_id = cursor.lastrowid
        
        return channel_id



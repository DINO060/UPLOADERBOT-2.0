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
    cx = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
    try:
        cx.execute("PRAGMA journal_mode=WAL")
        cx.execute("PRAGMA synchronous=NORMAL")
        cx.execute("PRAGMA busy_timeout=10000")
        cx.execute("PRAGMA foreign_keys=ON")
        cx.execute("PRAGMA cache_size=10000")
    except Exception:
        pass
    return cx


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
        # Detect schema
        cols = [r[1] for r in cx.execute("PRAGMA table_info(channels)").fetchall()]
        has_name = 'name' in cols
        has_title = 'title' in cols
        has_user_id = 'user_id' in cols
        has_created_at = 'created_at' in cols

        if has_user_id and has_name:
            select_cols = "c.id, c.name, c.username, c.user_id" + (", c.created_at" if has_created_at else "")
            rows = cx.execute(
                f"""
                SELECT {select_cols}
                FROM channels c
                WHERE c.user_id = ?
                """,
                (user_id,),
            ).fetchall()
            map_cols = ["id", "name", "username", "user_id"] + (["created_at"] if has_created_at else [])
            return [dict(zip(map_cols, r)) for r in rows]

        # Fallback: legacy schema using title + channel_members
        if has_title:
            select_cols = "c.id, c.title AS name, c.username, cm.user_id" + (", c.created_at" if has_created_at else "")
            rows = cx.execute(
                f"""
                SELECT {select_cols}
                FROM channels c
                JOIN channel_members cm ON cm.channel_id = c.id
                WHERE cm.user_id = ?
                """,
                (user_id,),
            ).fetchall()
            map_cols = ["id", "name", "username", "user_id"] + (["created_at"] if has_created_at else [])
            return [dict(zip(map_cols, r)) for r in rows]

        return []


def get_channel_by_username(username: str, user_id: int) -> Optional[Dict[str, Any]]:
    """Gets a channel by its username for a specific user"""
    with db() as cx:
        # Nettoyer le username
        clean_username = username.lstrip('@')
        with_at = f"@{clean_username}" if not username.startswith('@') else username

        # Detect schema
        cols = [r[1] for r in cx.execute("PRAGMA table_info(channels)").fetchall()]
        has_name = 'name' in cols
        has_title = 'title' in cols
        has_user_id = 'user_id' in cols
        has_created_at = 'created_at' in cols

        # Preferred schema path: channels has (name, user_id)
        if has_name and has_user_id:
            select_cols = "c.id, c.name, c.username, c.user_id" + (", c.created_at" if has_created_at else "")
            for uname in (username, clean_username, with_at):
                r = cx.execute(
                    f"""
                    SELECT {select_cols}
                    FROM channels c
                    WHERE c.username = ? AND c.user_id = ?
                    """,
                    (uname, user_id),
                ).fetchone()
                if r:
                    map_cols = ["id", "name", "username", "user_id"] + (["created_at"] if has_created_at else [])
                    return dict(zip(map_cols, r))

        # Fallback: legacy schema: title + channel_members
        if has_title:
            select_cols = "c.id, c.title AS name, c.username, cm.user_id" + (", c.created_at" if has_created_at else "")
            for uname in (username, clean_username, with_at):
                r = cx.execute(
                    f"""
                    SELECT {select_cols}
                    FROM channels c
                    JOIN channel_members cm ON cm.channel_id = c.id
                    WHERE c.username = ? AND cm.user_id = ?
                    """,
                    (uname, user_id),
                ).fetchone()
                if r:
                    map_cols = ["id", "name", "username", "user_id"] + (["created_at"] if has_created_at else [])
                    return dict(zip(map_cols, r))

        return None


def add_channel(name: str, username: str, user_id: int) -> int:
    """Add a new channel for a user - Compatible avec nouveau schéma"""
    with db() as cx:
        # Detect schema
        cols = [r[1] for r in cx.execute("PRAGMA table_info(channels)").fetchall()]
        has_name = 'name' in cols
        has_title = 'title' in cols
        has_user_id = 'user_id' in cols
        has_tg_chat_id = 'tg_chat_id' in cols
        
        print(f"DEBUG add_channel: cols={cols}")
        print(f"DEBUG add_channel: has_tg_chat_id={has_tg_chat_id}, has_title={has_title}, has_name={has_name}, has_user_id={has_user_id}")

        # Nouveau schéma avec tg_chat_id
        if has_tg_chat_id and has_title:
            # Pour la compatibilité, on ne peut pas vraiment ajouter un canal sans tg_chat_id
            # Cette fonction est obsolète mais on l'adapte pour éviter les erreurs
            print(f"WARN: add_channel appelée avec ancien format. name={name}, username={username}")
            
            # Canal nouveau - générer un tg_chat_id unique factice
            import time
            import random
            fake_chat_id = -(int(time.time()) * 1000 + random.randint(1000, 9999))
            
            try:
                cursor = cx.execute(
                    """
                    INSERT INTO channels (tg_chat_id, title, username, bot_is_admin)
                    VALUES (?, ?, ?, 0)
                    """,
                    (fake_chat_id, name, username),
                )
                channel_id = cursor.lastrowid
                print(f"Canal ajouté avec ID={channel_id}")
                
                # Ajouter l'utilisateur comme membre
                cx.execute(
                    """
                    INSERT OR IGNORE INTO channel_members (channel_id, user_id)
                    VALUES (?, ?)
                    """,
                    (channel_id, user_id),
                )
                print(f"Utilisateur {user_id} ajouté comme membre")
                
                return channel_id
                
            except Exception as e:
                print(f"Erreur ajout canal: {e}")
                raise

        # Ancien schéma (fallback)
        elif has_name and has_user_id:
            cursor = cx.execute(
                """
                INSERT INTO channels (name, username, user_id)
                VALUES (?, ?, ?)
                """,
                (name, username, user_id),
            )
            return cursor.lastrowid

        # Legacy: insert channel and membership separately
        if has_title:
            cursor = cx.execute(
                """
                INSERT INTO channels (title, username)
                VALUES (?, ?)
                """,
                (name, username),
            )
            channel_id = cursor.lastrowid
            cx.execute(
                """
                INSERT OR IGNORE INTO channel_members (channel_id, user_id)
                VALUES (?, ?)
                """,
                (channel_id, user_id),
            )
            return channel_id

        # If schema unknown, raise
        raise sqlite3.OperationalError("Unsupported channels schema")



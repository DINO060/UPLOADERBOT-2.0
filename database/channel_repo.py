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
      SELECT c.id,c.tg_chat_id,c.title,c.username,c.bot_is_admin
      FROM channels c
      JOIN channel_members m ON m.channel_id = c.id
      WHERE m.user_id = ?
    """,
            (user_id,),
        ).fetchall()
        cols = ["id", "tg_chat_id", "title", "username", "bot_is_admin"]
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
            SELECT c.id, c.tg_chat_id, c.title, c.username, c.bot_is_admin
            FROM channels c
            JOIN channel_members m ON m.channel_id = c.id
            WHERE c.username = ? AND m.user_id = ?
            """,
            (username, user_id)
        ).fetchone()
        
        # Si pas trouvé, essayer sans @
        if not r:
            r = cx.execute(
                """
                SELECT c.id, c.tg_chat_id, c.title, c.username, c.bot_is_admin
                FROM channels c
                JOIN channel_members m ON m.channel_id = c.id
                WHERE c.username = ? AND m.user_id = ?
                """,
                (clean_username, user_id)
            ).fetchone()
        
        # Si pas trouvé, essayer avec @
        if not r:
            r = cx.execute(
                """
                SELECT c.id, c.tg_chat_id, c.title, c.username, c.bot_is_admin
                FROM channels c
                JOIN channel_members m ON m.channel_id = c.id
                WHERE c.username = ? AND m.user_id = ?
                """,
                (with_at, user_id)
            ).fetchone()
        
        if r:
            cols = ["id", "tg_chat_id", "title", "username", "bot_is_admin"]
            result = dict(zip(cols, r))
            # Ajouter user_id pour la compatibilité avec l'ancien format
            result["user_id"] = user_id
            return result
        
        return None


def add_channel(name: str, username: str, user_id: int) -> int:
    """Add a new channel for a user"""
    with db() as cx:
        # Créer un tg_chat_id fictif (négatif pour les canaux ajoutés manuellement)
        import random
        fake_tg_chat_id = -random.randint(1000000, 9999999)

        # Détecter la structure de la table channels
        info = cx.execute("PRAGMA table_info(channels)").fetchall()
        cols = {row[1]: row for row in info}  # name -> full row (cid,name,type,notnull,default,pk)

        channel_id = None

        # Cas 1: nouveau schéma présent (tg_chat_id,title,username,bot_is_admin)
        if all(k in cols for k in ("tg_chat_id", "title", "username", "bot_is_admin")):
            # Construire une liste de colonnes/valeurs dynamiquement pour satisfaire d'éventuelles contraintes legacy
            insert_cols = ["tg_chat_id", "title", "username", "bot_is_admin"]
            insert_vals = [fake_tg_chat_id, name, username, 0]

            # Si la colonne legacy 'name' existe (souvent NOT NULL), l'alimenter avec 'name'
            if "name" in cols:
                insert_cols.append("name")
                insert_vals.append(name)

            # Si la colonne legacy 'user_id' existe (souvent NOT NULL), l'alimenter avec user_id
            if "user_id" in cols:
                insert_cols.append("user_id")
                insert_vals.append(user_id)

            placeholders = ",".join(["?"] * len(insert_cols))
            sql = f"INSERT INTO channels ({','.join(insert_cols)}) VALUES ({placeholders})"
            cursor = cx.execute(sql, tuple(insert_vals))
            channel_id = cursor.lastrowid

        # Cas 2: uniquement schéma legacy (name,username,user_id)
        elif all(k in cols for k in ("name", "username", "user_id")):
            cursor = cx.execute(
                """
                INSERT INTO channels (name, username, user_id)
                VALUES (?, ?, ?)
                """,
                (name, username, user_id)
            )
            channel_id = cursor.lastrowid
        else:
            # Schéma inattendu
            raise RuntimeError("Unsupported channels table schema")

        # Associer l'utilisateur comme membre si la table channel_members existe
        try:
            cx.execute("SELECT 1 FROM channel_members LIMIT 1")
            add_member_if_missing(channel_id, user_id)
        except Exception:
            # Table absente dans certains schémas; ignorer
            pass

        return channel_id



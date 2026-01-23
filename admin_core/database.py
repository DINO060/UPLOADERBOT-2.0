"""
ADMIN CORE - Database
=====================
Base de donn\u00e9es SQLite pour le module Admin Core.
G\u00e8re les utilisateurs, bans, stats, et configurations.
"""

import sqlite3
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager

logger = logging.getLogger("admin_core.database")


class AdminDatabase:
    """
    Gestionnaire de base de donn\u00e9es pour Admin Core.

    Tables:
        - users: Tous les utilisateurs du bot
        - banned_users: Utilisateurs bannis
        - force_join_channels: Canaux Force Join
        - broadcast_history: Historique des broadcasts
        - user_stats: Statistiques par utilisateur
        - rate_limits: Rate limiting
        - buttons: Boutons configurables
    """

    def __init__(self, db_path: str = "data/admin_core.db"):
        self.db_path = db_path
        self._connection = None

    @contextmanager
    def get_connection(self):
        """Context manager pour les connexions DB."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()

    def setup(self):
        """Cr\u00e9e toutes les tables n\u00e9cessaires."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Table des utilisateurs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    language_code TEXT DEFAULT 'en',
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1,
                    total_messages INTEGER DEFAULT 0
                )
            """)

            # Table des utilisateurs bannis
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS banned_users (
                    user_id INTEGER PRIMARY KEY,
                    banned_by INTEGER,
                    reason TEXT,
                    banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            # Table des canaux Force Join
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS force_join_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT UNIQUE NOT NULL,
                    channel_name TEXT,
                    added_by INTEGER,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                )
            """)

            # Historique des broadcasts
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broadcast_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_by INTEGER,
                    message_type TEXT,
                    total_users INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    status TEXT DEFAULT 'running'
                )
            """)

            # Statistiques utilisateurs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_stats (
                    user_id INTEGER PRIMARY KEY,
                    commands_used INTEGER DEFAULT 0,
                    files_sent INTEGER DEFAULT 0,
                    files_received INTEGER DEFAULT 0,
                    last_command TEXT,
                    last_command_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            # Rate limiting
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rate_limits (
                    user_id INTEGER PRIMARY KEY,
                    message_count INTEGER DEFAULT 0,
                    window_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_limited INTEGER DEFAULT 0,
                    limited_until TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            # Boutons configurables
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS buttons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    button_key TEXT UNIQUE NOT NULL,
                    button_text TEXT NOT NULL,
                    button_url TEXT NOT NULL,
                    position INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Configuration key-value
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            logger.info("Admin Core database setup complete")

    # ==================== USERS ====================

    def add_user(self, user_id: int, username: str = None,
                 first_name: str = None, last_name: str = None,
                 language_code: str = "en") -> bool:
        """Ajoute ou met \u00e0 jour un utilisateur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, language_code, last_seen)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    language_code = excluded.language_code,
                    last_seen = CURRENT_TIMESTAMP,
                    is_active = 1
            """, (user_id, username, first_name, last_name, language_code))
            return True

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """R\u00e9cup\u00e8re un utilisateur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_users(self, active_only: bool = True) -> List[int]:
        """R\u00e9cup\u00e8re tous les IDs utilisateurs."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if active_only:
                cursor.execute("SELECT user_id FROM users WHERE is_active = 1")
            else:
                cursor.execute("SELECT user_id FROM users")
            return [row[0] for row in cursor.fetchall()]

    def get_users_count(self, active_only: bool = True) -> int:
        """Compte le nombre d'utilisateurs."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if active_only:
                cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
            else:
                cursor.execute("SELECT COUNT(*) FROM users")
            return cursor.fetchone()[0]

    def set_user_inactive(self, user_id: int):
        """Marque un utilisateur comme inactif (bot bloqu\u00e9)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET is_active = 0 WHERE user_id = ?",
                (user_id,)
            )

    def increment_user_messages(self, user_id: int):
        """Incr\u00e9mente le compteur de messages d'un utilisateur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users
                SET total_messages = total_messages + 1, last_seen = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (user_id,))

    # ==================== BAN SYSTEM ====================

    def ban_user(self, user_id: int, banned_by: int,
                 reason: str = None, duration_seconds: int = None) -> bool:
        """Banni un utilisateur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            expires_at = None
            if duration_seconds:
                expires_at = datetime.now().timestamp() + duration_seconds

            cursor.execute("""
                INSERT INTO banned_users (user_id, banned_by, reason, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    banned_by = excluded.banned_by,
                    reason = excluded.reason,
                    banned_at = CURRENT_TIMESTAMP,
                    expires_at = excluded.expires_at
            """, (user_id, banned_by, reason, expires_at))

            logger.info(f"User {user_id} banned by {banned_by}. Reason: {reason}")
            return True

    def unban_user(self, user_id: int) -> bool:
        """D\u00e9banni un utilisateur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
            if cursor.rowcount > 0:
                logger.info(f"User {user_id} unbanned")
                return True
            return False

    def is_banned(self, user_id: int) -> Tuple[bool, Optional[str]]:
        """V\u00e9rifie si un utilisateur est banni."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT reason, expires_at FROM banned_users WHERE user_id = ?
            """, (user_id,))
            row = cursor.fetchone()

            if not row:
                return False, None

            reason, expires_at = row

            # V\u00e9rifier si le ban a expir\u00e9
            if expires_at:
                if datetime.now().timestamp() > expires_at:
                    self.unban_user(user_id)
                    return False, None

            return True, reason

    def get_banned_users(self) -> List[Dict[str, Any]]:
        """R\u00e9cup\u00e8re la liste des utilisateurs bannis."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, u.username, u.first_name
                FROM banned_users b
                LEFT JOIN users u ON b.user_id = u.user_id
            """)
            return [dict(row) for row in cursor.fetchall()]

    # ==================== FORCE JOIN ====================

    def add_force_join_channel(self, channel_id: str, channel_name: str = None,
                               added_by: int = None) -> bool:
        """Ajoute un canal Force Join."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO force_join_channels (channel_id, channel_name, added_by)
                    VALUES (?, ?, ?)
                """, (channel_id, channel_name, added_by))
                return True
            except sqlite3.IntegrityError:
                return False

    def remove_force_join_channel(self, channel_id: str) -> bool:
        """Retire un canal Force Join."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM force_join_channels WHERE channel_id = ?",
                (channel_id,)
            )
            return cursor.rowcount > 0

    def get_force_join_channels(self, active_only: bool = True) -> List[str]:
        """R\u00e9cup\u00e8re les canaux Force Join."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if active_only:
                cursor.execute(
                    "SELECT channel_id FROM force_join_channels WHERE is_active = 1"
                )
            else:
                cursor.execute("SELECT channel_id FROM force_join_channels")
            return [row[0] for row in cursor.fetchall()]

    # ==================== BROADCAST ====================

    def create_broadcast(self, started_by: int, message_type: str,
                         total_users: int) -> int:
        """Cr\u00e9e un enregistrement de broadcast."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO broadcast_history (started_by, message_type, total_users)
                VALUES (?, ?, ?)
            """, (started_by, message_type, total_users))
            return cursor.lastrowid

    def update_broadcast(self, broadcast_id: int, success_count: int,
                         failed_count: int, status: str = "running"):
        """Met \u00e0 jour un broadcast."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE broadcast_history
                SET success_count = ?, failed_count = ?, status = ?,
                    completed_at = CASE WHEN ? = 'completed' THEN CURRENT_TIMESTAMP ELSE completed_at END
                WHERE id = ?
            """, (success_count, failed_count, status, status, broadcast_id))

    def get_last_broadcast(self) -> Optional[Dict[str, Any]]:
        """R\u00e9cup\u00e8re le dernier broadcast."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM broadcast_history ORDER BY id DESC LIMIT 1
            """)
            row = cursor.fetchone()
            return dict(row) if row else None

    # ==================== RATE LIMITING ====================

    def check_rate_limit(self, user_id: int, max_messages: int,
                         window_seconds: int) -> Tuple[bool, int]:
        """
        V\u00e9rifie et met \u00e0 jour le rate limit.

        Returns:
            (is_limited, remaining_messages)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # R\u00e9cup\u00e9rer ou cr\u00e9er l'entr\u00e9e
            cursor.execute("""
                INSERT INTO rate_limits (user_id, message_count, window_start)
                VALUES (?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    message_count = CASE
                        WHEN (julianday('now') - julianday(window_start)) * 86400 > ?
                        THEN 1
                        ELSE message_count + 1
                    END,
                    window_start = CASE
                        WHEN (julianday('now') - julianday(window_start)) * 86400 > ?
                        THEN CURRENT_TIMESTAMP
                        ELSE window_start
                    END
            """, (user_id, window_seconds, window_seconds))

            # V\u00e9rifier le compteur
            cursor.execute("""
                SELECT message_count, is_limited, limited_until
                FROM rate_limits WHERE user_id = ?
            """, (user_id,))
            row = cursor.fetchone()

            if row:
                count, is_limited, limited_until = row

                # V\u00e9rifier si la limite est d\u00e9pass\u00e9e
                if count > max_messages:
                    return True, 0

                return False, max_messages - count

            return False, max_messages

    # ==================== BUTTONS ====================

    def add_button(self, key: str, text: str, url: str, position: int = 0) -> bool:
        """Ajoute un bouton."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO buttons (button_key, button_text, button_url, position)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(button_key) DO UPDATE SET
                    button_text = excluded.button_text,
                    button_url = excluded.button_url,
                    position = excluded.position
            """, (key, text, url, position))
            return True

    def remove_button(self, key: str) -> bool:
        """Supprime un bouton."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM buttons WHERE button_key = ?", (key,))
            return cursor.rowcount > 0

    def get_buttons(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """R\u00e9cup\u00e8re les boutons."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if active_only:
                cursor.execute("""
                    SELECT button_key, button_text, button_url, position
                    FROM buttons WHERE is_active = 1 ORDER BY position
                """)
            else:
                cursor.execute("""
                    SELECT button_key, button_text, button_url, position, is_active
                    FROM buttons ORDER BY position
                """)
            return [dict(row) for row in cursor.fetchall()]

    # ==================== CONFIG ====================

    def set_config(self, key: str, value: str):
        """D\u00e9finit une valeur de configuration."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO config (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, value))

    def get_config(self, key: str, default: str = None) -> Optional[str]:
        """R\u00e9cup\u00e8re une valeur de configuration."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default

    # ==================== STATS ====================

    def get_stats(self) -> Dict[str, Any]:
        """R\u00e9cup\u00e8re les statistiques globales."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            stats = {}

            # Total users
            cursor.execute("SELECT COUNT(*) FROM users")
            stats["total_users"] = cursor.fetchone()[0]

            # Active users
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
            stats["active_users"] = cursor.fetchone()[0]

            # Banned users
            cursor.execute("SELECT COUNT(*) FROM banned_users")
            stats["banned_users"] = cursor.fetchone()[0]

            # Users today
            cursor.execute("""
                SELECT COUNT(*) FROM users
                WHERE date(first_seen) = date('now')
            """)
            stats["users_today"] = cursor.fetchone()[0]

            # Total messages
            cursor.execute("SELECT SUM(total_messages) FROM users")
            stats["total_messages"] = cursor.fetchone()[0] or 0

            # Force join channels
            cursor.execute("SELECT COUNT(*) FROM force_join_channels WHERE is_active = 1")
            stats["force_join_channels"] = cursor.fetchone()[0]

            return stats

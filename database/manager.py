from typing import Dict, List, Optional, Any
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from config import settings
import os
import json

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Exception pour les erreurs de base de données"""
    pass


class DatabaseManager:
    """
    Gestionnaire de base de données pour le bot Telegram

    Cette classe gère toutes les opérations liées à la base de données,
    y compris la création de tables, l'ajout de messages et la récupération
    des données.
    """

    def __init__(self):
        """Initialise le gestionnaire de base de données"""
        self.db_path = settings.db_config["path"]
        self.connection = None
        self.setup_database()

    def setup_database(self) -> bool:
        """Initialise la base de données et crée les tables nécessaires"""
        try:
            # Assurons-nous que le dossier parent existe
            db_dir = os.path.dirname(self.db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
                logger.info(f"Dossier de base de données créé: {db_dir}")
            
            self.connection = sqlite3.connect(
                self.db_path,
                timeout=settings.db_config["timeout"],
                check_same_thread=settings.db_config["check_same_thread"]
            )
            cursor = self.connection.cursor()

            # Table des canaux
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    username TEXT UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    thumbnail TEXT,
                    tag TEXT
                )
            ''')

            # Ajouter les colonnes thumbnail et tag si elles n'existent pas
            try:
                cursor.execute("ALTER TABLE channels ADD COLUMN thumbnail TEXT")
            except sqlite3.OperationalError:
                pass  # La colonne existe déjà
            
            try:
                cursor.execute("ALTER TABLE channels ADD COLUMN tag TEXT")
            except sqlite3.OperationalError:
                pass  # La colonne existe déjà

            # Table des publications avec colonnes pour les réactions et boutons URL
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    post_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    caption TEXT,
                    buttons TEXT,
                    reactions TEXT,
                    scheduled_time TIMESTAMP,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (channel_id) REFERENCES channels (id)
                )
            ''')

            # Migration : Ajouter la colonne post_type si elle n'existe pas
            try:
                cursor.execute("ALTER TABLE posts ADD COLUMN post_type TEXT")
                logger.info("✅ Colonne post_type ajoutée à la table posts")
            except sqlite3.OperationalError:
                logger.info("ℹ️ Colonne post_type existe déjà")
            
            # Migration : Mettre à jour les posts existants sans post_type
            try:
                cursor.execute("UPDATE posts SET post_type = 'text' WHERE post_type IS NULL")
                updated_rows = cursor.rowcount
                if updated_rows > 0:
                    logger.info(f"✅ {updated_rows} posts mis à jour avec post_type = 'text'")
            except sqlite3.OperationalError:
                pass

            # Migration : Ajouter la colonne status si elle n'existe pas
            try:
                cursor.execute("ALTER TABLE posts ADD COLUMN status TEXT")
                logger.info("✅ Colonne status ajoutée à la table posts")
            except sqlite3.OperationalError:
                logger.info("ℹ️ Colonne status existe déjà")
            
            # Migration : Mettre à jour les posts existants sans status
            try:
                cursor.execute("UPDATE posts SET status = 'pending' WHERE status IS NULL")
                updated_rows = cursor.rowcount
                if updated_rows > 0:
                    logger.info(f"✅ {updated_rows} posts mis à jour avec status = 'pending'")
            except sqlite3.OperationalError:
                pass

            # Table des fuseaux horaires des utilisateurs
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_timezones (
                    user_id INTEGER PRIMARY KEY,
                    timezone TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Ajout de la table channel_thumbnails
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channel_thumbnails (
                    channel_username TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    thumbnail_file_id TEXT NOT NULL,
                    local_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (channel_username, user_id)
                )
            ''')

            self.connection.commit()
            return True

        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la configuration de la base de données: {e}")
            raise DatabaseError(f"Erreur de configuration de la base de données: {e}")

    def check_database_status(self) -> Dict[str, bool]:
        """Vérifie l'état de la base de données"""
        try:
            cursor = self.connection.cursor()

            # Vérifie les tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()

            return {
                "connection": self.connection is not None,
                "tables": len(tables) >= 2,  # Au moins 2 tables (channels et posts)
                "writable": self._test_write()
            }

        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la vérification de la base de données: {e}")
            return {
                "connection": False,
                "tables": False,
                "writable": False
            }

    def _test_write(self) -> bool:
        """Teste si la base de données est accessible en écriture"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    def add_channel(self, name: str, username: str, user_id: int) -> int:
        """Ajoute un nouveau canal à la base de données"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO channels (name, username, user_id) VALUES (?, ?, ?)",
                (name, username, user_id)
            )
            self.connection.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de l'ajout du canal: {e}")
            raise DatabaseError(f"Erreur lors de l'ajout du canal: {e}")

    def get_channel(self, channel_id: int) -> Optional[Dict[str, Any]]:
        """Récupère les informations d'un canal"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "name": row[1],
                    "username": row[2],
                    "user_id": row[3],
                    "created_at": row[4]
                }
            return None
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la récupération du canal: {e}")
            raise DatabaseError(f"Erreur lors de la récupération du canal: {e}")

    def list_channels(self, user_id: int) -> List[Dict[str, Any]]:
        """Liste tous les canaux d'un utilisateur"""
        try:
            cursor = self.connection.cursor()
            # Vérifier d'abord si la colonne created_at existe
            cursor.execute("PRAGMA table_info(channels)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'created_at' in columns:
                cursor.execute(
                    "SELECT id, name, username, user_id, created_at FROM channels WHERE user_id = ? ORDER BY name",
                    (user_id,)
                )
                return [
                    {
                        "id": row[0],
                        "name": row[1],
                        "username": row[2],
                        "user_id": row[3],
                        "created_at": row[4]
                    }
                    for row in cursor.fetchall()
                ]
            else:
                # Version sans created_at
                cursor.execute(
                    "SELECT id, name, username, user_id FROM channels WHERE user_id = ? ORDER BY name",
                    (user_id,)
                )
                return [
                    {
                        "id": row[0],
                        "name": row[1],
                        "username": row[2],
                        "user_id": row[3]
                    }
                    for row in cursor.fetchall()
                ]
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la liste des canaux: {e}")
            raise DatabaseError(f"Erreur lors de la liste des canaux: {e}")

    def delete_channel(self, channel_id: int, user_id: int) -> bool:
        """Supprime un canal et toutes ses publications associées"""
        try:
            cursor = self.connection.cursor()
            # Vérifier que le canal appartient bien à l'utilisateur
            cursor.execute("SELECT id FROM channels WHERE id = ? AND user_id = ?", (channel_id, user_id))
            if not cursor.fetchone():
                return False
            
            # Supprimer les publications associées
            cursor.execute("DELETE FROM posts WHERE channel_id = ?", (channel_id,))
            
            # Supprimer le canal
            cursor.execute("DELETE FROM channels WHERE id = ? AND user_id = ?", (channel_id, user_id))
            
            self.connection.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la suppression du canal: {e}")
            return False

    def get_channel_by_username(self, username: str, user_id: int) -> Optional[Dict[str, Any]]:
        """Récupère un canal par son username pour un utilisateur spécifique"""
        try:
            cursor = self.connection.cursor()
            # Essayer avec le username tel quel ET avec/sans @
            clean_username = username.lstrip('@')
            with_at = f"@{clean_username}" if not username.startswith('@') else username
            
            # Vérifier d'abord si la colonne created_at existe
            cursor.execute("PRAGMA table_info(channels)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'created_at' in columns:
                # Essayer d'abord avec le format exact
                cursor.execute(
                    "SELECT id, name, username, user_id, created_at FROM channels WHERE username = ? AND user_id = ?",
                    (username, user_id)
                )
                row = cursor.fetchone()
                
                # Si pas trouvé, essayer sans @
                if not row:
                    cursor.execute(
                        "SELECT id, name, username, user_id, created_at FROM channels WHERE username = ? AND user_id = ?",
                        (clean_username, user_id)
                    )
                    row = cursor.fetchone()
                
                # Si pas trouvé, essayer avec @
                if not row:
                    cursor.execute(
                        "SELECT id, name, username, user_id, created_at FROM channels WHERE username = ? AND user_id = ?",
                        (with_at, user_id)
                    )
                    row = cursor.fetchone()
                
                if row:
                    return {
                        "id": row[0],
                        "name": row[1],
                        "username": row[2],
                        "user_id": row[3],
                        "created_at": row[4]
                    }
            else:
                # Version sans created_at - même logique
                cursor.execute(
                    "SELECT id, name, username, user_id FROM channels WHERE username = ? AND user_id = ?",
                    (username, user_id)
                )
                row = cursor.fetchone()
                
                if not row:
                    cursor.execute(
                        "SELECT id, name, username, user_id FROM channels WHERE username = ? AND user_id = ?",
                        (clean_username, user_id)
                    )
                    row = cursor.fetchone()
                
                if not row:
                    cursor.execute(
                        "SELECT id, name, username, user_id FROM channels WHERE username = ? AND user_id = ?",
                        (with_at, user_id)
                    )
                    row = cursor.fetchone()
                
                if row:
                    return {
                        "id": row[0],
                        "name": row[1],
                        "username": row[2],
                        "user_id": row[3]
                    }
            return None
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la récupération du canal par username: {e}")
            raise DatabaseError(f"Erreur lors de la récupération du canal par username: {e}")

    def set_channel_tag(self, username: str, user_id: int, tag: str) -> bool:
        """Définit le tag d'un canal"""
        try:
            cursor = self.connection.cursor()
            # Nettoyer le username (enlever @ si présent)
            clean_username = username.lstrip('@')
            # Essayer sans @
            cursor.execute(
                "UPDATE channels SET tag = ? WHERE username = ? AND user_id = ?",
                (tag, clean_username, user_id)
            )
            if cursor.rowcount == 0:
                # Essayer avec @
                with_at = f"@{clean_username}"
                cursor.execute(
                    "UPDATE channels SET tag = ? WHERE username = ? AND user_id = ?",
                    (tag, with_at, user_id)
                )
            self.connection.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la mise à jour du tag: {e}")
            return False

    def get_channel_tag(self, username: str, user_id: int) -> Optional[str]:
        """Récupère le tag d'un canal"""
        try:
            cursor = self.connection.cursor()
            # Nettoyer le username (enlever @ si présent)
            clean_username = username.lstrip('@')
            
            cursor.execute(
                "SELECT tag FROM channels WHERE username = ? AND user_id = ?",
                (clean_username, user_id)
            )
            row = cursor.fetchone()
            return row[0] if row and row[0] else None
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la récupération du tag: {e}")
            return None

    def add_post(self, channel_id: int, post_type: str, content: str, 
                caption: Optional[str] = None, buttons: Optional[str] = None,
                reactions: Optional[str] = None, scheduled_time: Optional[str] = None) -> int:
        """Ajoute une nouvelle publication"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                INSERT INTO posts 
                (channel_id, post_type, content, caption, buttons, reactions, scheduled_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (channel_id, post_type, content, caption, buttons, reactions, scheduled_time)
            )
            self.connection.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de l'ajout de la publication: {e}")
            raise DatabaseError(f"Erreur lors de l'ajout de la publication: {e}")

    def get_post(self, post_id: int) -> Optional[Dict[str, Any]]:
        """Récupère les informations d'une publication"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "channel_id": row[1],
                    "post_type": row[2],
                    "content": row[3],
                    "caption": row[4],
                    "buttons": row[5],
                    "reactions": row[6],
                    "scheduled_time": row[7],
                    "status": row[8],
                    "created_at": row[9]
                }
            return None
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la récupération de la publication: {e}")
            raise DatabaseError(f"Erreur lors de la récupération de la publication: {e}")

    def update_post_status(self, post_id: int, status: str) -> bool:
        """Met à jour le statut d'une publication"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "UPDATE posts SET status = ? WHERE id = ?",
                (status, post_id)
            )
            self.connection.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la mise à jour du statut: {e}")
            raise DatabaseError(f"Erreur lors de la mise à jour du statut: {e}")

    def get_pending_posts(self) -> List[Dict[str, Any]]:
        """Récupère toutes les publications en attente"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                SELECT p.*, c.username 
                FROM posts p 
                JOIN channels c ON p.channel_id = c.id 
                WHERE p.status = 'pending'
                ORDER BY p.scheduled_time
                """
            )
            return [
                {
                    "id": row[0],
                    "channel_id": row[1],
                    "post_type": row[2],
                    "content": row[3],
                    "caption": row[4],
                    "buttons": row[5],
                    "reactions": row[6],
                    "scheduled_time": row[7],
                    "status": row[8],
                    "created_at": row[9],
                    "channel_username": row[10]
                }
                for row in cursor.fetchall()
            ]
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la récupération des publications en attente: {e}")
            raise DatabaseError(f"Erreur lors de la récupération des publications en attente: {e}")

    def set_user_timezone(self, user_id: int, timezone: str) -> bool:
        """Définit le fuseau horaire d'un utilisateur"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                INSERT INTO user_timezones (user_id, timezone)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                timezone = excluded.timezone,
                updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, timezone)
            )
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la mise à jour du fuseau horaire: {e}")
            raise DatabaseError(f"Erreur lors de la mise à jour du fuseau horaire: {e}")

    def get_user_timezone(self, user_id: int) -> Optional[str]:
        """Récupère le fuseau horaire d'un utilisateur"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT timezone FROM user_timezones WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la récupération du fuseau horaire: {e}")
            raise DatabaseError(f"Erreur lors de la récupération du fuseau horaire: {e}")

    def __del__(self):
        """Ferme la connexion à la base de données lors de la destruction de l'objet"""
        if self.connection:
            self.connection.close()

    def close(self):
        """Ferme la connexion à la base de données"""
        if self.connection:
            self.connection.close()
            self.connection = None

    def get_scheduled_posts(self, user_id: int) -> List[Dict[str, Any]]:
        """Récupère les publications planifiées d'un utilisateur"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                SELECT p.*, c.username 
                FROM posts p 
                JOIN channels c ON p.channel_id = c.id 
                WHERE p.status = 'pending' AND c.user_id = ? AND p.scheduled_time IS NOT NULL
                ORDER BY p.scheduled_time
                """,
                (user_id,)
            )
            return [
                {
                    "id": row[0],
                    "channel_id": row[1],
                    "post_type": row[2],
                    "content": row[3],
                    "caption": row[4],
                    "buttons": row[5],
                    "reactions": row[6],
                    "scheduled_time": row[7],
                    "status": row[8],
                    "created_at": row[9],
                    "channel_username": row[10]
                }
                for row in cursor.fetchall()
            ]
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la récupération des publications planifiées: {e}")
            raise DatabaseError(f"Erreur lors de la récupération des publications planifiées: {e}")

    def save_thumbnail(self, channel_username: str, user_id: int, thumbnail_file_id: str, local_path: str = None) -> bool:
        """Sauvegarde un thumbnail pour un canal avec file_id ET fichier local optionnel"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO channel_thumbnails (channel_username, user_id, thumbnail_file_id, local_path) VALUES (?, ?, ?, ?)",
                (channel_username, user_id, thumbnail_file_id, local_path)
            )
            self.connection.commit()
            logger.info(f"✅ Thumbnail sauvé pour @{channel_username}: file_id={thumbnail_file_id[:30]}..., local_path={local_path}")
            return True
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la sauvegarde du thumbnail: {e}")
            return False

    def get_thumbnail(self, channel_username: str, user_id: int) -> Optional[Dict[str, str]]:
        """Récupère le file_id ET le chemin local du thumbnail d'un canal"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT thumbnail_file_id, local_path FROM channel_thumbnails WHERE channel_username = ? AND user_id = ?",
                (channel_username, user_id)
            )
            result = cursor.fetchone()
            if result:
                return {
                    "file_id": result[0],
                    "local_path": result[1]
                }
            return None
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la récupération du thumbnail: {e}")
            return None

    def delete_thumbnail(self, channel_username: str, user_id: int) -> bool:
        """Supprime le thumbnail d'un canal"""
        try:
            # Nettoyer le nom d'utilisateur (enlever @ si présent) pour cohérence
            clean_username = channel_username.lstrip('@')
            
            cursor = self.connection.cursor()
            cursor.execute('''
                DELETE FROM channel_thumbnails 
                WHERE channel_username = ? AND user_id = ?
            ''', (clean_username, user_id))
            self.connection.commit()
            
            logger.info(f"Thumbnail supprimé pour canal '{clean_username}' (original: '{channel_username}'), user_id: {user_id}")
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erreur lors de la suppression du thumbnail: {e}")
            return False
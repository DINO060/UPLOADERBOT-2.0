"""
Module de suppression sécurisée de canaux
À intégrer dans database/manager.py ou utiliser comme module séparé
"""

import sqlite3
import logging
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

@contextmanager
def secure_db_connection(db_path: str):
    """Connexion sécurisée avec les bonnes options"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def delete_channel_secure(db_path: str, channel_id: int, user_id: Optional[int] = None) -> bool:
    """
    Suppression sécurisée d'un canal avec toutes ses dépendances
    
    Args:
        db_path: Chemin vers la base de données
        channel_id: ID du canal à supprimer
        user_id: ID de l'utilisateur (pour vérification des droits si nécessaire)
        
    Returns:
        True si le canal a été supprimé, False sinon
    """
    try:
        with secure_db_connection(db_path) as conn:
            # 1. Vérifier que le canal existe (et appartient à l'utilisateur si spécifié)
            if user_id:
                check_query = "SELECT 1 FROM channels WHERE channel_id = ? AND user_id = ?"
                exists = conn.execute(check_query, (channel_id, user_id)).fetchone()
            else:
                check_query = "SELECT 1 FROM channels WHERE channel_id = ?"
                exists = conn.execute(check_query, (channel_id,)).fetchone()
            
            if not exists:
                logger.warning(f"Canal {channel_id} introuvable ou accès refusé")
                return False
            
            # 2. Suppression des dépendances (ordre important)
            cleanup_tables = [
                "user_reactions",
                "reaction_counts", 
                "scheduled_posts",
                "posts",
                "jobs",
                "files"
            ]
            
            deleted_total = 0
            for table in cleanup_tables:
                try:
                    cursor = conn.execute(f"DELETE FROM {table} WHERE channel_id = ?", (channel_id,))
                    deleted = cursor.rowcount
                    if deleted > 0:
                        logger.info(f"Supprimé {deleted} entrées de {table} pour le canal {channel_id}")
                        deleted_total += deleted
                except sqlite3.OperationalError as e:
                    if "no such table" in str(e):
                        logger.debug(f"Table {table} n'existe pas (ignoré)")
                    else:
                        logger.warning(f"Erreur lors du nettoyage de {table}: {e}")
            
            # 3. Supprimer le canal lui-même
            cursor = conn.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
            
            if cursor.rowcount > 0:
                logger.info(f"Canal {channel_id} supprimé avec succès ({deleted_total} dépendances nettoyées)")
                return True
            else:
                logger.error(f"Échec de la suppression du canal {channel_id}")
                return False
                
    except Exception as e:
        logger.error(f"Erreur lors de la suppression du canal {channel_id}: {e}")
        return False

# Fonction simplifiée pour intégration dans le bot existant
def safe_delete_channel(channel_id: int, user_id: Optional[int] = None) -> bool:
    """
    Version simplifiée pour remplacer la fonction delete_channel existante
    """
    import os
    db_path = os.path.join(os.path.dirname(__file__), '..', 'bot.db')
    return delete_channel_secure(db_path, channel_id, user_id)
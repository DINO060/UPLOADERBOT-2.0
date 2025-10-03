#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module de connexion DB standardisé
=================================
Source unique pour toutes les connexions avec FK activées
"""

import sqlite3
import logging
import sys
import os

# Ajouter le répertoire racine au path pour importer config.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_CONFIG

logger = logging.getLogger(__name__)

def connect_db():
    """
    Connexion standardisée à la base avec FK activées
    IMPORTANT: FK activées sur CHAQUE connexion
    """
    conn = sqlite3.connect(
        DB_CONFIG["path"], 
        timeout=DB_CONFIG["timeout"], 
        check_same_thread=DB_CONFIG["check_same_thread"]
    )
    conn.execute("PRAGMA foreign_keys = ON;")  # IMPORTANT sur CHAQUE connexion
    
    # Log du chemin absolu ouvert (debug)
    for _, name, file in conn.execute("PRAGMA database_list;").fetchall():
        logger.debug(f"[DB] using: {file}")
    
    return conn

def table_exists(cursor: sqlite3.Cursor, name: str) -> bool:
    """Vérifier si une table existe"""
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (name,))
    return cursor.fetchone() is not None

def id_column_for_channels(cursor: sqlite3.Cursor) -> str:
    """Détecter le bon nom de la clé primaire des channels"""
    cursor.execute("PRAGMA table_info(channels)")
    cols = [c[1] for c in cursor.fetchall()]
    return "channel_id" if "channel_id" in cols else "id"
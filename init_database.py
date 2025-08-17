#!/usr/bin/env python3
"""
Script d'initialisation de la base de données pour le bot Telegram
Ce script crée toutes les tables nécessaires et résout les problèmes de migration
"""

import sqlite3
import os
import sys
from pathlib import Path

# Ajouter le répertoire parent au path pour les imports
sys.path.append(str(Path(__file__).parent))

try:
    from config import settings
    from database.channel_repo import init_db as init_channel_db
    from database.manager import DatabaseManager
except ImportError as e:
    print(f"Erreur d'import: {e}")
    sys.exit(1)

def create_files_table():
    """Crée la table files si elle n'existe pas"""
    db_path = settings.db_config.get("path", "bot.db")
    
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT UNIQUE,
                file_name TEXT,
                file_path TEXT,
                file_size INTEGER,
                mime_type TEXT,
                user_id INTEGER,
                channel_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE
            )
        """)
        
        # Créer la table posts si elle n'existe pas
        conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                channel_id INTEGER,
                content TEXT,
                caption TEXT,
                file_path TEXT,
                file_id TEXT,
                post_type TEXT DEFAULT 'text',
                status TEXT DEFAULT 'pending',
                scheduled_time DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE
            )
        """)
        
        # Créer la table users si elle n'existe pas
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                timezone TEXT DEFAULT 'UTC',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Créer la table user_settings si elle n'existe pas
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                daily_limit REAL DEFAULT 2.0,
                cooldown INTEGER DEFAULT 30,
                fast_mode BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        conn.commit()
        print("✅ Tables files, posts, users et user_settings créées avec succès")

def check_database_integrity():
    """Vérifie l'intégrité de la base de données"""
    db_path = settings.db_config.get("path", "bot.db")
    
    with sqlite3.connect(db_path) as conn:
        # Vérifier que toutes les tables existent
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [table[0] for table in tables]
        
        required_tables = ['channels', 'channel_members', 'files', 'posts', 'users', 'user_settings']
        
        for table in required_tables:
            if table in table_names:
                print(f"✅ Table {table} existe")
            else:
                print(f"❌ Table {table} manquante")
        
        # Vérifier les permissions sur le fichier de base de données
        if os.access(db_path, os.W_OK):
            print(f"✅ Permissions d'écriture sur {db_path}")
        else:
            print(f"❌ Pas de permissions d'écriture sur {db_path}")

def add_sample_data():
    """Ajoute des données d'exemple pour les tests"""
    db_path = settings.db_config.get("path", "bot.db")
    
    with sqlite3.connect(db_path) as conn:
        # Ajouter un canal d'exemple si aucun n'existe
        channels_count = conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
        
        if channels_count == 0:
            # Ajouter un canal d'exemple
            conn.execute("""
                INSERT INTO channels (tg_chat_id, title, username, bot_is_admin)
                VALUES (?, ?, ?, ?)
            """, (-123456789, "Canal d'exemple", "example_channel", 1))
            
            channel_id = conn.lastrowid
            
            # Ajouter un membre d'exemple (utilisateur 1)
            conn.execute("""
                INSERT INTO channel_members (channel_id, user_id)
                VALUES (?, ?)
            """, (channel_id, 1))
            
            conn.commit()
            print("✅ Données d'exemple ajoutées")

def main():
    """Fonction principale d'initialisation"""
    print("🚀 Initialisation de la base de données...")
    
    try:
        # Initialiser les tables de base (channels et channel_members)
        init_channel_db()
        print("✅ Tables de base initialisées")
        
        # Créer les tables manquantes
        create_files_table()
        
        # Vérifier l'intégrité
        check_database_integrity()
        
        # Ajouter des données d'exemple
        add_sample_data()
        
        print("\n🎉 Initialisation terminée avec succès!")
        print("Vous pouvez maintenant redémarrer votre bot.")
        
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

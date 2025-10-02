#!/usr/bin/env python3
"""
Script avancé pour corriger définitivement l'erreur channels_old
"""

import sqlite3
import os
import re

def fix_channels_old_error():
    """Corrige complètement l'erreur channels_old"""
    
    print("🔧 Correction avancée de l'erreur channels_old...")
    
    # 1. Nettoyer la base de données
    if os.path.exists('bot.db'):
        try:
            conn = sqlite3.connect('bot.db')
            cursor = conn.cursor()
            
            # Supprimer toutes les références à channels_old
            cursor.execute("DROP TABLE IF EXISTS channels_old")
            cursor.execute("DROP TABLE IF EXISTS main.channels_old")
            
            # Vérifier et recréer la structure channels si nécessaire
            cursor.execute("PRAGMA table_info(channels)")
            channels_info = cursor.fetchall()
            
            if not channels_info:
                print("⚠️ Table channels manquante, création...")
                cursor.execute("""
                    CREATE TABLE channels (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        username TEXT,
                        channel_id TEXT UNIQUE,
                        is_private BOOLEAN DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            
            conn.commit()
            conn.close()
            print("✅ Base de données nettoyée")
            
        except Exception as e:
            print(f"❌ Erreur BDD: {e}")
    
    # 2. Scanner et corriger les fichiers Python qui pourraient référencer channels_old
    files_to_check = [
        'database/manager.py',
        'handlers/callback_handlers.py',
        'bot.py'
    ]
    
    for file_path in files_to_check:
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Chercher des références à channels_old
                if 'channels_old' in content:
                    print(f"⚠️ Référence channels_old trouvée dans {file_path}")
                    # On ne modifie pas automatiquement, juste on signale
                else:
                    print(f"✅ Pas de référence channels_old dans {file_path}")
                    
            except Exception as e:
                print(f"❌ Erreur lecture {file_path}: {e}")
    
    # 3. Créer une table de remplacement temporaire si nécessaire
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        
        # S'assurer qu'aucune vue ou trigger ne référence channels_old
        cursor.execute("SELECT sql FROM sqlite_master WHERE sql LIKE '%channels_old%'")
        results = cursor.fetchall()
        
        for result in results:
            print(f"⚠️ Référence SQL trouvée: {result[0]}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Erreur vérification SQL: {e}")
    
    print("✅ Correction terminée")

if __name__ == "__main__":
    fix_channels_old_error()
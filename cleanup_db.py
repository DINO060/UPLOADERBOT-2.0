#!/usr/bin/env python3
"""
Script de nettoyage de la base de données
Corrige l'erreur 'no such table: main.channels_old'
"""

import sqlite3
import os
import sys

def cleanup_database():
    """Nettoie la base de données des tables obsolètes"""
    db_path = 'bot.db'
    
    if not os.path.exists(db_path):
        print("❌ Fichier bot.db introuvable")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("🧹 Nettoyage de la base de données...")
        
        # Supprimer les tables obsolètes
        obsolete_tables = ['channels_old', 'temp_channels', 'backup_channels']
        
        for table in obsolete_tables:
            try:
                cursor.execute(f'DROP TABLE IF EXISTS {table}')
                print(f"✅ Table {table} supprimée (si elle existait)")
            except Exception as e:
                print(f"⚠️ Erreur lors de la suppression de {table}: {e}")
        
        # Vérifier les tables existantes
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"📊 Tables restantes: {[t[0] for t in tables]}")
        
        conn.commit()
        conn.close()
        
        print("✅ Nettoyage de la base de données terminé avec succès")
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors du nettoyage: {e}")
        return False

if __name__ == "__main__":
    success = cleanup_database()
    sys.exit(0 if success else 1)
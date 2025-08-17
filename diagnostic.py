#!/usr/bin/env python3
"""
Script de diagnostic pour le bot Telegram
Ce script vérifie l'état du bot et identifie les problèmes potentiels
"""

import sqlite3
import os
import sys
from pathlib import Path

# Ajouter le répertoire parent au path pour les imports
sys.path.append(str(Path(__file__).parent))

try:
    from config import settings
    from database.channel_repo import list_user_channels, init_db
except ImportError as e:
    print(f"Erreur d'import: {e}")
    sys.exit(1)

def check_database():
    """Vérifie l'état de la base de données"""
    print("🔍 Vérification de la base de données...")
    
    db_path = settings.db_config.get("path", "bot.db")
    
    if not os.path.exists(db_path):
        print(f"❌ Fichier de base de données introuvable: {db_path}")
        return False
    
    print(f"✅ Fichier de base de données trouvé: {db_path}")
    
    try:
        with sqlite3.connect(db_path) as conn:
            # Vérifier les tables
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            table_names = [table[0] for table in tables]
            
            required_tables = ['channels', 'channel_members', 'files', 'posts', 'users', 'user_settings']
            
            for table in required_tables:
                if table in table_names:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    print(f"✅ Table {table}: {count} enregistrements")
                else:
                    print(f"❌ Table {table} manquante")
            
            # Vérifier les permissions
            if os.access(db_path, os.W_OK):
                print("✅ Permissions d'écriture sur la base de données")
            else:
                print("❌ Pas de permissions d'écriture sur la base de données")
                
    except Exception as e:
        print(f"❌ Erreur lors de la vérification de la base de données: {e}")
        return False
    
    return True

def check_channels():
    """Vérifie les canaux configurés"""
    print("\n🔍 Vérification des canaux...")
    
    try:
        # Tester avec un utilisateur d'exemple
        channels = list(list_user_channels(1))
        print(f"✅ {len(channels)} canaux trouvés pour l'utilisateur 1")
        
        for i, channel in enumerate(channels, 1):
            print(f"  {i}. {channel.get('title', 'N/A')} (@{channel.get('username', 'N/A')})")
            
    except Exception as e:
        print(f"❌ Erreur lors de la récupération des canaux: {e}")
        return False
    
    return True

def check_environment():
    """Vérifie l'environnement d'exécution"""
    print("\n🔍 Vérification de l'environnement...")
    
    # Vérifier les variables d'environnement
    required_vars = ['API_ID', 'API_HASH', 'BOT_TOKEN']
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"✅ {var}: {'*' * len(value)} (configuré)")
        else:
            print(f"❌ {var}: non configuré")
    
    # Vérifier les dossiers
    folders = ['downloads', 'temp', 'thumbnails', 'logs']
    
    for folder in folders:
        folder_path = os.path.join(os.getcwd(), folder)
        if os.path.exists(folder_path):
            print(f"✅ Dossier {folder}: existe")
        else:
            print(f"❌ Dossier {folder}: manquant")
    
    # Vérifier les fichiers de session
    session_files = ['pyro_user.session', 'telethon_user.session', 'uploader_session.session']
    
    for session_file in session_files:
        if os.path.exists(session_file):
            print(f"✅ Session {session_file}: existe")
        else:
            print(f"⚠️ Session {session_file}: manquant (peut être normal)")

def check_config():
    """Vérifie la configuration"""
    print("\n🔍 Vérification de la configuration...")
    
    try:
        print(f"✅ API_ID: {'*' * len(settings.api_id) if settings.api_id else 'Non configuré'}")
        print(f"✅ API_HASH: {'*' * len(settings.api_hash) if settings.api_hash else 'Non configuré'}")
        print(f"✅ BOT_TOKEN: {'*' * len(settings.bot_token) if settings.bot_token else 'Non configuré'}")
        print(f"✅ DB_PATH: {settings.db_path}")
        print(f"✅ DOWNLOAD_FOLDER: {settings.download_folder}")
        
        if settings.admin_ids:
            print(f"✅ ADMIN_IDS: {settings.admin_ids}")
        else:
            print("⚠️ ADMIN_IDS: non configuré")
            
    except Exception as e:
        print(f"❌ Erreur lors de la vérification de la configuration: {e}")

def main():
    """Fonction principale de diagnostic"""
    print("🚀 Diagnostic du bot Telegram")
    print("=" * 50)
    
    # Vérifier l'environnement
    check_environment()
    
    # Vérifier la configuration
    check_config()
    
    # Vérifier la base de données
    db_ok = check_database()
    
    # Vérifier les canaux
    if db_ok:
        check_channels()
    
    print("\n" + "=" * 50)
    print("📋 Résumé du diagnostic:")
    
    if db_ok:
        print("✅ La base de données semble fonctionnelle")
    else:
        print("❌ Problèmes détectés avec la base de données")
        print("💡 Solution: Exécutez le script init_database.py")
    
    print("\n🔧 Actions recommandées:")
    print("1. Si des tables manquent: python init_database.py")
    print("2. Si des variables d'environnement manquent: configurez votre fichier .env")
    print("3. Si des dossiers manquent: créez-les manuellement")
    print("4. Redémarrez le bot après les corrections")

if __name__ == "__main__":
    main()

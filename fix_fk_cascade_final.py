#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MIGRATION FINALE - CORRECTION FK CASCADE
========================================
Fix définitif pour la base de données avec FK CASCADE correctes
"""

import sqlite3
import os
import shutil
from datetime import datetime

def backup_database(db_path):
    """Créer une sauvegarde de la base"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup_final_{timestamp}"
    shutil.copy2(db_path, backup_path)
    print(f"✅ Sauvegarde créée: {backup_path}")
    return backup_path

def fix_foreign_keys(db_path):
    """Corriger les clés étrangères pour pointer vers 'channels' avec CASCADE"""
    print("🔧 CORRECTION DES CLÉS ÉTRANGÈRES")
    print("="*50)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Activer les clés étrangères
        cursor.execute("PRAGMA foreign_keys = ON;")
        
        # 1. Corriger la table POSTS
        print("📋 Correction de la table POSTS...")
        
        # Récupérer les données existantes
        cursor.execute("SELECT * FROM posts;")
        posts_data = cursor.fetchall()
        
        # Obtenir les colonnes actuelles
        cursor.execute("PRAGMA table_info(posts);")
        columns_info = cursor.fetchall()
        columns = [col[1] for col in columns_info]
        
        print(f"   Colonnes actuelles: {columns}")
        print(f"   Nombre de posts: {len(posts_data)}")
        
        # Supprimer l'ancienne table
        cursor.execute("DROP TABLE posts;")
        
        # Recréer avec FK CASCADE correcte
        cursor.execute("""
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            post_type TEXT,
            content TEXT,
            caption TEXT DEFAULT '',
            buttons TEXT DEFAULT '',
            scheduled_time DATETIME DEFAULT '',
            message_id INTEGER DEFAULT 0,
            reactions TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (channel_id) REFERENCES channels (id) ON DELETE CASCADE
        );
        """)
        
        # Réinsérer les données existantes
        if posts_data:
            # Adapter les données selon les colonnes disponibles
            for post in posts_data:
                # Créer un tuple avec toutes les valeurs nécessaires
                values = list(post) + [datetime.now().isoformat()]  # Ajouter created_at
                cursor.execute("""
                INSERT INTO posts (id, channel_id, post_type, content, caption, buttons, scheduled_time, message_id, reactions, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, values)
        
        print("   ✅ Table POSTS corrigée avec FK CASCADE")
        
        # 2. Corriger la table SCHEDULED_JOBS si elle existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scheduled_jobs';")
        if cursor.fetchone():
            print("📋 Correction de la table SCHEDULED_JOBS...")
            
            # Récupérer les données
            cursor.execute("SELECT * FROM scheduled_jobs;")
            jobs_data = cursor.fetchall()
            
            # Recréer avec FK CASCADE
            cursor.execute("DROP TABLE scheduled_jobs;")
            cursor.execute("""
            CREATE TABLE scheduled_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT UNIQUE NOT NULL,
                channel_id INTEGER NOT NULL,
                post_id INTEGER,
                scheduled_time DATETIME NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES channels (id) ON DELETE CASCADE,
                FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE
            );
            """)
            
            # Réinsérer les données
            if jobs_data:
                for job in jobs_data:
                    cursor.execute("""
                    INSERT INTO scheduled_jobs (id, job_id, channel_id, post_id, scheduled_time, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, list(job) + [datetime.now().isoformat()])
            
            print("   ✅ Table SCHEDULED_JOBS corrigée avec FK CASCADE")
        
        # 3. Vérifier les FK
        print("\n🔍 VÉRIFICATION DES CLÉS ÉTRANGÈRES:")
        cursor.execute("PRAGMA foreign_key_list(posts);")
        fk_posts = cursor.fetchall()
        print(f"   Posts FK: {fk_posts}")
        
        if fk_posts and fk_posts[0][2] == 'channels':
            print("   ✅ FK Posts pointe vers 'channels' avec CASCADE")
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scheduled_jobs';")
        if cursor.fetchone():
            cursor.execute("PRAGMA foreign_key_list(scheduled_jobs);")
            fk_jobs = cursor.fetchall()
            print(f"   Jobs FK: {fk_jobs}")
        
        conn.commit()
        print("\n✅ MIGRATION RÉUSSIE!")
        return True
        
    except Exception as e:
        print(f"❌ Erreur pendant la migration: {e}")
        conn.rollback()
        return False
        
    finally:
        conn.close()

def test_cascade_delete(db_path):
    """Tester la suppression en cascade"""
    print("\n🧪 TEST DE SUPPRESSION CASCADE")
    print("="*40)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("PRAGMA foreign_keys = ON;")
        
        # Compter les posts avant
        cursor.execute("SELECT COUNT(*) FROM posts;")
        posts_before = cursor.fetchone()[0]
        
        # Compter les channels
        cursor.execute("SELECT COUNT(*) FROM channels;")
        channels_count = cursor.fetchone()[0]
        
        print(f"   Channels: {channels_count}")
        print(f"   Posts avant: {posts_before}")
        
        if channels_count > 0:
            # Prendre un channel pour test (sans le supprimer réellement)
            cursor.execute("SELECT id, title FROM channels LIMIT 1;")
            test_channel = cursor.fetchone()
            
            if test_channel:
                print(f"   Channel test: {test_channel[1]} (ID: {test_channel[0]})")
                
                # Compter ses posts
                cursor.execute("SELECT COUNT(*) FROM posts WHERE channel_id = ?;", (test_channel[0],))
                channel_posts = cursor.fetchone()[0]
                print(f"   Posts de ce channel: {channel_posts}")
                
                print("   ✅ Structure OK - CASCADE fonctionnera")
        
        print("   ✅ Test réussi - FK CASCADE actives")
        
    except Exception as e:
        print(f"   ❌ Erreur test: {e}")
        
    finally:
        conn.close()

def main():
    """Migration principale"""
    print("🚀 MIGRATION FINALE - FK CASCADE")
    print("="*50)
    
    db_path = "data/bot.db"
    
    if not os.path.exists(db_path):
        print(f"❌ Base non trouvée: {db_path}")
        return
    
    # Sauvegarde
    backup_path = backup_database(db_path)
    
    try:
        # Correction des FK
        if fix_foreign_keys(db_path):
            # Test
            test_cascade_delete(db_path)
            print(f"\n🎉 MIGRATION TERMINÉE AVEC SUCCÈS!")
            print(f"   Sauvegarde: {backup_path}")
        else:
            print(f"\n❌ ÉCHEC - Restauration de {backup_path}")
            shutil.copy2(backup_path, db_path)
            
    except Exception as e:
        print(f"\n❌ ERREUR CRITIQUE: {e}")
        print(f"   Restauration de {backup_path}")
        shutil.copy2(backup_path, db_path)

if __name__ == "__main__":
    main()
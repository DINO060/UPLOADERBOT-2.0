#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NETTOYAGE ET MIGRATION FK CASCADE
================================
Nettoie les données orphelines puis applique les FK CASCADE
"""

import sqlite3
import os
import shutil
from datetime import datetime

def cleanup_orphaned_data(db_path):
    """Nettoyer les données orphelines avant migration"""
    print("🧹 NETTOYAGE DES DONNÉES ORPHELINES")
    print("="*50)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 1. Supprimer les posts avec channel_id NULL
        cursor.execute("SELECT COUNT(*) FROM posts WHERE channel_id IS NULL;")
        null_posts = cursor.fetchone()[0]
        
        if null_posts > 0:
            print(f"🗑️ Suppression de {null_posts} posts avec channel_id NULL...")
            cursor.execute("DELETE FROM posts WHERE channel_id IS NULL;")
        
        # 2. Supprimer les posts avec channel_id invalide
        cursor.execute("SELECT id FROM channels;")
        valid_channels = [row[0] for row in cursor.fetchall()]
        
        if valid_channels:
            placeholders = ','.join('?' for _ in valid_channels)
            cursor.execute(f"SELECT COUNT(*) FROM posts WHERE channel_id NOT IN ({placeholders});", valid_channels)
            invalid_posts = cursor.fetchone()[0]
            
            if invalid_posts > 0:
                print(f"🗑️ Suppression de {invalid_posts} posts avec channel_id invalide...")
                cursor.execute(f"DELETE FROM posts WHERE channel_id NOT IN ({placeholders});", valid_channels)
        
        # 3. Nettoyer les scheduled_jobs orphelins si la table existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scheduled_jobs';")
        if cursor.fetchone():
            # Jobs avec channel_id invalide
            if valid_channels:
                cursor.execute(f"SELECT COUNT(*) FROM scheduled_jobs WHERE channel_id NOT IN ({placeholders});", valid_channels)
                invalid_jobs = cursor.fetchone()[0]
                
                if invalid_jobs > 0:
                    print(f"🗑️ Suppression de {invalid_jobs} jobs avec channel_id invalide...")
                    cursor.execute(f"DELETE FROM scheduled_jobs WHERE channel_id NOT IN ({placeholders});", valid_channels)
            
            # Jobs avec post_id invalide
            cursor.execute("SELECT id FROM posts;")
            valid_posts = [row[0] for row in cursor.fetchall()]
            
            if valid_posts:
                post_placeholders = ','.join('?' for _ in valid_posts)
                cursor.execute(f"SELECT COUNT(*) FROM scheduled_jobs WHERE post_id IS NOT NULL AND post_id NOT IN ({post_placeholders});", valid_posts)
                invalid_job_posts = cursor.fetchone()[0]
                
                if invalid_job_posts > 0:
                    print(f"🗑️ Suppression de {invalid_job_posts} jobs avec post_id invalide...")
                    cursor.execute(f"DELETE FROM scheduled_jobs WHERE post_id IS NOT NULL AND post_id NOT IN ({post_placeholders});", valid_posts)
        
        conn.commit()
        
        # Comptes après nettoyage
        cursor.execute("SELECT COUNT(*) FROM posts;")
        posts_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM channels;")
        channels_count = cursor.fetchone()[0]
        
        print(f"✅ Nettoyage terminé:")
        print(f"   Channels: {channels_count}")
        print(f"   Posts valides: {posts_count}")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur nettoyage: {e}")
        conn.rollback()
        return False
        
    finally:
        conn.close()

def apply_fk_cascade(db_path):
    """Appliquer les FK CASCADE après nettoyage"""
    print("\n🔧 APPLICATION DES FK CASCADE")
    print("="*40)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("PRAGMA foreign_keys = ON;")
        
        # 1. Récupérer les données des posts
        cursor.execute("SELECT * FROM posts;")
        posts_data = cursor.fetchall()
        
        # 2. Recréer la table posts avec FK CASCADE
        print("📋 Recréation de la table POSTS avec FK CASCADE...")
        
        cursor.execute("DROP TABLE posts;")
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
        
        # 3. Réinsérer les données avec created_at
        if posts_data:
            print(f"   Réinsertion de {len(posts_data)} posts...")
            for post in posts_data:
                values = list(post) + [datetime.now().isoformat()]
                cursor.execute("""
                INSERT INTO posts (id, channel_id, post_type, content, caption, buttons, scheduled_time, message_id, reactions, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, values)
        
        # 4. Traiter scheduled_jobs si elle existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scheduled_jobs';")
        if cursor.fetchone():
            print("📋 Recréation de la table SCHEDULED_JOBS avec FK CASCADE...")
            
            cursor.execute("SELECT * FROM scheduled_jobs;")
            jobs_data = cursor.fetchall()
            
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
            
            if jobs_data:
                print(f"   Réinsertion de {len(jobs_data)} jobs...")
                for job in jobs_data:
                    values = list(job) + [datetime.now().isoformat()]
                    cursor.execute("""
                    INSERT INTO scheduled_jobs (id, job_id, channel_id, post_id, scheduled_time, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, values)
        
        conn.commit()
        
        # Vérification finale
        print("\n🔍 VÉRIFICATION FINALE:")
        cursor.execute("PRAGMA foreign_key_list(posts);")
        fk_posts = cursor.fetchall()
        print(f"   Posts FK: {fk_posts}")
        
        if fk_posts and 'CASCADE' in str(fk_posts[0]):
            print("   ✅ FK CASCADE activées sur posts")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur FK CASCADE: {e}")
        conn.rollback()
        return False
        
    finally:
        conn.close()

def main():
    """Migration complète avec nettoyage"""
    print("🚀 MIGRATION COMPLÈTE - NETTOYAGE + FK CASCADE")
    print("="*60)
    
    db_path = "data/bot.db"
    
    if not os.path.exists(db_path):
        print(f"❌ Base non trouvée: {db_path}")
        return
    
    # Sauvegarde
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup_clean_{timestamp}"
    shutil.copy2(db_path, backup_path)
    print(f"✅ Sauvegarde: {backup_path}")
    
    try:
        # 1. Nettoyage
        if not cleanup_orphaned_data(db_path):
            raise Exception("Échec du nettoyage")
        
        # 2. FK CASCADE
        if not apply_fk_cascade(db_path):
            raise Exception("Échec des FK CASCADE")
        
        print(f"\n🎉 MIGRATION RÉUSSIE!")
        print(f"   Base corrigée: {db_path}")
        print(f"   Sauvegarde: {backup_path}")
        
        # Test rapide
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("SELECT COUNT(*) FROM posts;")
        posts = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM channels;")  
        channels = cursor.fetchone()[0]
        conn.close()
        
        print(f"   📊 Résultat final: {channels} channels, {posts} posts")
        
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        print(f"   Restauration de {backup_path}")
        shutil.copy2(backup_path, db_path)

if __name__ == "__main__":
    main()
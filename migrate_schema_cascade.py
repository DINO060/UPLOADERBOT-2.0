#!/usr/bin/env python3
"""
Migration complète du schéma DB pour corriger les Foreign Keys CASCADE
Corrige définitivement le problème de suppression de canaux
"""

import sqlite3
import os
import shutil
from datetime import datetime
from pathlib import Path

def backup_database(db_path: str) -> str:
    """Créer une sauvegarde avant migration"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup_{timestamp}"
    
    if os.path.exists(db_path):
        shutil.copy2(db_path, backup_path)
        print(f"✅ Sauvegarde créée: {backup_path}")
        return backup_path
    else:
        print(f"⚠️ Fichier DB {db_path} introuvable")
        return None

def migrate_database_schema(db_path: str):
    """Migration complète pour corriger les FK CASCADE"""
    print("🔧 MIGRATION COMPLÈTE DU SCHÉMA")
    print("=" * 50)
    
    # 1. Sauvegarde
    backup_path = backup_database(db_path)
    
    conn = sqlite3.connect(db_path)
    try:
        # Désactiver les FK pendant la migration
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("BEGIN TRANSACTION;")
        
        print("📋 Recréation de la table POSTS avec FK CASCADE...")
        
        # POSTS : Recréation avec FK CASCADE correcte
        conn.execute("""
            CREATE TABLE posts_new (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id     INTEGER NOT NULL,
                post_type      TEXT NOT NULL,
                content        TEXT NOT NULL,
                caption        TEXT,
                buttons        TEXT,
                reactions      TEXT,
                scheduled_time TIMESTAMP,
                status         TEXT DEFAULT 'pending',
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE
            )
        """)
        
        # Copier les données valides (avec canaux existants)
        conn.execute("""
            INSERT INTO posts_new
            (id, channel_id, post_type, content, caption, buttons, reactions, scheduled_time, status, created_at)
            SELECT p.id, p.channel_id, 
                   COALESCE(p.post_type, 'text') as post_type,
                   p.content, p.caption, p.buttons, p.reactions, 
                   p.scheduled_time, 
                   COALESCE(p.status, 'pending') as status,
                   p.created_at
            FROM posts p
            JOIN channels c ON c.id = p.channel_id
        """)
        
        # Compter les posts copiés
        copied_posts = conn.execute("SELECT COUNT(*) FROM posts_new").fetchone()[0]
        original_posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        
        print(f"   ✅ Posts copiés: {copied_posts}/{original_posts}")
        
        # Remplacer la table
        conn.execute("DROP TABLE posts")
        conn.execute("ALTER TABLE posts_new RENAME TO posts")
        
        print("📋 Recréation de la table JOBS avec FK CASCADE...")
        
        # JOBS : Recréation avec FK CASCADE correcte
        conn.execute("""
            CREATE TABLE jobs_new (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id     INTEGER NOT NULL,
                job_id         TEXT UNIQUE,
                status         TEXT DEFAULT 'pending',
                scheduled_time TIMESTAMP,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE
            )
        """)
        
        # Vérifier si la table jobs existe
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
        
        if tables:
            # Copier les données jobs existantes
            conn.execute("""
                INSERT INTO jobs_new (id, channel_id, job_id, status, scheduled_time, created_at)
                SELECT j.id, j.channel_id, j.job_id, j.status, j.scheduled_time, j.created_at
                FROM jobs j
                JOIN channels c ON c.id = j.channel_id
            """)
            
            copied_jobs = conn.execute("SELECT COUNT(*) FROM jobs_new").fetchone()[0]
            original_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            print(f"   ✅ Jobs copiés: {copied_jobs}/{original_jobs}")
            
            conn.execute("DROP TABLE jobs")
        else:
            print("   ℹ️ Table jobs n'existait pas, création nouvelle")
        
        conn.execute("ALTER TABLE jobs_new RENAME TO jobs")
        
        # Créer les index utiles
        print("📊 Création des index...")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_channel_id ON posts(channel_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_channel_id ON jobs(channel_id)")
        
        # Valider la transaction
        conn.execute("COMMIT;")
        
        # Réactiver les FK
        conn.execute("PRAGMA foreign_keys = ON;")
        
        print("✅ Migration terminée avec succès!")
        
    except Exception as e:
        print(f"❌ Erreur pendant la migration: {e}")
        conn.execute("ROLLBACK;")
        
        # Restaurer la sauvegarde
        if backup_path and os.path.exists(backup_path):
            shutil.copy2(backup_path, db_path)
            print(f"🔄 Base restaurée depuis {backup_path}")
        
        raise e
    finally:
        conn.close()

def verify_migration(db_path: str):
    """Vérifier que la migration a fonctionné"""
    print("\n🧪 VÉRIFICATION DE LA MIGRATION")
    print("=" * 40)
    
    conn = sqlite3.connect(db_path)
    try:
        # Activer FK
        conn.execute("PRAGMA foreign_keys = ON;")
        
        # 1. Vérifier l'activation des FK
        fk_status = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        print(f"🔐 Foreign Keys: {'✅ ACTIVÉES' if fk_status else '❌ DÉSACTIVÉES'}")
        
        # 2. Vérifier les FK CASCADE sur posts
        posts_fks = conn.execute("PRAGMA foreign_key_list(posts);").fetchall()
        print("📋 Foreign Keys table POSTS:")
        for fk in posts_fks:
            on_delete = fk[5] if len(fk) > 5 else "NO ACTION"
            print(f"   - {fk[3]} -> {fk[2]}.{fk[4]} (on_delete: {on_delete})")
        
        # 3. Vérifier les FK CASCADE sur jobs
        jobs_fks = conn.execute("PRAGMA foreign_key_list(jobs);").fetchall()
        print("📋 Foreign Keys table JOBS:")
        for fk in jobs_fks:
            on_delete = fk[5] if len(fk) > 5 else "NO ACTION"
            print(f"   - {fk[3]} -> {fk[2]}.{fk[4]} (on_delete: {on_delete})")
        
        # 4. Test CASCADE fonctionnel
        print("\n🧪 Test CASCADE:")
        
        # Créer un canal de test
        cursor = conn.execute("""
            INSERT INTO channels(name, username, user_id) 
            VALUES ('Test CASCADE', '@test_cascade', 999999)
        """)
        test_channel_id = cursor.lastrowid
        
        # Créer un post lié
        conn.execute("""
            INSERT INTO posts(channel_id, post_type, content) 
            VALUES (?, 'text', 'Test post CASCADE')
        """, (test_channel_id,))
        
        # Compter avant suppression
        posts_before = conn.execute("SELECT COUNT(*) FROM posts WHERE channel_id = ?", (test_channel_id,)).fetchone()[0]
        print(f"   Posts avant suppression: {posts_before}")
        
        # Supprimer le canal
        conn.execute("DELETE FROM channels WHERE id = ?", (test_channel_id,))
        
        # Compter après suppression
        posts_after = conn.execute("SELECT COUNT(*) FROM posts WHERE channel_id = ?", (test_channel_id,)).fetchone()[0]
        print(f"   Posts après suppression: {posts_after}")
        
        if posts_after == 0:
            print("   ✅ CASCADE fonctionne correctement!")
        else:
            print("   ❌ CASCADE ne fonctionne pas!")
        
        conn.commit()
        
    finally:
        conn.close()

def fix_db_paths():
    """Corriger les chemins de DB inconsistants dans le code"""
    print("\n🔧 CORRECTION DES CHEMINS DB")
    print("=" * 35)
    
    # Créer le dossier data s'il n'existe pas
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    
    # S'assurer que bot.db est dans data/
    main_db = "bot.db" 
    data_db = "data/bot.db"
    
    if os.path.exists(main_db) and not os.path.exists(data_db):
        shutil.move(main_db, data_db)
        print(f"✅ Déplacé {main_db} vers {data_db}")
    elif os.path.exists(data_db):
        print(f"✅ {data_db} déjà en place")
    else:
        print(f"ℹ️ Aucune DB trouvée, sera créée au besoin")

def main():
    """Fonction principale de migration"""
    print("🚀 MIGRATION COMPLÈTE - CORRECTION SCHÉMA CASCADE")
    print("=" * 60)
    
    # 1. Corriger les chemins
    fix_db_paths()
    
    # 2. Déterminer le bon chemin DB
    possible_paths = ["data/bot.db", "bot.db"]
    db_path = None
    
    for path in possible_paths:
        if os.path.exists(path):
            db_path = path
            print(f"📁 Base trouvée: {path}")
            break
    
    if not db_path:
        print("❌ Aucune base de données trouvée!")
        return
    
    # 3. Migration du schéma
    try:
        migrate_database_schema(db_path)
        verify_migration(db_path)
        
        print(f"\n🎉 MIGRATION RÉUSSIE!")
        print(f"\n💡 La suppression de canaux fonctionne maintenant via:")
        print(f"   DELETE FROM channels WHERE id = ? --> CASCADE automatique")
        
    except Exception as e:
        print(f"\n❌ ÉCHEC DE LA MIGRATION: {e}")

if __name__ == "__main__":
    main()
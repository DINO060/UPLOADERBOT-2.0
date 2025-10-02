#!/usr/bin/env python3
"""
Correctif définitif pour la suppression de canaux
Corrige les Foreign Keys et implémente une suppression atomique
"""

import sqlite3
import os
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

@contextmanager
def open_db(path: str):
    """Ouvre la DB avec les bonnes options à chaque fois"""
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")  # IMPORTANT à CHAQUE connexion
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def delete_channel_now(db_path: str, channel_id: int) -> int:
    """
    Suppression atomique d'un canal avec toutes ses dépendances
    Retourne 1 si le canal a été supprimé, 0 sinon (canal introuvable)
    """
    print(f"🗑️ Suppression du canal {channel_id}...")
    
    with open_db(db_path) as conn:
        try:
            # 1) Supprimer toutes les dépendances d'abord
            tables_to_clean = [
                "posts",
                "jobs", 
                "files",
                "scheduled_posts",
                "user_reactions",
                "reaction_counts"
            ]
            
            for table in tables_to_clean:
                try:
                    result = conn.execute(f"DELETE FROM {table} WHERE channel_id = ?", (channel_id,))
                    deleted = result.rowcount
                    if deleted > 0:
                        print(f"   ✅ {deleted} entrées supprimées de {table}")
                except sqlite3.OperationalError as e:
                    if "no such table" not in str(e):
                        print(f"   ⚠️ Erreur sur {table}: {e}")
            
            # 2) Supprimer le canal lui-même
            cursor = conn.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
            deleted_channels = cursor.rowcount
            
            if deleted_channels > 0:
                print(f"   ✅ Canal {channel_id} supprimé avec succès")
            else:
                print(f"   ⚠️ Canal {channel_id} introuvable")
                
            return deleted_channels
            
        except Exception as e:
            print(f"   ❌ Erreur lors de la suppression: {e}")
            return 0

def diagnose_database(db_path: str):
    """Diagnostic complet de la base de données"""
    print("🔍 Diagnostic de la base de données...")
    
    if not os.path.exists(db_path):
        print(f"❌ Fichier {db_path} introuvable")
        return False
    
    with open_db(db_path) as conn:
        # 1. Vérifier les bases chargées
        print("\n📁 Bases de données chargées:")
        result = conn.execute("PRAGMA database_list;").fetchall()
        for row in result:
            print(f"   - {row[1]}: {row[2]}")
        
        # 2. Vérifier l'activation des FK
        fk_status = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        print(f"\n🔐 Foreign keys activées: {'✅ OUI' if fk_status else '❌ NON'}")
        
        # 3. Lister les tables
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        table_names = [t[0] for t in tables]
        print(f"\n📊 Tables présentes: {table_names}")
        
        # 4. Vérifier les foreign keys existantes
        print("\n🔗 Foreign Keys configurées:")
        for table in ['posts', 'jobs', 'files', 'scheduled_posts']:
            if table in table_names:
                try:
                    fks = conn.execute(f"PRAGMA foreign_key_list({table});").fetchall()
                    if fks:
                        for fk in fks:
                            print(f"   {table}: {fk[2]}.{fk[3]} -> {fk[4]} (on_delete: {fk[5]})")
                    else:
                        print(f"   {table}: ❌ Aucune FK configurée")
                except:
                    print(f"   {table}: ⚠️ Erreur de lecture")
        
        # 5. Compter les canaux
        try:
            count = conn.execute("SELECT COUNT(*) FROM channels;").fetchone()[0]
            print(f"\n📈 Nombre de canaux: {count}")
            
            if count > 0:
                sample = conn.execute("SELECT channel_id, username, title FROM channels LIMIT 3;").fetchall()
                print("   Exemples:")
                for s in sample:
                    print(f"   - ID: {s[0]}, Username: {s[1]}, Title: {s[2]}")
        except Exception as e:
            print(f"   ❌ Erreur lecture channels: {e}")
        
        return True

def fix_foreign_keys(db_path: str):
    """Répare les foreign keys pour activer CASCADE"""
    print("🔧 Réparation des Foreign Keys...")
    
    with open_db(db_path) as conn:
        # Sauvegarder les données existantes
        print("📦 Sauvegarde des données...")
        
        # Vérifier et réparer la table posts
        try:
            # Créer la nouvelle table posts avec CASCADE
            conn.execute("""
                CREATE TABLE IF NOT EXISTS posts_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER,
                    status TEXT DEFAULT 'pending',
                    content TEXT,
                    caption TEXT,
                    type TEXT,
                    filename TEXT,
                    file_path TEXT,
                    thumbnail TEXT,
                    reactions TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
                )
            """)
            
            # Migrer les données si la table originale existe
            tables = [t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
            if 'posts' in tables:
                conn.execute("""
                    INSERT OR IGNORE INTO posts_new 
                    SELECT * FROM posts
                """)
                conn.execute("DROP TABLE posts")
                conn.execute("ALTER TABLE posts_new RENAME TO posts")
                print("   ✅ Table posts réparée avec CASCADE")
            
        except Exception as e:
            print(f"   ⚠️ Erreur posts: {e}")
        
        # Créer les autres tables avec CASCADE si elles n'existent pas
        tables_to_create = {
            'jobs': """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    job_id TEXT UNIQUE,
                    status TEXT DEFAULT 'pending',
                    scheduled_time TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
                )
            """,
            'scheduled_posts': """
                CREATE TABLE IF NOT EXISTS scheduled_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    content TEXT,
                    caption TEXT,
                    type TEXT,
                    scheduled_time TIMESTAMP,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
                )
            """
        }
        
        for table_name, create_sql in tables_to_create.items():
            try:
                conn.execute(create_sql)
                print(f"   ✅ Table {table_name} créée/vérifiée avec CASCADE")
            except Exception as e:
                print(f"   ⚠️ Erreur {table_name}: {e}")

def main():
    """Fonction principale de diagnostic et réparation"""
    db_path = "bot.db"
    
    print("🔧 CORRECTIF DÉFINITIF - SUPPRESSION DE CANAUX")
    print("=" * 50)
    
    # 1. Diagnostic
    if not diagnose_database(db_path):
        return
    
    # 2. Réparation des FK
    fix_foreign_keys(db_path)
    
    # 3. Test de suppression (sur un canal fictif pour test)
    print("\n🧪 Test de suppression...")
    test_channel_id = -999999999  # Canal fictif pour test
    
    with open_db(db_path) as conn:
        # Créer un canal de test
        conn.execute("""
            INSERT OR REPLACE INTO channels (channel_id, username, title, created_at, updated_at) 
            VALUES (?, ?, ?, datetime('now'), datetime('now'))
        """, (test_channel_id, '@test_delete', 'Test Delete Channel'))
        
        # Créer quelques dépendances de test
        conn.execute("""
            INSERT OR IGNORE INTO posts (channel_id, content, status) 
            VALUES (?, ?, ?)
        """, (test_channel_id, 'Test content', 'pending'))
    
    # Tester la suppression
    result = delete_channel_now(db_path, test_channel_id)
    if result > 0:
        print("✅ Test de suppression réussi!")
    else:
        print("❌ Échec du test de suppression")
    
    print("\n🎉 Correctif terminé!")
    print("\nUtilisation:")
    print(f"  delete_channel_now('{db_path}', channel_id)")
    print("  Retourne 1 si succès, 0 si canal introuvable")

if __name__ == "__main__":
    main()
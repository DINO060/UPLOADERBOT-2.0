#!/usr/bin/env python3
"""
Correctif immédiat - Suppression de canaux qui marche à tous les coups
Diagnostic complet + suppression atomique manuelle
"""

import sqlite3
import os
from contextlib import contextmanager

@contextmanager
def open_db(path: str):
    """Connexion avec PRAGMA foreign_keys OBLIGATOIRE"""
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")  # CRITIQUE à chaque connexion
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def delete_channel_now(db_path: str, channel_id: int) -> int:
    """
    Suppression atomique manuelle - marche à tous les coups
    Retourne 1 si le canal a été supprimé, 0 sinon (canal introuvable)
    """
    print(f"🗑️ Suppression immédiate du canal {channel_id}")
    
    with open_db(db_path) as conn:
        # 1) Supprimer TOUTES les dépendances d'abord (ordre important)
        dependency_tables = [
            "user_reactions",
            "reaction_counts",
            "scheduled_posts", 
            "posts",
            "jobs",
            "files"
        ]
        
        total_deleted = 0
        for table in dependency_tables:
            try:
                cur = conn.execute(f"DELETE FROM {table} WHERE channel_id = ?", (channel_id,))
                deleted = cur.rowcount
                if deleted > 0:
                    print(f"   ✅ {deleted} entrées supprimées de {table}")
                    total_deleted += deleted
            except sqlite3.OperationalError as e:
                if "no such table" in str(e):
                    print(f"   ℹ️ Table {table} n'existe pas (OK)")
                else:
                    print(f"   ⚠️ Erreur sur {table}: {e}")
        
        # 2) Supprimer le canal lui-même
        cur = conn.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
        deleted_channels = cur.rowcount
        
        print(f"   📊 Total: {total_deleted} dépendances + {deleted_channels} canal(aux)")
        return deleted_channels

def diagnostic_complet(db_path: str):
    """Diagnostic express pour trouver la vraie cause"""
    print("🔍 DIAGNOSTIC COMPLET")
    print("=" * 50)
    
    if not os.path.exists(db_path):
        print(f"❌ Fichier DB {db_path} INTROUVABLE!")
        return False
    
    with open_db(db_path) as conn:
        # 1) Vérifier le bon fichier DB
        print("📁 Bases de données chargées:")
        dbs = conn.execute("PRAGMA database_list;").fetchall()
        for db in dbs:
            print(f"   - {db[1]}: {db[2]}")
        
        # 2) Vérifier activation FK
        fk_status = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        print(f"🔐 Foreign Keys: {'✅ ACTIVÉES' if fk_status else '❌ DÉSACTIVÉES'}")
        
        # 3) Tables existantes
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        table_names = [t[0] for t in tables]
        print(f"📊 Tables: {table_names}")
        
        # 4) Vérifier les FK CASCADE
        print("🔗 Foreign Keys CASCADE:")
        for table in ['posts', 'jobs', 'files', 'scheduled_posts']:
            if table in table_names:
                fks = conn.execute(f"PRAGMA foreign_key_list({table});").fetchall()
                if fks:
                    for fk in fks:
                        cascade = fk[5] if len(fk) > 5 else "NO ACTION"
                        print(f"   {table}: {fk[2]} -> {fk[4]} (on_delete: {cascade})")
                else:
                    print(f"   {table}: ❌ Aucune FK")
        
        # 5) Test sur un canal existant
        sample_channels = conn.execute("SELECT channel_id, username FROM channels LIMIT 3;").fetchall()
        print(f"📺 Canaux existants: {len(sample_channels)}")
        for ch in sample_channels:
            print(f"   - ID: {ch[0]}, Username: {ch[1]}")
            
        return True

def smoke_test_suppression(db_path: str):
    """Test complet de suppression avec canal factice"""
    print("\n🧪 SMOKE TEST SUPPRESSION")
    print("=" * 30)
    
    test_channel_id = -999888777  # Canal de test
    
    with open_db(db_path) as conn:
        # 1) Créer un canal de test avec dépendances
        print("📝 Création canal de test...")
        conn.execute("""
            INSERT OR REPLACE INTO channels 
            (channel_id, username, title, created_at, updated_at) 
            VALUES (?, ?, ?, datetime('now'), datetime('now'))
        """, (test_channel_id, '@test_delete', 'Test Delete'))
        
        # Créer des dépendances
        try:
            conn.execute("""
                INSERT OR IGNORE INTO posts (channel_id, content, status, created_at) 
                VALUES (?, ?, ?, datetime('now'))
            """, (test_channel_id, 'Test post', 'pending'))
        except:
            print("   ⚠️ Table posts indisponible pour test")
    
    # 2) Compter avant suppression
    with open_db(db_path) as conn:
        def count(table, where="1=1"):
            try:
                return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
            except:
                return 0
        
        before_channels = count("channels", f"channel_id={test_channel_id}")
        before_posts = count("posts", f"channel_id={test_channel_id}")
        print(f"📊 AVANT: channels={before_channels}, posts={before_posts}")
    
    # 3) Tester la suppression
    result = delete_channel_now(db_path, test_channel_id)
    
    # 4) Vérifier après
    with open_db(db_path) as conn:
        def count(table, where="1=1"):
            try:
                return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
            except:
                return 0
        
        after_channels = count("channels", f"channel_id={test_channel_id}")
        after_posts = count("posts", f"channel_id={test_channel_id}")
        print(f"📊 APRÈS: channels={after_channels}, posts={after_posts}")
    
    if result == 1 and after_channels == 0:
        print("✅ TEST RÉUSSI - Suppression fonctionne!")
        return True
    else:
        print("❌ TEST ÉCHOUÉ - Problème détecté")
        return False

def main():
    """Fonction principale"""
    db_path = "bot.db"
    
    print("🔧 CORRECTIF IMMÉDIAT - SUPPRESSION CANAUX")
    print("=" * 50)
    
    # 1) Diagnostic complet
    if not diagnostic_complet(db_path):
        print("❌ Impossible de continuer")
        return
    
    # 2) Smoke test
    success = smoke_test_suppression(db_path)
    
    if success:
        print("\n🎉 CORRECTIF VALIDÉ!")
        print("\n💡 Utilisation:")
        print(f"   from delete_channel_now import delete_channel_now")
        print(f"   result = delete_channel_now('{db_path}', channel_id)")
        print(f"   # result == 1 → OK, result == 0 → canal introuvable")
    else:
        print("\n🚨 PROBLÈME DÉTECTÉ - Voir diagnostic ci-dessus")

if __name__ == "__main__":
    main()
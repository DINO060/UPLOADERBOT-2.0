#!/usr/bin/env python3
"""
Diagnostic et correctif adapté à la vraie structure de votre DB
"""

import sqlite3
from contextlib import contextmanager

@contextmanager
def open_db(path: str):
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def analyze_real_structure(db_path: str):
    """Analyser la vraie structure de votre DB"""
    print("🔍 ANALYSE DE LA STRUCTURE RÉELLE")
    print("=" * 40)
    
    with open_db(db_path) as conn:
        # 1) Structure de la table channels
        print("📋 Structure table 'channels':")
        channels_info = conn.execute("PRAGMA table_info(channels);").fetchall()
        if channels_info:
            for col in channels_info:
                print(f"   - {col[1]} ({col[2]}) {'NOT NULL' if col[3] else 'NULL'}")
        else:
            print("   ❌ Table channels introuvable")
            return False
        
        # 2) Contenu actuel
        try:
            channels = conn.execute("SELECT * FROM channels LIMIT 3;").fetchall()
            print(f"\n📊 Canaux actuels: {len(channels)}")
            for ch in channels:
                print(f"   - {ch}")
        except Exception as e:
            print(f"   ⚠️ Erreur lecture channels: {e}")
        
        # 3) Autres tables
        all_tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        table_names = [t[0] for t in all_tables]
        print(f"\n📊 Toutes les tables: {table_names}")
        
        # 4) Structure des autres tables importantes
        for table in ['posts', 'jobs', 'user_prefs']:
            if table in table_names:
                print(f"\n📋 Structure table '{table}':")
                info = conn.execute(f"PRAGMA table_info({table});").fetchall()
                for col in info:
                    print(f"   - {col[1]} ({col[2]})")
        
        return True

def create_test_channel_adapted(db_path: str):
    """Créer un canal de test avec la vraie structure"""
    print("\n🧪 TEST AVEC VRAIE STRUCTURE")
    print("=" * 30)
    
    test_channel_id = -999888777
    
    with open_db(db_path) as conn:
        # Découvrir la structure channels
        channels_info = conn.execute("PRAGMA table_info(channels);").fetchall()
        columns = [col[1] for col in channels_info]
        
        print(f"📝 Colonnes disponibles: {columns}")
        
        # Construire INSERT adapté
        if 'channel_id' in columns:
            # Essayer avec les colonnes qui existent vraiment
            base_columns = ['channel_id']
            base_values = [test_channel_id]
            
            if 'username' in columns:
                base_columns.append('username')
                base_values.append('@test_delete')
            
            if 'name' in columns:  # au lieu de title
                base_columns.append('name')
                base_values.append('Test Delete')
            elif 'title' in columns:
                base_columns.append('title') 
                base_values.append('Test Delete')
            
            if 'created_at' in columns:
                base_columns.append('created_at')
                base_values.append('datetime("now")')
            
            # Construire la requête
            placeholders = ', '.join(['?' if 'datetime' not in str(v) else str(v) for v in base_values])
            clean_values = [v for v in base_values if 'datetime' not in str(v)]
            
            insert_sql = f"""
                INSERT OR REPLACE INTO channels ({', '.join(base_columns)}) 
                VALUES ({placeholders})
            """
            
            print(f"📝 SQL: {insert_sql}")
            print(f"📝 Values: {clean_values}")
            
            try:
                if 'datetime' in placeholders:
                    # Requête avec datetime()
                    conn.execute(f"""
                        INSERT OR REPLACE INTO channels ({', '.join(base_columns)}) 
                        VALUES ({', '.join(['?' if 'datetime' not in str(v) else 'datetime("now")' for v in base_values])})
                    """, clean_values)
                else:
                    conn.execute(insert_sql, clean_values)
                
                print("✅ Canal de test créé")
                
                # Vérifier
                result = conn.execute("SELECT * FROM channels WHERE channel_id = ?", (test_channel_id,)).fetchone()
                print(f"📊 Canal créé: {result}")
                
                return test_channel_id
                
            except Exception as e:
                print(f"❌ Erreur création: {e}")
                return None

def delete_channel_real(db_path: str, channel_id: int):
    """Suppression adaptée à votre structure"""
    print(f"\n🗑️ SUPPRESSION CANAL {channel_id}")
    
    with open_db(db_path) as conn:
        # Supprimer des tables qui existent vraiment
        all_tables = [t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
        
        # Tables potentielles avec channel_id
        potential_tables = ['posts', 'jobs', 'files', 'scheduled_posts', 'user_reactions', 'reaction_counts']
        
        total_deleted = 0
        for table in potential_tables:
            if table in all_tables:
                try:
                    # Vérifier si la table a une colonne channel_id
                    columns = [col[1] for col in conn.execute(f"PRAGMA table_info({table});").fetchall()]
                    if 'channel_id' in columns:
                        cur = conn.execute(f"DELETE FROM {table} WHERE channel_id = ?", (channel_id,))
                        deleted = cur.rowcount
                        if deleted > 0:
                            print(f"   ✅ {deleted} entrées supprimées de {table}")
                            total_deleted += deleted
                except Exception as e:
                    print(f"   ⚠️ Erreur sur {table}: {e}")
        
        # Supprimer le canal
        cur = conn.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
        deleted_channels = cur.rowcount
        
        print(f"   📊 Total: {total_deleted} dépendances + {deleted_channels} canal(aux)")
        return deleted_channels > 0

def main():
    db_path = "bot.db"
    
    # 1) Analyser la structure réelle
    if not analyze_real_structure(db_path):
        return
    
    # 2) Créer et supprimer un canal de test
    test_id = create_test_channel_adapted(db_path)
    if test_id:
        success = delete_channel_real(db_path, test_id)
        if success:
            print("\n✅ CORRECTIF VALIDÉ - La suppression fonctionne!")
        else:
            print("\n❌ PROBLÈME - La suppression a échoué")
    
    print("\n💡 Votre structure de DB est maintenant analysée!")

if __name__ == "__main__":
    main()
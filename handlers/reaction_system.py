"""
Système de réactions optimisé - basé sur la solution ChatGPT
Toggle parfait avec answerCallbackQuery garanti
"""

import re
import json
import time
import asyncio
import logging
import sqlite3
from typing import Dict, Set, Optional, Tuple
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# === CONFIGURATION ===
REACTION_COOLDOWN = 0.2  # 200ms anti-spam
DEFAULT_REACTIONS = ["👍", "🔥", "❤️", "😂", "😮", "😢", "🎉"]

# === CACHE EN MÉMOIRE (pour performance) ===
# post_id -> {"chat_id": int, "message_id": int}
POSTS_CACHE: Dict[int, Dict] = {}
# (post_id, user_id) -> last_timestamp pour anti-spam
LAST_CLICK: Dict[Tuple[int, int], float] = {}

def _get_db_path() -> str:
    """Récupère le chemin de la base de données"""
    try:
        from config import app_settings
        return app_settings.db_config.database_path
    except:
        return "data/bot.db"

def _ensure_reactions_tables():
    """Créer les tables de réactions si elles n'existent pas"""
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Table pour mapper post_id -> message
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS post_messages (
            post_id INTEGER PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Table pour les votes (remplace reactions_votes)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS reaction_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            emoji TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(post_id, user_id, emoji)
        )
        """)
        
        conn.commit()

def save_post_mapping(post_id: int, chat_id: int, message_id: int) -> None:
    """Enregistre le mapping post_id -> (chat_id, message_id)"""
    POSTS_CACHE[post_id] = {"chat_id": chat_id, "message_id": message_id}
    
    # Sauvegarder aussi en DB
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO post_messages (post_id, chat_id, message_id)
        VALUES (?, ?, ?)
        """, (post_id, chat_id, message_id))
        conn.commit()

def get_post_mapping(post_id: int) -> Optional[Dict]:
    """Récupère le mapping post_id -> (chat_id, message_id)"""
    # Vérifier d'abord le cache
    if post_id in POSTS_CACHE:
        return POSTS_CACHE[post_id]
    
    # Sinon chercher en DB
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT chat_id, message_id FROM post_messages WHERE post_id = ?
        """, (post_id,))
        row = cursor.fetchone()
        
        if row:
            mapping = {"chat_id": row[0], "message_id": row[1]}
            POSTS_CACHE[post_id] = mapping  # Mettre en cache
            return mapping
    
    return None

def counts_for(post_id: int) -> Dict[str, int]:
    """Récupère les compteurs pour un post"""
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT emoji, COUNT(*) FROM reaction_votes 
        WHERE post_id = ? 
        GROUP BY emoji
        """, (post_id,))
        
        return dict(cursor.fetchall())

def build_react_keyboard(reactions: list, post_id: int) -> InlineKeyboardMarkup:
    """Construit le clavier de réactions avec compteurs"""
    if not reactions:
        reactions = ["👍", "🔥"]  # Réactions par défaut
    
    counts = counts_for(post_id)
    keyboard = []
    
    # Créer les boutons par rangée (max 4 par rangée)
    row = []
    for emoji in reactions:
        count = counts.get(emoji, 0)
        text = f"{emoji} {count}" if count > 0 else emoji
        # FORMAT COURT: r:emoji:post_id (au lieu de react_post_id_emoji)
        callback_data = f"r:{emoji}:{post_id}"
        
        row.append(InlineKeyboardButton(text, callback_data=callback_data))
        
        if len(row) >= 4:  # Max 4 boutons par rangée
            keyboard.append(row)
            row = []
    
    if row:  # Ajouter la dernière rangée si non vide
        keyboard.append(row)
    
    return InlineKeyboardMarkup(keyboard)

async def handle_reaction_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Gestionnaire de toggle des réactions - VERSION OPTIMISÉE
    Format callback: r:emoji:post_id (ex: r:👍:123)
    """
    query = update.callback_query
    callback_data = query.data
    user_id = update.effective_user.id
    
    # TOUJOURS répondre au callback (sinon bouton freeze)
    try:
        await query.answer()
        logger.debug(f"✅ answerCallbackQuery OK pour: {callback_data}")
    except Exception as e:
        logger.error(f"❌ Erreur answerCallbackQuery: {e}")
        return
    
    # Parser le callback: r:emoji:post_id
    match = re.match(r"^r:(.+):(\d+)$", callback_data)
    if not match:
        logger.warning(f"Format callback invalide: {callback_data}")
        return
    
    emoji = match.group(1)
    post_id = int(match.group(2))
    
    logger.info(f"🎯 Réaction toggle: user={user_id}, post={post_id}, emoji={emoji}")
    
    # Anti-spam: 200ms par user/post
    now = time.monotonic()
    key = (post_id, user_id)
    if now - LAST_CLICK.get(key, 0.0) < REACTION_COOLDOWN:
        logger.debug(f"🚫 Cooldown actif pour user {user_id} sur post {post_id}")
        return
    LAST_CLICK[key] = now
    
    # S'assurer que les tables existent
    _ensure_reactions_tables()
    
    # Toggle en base de données
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Vérifier si l'utilisateur a déjà cette réaction
        cursor.execute("""
        SELECT 1 FROM reaction_votes 
        WHERE post_id = ? AND user_id = ? AND emoji = ?
        """, (post_id, user_id, emoji))
        
        has_reaction = cursor.fetchone() is not None
        
        if has_reaction:
            # Retirer la réaction (toggle OFF)
            cursor.execute("""
            DELETE FROM reaction_votes 
            WHERE post_id = ? AND user_id = ? AND emoji = ?
            """, (post_id, user_id, emoji))
            action = "removed"
        else:
            # Ajouter la réaction (toggle ON)
            cursor.execute("""
            INSERT OR IGNORE INTO reaction_votes (post_id, user_id, emoji)
            VALUES (?, ?, ?)
            """, (post_id, user_id, emoji))
            action = "added"
        
        conn.commit()
    
    logger.info(f"✅ Réaction {action}: {emoji} par user {user_id} sur post {post_id}")
    
    # Récupérer le mapping du message pour l'éditer
    post_mapping = get_post_mapping(post_id)
    if not post_mapping:
        logger.warning(f"❌ Mapping introuvable pour post {post_id}")
        return
    
    # Construire le nouveau clavier avec les compteurs mis à jour
    # Récupérer les emojis présents dans le clavier actuel
    current_markup = query.message.reply_markup
    current_emojis = []
    
    if current_markup and current_markup.inline_keyboard:
        for row in current_markup.inline_keyboard:
            for button in row:
                if button.callback_data and button.callback_data.startswith("r:"):
                    match = re.match(r"^r:(.+):\d+$", button.callback_data)
                    if match:
                        current_emojis.append(match.group(1))
    
    # Utiliser les emojis actuels ou défaut si aucun
    emojis_to_use = current_emojis if current_emojis else ["👍", "🔥"]
    new_keyboard = build_react_keyboard(emojis_to_use, post_id)
    
    # Éditer le message avec le nouveau clavier
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=post_mapping["chat_id"],
            message_id=post_mapping["message_id"],
            reply_markup=new_keyboard
        )
        logger.debug(f"✅ Clavier mis à jour pour post {post_id}")
    except Exception as e:
        logger.error(f"❌ Erreur mise à jour clavier: {e}")

def attach_reactions_to_post(post_id: int, reactions: list = None) -> InlineKeyboardMarkup:
    """
    Attache des réactions à un post (à utiliser lors de l'envoi)
    
    Args:
        post_id: ID unique du post
        reactions: Liste des emojis de réaction (optionnel)
    
    Returns:
        InlineKeyboardMarkup: Clavier avec les boutons de réaction
    """
    if not reactions:
        reactions = ["👍", "🔥"]  # Par défaut
    
    return build_react_keyboard(reactions, post_id)

# Export des fonctions principales
__all__ = [
    'handle_reaction_toggle',
    'save_post_mapping', 
    'attach_reactions_to_post',
    'build_react_keyboard',
    'counts_for'
]
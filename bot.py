"""
Bot Telegram pour la gestion des publications avec réactions et boutons URL
"""

import os
# Configuration de l'encodage pour gérer correctement les emojis
os.environ['PYTHONIOENCODING'] = 'utf-8'

import re
import logging
import asyncio
import sqlite3
import io
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, List, Dict, Any, Callable, Awaitable
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from dotenv import load_dotenv
import pytz
import time
import sys
import platform
from telethon import TelegramClient
import math
from PIL import Image
from conversation_states import (
    MAIN_MENU, POST_CONTENT, POST_ACTIONS, SEND_OPTIONS, AUTO_DESTRUCTION,
    SCHEDULE_SEND, EDIT_POST, SCHEDULE_SELECT_CHANNEL, STATS_SELECT_CHANNEL,
    WAITING_CHANNEL_INFO, SETTINGS, BACKUP_MENU, WAITING_CHANNEL_SELECTION,
    WAITING_PUBLICATION_CONTENT, WAITING_TIMEZONE, WAITING_THUMBNAIL,
    WAITING_REACTION_INPUT, WAITING_URL_INPUT, WAITING_RENAME_INPUT,
    WAITING_SCHEDULE_TIME, WAITING_EDIT_TIME, WAITING_CUSTOM_USERNAME,
    WAITING_TAG_INPUT
)
from config import settings
from database.manager import DatabaseManager
from handlers.reaction_functions import (
    handle_reaction_input,
    handle_url_input,
    remove_reactions,
    remove_url_buttons,
    add_reactions_to_post,
    add_url_button_to_post,
)
from utils.scheduler import SchedulerManager
# Imports schedule_handler supprimés - utilisation de callback_handlers.py
from handlers.thumbnail_handler import (
    handle_thumbnail_functions,
    handle_add_thumbnail_to_post,
    handle_set_thumbnail_and_rename,
    handle_view_thumbnail,
    handle_delete_thumbnail,
    handle_thumbnail_input,
    handle_add_thumbnail
)
from pyrogram import Client
from handlers.callback_handlers import handle_callback, send_post_now
from handlers.message_handlers import handle_text, handle_media, handle_channel_info, handle_post_content, handle_tag_input
from handlers.media_handler import send_file_smart

load_dotenv()

# Wrapper pour handle_schedule_time
async def handle_schedule_time_wrapper(update, context):
    """Wrapper pour handle_schedule_time"""
    try:
        from handlers.callback_handlers import handle_schedule_time
        return await handle_schedule_time(update, context)
    except Exception as e:
        logger.error(f"❌ Erreur dans handle_schedule_time_wrapper: {e}")
        return MAIN_MENU

# Configuration des boutons ReplyKeyboard (en haut du fichier)
REPLY_KEYBOARD_BUTTONS = ["📋 Aperçu", "🚀 Envoyer", "🗑️ Tout supprimer", "❌ Annuler"]

# Filtre intelligent pour les boutons ReplyKeyboard
class ReplyKeyboardButtonFilter(filters.MessageFilter):
    def filter(self, message):
        if not message.text:
            return False
        text = message.text.strip().lower()
        # Vérifier si c'est un de nos boutons (sans tenir compte des emojis)
        return any(keyword in text for keyword in ["aperçu", "envoyer", "tout supprimer", "annuler"])

reply_keyboard_filter = filters.TEXT & ReplyKeyboardButtonFilter()

# Fonction pour créer le ReplyKeyboard standard
def create_reply_keyboard():
    """Crée le clavier de réponse standard"""
    reply_keyboard = [
        [KeyboardButton("📋 Aperçu"), KeyboardButton("🚀 Envoyer")],
        [KeyboardButton("🗑️ Tout supprimer"), KeyboardButton("❌ Annuler")]
    ]
    return ReplyKeyboardMarkup(
        reply_keyboard,
        resize_keyboard=True,
        one_time_keyboard=False
    )

# Handler principal pour TOUS les boutons ReplyKeyboard
async def handle_reply_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère TOUS les boutons ReplyKeyboard de manière intelligente"""
    try:
        user_text = update.message.text.strip()
        logger.info(f"🎯 REPLYKEYBOARD: Bouton '{user_text}' cliqué")
        
        # Récupérer le contexte
        posts = context.user_data.get("posts", [])
        selected_channel = context.user_data.get('selected_channel', {})
        
        if "aperçu" in user_text.lower():
            if not posts:
                await update.message.reply_text(
                    "🔍 **Aperçu indisponible**\n\nAucune publication en cours de création.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                    ]]),
                    parse_mode='Markdown'
                )
                return MAIN_MENU
            else:
                # Afficher l'aperçu détaillé des posts
                for i, post in enumerate(posts):
                    try:
                        preview_text = f"📋 **Aperçu post {i + 1}**\n\n"
                        preview_text += f"Type: {post.get('type', 'Inconnu')}\n"
                        preview_text += f"Canal: {post.get('channel_name', 'Non défini')}\n"
                        
                        if post.get('type') == 'text':
                            content_preview = post.get('content', '')[:200]
                            if len(post.get('content', '')) > 200:
                                content_preview += '...'
                            preview_text += f"Contenu: {content_preview}"
                            await update.message.reply_text(preview_text, parse_mode="Markdown")
                        else:
                            caption_preview = post.get('caption', '')
                            if caption_preview:
                                preview_text += f"Légende: {caption_preview[:100]}"
                                if len(caption_preview) > 100:
                                    preview_text += '...'
                            
                            if post.get('type') == 'photo':
                                await context.bot.send_photo(
                                    chat_id=update.effective_chat.id,
                                    photo=post.get('content'),
                                    caption=preview_text,
                                    parse_mode="Markdown"
                                )
                            elif post.get('type') == 'video':
                                await context.bot.send_video(
                                    chat_id=update.effective_chat.id,
                                    video=post.get('content'),
                                    caption=preview_text,
                                    parse_mode="Markdown"
                                )
                            elif post.get('type') == 'document':
                                await context.bot.send_document(
                                    chat_id=update.effective_chat.id,
                                    document=post.get('content'),
                                    caption=preview_text,
                                    parse_mode="Markdown"
                                )
                    except Exception as e:
                        logger.error(f"Erreur aperçu post {i}: {e}")
                        await update.message.reply_text(f"❌ Erreur aperçu post {i + 1}")
                
                # Message de synthèse avec actions
                await update.message.reply_text(
                    f"📋 **Aperçu terminé** - {len(posts)} publication(s) affichée(s)",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🚀 Envoyer maintenant", callback_data="send_now"),
                        InlineKeyboardButton("📝 Modifier", callback_data="edit_posts")
                    ], [
                        InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                    ]]),
                    parse_mode='Markdown'
                )
                return WAITING_PUBLICATION_CONTENT
        
        elif "envoyer" in user_text.lower():
            return await handle_send_button(update, context)
        
        elif "tout supprimer" in user_text.lower():
            if not posts:
                await update.message.reply_text(
                    "🗑️ **Corbeille vide**\n\nAucune publication à supprimer.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                    ]]),
                    parse_mode='Markdown'
                )
                return MAIN_MENU
            else:
                # Supprimer tous les posts
                context.user_data['posts'] = []
                context.user_data.pop('selected_channel', None)
                
                await update.message.reply_text(
                    f"🗑️ **Publications supprimées**\n\n{len(posts)} publication(s) supprimée(s) avec succès.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                    ]]),
                    parse_mode='Markdown'
                )
                return MAIN_MENU
        
        elif "annuler" in user_text.lower():
            # Nettoyer toutes les données
            context.user_data.clear()
            
            await update.message.reply_text(
                "❌ **Opération annulée**\n\nToutes les données temporaires ont été effacées.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]]),
                parse_mode='Markdown'
            )
            return MAIN_MENU
        
        # Fallback pour les autres cas
        await update.message.reply_text(
            "❓ **Bouton non reconnu**\n\nUtilisez les boutons disponibles ci-dessous.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU
        
    except Exception as e:
        logger.error(f"Erreur dans handle_reply_keyboard: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

# -----------------------------------------------------------------------------
# CONFIGURATION DU LOGGING
# -----------------------------------------------------------------------------
def setup_logging():
    """Configure le système de logging"""
    # Créer le dossier logs s'il n'existe pas
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # Configuration du logger principal
    logger = logging.getLogger('UploaderBot')
    logger.setLevel(logging.INFO)

    # Handler pour la console avec encodage UTF-8
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    console_handler.stream.reconfigure(encoding='utf-8')  # Configuration de l'encodage UTF-8
    logger.addHandler(console_handler)

    # Handler pour le fichier avec encodage UTF-8
    file_handler = logging.FileHandler('logs/bot.log', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

# Configuration globale
logger = setup_logging()

# -----------------------------------------------------------------------------
# RATE LIMITER
# -----------------------------------------------------------------------------
class RateLimiter:
    def __init__(self):
        self.user_timestamps = {}

    async def can_send_message(self, chat_id, user_id, limit=1, per_seconds=1):
        now = time.time()
        key = (chat_id, user_id)
        timestamps = self.user_timestamps.get(key, [])
        # On ne garde que les timestamps récents
        timestamps = [t for t in timestamps if now - t < per_seconds]
        if len(timestamps) < limit:
            timestamps.append(now)
            self.user_timestamps[key] = timestamps
            return True
        return False

rate_limiter = RateLimiter()

# -----------------------------------------------------------------------------
# FONCTIONS UTILITAIRES
# -----------------------------------------------------------------------------
def normalize_channel_username(channel_username):
    """
    Normalise le nom d'utilisateur d'un canal en enlevant le @ s'il est présent
    Retourne None si l'entrée est vide ou None
    """
    if not channel_username:
        return None
    return channel_username.lstrip('@') if isinstance(channel_username, str) else None

def debug_thumbnail_search(user_id, channel_username, db_manager):
    """Fonction de debug pour diagnostiquer les problèmes de recherche de thumbnails"""
    logger.info(f"=== DEBUG THUMBNAIL SEARCH ===")
    logger.info(f"User ID: {user_id}")
    logger.info(f"Channel Username Original: '{channel_username}'")
    
    # Normalisation
    clean_username = normalize_channel_username(channel_username)
    logger.info(f"Channel Username Normalisé: '{clean_username}'")
    
    # Tester différentes variantes
    test_variants = [
        channel_username,
        clean_username,
        f"@{clean_username}" if clean_username and not clean_username.startswith('@') else clean_username,
        clean_username.lstrip('@') if clean_username else None
    ]
    
    logger.info(f"Variants à tester: {test_variants}")
    
    # Tester chaque variant
    for variant in test_variants:
        if variant:
            result = db_manager.get_thumbnail(variant, user_id)
            logger.info(f"Test variant '{variant}': {result}")
    
    # Vérifier directement dans la base de données
    try:
        conn = sqlite3.connect(settings.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT channel_username, thumbnail_file_id FROM channel_thumbnails WHERE user_id = ?", (user_id,))
        all_thumbnails = cursor.fetchall()
        logger.info(f"TOUS les thumbnails pour user {user_id}: {all_thumbnails}")
        conn.close()
    except Exception as e:
        logger.error(f"Erreur lors de la vérification DB: {e}")
    
    logger.info(f"=== FIN DEBUG ===")

def ensure_thumbnail_table_exists():
    """S'assure que la table channel_thumbnails existe"""
    try:
        conn = sqlite3.connect(settings.db_path)
        cursor = conn.cursor()
        
        # Vérifier si la table existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channel_thumbnails'")
        table_exists = cursor.fetchone() is not None
        
        if not table_exists:
            logger.info("Création de la table channel_thumbnails manquante...")
            cursor.execute('''
                CREATE TABLE channel_thumbnails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_username TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    thumbnail_file_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel_username, user_id)
                )
            ''')
            conn.commit()
            logger.info("✅ Table channel_thumbnails créée avec succès!")
        else:
            logger.info("✅ Table channel_thumbnails existe déjà")
        
        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ Erreur lors de la création de la table channel_thumbnails: {e}")
        return False

# Initialisation de la base de données
db_manager = DatabaseManager()
db_manager.setup_database()

# Vérifier et créer la table channel_thumbnails si nécessaire
def ensure_channel_thumbnails_table():
    """S'assure que la table channel_thumbnails existe dans la base de données"""
    try:
        cursor = db_manager.connection.cursor()
        
        # Vérifier si la table existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channel_thumbnails'")
        table_exists = cursor.fetchone() is not None
        
        if not table_exists:
            logger.info("⚠️ Table channel_thumbnails manquante - création en cours...")
            cursor.execute('''
                CREATE TABLE channel_thumbnails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_username TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    thumbnail_file_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel_username, user_id)
                )
            ''')
            db_manager.connection.commit()
            logger.info("✅ Table channel_thumbnails créée avec succès!")
        else:
            logger.info("✅ Table channel_thumbnails existe déjà")
        
        return True
    except Exception as e:
        logger.error(f"❌ Erreur lors de la vérification de la table channel_thumbnails: {e}")
        return False

# Exécuter la vérification
ensure_channel_thumbnails_table()

logger.info(f"Base de données initialisée avec succès")

# -----------------------------------------------------------------------------
# DECORATEURS ET UTILITAIRES
# -----------------------------------------------------------------------------
def admin_only(func):
    @wraps(func)
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in settings.ADMIN_IDS:
            await update.message.reply_text("❌ Vous n'avez pas les permissions nécessaires.")
            return
        return await func(update, context, *args, **kwargs)


async def retry_operation(operation, max_retries=3, delay=1):
    for attempt in range(max_retries):
        try:
            return await operation()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Tentative {attempt + 1} échouée: {e}")
            await asyncio.sleep(delay * (attempt + 1))


# -----------------------------------------------------------------------------
# DÉFINITION DES ÉTATS DE LA CONVERSATION
# -----------------------------------------------------------------------------
# Stockage des réactions
reaction_counts = {}

# Variable globale pour le userbot
userbot = None

# Ensemble pour stocker les callbacks déjà traités
processed_callbacks = set()

# Filtres personnalisés
class WaitingForUrlFilter(filters.MessageFilter):
    def filter(self, message):
        if not message.text:
            return False
        context = message.get_bot().application.user_data.get(message.from_user.id, {})
        return context.get('waiting_for_url', False)

class WaitingForReactionsFilter(filters.MessageFilter):
    def filter(self, message):
        if not message.text:
            return False
        context = message.get_bot().application.user_data.get(message.from_user.id, {})
        return context.get('waiting_for_reactions', False)

# Instances des filtres (ancienne classe ReplyKeyboardFilter supprimée - conflit avec la nouvelle)
waiting_for_url_filter = WaitingForUrlFilter()
waiting_for_reactions_filter = WaitingForReactionsFilter()
# reply_keyboard_filter est maintenant défini plus haut avec ReplyKeyboardButtonFilter






# SchedulerManager maintenant importé de schedule_handler


# Fonction pour initialiser le client Telethon
async def start_telethon_client():
    """Initialise le client Telethon"""
    try:
        client = TelegramClient(settings.SESSION_NAME, settings.API_ID, settings.API_HASH)
        await client.start()
        logger.info("Client Telethon démarré avec succès")
        return client
    except Exception as e:
        logger.error(f"Erreur lors du démarrage du client Telethon: {e}")
        return None


async def init_userbot():
    """Initialise le userbot au démarrage du bot"""
    global userbot
    userbot = await start_telethon_client()
    return userbot


def log_conversation_state(update, context, function_name, state_return):
    """Enregistre les informations d'état de conversation pour débogage"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    logger.info(f"[ÉTAT] Fonction: {function_name}, Utilisateur: {user_id}, Chat: {chat_id}")
    logger.info(f"[ÉTAT] État de retour: {state_return}")
    logger.info(f"[ÉTAT] État stocké: {context.user_data.get('conversation_state', 'Non défini')}")

    # Détecter les incohérences potentielles
    if 'conversation_state' in context.user_data and state_return != context.user_data['conversation_state']:
        logger.warning(
            f"[ÉTAT] Incohérence détectée! Retour: {state_return}, Stocké: {context.user_data['conversation_state']}")

    # Mettre à jour l'état stocké
    context.user_data['conversation_state'] = state_return

    return state_return


# Fonction start supprimée - utilise maintenant command_handlers.start dans CommandHandlers

# Fonction create_publication supprimée - utilise maintenant handle_create_publication dans callback_handlers.py


# planifier_post maintenant importé de schedule_handler


# Fonction send_post_now déplacée vers callback_handlers.py pour éviter l'import circulaire
# Elle est maintenant importée depuis callback_handlers


async def handle_set_thumbnail_and_rename(update, context):
    """Applique le thumbnail ET permet de renommer le fichier"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Extraire l'index du post
        post_index = int(query.data.split("_")[-1])
        
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        post = context.user_data['posts'][post_index]
        channel_username = post.get('channel', context.user_data.get('selected_channel', {}).get('username'))
        user_id = update.effective_user.id
        
        # Utiliser la fonction de normalisation
        clean_username = normalize_channel_username(channel_username)
        
        if not clean_username:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Impossible de déterminer le canal cible.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Récupérer et appliquer le thumbnail
        thumbnail_file_id = db_manager.get_thumbnail(clean_username, user_id)
        
        if thumbnail_file_id:
            post['thumbnail'] = thumbnail_file_id
            thumbnail_status = "✅ Thumbnail appliqué"
        else:
            thumbnail_status = "⚠️ Aucun thumbnail enregistré pour ce canal"
        
        # Stocker l'index pour le renommage
        context.user_data['waiting_for_rename'] = True
        context.user_data['current_post_index'] = post_index
        
        # Demander le nouveau nom
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"🖼️✏️ Thumbnail + Renommage\n\n"
                 f"{thumbnail_status}\n\n"
                 f"Maintenant, envoyez-moi le nouveau nom pour votre fichier (avec l'extension).\n"
                 f"Par exemple: mon_document.pdf",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_rename_{post_index}")
            ]])
        )
        
        return WAITING_RENAME_INPUT
        
    except Exception as e:
        logger.error(f"Erreur dans handle_set_thumbnail_and_rename: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

async def handle_view_thumbnail(update, context):
    """Affiche le thumbnail enregistré pour un canal"""
    query = update.callback_query
    await query.answer()
    
    channel_username = context.user_data.get('custom_channel')
    if not channel_username:
        selected_channel = context.user_data.get('selected_channel', {})
        channel_username = selected_channel.get('username')
    
    if not channel_username:
        await query.edit_message_text(
            "❌ Aucun canal sélectionné.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")
            ]])
        )
        return SETTINGS
    
    user_id = update.effective_user.id
    clean_username = normalize_channel_username(channel_username)
    
    thumbnail_file_id = db_manager.get_thumbnail(clean_username, user_id)
    
    if thumbnail_file_id:
        try:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=thumbnail_file_id,
                caption=f"🖼️ Thumbnail actuel pour @{clean_username}"
            )
            
            keyboard = [
                [InlineKeyboardButton("🔄 Changer", callback_data="add_thumbnail")],
                [InlineKeyboardButton("🗑️ Supprimer", callback_data="delete_thumbnail")],
                [InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")]
            ]
            
            await query.message.reply_text(
                "Que voulez-vous faire avec ce thumbnail?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Erreur lors de l'affichage du thumbnail: {e}")
            await query.edit_message_text(
                "❌ Impossible d'afficher le thumbnail.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
                ]])
            )
    else:
        await query.edit_message_text(
            "❌ Aucun thumbnail enregistré pour ce canal.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
            ]])
        )
    
    return SETTINGS

async def handle_delete_thumbnail(update, context):
    """Supprime le thumbnail enregistré pour un canal"""
    query = update.callback_query
    await query.answer()
    
    channel_username = context.user_data.get('custom_channel')
    if not channel_username:
        selected_channel = context.user_data.get('selected_channel', {})
        channel_username = selected_channel.get('username')
    
    if not channel_username:
        await query.edit_message_text(
            "❌ Aucun canal sélectionné.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")
            ]])
        )
        return SETTINGS
    
    user_id = update.effective_user.id
    clean_username = normalize_channel_username(channel_username)
    
    if db_manager.delete_thumbnail(clean_username, user_id):
        await query.edit_message_text(
            f"✅ Thumbnail supprimé pour @{clean_username}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
            ]])
        )
    else:
        await query.edit_message_text(
            "❌ Erreur lors de la suppression du thumbnail.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
            ]])
        )
    
    return SETTINGS

async def handle_rename_input(update, context):
    """Gère la saisie du nouveau nom de fichier"""
    try:
        if not context.user_data.get('waiting_for_rename') or 'current_post_index' not in context.user_data:
            await update.message.reply_text(
                "❌ Aucun renommage en cours.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        post_index = context.user_data['current_post_index']
        new_filename = update.message.text.strip()
        
        # Les boutons ReplyKeyboard sont maintenant gérés par le handler contextuel
        # Cette fonction ne traite que les vrais noms de fichiers
        
        # Validation du nom de fichier
        if not new_filename or '/' in new_filename or '\\' in new_filename:
            await update.message.reply_text(
                "❌ Nom de fichier invalide. Évitez les caractères spéciaux / et \\.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_rename_{post_index}")
                ]])
            )
            return WAITING_RENAME_INPUT
        
        # Appliquer le nouveau nom
        if 'posts' in context.user_data and post_index < len(context.user_data['posts']):
            context.user_data['posts'][post_index]['filename'] = new_filename
            
            # Nettoyer les variables temporaires
            context.user_data.pop('waiting_for_rename', None)
            context.user_data.pop('current_post_index', None)
            
            await update.message.reply_text(
                f"✅ Fichier renommé en : {new_filename}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            
            return WAITING_PUBLICATION_CONTENT
        else:
            await update.message.reply_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
    
    except Exception as e:
        logger.error(f"Erreur dans handle_rename_input: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

def is_valid_channel_username(username):
    """
    Vérifie que le username commence par @ ou t.me/ et ne contient pas d'espaces
    """
    if not username:
        return False
    username = username.strip()
    return (username.startswith('@') or username.startswith('t.me/')) and ' ' not in username


def clean_channel_username(username):
    """
    Nettoie le username du canal en enlevant les préfixes @ et t.me/
    """
    if not username:
        return None
    username = username.strip()
    if username.startswith('@'):
        return username[1:]
    elif username.startswith('t.me/'):
        return username[5:]
    return username


async def remove_reactions(update, context):
    """Supprime les réactions d'un message"""
    try:
        if not update.callback_query:
            return
        message = update.callback_query.message
        if not message:
            await update.callback_query.answer("Message non trouvé")
            return
        message_id = message.message_id
        chat_id = message.chat_id
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None
            )
            await update.callback_query.answer("✅ Réactions supprimées")
        except Exception as e:
            logger.error(f"Erreur lors de la suppression des réactions: {e}")
            await update.callback_query.answer("❌ Erreur lors de la suppression des réactions")
    except Exception as e:
        logger.error(f"Erreur dans remove_reactions: {e}")
        if update.callback_query:
            await update.callback_query.answer("❌ Une erreur est survenue")


async def remove_url_buttons(update, context):
    """Supprime les boutons URL d'un message"""
    try:
        if not update.callback_query:
            return
        message = update.callback_query.message
        if not message:
            await update.callback_query.answer("Message non trouvé")
            return
        message_id = message.message_id
        chat_id = message.chat_id
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None
            )
            await update.callback_query.answer("✅ Boutons URL supprimés")
        except Exception as e:
            logger.error(f"Erreur lors de la suppression des boutons URL: {e}")
            await update.callback_query.answer("❌ Erreur lors de la suppression des boutons URL")
    except Exception as e:
        logger.error(f"Erreur dans remove_url_buttons: {e}")
        if update.callback_query:
            await update.callback_query.answer("❌ Une erreur est survenue")


async def send_preview_file(update, context, post_index):
    """Envoie une prévisualisation du fichier à l'utilisateur"""
    try:
        posts = context.user_data.get("posts", [])
        if not posts or post_index >= len(posts):
            await update.callback_query.answer("❌ Aucun fichier trouvé")
            return
        post = posts[post_index]
        file_id = post.get("file_id")
        file_name = post.get("file_name", "fichier")
        file_size = post.get("file_size", 0)
        caption = post.get("caption", "")
        if not file_id:
            await update.callback_query.answer("❌ Fichier non trouvé")
            return
        preview_text = (
            f"📁 Prévisualisation du fichier {post_index + 1}/{len(posts)}\n\n"
            f"📝 Nom: {file_name}\n"
            f"📊 Taille: {file_size / 1024 / 1024:.2f} MB\n"
        )
        if caption:
            preview_text += f"\n📝 Légende: {caption}"
        try:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file_id,
                caption=preview_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_file_{post_index}")],
                    [InlineKeyboardButton("📝 Modifier la légende", callback_data=f"edit_caption_{post_index}")]
                ])
            )
            await update.callback_query.answer("✅ Prévisualisation envoyée")
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi de la prévisualisation: {e}")
            await update.callback_query.answer("❌ Erreur lors de l'envoi de la prévisualisation")
    except Exception as e:
        logger.error(f"Erreur dans send_preview_file: {e}")
        if update.callback_query:
            await update.callback_query.answer("❌ Une erreur est survenue")

async def cleanup(application):
    """Nettoie les ressources avant l'arrêt du bot"""
    try:
        # Fermer la connexion à la base de données
        try:
            if db_manager:
                db_manager.close()
        except:
            pass
        
        # Arrêter le client Telethon
        try:
            if application.bot_data.get('userbot'):
                await application.bot_data['userbot'].disconnect()
        except:
            pass
        
        # Arrêter le scheduler depuis l'application
        try:
            if hasattr(application, 'scheduler_manager') and application.scheduler_manager:
                application.scheduler_manager.stop()
        except:
            pass
        
        logger.info("✅ Nettoyage effectué avec succès")
    except Exception as e:
        logger.error(f"❌ Erreur lors du nettoyage: {e}")

# -----------------------------------------------------------------------------
# GESTION SIMPLE DU BOUTON "ENVOYER" - UTILISE LES FONCTIONS EXISTANTES
# -----------------------------------------------------------------------------

async def handle_send_button(update, context):
    """Gère le bouton 'Envoyer' du ReplyKeyboard en utilisant les fonctions existantes"""
    try:
        logger.info("Bouton 'Envoyer' activé par l'utilisateur")
        
        # Vérifier si un post planifié est sélectionné
        if 'current_scheduled_post' in context.user_data:
            logger.info("Post planifié détecté, envoi immédiat")
            scheduled_post = context.user_data['current_scheduled_post']
            return await send_post_now(update, context, scheduled_post=scheduled_post)
        
        # Vérifier s'il y a des posts en attente
        posts = context.user_data.get("posts", [])
        if not posts:
            await update.message.reply_text(
                "❌ Il n'y a pas encore de fichiers à envoyer.\n"
                "Veuillez d'abord ajouter du contenu (texte, photo, vidéo, document).",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📝 Créer une publication", callback_data="create_publication")
                ], [
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return WAITING_PUBLICATION_CONTENT
        
        # Obtenir les informations du canal
        selected_channel = context.user_data.get('selected_channel', {})
        channel = posts[0].get("channel") or selected_channel.get('username', '@default_channel')
        
        # Utiliser les MÊMES boutons que dans schedule_handler.py
        keyboard = [
            [InlineKeyboardButton("Régler temps d'auto destruction", callback_data="auto_destruction")],
            [InlineKeyboardButton("Maintenant", callback_data="send_now")],
            [InlineKeyboardButton("Planifier", callback_data="schedule_send")],
            [InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]
        ]
        
        # Message identique à celui de schedule_handler.py
        message = f"Vos {len(posts)} fichiers sont prêts à être envoyés à {channel}.\nQuand souhaitez-vous les envoyer ?"
        
        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        logger.info(f"Menu d'envoi affiché pour {len(posts)} fichiers vers {channel}")
        return WAITING_PUBLICATION_CONTENT
        
    except Exception as e:
        logger.error(f"Erreur dans handle_send_button: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors de la préparation de l'envoi.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


def analyze_posts_content(posts):
    """Analyse et résume le contenu des posts"""
    try:
        type_counts = {
            "photo": 0,
            "video": 0,
            "document": 0,
            "text": 0
        }
        
        total_reactions = 0
        total_buttons = 0
        
        for post in posts:
            post_type = post.get("type", "unknown")
            if post_type in type_counts:
                type_counts[post_type] += 1
            
            # Compter les réactions et boutons
            reactions = post.get("reactions", [])
            buttons = post.get("buttons", [])
            total_reactions += len(reactions)
            total_buttons += len(buttons)
        
        # Construire le résumé
        summary_parts = []
        total_files = sum(type_counts.values())
        
        if total_files == 1:
            # Un seul fichier
            for file_type, count in type_counts.items():
                if count > 0:
                    type_names = {
                        "photo": "📸 Photo",
                        "video": "🎥 Vidéo", 
                        "document": "📄 Document",
                        "text": "📝 Texte"
                    }
                    summary_parts.append(type_names.get(file_type, f"{file_type}"))
                    break
        else:
            # Plusieurs fichiers
            summary_parts.append(f"{total_files} fichiers")
            if type_counts["photo"] > 0:
                summary_parts.append(f"{type_counts['photo']} photo(s)")
            if type_counts["video"] > 0:
                summary_parts.append(f"{type_counts['video']} vidéo(s)")
            if type_counts["document"] > 0:
                summary_parts.append(f"{type_counts['document']} document(s)")
            if type_counts["text"] > 0:
                summary_parts.append(f"{type_counts['text']} texte(s)")
        
        # Ajouter les extras
        extras = []
        if total_reactions > 0:
            extras.append(f"{total_reactions} réaction(s)")
        if total_buttons > 0:
            extras.append(f"{total_buttons} bouton(s) URL")
        
        result = ", ".join(summary_parts)
        if extras:
            result += f" + {', '.join(extras)}"
            
        return result
        
    except Exception as e:
        logger.error(f"Erreur dans analyze_posts_content: {e}")
        return f"{len(posts)} fichier(s)"

def main():
    """Fonction principale du bot"""
    try:
        # Configuration de l'application
        application = Application.builder().token(settings.bot_token).build()

        # Ajout de logs pour le démarrage
        logger.info("🚀 Démarrage du bot...")
        logger.info(f"📱 Version Python: {platform.python_version()}")
        logger.info(f"💻 Système: {platform.system()} {platform.release()}")

        # Initialisation des compteurs de réactions globaux
        application.bot_data['reaction_counts'] = {}

        # Initialisation du scheduler
        application.scheduler_manager = SchedulerManager()
        application.scheduler_manager.start()
        logger.info("✅ Scheduler démarré avec succès")
        
        # Vérifier que le scheduler fonctionne
        logger.info(f"🔍 Scheduler running: {application.scheduler_manager.scheduler.running}")
        logger.info(f"🔍 Scheduler state: {application.scheduler_manager.scheduler.state}")
        
        # Définir le scheduler manager global pour les callbacks
        from handlers.callback_handlers import set_global_scheduler_manager
        set_global_scheduler_manager(application.scheduler_manager)
        
        # Définir l'application globale pour les tâches planifiées
        from utils.scheduler_utils import set_global_application
        set_global_application(application)
        
        # ✅ CORRECTION : Définir aussi le scheduler manager dans scheduler_utils
        from utils.scheduler_utils import set_global_scheduler_manager as set_scheduler_utils_manager
        set_scheduler_utils_manager(application.scheduler_manager)

        # ✅ NOUVEAU : Restaurer les posts planifiés depuis la base de données
        async def restore_scheduled_posts():
            """Restaure tous les posts planifiés depuis la base de données au démarrage"""
            try:
                logger.info("🔄 Restauration des posts planifiés...")
                
                # Récupérer tous les posts planifiés non envoyés
                with sqlite3.connect(settings.db_config["path"]) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT id, scheduled_time, post_type, content, caption, channel_id
                        FROM posts 
                        WHERE scheduled_time > datetime('now') 
                        AND (status = 'pending' OR status IS NULL)
                    """)
                    scheduled_posts = cursor.fetchall()
                    
                if not scheduled_posts:
                    logger.info("✅ Aucun post planifié à restaurer")
                    return
                    
                restored_count = 0
                for post_data in scheduled_posts:
                    try:
                        post_id, scheduled_time_str, post_type, content, caption, channel_id = post_data
                        
                        # Parser la date avec le bon fuseau horaire
                        from datetime import datetime
                        import pytz
                        
                        # Récupérer le fuseau horaire depuis la base de données
                        # On cherche l'utilisateur propriétaire du post
                        cursor.execute("SELECT c.user_id FROM channels c WHERE c.id = ?", (channel_id,))
                        user_result = cursor.fetchone()
                        
                        if user_result:
                            user_id = user_result[0]
                            cursor.execute("SELECT timezone FROM user_timezones WHERE user_id = ?", (user_id,))
                            tz_result = cursor.fetchone()
                            user_timezone = tz_result[0] if tz_result else 'Europe/Paris'
                        else:
                            user_timezone = 'Europe/Paris'  # Fallback
                        
                        scheduled_time = datetime.strptime(scheduled_time_str, '%Y-%m-%d %H:%M:%S')
                        # Localiser avec le bon fuseau horaire
                        scheduled_time = pytz.timezone(user_timezone).localize(scheduled_time)
                        
                        # Créer le job
                        job_id = f"post_{post_id}"
                        
                        # ✅ CORRECTION : Créer une fonction wrapper synchrone simple
                        def send_restored_post_job(post_id=post_id):
                            """Fonction wrapper pour envoyer un post restauré"""
                            import asyncio
                            try:
                                # Créer une nouvelle boucle pour le job
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                
                                # Fonction asynchrone pour envoyer le post
                                async def send_post_async():
                                    from utils.scheduler_utils import send_scheduled_file
                                    post_dict = {"id": post_id}
                                    await send_scheduled_file(post_dict, application)
                                
                                # Exécuter la fonction asynchrone
                                loop.run_until_complete(send_post_async())
                                loop.close()
                                
                                logger.info(f"✅ Post {post_id} envoyé avec succès")
                                
                            except Exception as job_error:
                                logger.error(f"❌ Erreur dans le job {post_id}: {job_error}")
                                logger.exception("Traceback:")
                        
                        # Ajouter le job au scheduler avec la fonction wrapper corrigée
                        application.scheduler_manager.scheduler.add_job(
                            func=send_restored_post_job,
                            trigger="date",
                            run_date=scheduled_time,
                            id=job_id,
                            replace_existing=True
                        )
                        
                        restored_count += 1
                        logger.info(f"✅ Post {post_id} restauré pour {scheduled_time}")
                        
                    except Exception as e:
                        logger.error(f"❌ Erreur lors de la restauration du post {post_id}: {e}")
                        continue
                
                logger.info(f"✅ {restored_count} posts planifiés restaurés avec succès")
                
            except Exception as e:
                logger.error(f"❌ Erreur lors de la restauration des posts planifiés: {e}")
                logger.exception("Traceback:")
        
        # Exécuter la restauration
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(restore_scheduled_posts())
        except Exception as e:
            logger.error(f"❌ Erreur lors de la restauration des posts: {e}")

        # ✅ NOUVEAU : Ajouter une tâche de nettoyage automatique des vieux fichiers
        try:
            from utils.file_manager import FileManager
            file_manager = FileManager()
            
            # Fonction de nettoyage
            def cleanup_old_files_job():
                try:
                    logger.info("🧹 Début du nettoyage automatique des vieux fichiers...")
                    deleted_count = file_manager.cleanup_old_files(max_age_days=7)
                    logger.info(f"✅ {deleted_count} fichiers supprimés")
                except Exception as e:
                    logger.error(f"❌ Erreur lors du nettoyage des fichiers: {e}")
            
            # Planifier le nettoyage tous les jours à 3h du matin
            application.scheduler_manager.scheduler.add_job(
                func=cleanup_old_files_job,
                trigger="cron",
                hour=3,
                minute=0,
                id="cleanup_old_files",
                replace_existing=True
            )
            logger.info("✅ Tâche de nettoyage automatique planifiée (tous les jours à 3h)")
            
            # Exécuter un nettoyage immédiat au démarrage
            cleanup_old_files_job()
            
        except Exception as e:
            logger.warning(f"⚠️ Impossible de planifier le nettoyage automatique: {e}")

        # Initialisation des clients Pyrogram/Telethon pour les gros fichiers
        async def init_clients():
            try:
                from utils.clients import client_manager
                await client_manager.start_clients()
                logger.info("✅ Clients Pyrogram/Telethon démarrés pour la gestion des gros fichiers")
            except Exception as e:
                logger.warning(f"⚠️ Impossible de démarrer les clients avancés: {e}")
                logger.warning("Les fichiers > 50MB ne pourront pas être traités avec thumbnail personnalisé")
        
        # Démarrer les clients dans une tâche asynchrone
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(init_clients())
        except Exception as e:
            logger.error(f"❌ Erreur démarrage clients: {e}")

        # Log des états de conversation pour débogage
        logger.info(f"Définition des états de conversation:")
        logger.info(f"MAIN_MENU = {MAIN_MENU}")
        logger.info(f"POST_CONTENT = {POST_CONTENT}")
        logger.info(f"POST_ACTIONS = {POST_ACTIONS}")
        logger.info(f"WAITING_PUBLICATION_CONTENT = {WAITING_PUBLICATION_CONTENT}")
        logger.info(f"WAITING_REACTION_INPUT = {WAITING_REACTION_INPUT}")
        logger.info(f"WAITING_URL_INPUT = {WAITING_URL_INPUT}")

        # Initialisation du userbot Telethon
        userbot = TelegramClient(settings.session_name, settings.api_id, settings.api_hash)
        userbot.start()
        logger.info("Client Telethon démarré avec succès")
        application.bot_data['userbot'] = userbot

        # Initialiser les command handlers
        from handlers.command_handlers import CommandHandlers
        
        # ✅ CORRECTION : ScheduledTasks supprimé - utiliser None
        command_handlers = CommandHandlers(db_manager, None)

        # Définition du ConversationHandler avec les différents états
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("start", command_handlers.start),
                CommandHandler("create", command_handlers.create_publication),
                CommandHandler("settings", command_handlers.settings),
            ],
            states={
                MAIN_MENU: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    CallbackQueryHandler(handle_callback),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
                ],
                POST_CONTENT: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    MessageHandler(filters.Document.ALL, handle_media),
                    MessageHandler(filters.PHOTO, handle_media),
                    MessageHandler(filters.VIDEO, handle_media),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_REACTION_INPUT: [
                    MessageHandler(filters.TEXT, handle_reaction_input),
                    CallbackQueryHandler(handle_callback)
                ],
                WAITING_URL_INPUT: [
                    MessageHandler(filters.TEXT, handle_url_input),
                    CallbackQueryHandler(handle_callback)
                ],
                WAITING_CHANNEL_SELECTION: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_THUMBNAIL: [
                    MessageHandler(filters.PHOTO, handle_thumbnail_input),
                ],
                WAITING_CUSTOM_USERNAME: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
                ],
                WAITING_CHANNEL_INFO: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    MessageHandler(filters.TEXT, handle_channel_info),
                ],
                SETTINGS: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    CallbackQueryHandler(handle_callback),
                ],
                POST_ACTIONS: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    CallbackQueryHandler(handle_callback),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
                ],
                WAITING_PUBLICATION_CONTENT: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    MessageHandler(filters.PHOTO, handle_post_content),
                    MessageHandler(filters.VIDEO, handle_post_content),
                    MessageHandler(filters.Document.ALL, handle_post_content),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_post_content),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_RENAME_INPUT: [
                    MessageHandler(filters.TEXT, handle_rename_input),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_TAG_INPUT: [
                    MessageHandler(filters.TEXT, handle_tag_input),
                    CallbackQueryHandler(handle_callback),
                ],
                SCHEDULE_SEND: [
                    # Handler pour la planification
                    MessageHandler(filters.TEXT, handle_schedule_time_wrapper),
                    CallbackQueryHandler(handle_callback),
                ],
                SCHEDULE_SELECT_CHANNEL: [
                    # Handler pour la sélection de canal planifié
                    CallbackQueryHandler(handle_callback),
                ],


            },
            fallbacks=[
                CommandHandler("cancel", lambda update, context: ConversationHandler.END),
                CommandHandler("start", command_handlers.start),
                # Handler de fallback pour les boutons ReplyKeyboard
                MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                CallbackQueryHandler(handle_callback),
            ],
            per_message=False,
            name="main_conversation",
            persistent=False,
            allow_reentry=True,
        )

        logger.info("ConversationHandler configuré avec états: %s",
                    ", ".join(str(state) for state in conv_handler.states.keys()))

        application.add_handler(conv_handler, group=0)  # Priorité normale après handler global
        logger.info("Ajout du handler de callback global")
        
        # Importer et utiliser le gestionnaire d'erreurs
        from handlers.command_handlers import error_handler
        application.add_error_handler(error_handler)

        # Démarrage du bot
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Erreur lors du démarrage du bot: {e}")
        raise
    finally:
        # Nettoyage à la fin
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_closed():
                loop.run_until_complete(cleanup(application))
        except RuntimeError:
            # Si la boucle est fermée, créer une nouvelle boucle
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(cleanup(application))
            loop.close()

if __name__ == '__main__':
    main()
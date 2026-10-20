from typing import Dict, Callable, Awaitable, Optional
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from datetime import datetime, timedelta
import sqlite3
import pytz
import os
import asyncio
import json
import sys
import time

from utils.message_utils import MessageError, PostType, safe_edit_message_text
from database.manager import DatabaseManager
from database.channel_repo import list_user_channels
from utils.validators import InputValidator
from conversation_states import (
    MAIN_MENU,
    SCHEDULE_SELECT_CHANNEL,
    SCHEDULE_SEND,
    SETTINGS,
    WAITING_CHANNEL_SELECTION,
    WAITING_CHANNEL_INFO,
    WAITING_PUBLICATION_CONTENT,
    AUTO_DESTRUCTION,
    WAITING_TAG_INPUT,

)
from utils.error_handler import handle_error
from utils.scheduler import SchedulerManager
from utils.scheduler_utils import send_scheduled_file
from config import settings

# Utilisation des constantes depuis settings
MAX_FILES_PER_MEDIA_GROUP = settings.MAX_FILES_PER_MEDIA_GROUP
DELAY_BETWEEN_GROUPS = settings.DELAY_BETWEEN_GROUPS
MAX_MEDIA_GROUP_SIZE = settings.MAX_MEDIA_GROUP_SIZE


logger = logging.getLogger(__name__)

# Variable globale pour le scheduler manager
_global_scheduler_manager = None

# === Reactions DB helpers (SQLite persistent toggle) ===
def _get_db_path() -> str:
    """Resolve SQLite DB path from settings with sensible fallbacks."""
    try:
        if hasattr(settings, 'db_config') and isinstance(settings.db_config, dict):
            p = settings.db_config.get('path')
            if p:
                return p
    except Exception:
        pass
    try:
        if hasattr(settings, 'db_path') and settings.db_path:
            return settings.db_path
    except Exception:
        pass
    # Fallback uniforme - toujours data/bot.db
    from pathlib import Path
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "bot.db")

def _ensure_reactions_schema(conn: sqlite3.Connection) -> None:
    """Create tables for reactions if they do not exist."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reactions_counts (
            chat_id    INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            emoji      TEXT    NOT NULL,
            count      INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, message_id, emoji)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reactions_votes (
            chat_id    INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id    INTEGER NOT NULL,
            emoji      TEXT,
            PRIMARY KEY (chat_id, message_id, user_id)
        )
        """
    )
    conn.commit()

# Fonction pour définir le scheduler manager global
def set_global_scheduler_manager(scheduler_manager):
    """Sets the global scheduler manager"""
    global _global_scheduler_manager
    _global_scheduler_manager = scheduler_manager
    logger.info("✅ Global scheduler manager set")

# Fonction pour valider qu'un post a un canal associé
async def ensure_post_has_channel(db_path: str, post_id: int, user_id: int):
    """
    Vérifie qu'un post a un canal associé et essaie de le récupérer si nécessaire.
    
    Args:
        db_path: Chemin vers la base de données
        post_id: ID du post à vérifier
        user_id: ID de l'utilisateur
        
    Returns:
        tuple: (success: bool, reason: str, channel: str or None)
    """
    try:
        import sqlite3
        
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # Vérifier si le post existe et a un canal
            cursor.execute("SELECT channel_id FROM posts WHERE id = ?", (post_id,))
            result = cursor.fetchone()
            
            if not result:
                logger.warning(f"⚠️ Post {post_id} not found in database")
                return False, "not_found", None
            
            channel_id = result[0]
            
            # Si le post a déjà un canal, c'est bon
            if channel_id:
                logger.info(f"✅ Post {post_id} has channel: {channel_id}")
                return True, "ok", channel_id
            
            # Essayer de récupérer un canal par défaut pour l'utilisateur
            logger.warning(f"⚠️ Post {post_id} has no channel, trying to find default channel for user {user_id}")
            
            # Chercher dans les canaux récents de l'utilisateur
            cursor.execute("""
                SELECT channel_id FROM channels 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT 1
            """, (user_id,))
            default_channel = cursor.fetchone()
            
            if default_channel:
                default_channel_id = default_channel[0]
                # Mettre à jour le post avec le canal par défaut
                cursor.execute("""
                    UPDATE posts 
                    SET channel_id = ? 
                    WHERE id = ?
                """, (default_channel_id, post_id))
                conn.commit()
                
                logger.info(f"✅ Post {post_id} bound to default channel: {default_channel_id}")
                return True, "bound_from_default", default_channel_id
            
            return False, "missing", None
            
    except Exception as e:
        logger.error(f"❌ Error in ensure_post_has_channel: {e}")
        return False, "error", None

# Fonction pour récupérer le gestionnaire de scheduler
def get_scheduler_manager():
    """Gets the scheduler manager instance"""
    global _global_scheduler_manager
    
    try:
        logger.info("🔍 Recherche du scheduler manager...")
        
        # Priorité 1 : Utiliser le scheduler global s'il est défini
        if _global_scheduler_manager is not None:
            logger.info("✅ Scheduler manager retrieved from global variable")
            logger.info(f"🔍 Global scheduler running: {_global_scheduler_manager.scheduler.running}")
            return _global_scheduler_manager
        
        # Priorité 2 : Essayer de récupérer depuis le module bot
        try:
            import sys
            if 'bot' in sys.modules:
                bot_module = sys.modules['bot']
                if hasattr(bot_module, 'application') and hasattr(bot_module.application, 'scheduler_manager'):
                    current_app = bot_module.application
                    scheduler = current_app.bot_data.get('scheduler_manager')
                    if scheduler:
                        logger.info("✅ Scheduler manager retrieved from bot module")
                        logger.info(f"🔍 Bot scheduler running: {scheduler.scheduler.running}")
                        return scheduler
                    else:
                        logger.warning("⚠️ Bot module found but no scheduler in bot_data")
                else:
                    logger.warning("⚠️ Bot module found but no application or scheduler_manager")
        except Exception as e:
            logger.debug(f"Unable to retrieve from bot module: {e}")
        
        # Priorité 3 : Fallback - créer une instance temporaire mais avec warning
        logger.warning("⚠️ Scheduler manager not found - creating temporary instance")
        logger.warning("⚠️ Scheduled tasks will not work properly!")
        temp_scheduler = SchedulerManager("UTC")
        temp_scheduler.start()
        return temp_scheduler
    except Exception as e:
        logger.error(f"Error retrieving scheduler manager: {e}")
        logger.exception("Scheduler manager retrieval traceback:")
        return None

# Fonction utilitaire pour éviter les erreurs "Message not modified" dans les callbacks
async def safe_edit_callback_message(query, text, reply_markup=None, parse_mode=None):
    """
    Safely edits a callback message avoiding the "Message not modified" error
    Optimized for CallbackQuery in this file
    """
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception as e:
        if "Message is not modified" in str(e):
            logger.debug("Identical message, no editing needed")
            return
        # Fallback si impossible d'éditer (message média ou sans texte)
        if "no text" in str(e).lower() or "There is no text in the message to edit" in str(e):
            logger.warning("Unable to edit message (no text). Sending a new message.")
            try:
                await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
                return
            except Exception as e2:
                # Si erreur de parsing HTML, renvoyer sans parse_mode
                if "can't parse entities" in str(e2).lower():
                    try:
                        await query.message.reply_text(text, reply_markup=reply_markup)
                        return
                    except Exception:
                        pass
                logger.error(f"Error sending replacement: {e2}")
                raise

# Fonction utilitaire pour normaliser les noms de canaux
def normalize_channel_username(channel_username):
    """
    Normalise le nom d'utilisateur d'un canal en enlevant @ si présent
    """
    if not channel_username:
        return None
    return channel_username.lstrip('@') if isinstance(channel_username, str) else None

def schedule_auto_destruction(context, chat_id, message_id, auto_destruction_time):
    """Programme l'auto-destruction d'un message avec asyncio uniquement (stable)."""
    import asyncio

    async def _delete():
        try:
            delay = max(0, int(auto_destruction_time or 0))
            await asyncio.sleep(delay)
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(f"🗑️ Message auto-supprimé après {delay}s")
        except Exception as e:
            logger.warning(f"Erreur suppression auto: {e}")

    try:
        asyncio.create_task(_delete())
        return True
    except Exception as e:
        logger.warning(f"Impossible de programmer l'auto-destruction: {e}")
        return False

# Définition des types pour les gestionnaires
HandlerType = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]

class CallbackError(Exception):
    """Exception pour les erreurs de callback"""
    pass

async def handle_reaction_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """
    Gère les callbacks de réaction de façon simple et efficace.
    Format: react_{post_id}_{emoji}
    """
    query = update.callback_query
    user_id = update.effective_user.id
    
    # TOUJOURS répondre au callback en premier (sinon bouton "mort")
    try:
        await query.answer()
        logger.info(f"🔔 answerCallbackQuery OK pour: {callback_data}")
    except Exception as e:
        logger.error(f"Erreur answerCallbackQuery: {e}")
    
    try:
        logger.info(f"🎯 DÉBUT handle_reaction_callback: {callback_data}, user: {user_id}")
        # Parser le callback_data: react_123_👍
        parts = callback_data.split("_", 2)
        if len(parts) != 3:
            logger.error(f"Format callback invalide: {callback_data}")
            return
            
        _, post_id, emoji = parts
        post_id = int(post_id)
        
        # Récupérer l'info du message
        message = query.message
        chat_id = message.chat_id
        message_id = message.message_id
        
        logger.info(f"🎯 Réaction: user={user_id}, post={post_id}, emoji={emoji}, msg={message_id}")
        
        # Connexion DB
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            _ensure_reactions_schema(conn)
            cursor = conn.cursor()
            
            # Vérifier si l'utilisateur a déjà réagi avec cet emoji
            cursor.execute("""
                SELECT 1 FROM reactions_votes 
                WHERE chat_id = ? AND message_id = ? AND user_id = ? AND emoji = ?
            """, (chat_id, message_id, user_id, emoji))
            
            already_reacted = cursor.fetchone() is not None
            
            if already_reacted:
                # Retirer la réaction (toggle OFF)
                cursor.execute("""
                    DELETE FROM reactions_votes 
                    WHERE chat_id = ? AND message_id = ? AND user_id = ? AND emoji = ?
                """, (chat_id, message_id, user_id, emoji))
                
                cursor.execute("""
                    UPDATE reactions_counts 
                    SET count = CASE WHEN count > 0 THEN count - 1 ELSE 0 END 
                    WHERE chat_id = ? AND message_id = ? AND emoji = ?
                """, (chat_id, message_id, emoji))
                
                action = "removed"
            else:
                # Supprimer toute autre réaction de cet utilisateur sur ce message
                cursor.execute("""
                    DELETE FROM reactions_votes 
                    WHERE chat_id = ? AND message_id = ? AND user_id = ?
                """, (chat_id, message_id, user_id))
                
                # Décrémenter le compteur des anciennes réactions
                cursor.execute("""
                    UPDATE reactions_counts 
                    SET count = CASE WHEN count > 0 THEN count - 1 ELSE 0 END 
                    WHERE chat_id = ? AND message_id = ? AND EXISTS (
                        SELECT 1 FROM reactions_votes rv 
                        WHERE rv.chat_id = reactions_counts.chat_id 
                        AND rv.message_id = reactions_counts.message_id 
                        AND rv.user_id = ?
                        AND rv.emoji = reactions_counts.emoji
                    )
                """, (chat_id, message_id, user_id))
                
                # Ajouter la nouvelle réaction
                cursor.execute("""
                    INSERT INTO reactions_votes (chat_id, message_id, user_id, emoji)
                    VALUES (?, ?, ?, ?)
                """, (chat_id, message_id, user_id, emoji))
                
                # Créer ou incrémenter le compteur
                cursor.execute("""
                    INSERT OR IGNORE INTO reactions_counts (chat_id, message_id, emoji, count)
                    VALUES (?, ?, ?, 0)
                """, (chat_id, message_id, emoji))
                
                cursor.execute("""
                    UPDATE reactions_counts 
                    SET count = count + 1 
                    WHERE chat_id = ? AND message_id = ? AND emoji = ?
                """, (chat_id, message_id, emoji))
                
                action = "added"
            
            conn.commit()
        
        # Mettre à jour les boutons avec les nouveaux compteurs
        await update_reaction_keyboard(query, post_id, chat_id, message_id)
        
        logger.info(f"✅ Réaction {action}: {emoji} par user {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Reaction callback error: {e}")


async def update_reaction_keyboard(query, post_id: int, chat_id: int, message_id: int):
    """Met à jour le clavier de réaction avec les nouveaux compteurs"""
    try:
        # Récupérer les compteurs actuels
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT emoji, count FROM reactions_counts 
                WHERE chat_id = ? AND message_id = ? AND count > 0
                ORDER BY emoji
            """, (chat_id, message_id))
            
            counts = dict(cursor.fetchall())
        
        # Récupérer le clavier actuel et le mettre à jour
        current_markup = query.message.reply_markup
        if not current_markup:
            return
            
        new_keyboard = []
        for row in current_markup.inline_keyboard:
            new_row = []
            for button in row:
                callback_data = button.callback_data
                if callback_data and callback_data.startswith(f"react_{post_id}_"):
                    # C'est un bouton de réaction
                    emoji = callback_data.split("_", 2)[2]
                    count = counts.get(emoji, 0)
                    new_text = f"{emoji} {count}" if count > 0 else emoji
                    new_row.append(InlineKeyboardButton(new_text, callback_data=callback_data))
                else:
                    # Autre bouton, on garde tel quel
                    new_row.append(button)
            new_keyboard.append(new_row)
        
        # Mettre à jour le message
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(new_keyboard))
        
    except Exception as e:
        logger.error(f"❌ Keyboard update error: {e}")


# Mapping des actions vers les gestionnaires
CALLBACK_HANDLERS: Dict[str, HandlerType] = {
    "main_menu": "start",
    "create_publication": "create_publication",
    "planifier_post": "planifier_post",
    "scheduled_posts": "planifier_post",  # Alias pour scheduled posts
    "modifier_heure": "handle_edit_time",
    "envoyer_maintenant": "handle_send_now",
    "annuler_publication": "handle_cancel_post",
    "retour": "planifier_post",
    "preview": "handle_preview",
    "settings": "handle_settings",
    "timezone": "handle_timezone_setup",
    "schedule_send": "schedule_send"
}

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Gère les callbacks de manière centralisée.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Raises:
        CallbackError: Si le callback est invalide ou non géré
    """
    # Récupère le callback Telegram standard
    query = update.callback_query
    user_id = update.effective_user.id
    if not query or not query.data:
        logger.warning("Callback sans données reçu")
        return
    # Buttons with their own handler in another group: left alone here (else « not implemented » replaced the
    # message they had just updated: an admin in the conversation tapping a reaction in their channel…)
    if query.data.startswith(("r:", "connect:", "del_btn_", "fsub_verify", "fsub_check")):
        return None

    # Minimal logging; noisy debug removed

    try:
        # Récupération du callback data complet
        callback_data = query.data
        
        # LOG TRÈS VISIBLE pour debug
        logger.info(f"🔥 CALLBACK REÇU: data='{callback_data}', user={user_id}")
        
        # HANDLER PRIORITAIRE POUR LES RÉACTIONS (avec answer() intégré)
        if callback_data.startswith("react_"):
            logger.info(f"🚀 DIRECTION vers handle_reaction_callback: {callback_data}")
            return await handle_reaction_callback(update, context, callback_data)
        
        # Pour tous les autres callbacks
        await query.answer()

        # Cas spécifiques pour les callbacks
        if callback_data in ("main_menu", "cancel"):
            # Back to main menu (« Cancel » of the channel choice had no branch: « not implemented »)
            keyboard = [
                [InlineKeyboardButton("📝 New post", callback_data="create_publication", api_kwargs={"style": "success"})],
                [InlineKeyboardButton("📅 Scheduled posts", callback_data="planifier_post", api_kwargs={"style": "primary"})],
                [InlineKeyboardButton("⚙️ Settings", callback_data="settings", api_kwargs={"style": "primary"})]
            ]

            # Add redirect buttons from admin config
            try:
                from bot import get_redirect_buttons_keyboard
                redirect_buttons = await get_redirect_buttons_keyboard()
                keyboard.extend(redirect_buttons)
            except Exception:
                pass

            await safe_edit_callback_message(
                query,
                "Main menu:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return MAIN_MENU

        elif callback_data in ("create_publication", "choose_channel", "schedule_publication"):
            # Aller directement à la sélection des canaux pour créer une publication. « 📺 Choose channel » (Send with no
            # channel) and « ⏰ Schedule a post » had no branch; choosing a channel keeps the files already sent.
            return await handle_create_publication(update, context)

        elif callback_data == "send_post":
            # « ↩️ Back » from the scheduling screen had no branch: back to the send options
            posts = context.user_data.get("posts", [])
            channel = (context.user_data.get("selected_channel") or {}).get("username") or "your channel"
            keyboard = [
                [InlineKeyboardButton("⏱️ Set auto-destruction time", callback_data="auto_destruction")],
                [InlineKeyboardButton("📤 Send now", callback_data="send_now", api_kwargs={"style": "success"})],
                [InlineKeyboardButton("📅 Schedule", callback_data="schedule_send", api_kwargs={"style": "primary"})],
                [InlineKeyboardButton("↩️ Back", callback_data="main_menu")]
            ]
            await safe_edit_callback_message(
                query, f"Your {len(posts)} files are ready to be sent to {channel}.\nWhen would you like to send them?",
                reply_markup=InlineKeyboardMarkup(keyboard))
            return WAITING_PUBLICATION_CONTENT
            
        elif callback_data == "planifier_post" or callback_data == "scheduled_posts":
            return await planifier_post(update, context)

        # ============================================================
        # ADMIN PANEL CALLBACKS
        # ============================================================
        elif callback_data == "adm_broadcast":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            # Get user count
            from database.manager import DatabaseManager
            db = DatabaseManager()
            total_users = db.get_total_users()

            await safe_edit_callback_message(
                query,
                f"📢 **Broadcast Message**\n\n"
                f"👥 Recipients: `{total_users}` users\n\n"
                f"Send me the message you want to broadcast.\n\n"
                f"✅ Supported:\n"
                f"• Text\n"
                f"• Photo with caption\n"
                f"• Video with caption\n"
                f"• Document with caption\n\n"
                f"_Send /cancel to abort_",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Back", callback_data="adm_panel")]
                ])
            )
            context.user_data['waiting_broadcast'] = True
            return MAIN_MENU

        elif callback_data == "adm_broadcast_confirm":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            # Get stored broadcast data
            broadcast_data = context.user_data.get('broadcast_data')
            if not broadcast_data:
                await query.answer("No broadcast data found", show_alert=True)
                return MAIN_MENU

            await query.answer("📤 Starting broadcast...")

            # Start broadcast
            from database.manager import DatabaseManager
            from bot import get_redirect_buttons_keyboard, is_user_banned
            import asyncio

            db = DatabaseManager()
            user_ids = db.get_all_user_ids()

            success_count = 0
            fail_count = 0
            blocked_count = 0

            # Get redirect buttons
            redirect_buttons = await get_redirect_buttons_keyboard()

            # Progress message
            progress_msg = await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"📤 **Broadcasting...**\n\n"
                     f"⏳ Progress: 0/{len(user_ids)}\n"
                     f"✅ Success: 0\n"
                     f"❌ Failed: 0"
            )

            for i, user_id in enumerate(user_ids):
                try:
                    # Skip banned users
                    if await is_user_banned(user_id):
                        blocked_count += 1
                        continue

                    # Build keyboard with redirect buttons
                    keyboard = list(redirect_buttons) if redirect_buttons else []

                    # Send based on type
                    msg_type = broadcast_data.get('type')
                    if msg_type == 'text':
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=broadcast_data.get('text', ''),
                            parse_mode='HTML',
                            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                        )
                    elif msg_type == 'photo':
                        await context.bot.send_photo(
                            chat_id=user_id,
                            photo=broadcast_data.get('file_id'),
                            caption=broadcast_data.get('caption', ''),
                            parse_mode='HTML',
                            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                        )
                    elif msg_type == 'video':
                        await context.bot.send_video(
                            chat_id=user_id,
                            video=broadcast_data.get('file_id'),
                            caption=broadcast_data.get('caption', ''),
                            parse_mode='HTML',
                            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                        )
                    elif msg_type == 'document':
                        await context.bot.send_document(
                            chat_id=user_id,
                            document=broadcast_data.get('file_id'),
                            caption=broadcast_data.get('caption', ''),
                            parse_mode='HTML',
                            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                        )

                    success_count += 1

                except Exception as e:
                    fail_count += 1
                    logger.warning(f"Broadcast to {user_id} failed: {e}")

                # Update progress every 10 users
                if (i + 1) % 10 == 0:
                    try:
                        await progress_msg.edit_text(
                            f"📤 **Broadcasting...**\n\n"
                            f"⏳ Progress: {i + 1}/{len(user_ids)}\n"
                            f"✅ Success: {success_count}\n"
                            f"❌ Failed: {fail_count}"
                        )
                    except Exception:
                        pass

                # Rate limiting - small delay
                await asyncio.sleep(0.05)

            # Final result
            try:
                await progress_msg.edit_text(
                    f"✅ **Broadcast Complete!**\n\n"
                    f"📊 **Results:**\n"
                    f"• Total: `{len(user_ids)}` users\n"
                    f"• ✅ Success: `{success_count}`\n"
                    f"• ❌ Failed: `{fail_count}`\n"
                    f"• 🚫 Banned: `{blocked_count}`",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("↩️ Back to Admin", callback_data="adm_panel")]
                    ])
                )
            except Exception:
                pass

            # Clear broadcast data
            context.user_data.pop('broadcast_data', None)
            context.user_data.pop('waiting_broadcast', None)

            return MAIN_MENU

        elif callback_data == "adm_broadcast_cancel":
            context.user_data.pop('broadcast_data', None)
            context.user_data.pop('waiting_broadcast', None)
            await query.answer("Broadcast cancelled")
            # Return to admin panel
            from database.manager import DatabaseManager
            db = DatabaseManager()
            total_users = db.get_total_users() if hasattr(db, 'get_total_users') else "N/A"

            keyboard = [
                [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast")],
                [InlineKeyboardButton("👥 Force Join Channels", callback_data="adm_fsub")],
                [InlineKeyboardButton("🚫 Ban/Unban User", callback_data="adm_ban")],
                [InlineKeyboardButton("🔘 Redirect Buttons", callback_data="adm_redirect_buttons")],
                [InlineKeyboardButton("📊 Bot Stats", callback_data="adm_stats")],
                [InlineKeyboardButton("↩️ Main Menu", callback_data="main_menu")]
            ]

            await safe_edit_callback_message(
                query,
                f"🛠 **Admin Panel**\n\n"
                f"👥 Total users: `{total_users}`\n\n"
                "Select an option below:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return MAIN_MENU

        elif callback_data == "adm_fsub":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            # Load current channels
            from bot import load_fj_channels
            channels = await load_fj_channels()

            channels_text = ""
            if channels:
                channels_text = "\n📋 **Current channels:**\n" + "\n".join(f"• `{ch}`" for ch in channels)
            else:
                channels_text = "\n📋 _No channels configured_"

            keyboard = [
                [InlineKeyboardButton("➕ Add Channel", callback_data="adm_fsub_add")],
                [InlineKeyboardButton("➖ Remove Channel", callback_data="adm_fsub_remove")],
                [InlineKeyboardButton("↩️ Back", callback_data="adm_panel")]
            ]
            await safe_edit_callback_message(
                query,
                f"👥 **Force Join Channels**\n\n"
                f"Manage channels users must join before using the bot.\n"
                f"{channels_text}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return MAIN_MENU

        elif callback_data == "adm_fsub_add":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            await safe_edit_callback_message(
                query,
                "➕ **Add Force Join Channel**\n\n"
                "Send the channel username or ID.\n\n"
                "Examples:\n"
                "• `@mychannel`\n"
                "• `-100123456789`\n"
                "• `t.me/mychannel`\n\n"
                "_Send /cancel to abort_",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Cancel", callback_data="adm_fsub")]
                ])
            )
            context.user_data['waiting_fsub_add'] = True
            return MAIN_MENU

        elif callback_data == "adm_fsub_remove":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            # Load current channels and show as buttons
            from bot import load_fj_channels
            channels = await load_fj_channels()

            if not channels:
                await query.answer("No channels to remove", show_alert=True)
                return MAIN_MENU

            keyboard = []
            for ch in channels:
                keyboard.append([InlineKeyboardButton(f"🗑 {ch}", callback_data=f"adm_fsub_del:{ch}")])
            keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="adm_fsub")])

            await safe_edit_callback_message(
                query,
                "➖ **Remove Force Join Channel**\n\n"
                "Click on a channel to remove it:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return MAIN_MENU

        elif callback_data.startswith("adm_fsub_del:"):
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            channel_to_remove = callback_data.replace("adm_fsub_del:", "")

            from bot import load_fj_channels, save_fj_channels, fj_lock
            async with fj_lock:
                channels = await load_fj_channels()
                if channel_to_remove in channels:
                    channels.remove(channel_to_remove)
                    await save_fj_channels(channels)
                    await query.answer(f"✅ Removed: {channel_to_remove}", show_alert=True)
                else:
                    await query.answer("Channel not found", show_alert=True)

            # Refresh the list
            channels = await load_fj_channels()
            if not channels:
                await safe_edit_callback_message(
                    query,
                    "👥 **Force Join Channels**\n\n"
                    "📋 _No channels configured_",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("➕ Add Channel", callback_data="adm_fsub_add")],
                        [InlineKeyboardButton("↩️ Back", callback_data="adm_panel")]
                    ])
                )
            else:
                keyboard = []
                for ch in channels:
                    keyboard.append([InlineKeyboardButton(f"🗑 {ch}", callback_data=f"adm_fsub_del:{ch}")])
                keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="adm_fsub")])
                await safe_edit_callback_message(
                    query,
                    "➖ **Remove Force Join Channel**\n\n"
                    "Click on a channel to remove it:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            return MAIN_MENU

        elif callback_data == "adm_ban":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            # Get banned users count
            from bot import load_banned_users
            banned = await load_banned_users()
            banned_count = len(banned)

            keyboard = [
                [InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban_user")],
                [InlineKeyboardButton("✅ Unban User", callback_data="adm_unban_user")],
                [InlineKeyboardButton("📋 Banned List", callback_data="adm_ban_list")],
                [InlineKeyboardButton("↩️ Back", callback_data="adm_panel")]
            ]
            await safe_edit_callback_message(
                query,
                f"🚫 **Ban Management**\n\n"
                f"Ban or unban users from using the bot.\n\n"
                f"📊 Currently banned: `{banned_count}` user(s)",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return MAIN_MENU

        elif callback_data == "adm_ban_user":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            await safe_edit_callback_message(
                query,
                "🚫 **Ban User**\n\n"
                "Send the user ID to ban.\n\n"
                "You can get the user ID by forwarding a message from them to @userinfobot\n\n"
                "_Send /cancel to abort_",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Cancel", callback_data="adm_ban")]
                ])
            )
            context.user_data['waiting_ban_user'] = True
            return MAIN_MENU

        elif callback_data == "adm_unban_user":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            # Show banned users as buttons
            from bot import load_banned_users
            banned = await load_banned_users()

            if not banned:
                await query.answer("No banned users", show_alert=True)
                return MAIN_MENU

            keyboard = []
            for b in banned[:20]:  # Limit to 20
                user_id = b.get("user_id", 0)
                reason = b.get("reason", "No reason")[:20]
                keyboard.append([InlineKeyboardButton(
                    f"✅ {user_id} - {reason}",
                    callback_data=f"adm_do_unban:{user_id}"
                )])
            keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="adm_ban")])

            await safe_edit_callback_message(
                query,
                "✅ **Unban User**\n\n"
                "Click on a user to unban:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return MAIN_MENU

        elif callback_data.startswith("adm_do_unban:"):
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            user_id_to_unban = int(callback_data.replace("adm_do_unban:", ""))

            from bot import unban_user
            success = await unban_user(user_id_to_unban)

            if success:
                await query.answer(f"✅ User {user_id_to_unban} unbanned!", show_alert=True)
            else:
                await query.answer("User was not banned", show_alert=True)

            # Refresh list
            from bot import load_banned_users
            banned = await load_banned_users()

            if not banned:
                await safe_edit_callback_message(
                    query,
                    "🚫 **Ban Management**\n\n"
                    "📋 _No banned users_",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban_user")],
                        [InlineKeyboardButton("↩️ Back", callback_data="adm_panel")]
                    ])
                )
            else:
                keyboard = []
                for b in banned[:20]:
                    uid = b.get("user_id", 0)
                    reason = b.get("reason", "No reason")[:20]
                    keyboard.append([InlineKeyboardButton(
                        f"✅ {uid} - {reason}",
                        callback_data=f"adm_do_unban:{uid}"
                    )])
                keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="adm_ban")])
                await safe_edit_callback_message(
                    query,
                    "✅ **Unban User**\n\n"
                    "Click on a user to unban:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            return MAIN_MENU

        elif callback_data == "adm_ban_list":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            from bot import load_banned_users
            banned = await load_banned_users()

            if not banned:
                await safe_edit_callback_message(
                    query,
                    "📋 **Banned Users List**\n\n"
                    "_No banned users_",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("↩️ Back", callback_data="adm_ban")]
                    ])
                )
            else:
                text = "📋 **Banned Users List**\n\n"
                for i, b in enumerate(banned[:15], 1):  # Limit to 15
                    uid = b.get("user_id", 0)
                    reason = b.get("reason", "No reason")
                    banned_at = b.get("banned_at", "Unknown")[:10]
                    text += f"{i}. `{uid}`\n   📝 {reason}\n   📅 {banned_at}\n\n"

                if len(banned) > 15:
                    text += f"_... and {len(banned) - 15} more_"

                await safe_edit_callback_message(
                    query,
                    text,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("↩️ Back", callback_data="adm_ban")]
                    ])
                )
            return MAIN_MENU

        elif callback_data == "adm_stats":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            # Get stats
            from database.manager import DatabaseManager
            db = DatabaseManager()
            total_users = db.get_total_users() if hasattr(db, 'get_total_users') else "N/A"

            import platform
            import psutil
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent

            stats_text = (
                "📊 **Bot Statistics**\n\n"
                f"👥 Total Users: `{total_users}`\n"
                f"💻 CPU: `{cpu}%`\n"
                f"🧠 RAM: `{ram}%`\n"
                f"🐍 Python: `{platform.python_version()}`\n"
                f"💻 OS: `{platform.system()}`"
            )

            await safe_edit_callback_message(
                query,
                stats_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Refresh", callback_data="adm_stats")],
                    [InlineKeyboardButton("↩️ Back", callback_data="adm_panel")]
                ])
            )
            return MAIN_MENU

        elif callback_data == "adm_shortlinks":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            await safe_edit_callback_message(
                query,
                "🔗 **Short Links Configuration**\n\n"
                "Configure short link providers for monetization.\n\n"
                "Coming soon...",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Back", callback_data="adm_panel")]
                ])
            )
            return MAIN_MENU

        elif callback_data == "adm_panel":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            from database.manager import DatabaseManager
            db = DatabaseManager()
            total_users = db.get_total_users() if hasattr(db, 'get_total_users') else "N/A"

            keyboard = [
                [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast")],
                [InlineKeyboardButton("👥 Force Join Channels", callback_data="adm_fsub")],
                [InlineKeyboardButton("🚫 Ban/Unban User", callback_data="adm_ban")],
                [InlineKeyboardButton("🔘 Redirect Buttons", callback_data="adm_redirect_buttons")],
                [InlineKeyboardButton("📊 Bot Stats", callback_data="adm_stats")],
                [InlineKeyboardButton("↩️ Main Menu", callback_data="main_menu")]
            ]

            await safe_edit_callback_message(
                query,
                f"🛠 **Admin Panel**\n\n"
                f"👥 Total users: `{total_users}`\n\n"
                "Select an option below:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return MAIN_MENU

        # ============================================================
        # REDIRECT BUTTONS CALLBACKS
        # ============================================================
        elif callback_data == "adm_redirect_buttons":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            from bot import load_redirect_buttons
            buttons = await load_redirect_buttons()

            buttons_text = ""
            if buttons:
                buttons_text = "\n📋 **Current buttons:**\n"
                for i, b in enumerate(buttons, 1):
                    buttons_text += f"{i}. [{b.get('text', 'Button')}]({b.get('url', '')})\n"
            else:
                buttons_text = "\n📋 _No buttons configured_"

            keyboard = [
                [InlineKeyboardButton("➕ Add Button", callback_data="adm_redirect_add")],
                [InlineKeyboardButton("➖ Remove Button", callback_data="adm_redirect_remove")],
                [InlineKeyboardButton("👁 Preview", callback_data="adm_redirect_preview")],
                [InlineKeyboardButton("↩️ Back", callback_data="adm_panel")]
            ]

            await safe_edit_callback_message(
                query,
                f"🔘 **Redirect Buttons**\n\n"
                f"These buttons will appear under:\n"
                f"• Welcome message (/start)\n"
                f"• Broadcast messages\n"
                f"{buttons_text}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return MAIN_MENU

        elif callback_data == "adm_redirect_add":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            await safe_edit_callback_message(
                query,
                "➕ **Add Redirect Button**\n\n"
                "Send the button in this format:\n\n"
                "`Button Text | https://example.com`\n\n"
                "Example:\n"
                "`Join Channel | https://t.me/mychannel`\n\n"
                "_Send /cancel to abort_",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Cancel", callback_data="adm_redirect_buttons")]
                ])
            )
            context.user_data['waiting_redirect_button'] = True
            return MAIN_MENU

        elif callback_data == "adm_redirect_remove":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            from bot import load_redirect_buttons
            buttons = await load_redirect_buttons()

            if not buttons:
                await query.answer("No buttons to remove", show_alert=True)
                return MAIN_MENU

            keyboard = []
            for i, b in enumerate(buttons):
                text = b.get("text", "Button")[:20]
                keyboard.append([InlineKeyboardButton(
                    f"🗑 {text}",
                    callback_data=f"adm_redirect_del:{i}"
                )])
            keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="adm_redirect_buttons")])

            await safe_edit_callback_message(
                query,
                "➖ **Remove Redirect Button**\n\n"
                "Click on a button to remove it:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return MAIN_MENU

        elif callback_data.startswith("adm_redirect_del:"):
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            index = int(callback_data.replace("adm_redirect_del:", ""))

            from bot import remove_redirect_button, load_redirect_buttons
            success = await remove_redirect_button(index)

            if success:
                await query.answer("✅ Button removed!", show_alert=True)
            else:
                await query.answer("Failed to remove button", show_alert=True)

            # Refresh list
            buttons = await load_redirect_buttons()
            if not buttons:
                await safe_edit_callback_message(
                    query,
                    "🔘 **Redirect Buttons**\n\n"
                    "📋 _No buttons configured_",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("➕ Add Button", callback_data="adm_redirect_add")],
                        [InlineKeyboardButton("↩️ Back", callback_data="adm_panel")]
                    ])
                )
            else:
                keyboard = []
                for i, b in enumerate(buttons):
                    text = b.get("text", "Button")[:20]
                    keyboard.append([InlineKeyboardButton(
                        f"🗑 {text}",
                        callback_data=f"adm_redirect_del:{i}"
                    )])
                keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="adm_redirect_buttons")])
                await safe_edit_callback_message(
                    query,
                    "➖ **Remove Redirect Button**\n\n"
                    "Click on a button to remove it:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            return MAIN_MENU

        elif callback_data == "adm_redirect_preview":
            from config.settings import bot_config
            admin_ids = bot_config.get("admin_ids", [])
            if update.effective_user.id not in admin_ids:
                await query.answer("❌ Admin only", show_alert=True)
                return MAIN_MENU

            from bot import get_redirect_buttons_keyboard
            redirect_buttons = await get_redirect_buttons_keyboard()

            if not redirect_buttons:
                await query.answer("No buttons configured", show_alert=True)
                return MAIN_MENU

            # Add back button
            redirect_buttons.append([InlineKeyboardButton("↩️ Back", callback_data="adm_redirect_buttons")])

            await safe_edit_callback_message(
                query,
                "👁 **Preview**\n\n"
                "This is how the buttons will appear:",
                reply_markup=InlineKeyboardMarkup(redirect_buttons)
            )
            return MAIN_MENU

        elif callback_data == "channel_stats":
            # Génération du lien SSO pour les statistiques
            try:
                from ..utils_sso import make_sso_link
            except ImportError:
                sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from utils_sso import make_sso_link
            
            user_id = update.effective_user.id
            try:
                # Accuser la réception du clic pour éviter le spinner côté Telegram
                await query.answer()
                sso_link = make_sso_link(user_id, redirect="/channels")
                
                await safe_edit_callback_message(
                    query,
                    "📊 **Accès aux Statistiques**\n\n"
                    "🔐 Un lien sécurisé a été généré pour vous connecter automatiquement.\n\n"
                    "⏱ Ce lien expire dans 60 secondes.\n\n"
                    "Cliquez sur le bouton ci-dessous pour accéder à vos statistiques:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🌐 Open Statistics", url=sso_link)],
                        [InlineKeyboardButton("↩️ Back", callback_data="main_menu")]
                    ])
                )
            except Exception as e:
                logger.error(f"Erreur lors de la génération du lien SSO: {e}")
                await safe_edit_callback_message(
                    query,
                    "❌ Error generating access link.\n"
                    "Veuillez réessayer plus tard.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("↩️ Back", callback_data="main_menu")]
                    ])
                )
            return MAIN_MENU
            
        elif callback_data == "schedule_send":
            return await schedule_send(update, context)
            
        elif callback_data == "send_now":
            # Bouton "Maintenant" - utilise maintenant la vraie fonction send_post_now
            logger.info("🔥 DEBUG: Callback send_now reçu, appel de send_post_now")
            return await send_post_now(update, context)
            
        elif callback_data == "auto_destruction":
            # Bouton "Régler temps d'auto destruction" - FONCTIONNALITÉ RÉELLE
            from utils.message_templates import MessageTemplates
            
            keyboard = [
                [InlineKeyboardButton("5 minutes", callback_data="auto_dest_300")],
                [InlineKeyboardButton("30 minutes", callback_data="auto_dest_1800")],
                [InlineKeyboardButton("1 hour", callback_data="auto_dest_3600")],
                [InlineKeyboardButton("6 hours", callback_data="auto_dest_21600")],
                [InlineKeyboardButton("24 hours", callback_data="auto_dest_86400")],
                [InlineKeyboardButton("❌ Disable", callback_data="auto_dest_0")],
                [InlineKeyboardButton("↩️ Back", callback_data="send_post")]
            ]
            
            await safe_edit_callback_message(
                query,
                MessageTemplates.get_auto_destruction_message(),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return AUTO_DESTRUCTION
            
        # Gestion des choix d'auto-destruction
        elif callback_data.startswith("auto_dest_"):
            seconds = int(callback_data.split("_")[-1])
            
            if seconds == 0:
                # Désactiver l'auto-destruction
                context.user_data.pop('auto_destruction_time', None)
                await safe_edit_callback_message(
                    query,
                    "✅ **Auto-destruction disabled**\n\n"
                    "Your messages will not be automatically deleted.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Back to send menu", callback_data="send_post")
                    ]]),
                    parse_mode='Markdown'
                )
            else:
                # Enregistrer le temps d'auto-destruction
                context.user_data['auto_destruction_time'] = seconds
                
                # Convertir en format lisible
                if seconds < 3600:
                    time_str = f"{seconds // 60} minute(s)"
                elif seconds < 86400:
                    time_str = f"{seconds // 3600} hour(s)"
                else:
                    time_str = f"{seconds // 86400} day(s)"
                
                await safe_edit_callback_message(
                    query,
                    f"✅ **Auto-destruction configured**\n\n"
                    f"⏰ Duration: {time_str}\n\n"
                    f"Your next messages will be automatically deleted after {time_str}.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Back to send menu", callback_data="send_post")
                    ]]),
                    parse_mode='Markdown'
                )
            
            return MAIN_MENU
            
        elif callback_data in ("schedule_today", "schedule_tomorrow", "schedule_overmorrow"):
            # Stocker le jour sélectionné et rediriger vers handle_schedule_time
            logger.info(f"🔍 DEBUG: sélection jour {callback_data}")
            
            if callback_data == "schedule_today":
                context.user_data['schedule_day'] = 'today'
            elif callback_data == "schedule_tomorrow":
                context.user_data['schedule_day'] = 'tomorrow'
            else:
                context.user_data['schedule_day'] = 'overmorrow'
            jour = "today" if context.user_data['schedule_day'] == 'today' else ("tomorrow" if context.user_data['schedule_day'] == 'tomorrow' else "overmorrow")
            
            logger.info(f"📅 Selected day: {jour}")
            logger.info(f"🔍 DEBUG: user_data après sélection jour: editing_post_id={context.user_data.get('editing_post_id')}, current_scheduled_post={bool(context.user_data.get('current_scheduled_post'))}")

            # Mise à jour du message pour indiquer que l'heure est attendue
            await query.edit_message_text(
                f"✅ Day selected: {jour}.\n\n"
                "Now send the time in one of the formats:\n"
                "   • '15:30' or '1530' (24h)\n"
                "   • '6' (06:00)\n"
                "   • '5 3' (05:03)\n\n"
                "⏰ Waiting for time...",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Back", callback_data="schedule_send")
                ]])
            )
            return SCHEDULE_SEND
            
        elif callback_data == "modifier_heure":
            return await handle_edit_time(update, context)
            
        elif callback_data == "envoyer_maintenant":
            # Vérifier s'il s'agit d'un post planifié ou d'un nouveau post
            current_scheduled_post = context.user_data.get('current_scheduled_post')
            if current_scheduled_post:
                logger.info(f"🚀 Envoi immédiat d'un post planifié (ID: {current_scheduled_post.get('id')})")
                return await send_post_now(update, context, scheduled_post=current_scheduled_post)
            else:
                logger.info("🚀 Envoi immédiat d'un nouveau post")
                return await send_post_now(update, context)
            
        elif callback_data == "annuler_publication":
            return await handle_cancel_post(update, context)
            
        elif callback_data == "confirm_cancel":
            return await handle_confirm_cancel(update, context)
            
        elif callback_data == "retour":
            return await planifier_post(update, context)
            
        elif callback_data == "settings":
            # Redirection vers le menu des paramètres personnalisés
            return await custom_settings_menu(update, context)
            
        # Gestion des canaux
        elif callback_data == "manage_channels":
            return await manage_channels_menu(update, context)
            
        elif callback_data == "timezone_settings":
            return await handle_timezone_settings(update, context)
            
        elif callback_data == "language_settings":
            return await handle_language_settings(update, context)
            
        elif callback_data.startswith("set_language_"):
            lang_code = callback_data.replace("set_language_", "")
            return await handle_set_language(update, context, lang_code)
            
        elif callback_data.startswith("set_timezone_"):
            timezone_code = callback_data.replace("set_timezone_", "")
            return await handle_set_timezone(update, context, timezone_code)
            
        elif callback_data == "manual_timezone":
            return await handle_manual_timezone(update, context)
            
        elif callback_data == "add_channel":
            return await add_channel_prompt(update, context)
            

            
        elif callback_data.startswith("select_channel_"):
            channel_username = callback_data.replace("select_channel_", "")
            return await select_channel(update, context, channel_username)
            
        elif callback_data.startswith("channel_"):
            channel_username = callback_data.replace("channel_", "")
            return await show_channel_options(update, context, channel_username)
            
        elif callback_data.startswith("custom_channel_"):
            channel_username = callback_data.replace("custom_channel_", "")
            return await custom_channel_settings(update, context, channel_username)
            
        elif callback_data == "custom_settings":
            return await custom_settings_menu(update, context)
            

            

            
        elif callback_data.startswith("delete_channel_"):
            channel_id = callback_data.replace("delete_channel_", "")
            return await delete_channel(update, context, channel_id)
            
        elif callback_data.startswith("confirm_delete_channel_"):
            channel_id = callback_data.replace("confirm_delete_channel_", "")
            return await confirm_delete_channel(update, context, channel_id)
            
        elif callback_data.startswith("edit_file_"):
            post_index = callback_data.replace("edit_file_", "")
            return await show_edit_file_menu(update, context, int(post_index))
            
        elif callback_data == "preview_all":
            await query.edit_message_text(
                "📋 **Aperçu général**\n\n"
                "Cette fonctionnalité sera bientôt disponible.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Back", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
            
        elif callback_data == "delete_all_posts":
            # Supprimer tous les posts mais garder le canal sélectionné
            if 'posts' in context.user_data:
                context.user_data['posts'] = []
            # Ne pas supprimer le canal : context.user_data.pop('selected_channel', None)
            
            await query.edit_message_text(
                "🗑️ **All posts deleted**\n\n"
                "📤 Now send your new files:"
            )
            return WAITING_PUBLICATION_CONTENT
            
        elif callback_data.startswith("rename_post_"):
            post_index = callback_data.replace("rename_post_", "")
            return await handle_rename_post(update, context, int(post_index))
            
        elif callback_data.startswith("edit_file_"):
            post_index = callback_data.replace("edit_file_", "")
            return await show_edit_file_menu(update, context, int(post_index))
            

            

            
        elif callback_data.startswith("add_reactions_"):
            # Gestion de l'ajout de réactions
            try:
                post_index = int(callback_data.split('_')[-1])
            except Exception as e:
                logger.error(f"Erreur parsing add_reactions_: {callback_data} - {e}")
                await query.answer("❌ Format error")
                return MAIN_MENU
            from .reaction_functions import add_reactions_to_post
            return await add_reactions_to_post(update, context)
            
        elif callback_data == "cancel_waiting_reactions":
            # Annuler proprement: supprimer le prompt et le message avec le bouton
            ctx = context.user_data.pop('reaction_input_ctx', {})
            context.user_data.pop('waiting_for_reactions', None)
            try:
                if ctx:
                    await context.bot.delete_message(ctx.get('prompt_chat_id'), ctx.get('prompt_message_id'))
            except Exception:
                pass
            try:
                await query.delete_message()
            except Exception:
                pass
            return WAITING_PUBLICATION_CONTENT

        elif callback_data == "cancel_waiting_url":
            # Annuler pour l'ajout de bouton URL: supprimer prompt + message bouton
            context.user_data.pop('waiting_for_url', None)
            context.user_data.pop('current_post_index', None)
            # Supprimer le prompt si présent
            try:
                prompt_id = context.user_data.pop('last_prompt_message_id', None)
                if prompt_id:
                    await context.bot.delete_message(query.message.chat_id, prompt_id)
            except Exception:
                pass
            try:
                await query.delete_message()
            except Exception:
                pass
            return WAITING_PUBLICATION_CONTENT
            
        elif callback_data.startswith("add_url_button_"):
            # Gestion de l'ajout de boutons URL
            try:
                post_index = int(callback_data.split('_')[-1])
            except Exception as e:
                logger.error(f"Erreur parsing add_url_button_: {callback_data} - {e}")
                await query.answer("❌ Format error")
                return MAIN_MENU
            from .reaction_functions import add_url_button_to_post
            return await add_url_button_to_post(update, context)
            
        elif callback_data.startswith("remove_reactions_"):
            # Gestion de la suppression de réactions
            try:
                post_index = int(callback_data.split('_')[-1])
            except Exception as e:
                logger.error(f"Erreur parsing remove_reactions_: {callback_data} - {e}")
                await query.answer("❌ Format error")
                return MAIN_MENU
            from .reaction_functions import remove_reactions
            return await remove_reactions(update, context)
            
        elif callback_data.startswith("remove_url_buttons_"):
            # Gestion de la suppression de boutons URL
            try:
                post_index = int(callback_data.split('_')[-1])
            except Exception as e:
                logger.error(f"Erreur parsing remove_url_buttons_: {callback_data} - {e}")
                await query.answer("❌ Format error")
                return MAIN_MENU
            from .reaction_functions import remove_url_buttons
            return await remove_url_buttons(update, context)
            
        elif callback_data.startswith("delete_post_"):
            # Gestion de la suppression de posts
            try:
                post_index = int(callback_data.split('_')[-1])
            except Exception as e:
                logger.error(f"Erreur parsing delete_post_: {callback_data} - {e}")
                await query.answer("❌ Format error")
                return MAIN_MENU
            return await handle_delete_post(update, context, post_index)
            
        elif callback_data.startswith("cancel_rename_"):
            # Annuler le prompt Rename simple
            try:
                context.user_data.pop('waiting_for_rename', None)
                context.user_data.pop('current_post_index', None)
                prompt_msg_id = context.user_data.pop('rename_prompt_message_id', None)
                prompt_chat_id = context.user_data.pop('rename_prompt_chat_id', None)
                if prompt_msg_id and prompt_chat_id:
                    try:
                        await context.bot.delete_message(chat_id=prompt_chat_id, message_id=prompt_msg_id)
                    except Exception:
                        pass
                try:
                    await query.delete_message()
                except Exception:
                    pass
            except Exception:
                pass
            return WAITING_PUBLICATION_CONTENT

        elif callback_data.startswith("cancel_thumbnail_rename_"):
            # Fonction désactivée - thumbnails supprimés
            try:
                await query.delete_message()
            except Exception:
                pass
            return WAITING_PUBLICATION_CONTENT

        elif callback_data.startswith("edit_tag_"):
            # Gestion de l'ajout/modification de hashtags
            channel_username = callback_data.replace("edit_tag_", "")
            return await handle_edit_tag(update, context, channel_username)

        elif callback_data.startswith("show_post_"):
            # Gestion de l'affichage des posts planifiés
            return await show_scheduled_post(update, context)

        # ANCIEN GESTIONNAIRE POUR LES RÉACTIONS - DÉSACTIVÉ (handler prioritaire utilisé)
        elif False and callback_data.startswith("react_"):
            try:
                logger.debug(f"[react_] callback received: data='{callback_data}', user_id={user_id}")
                parts = callback_data.split("_", 2)
                # Format attendu: react_{post_index}_{emoji...}
                if len(parts) == 3:
                    post_index = parts[1]
                    emoji = parts[2]
                else:
                    # Fallback minimal
                    post_index = "0"
                    emoji = parts[-1] if parts else "?"

                logger.debug(f"[react_] parsed -> post_index='{post_index}', emoji='{emoji}'")

                msg = query.message
                if not msg:
                    await query.answer("❌ Message error", show_alert=False)
                    return MAIN_MENU

                chat_id = msg.chat_id
                message_id = msg.message_id
                uid = user_id

                db_path = _get_db_path()
                logger.debug(f"[react_] DB path='{db_path}', chat_id={chat_id}, message_id={message_id}, uid={uid}")
                with sqlite3.connect(db_path) as conn:
                    _ensure_reactions_schema(conn)
                    cur = conn.cursor()
                    # Transaction pour éviter les courses
                    cur.execute("BEGIN IMMEDIATE")

                    # Vote actuel de l'utilisateur
                    cur.execute(
                        "SELECT emoji FROM reactions_votes WHERE chat_id=? AND message_id=? AND user_id=?",
                        (chat_id, message_id, uid),
                    )
                    row = cur.fetchone()
                    prev_emoji = row[0] if row else None
                    logger.debug(f"[react_] previous vote -> prev_emoji='{prev_emoji}'")

                    # S'assurer que les lignes de compteur existent
                    cur.execute(
                        "INSERT OR IGNORE INTO reactions_counts (chat_id, message_id, emoji, count) VALUES (?,?,?,0)",
                        (chat_id, message_id, emoji),
                    )
                    if prev_emoji and prev_emoji != emoji:
                        cur.execute(
                            "INSERT OR IGNORE INTO reactions_counts (chat_id, message_id, emoji, count) VALUES (?,?,?,0)",
                            (chat_id, message_id, prev_emoji),
                        )

                    action = "added"
                    if prev_emoji == emoji:
                        # Toggle OFF
                        cur.execute(
                            "DELETE FROM reactions_votes WHERE chat_id=? AND message_id=? AND user_id=?",
                            (chat_id, message_id, uid),
                        )
                        cur.execute(
                            "UPDATE reactions_counts SET count = CASE WHEN count>0 THEN count-1 ELSE 0 END WHERE chat_id=? AND message_id=? AND emoji=?",
                            (chat_id, message_id, emoji),
                        )
                        action = "removed"
                        logger.debug(f"[react_] action taken: {action} for emoji='{emoji}'")
                    else:
                        # Switch or add
                        if prev_emoji:
                            # decrement previous
                            cur.execute(
                                "UPDATE reactions_counts SET count = CASE WHEN count>0 THEN count-1 ELSE 0 END WHERE chat_id=? AND message_id=? AND emoji=?",
                                (chat_id, message_id, prev_emoji),
                            )
                            cur.execute(
                                "UPDATE reactions_votes SET emoji=? WHERE chat_id=? AND message_id=? AND user_id=?",
                                (emoji, chat_id, message_id, uid),
                            )
                            action = "switched"
                            logger.debug(f"[react_] action taken: {action} from prev_emoji='{prev_emoji}' to emoji='{emoji}'")
                        else:
                            cur.execute(
                                "INSERT OR REPLACE INTO reactions_votes (chat_id, message_id, user_id, emoji) VALUES (?,?,?,?)",
                                (chat_id, message_id, uid, emoji),
                            )
                        # increment new
                        cur.execute(
                            "UPDATE reactions_counts SET count = count + 1 WHERE chat_id=? AND message_id=? AND emoji=?",
                            (chat_id, message_id, emoji),
                        )

                    conn.commit()
                    logger.debug(f"[react_] transaction committed; action='{action}'")

                    # Récupérer les compteurs des emojis présents dans le clavier actuel
                    current_kb = getattr(msg, 'reply_markup', None)
                    inline_kb = getattr(current_kb, 'inline_keyboard', None) if current_kb else None
                    emojis_in_kb = []
                    if inline_kb:
                        for row_btns in inline_kb:
                            for btn in row_btns:
                                btn_data = getattr(btn, 'callback_data', None)
                                if btn_data and btn_data.startswith(f"react_{post_index}_"):
                                    e = btn_data.split("_", 2)[2]
                                    emojis_in_kb.append(e)
                    logger.debug(f"[react_] emojis present in keyboard: {emojis_in_kb}")

                    counts: dict[str, int] = {}
                    if emojis_in_kb:
                        placeholders = ",".join(["?"] * len(emojis_in_kb))
                        cur.execute(
                            f"SELECT emoji, count FROM reactions_counts WHERE chat_id=? AND message_id=? AND emoji IN ({placeholders})",
                            (chat_id, message_id, *emojis_in_kb),
                        )
                        for e, c in cur.fetchall() or []:
                            counts[e] = int(c or 0)
                    logger.debug(f"[react_] fetched counts: {counts}")

                # Réponse utilisateur
                try:
                    if action == "removed":
                        await query.answer(f"Removed {emoji}")
                    elif action == "switched":
                        await query.answer(f"Switched to {emoji}")
                    else:
                        await query.answer(f"Added {emoji}")
                except Exception:
                    pass

                # Mettre à jour le clavier avec les compteurs
                try:
                    if inline_kb:
                        new_keyboard = []
                        for row_btns in inline_kb:
                            new_row = []
                            for btn in row_btns:
                                try:
                                    btn_data = getattr(btn, 'callback_data', None)
                                    btn_text = getattr(btn, 'text', '')
                                    if btn_data and btn_data.startswith(f"react_{post_index}_"):
                                        e = btn_data.split("_", 2)[2]
                                        c = counts.get(e, 0)
                                        label = f"{e} {c}" if c > 0 else f"{e}"
                                        new_row.append(InlineKeyboardButton(label, callback_data=btn_data))
                                    else:
                                        new_row.append(btn)
                                except Exception:
                                    new_row.append(btn)
                            new_keyboard.append(new_row)
                        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(new_keyboard))
                        logger.debug("[react_] inline keyboard updated with new counts")
                except Exception as e:
                    logger.warning(f"Échec mise à jour du clavier réactions (persist): {e}")

                return MAIN_MENU
            except Exception as e:
                logger.error(f"Erreur gestion react_ (persistent) for data='{callback_data}': {e}")
                try:
                    await query.answer("Erreur réaction", show_alert=False)
                except Exception:
                    pass

        # GESTIONNAIRE POUR LES RÉACTIONS DANS LE CANAL (format legacy: reaction_{post_index}_{reaction} ou court: reaction_{emoji})
        elif callback_data.startswith("reaction_"):
            # Legacy handler removed: all reactions must use 'react_' persistent callbacks
            try:
                await query.answer("❌ Legacy reaction button. Please update.", show_alert=False)
            except Exception:
                pass
            return MAIN_MENU

        # Si le callback n'est pas dans la liste des cas directement gérés
        logger.warning(f"Callback non géré directement : {callback_data}")
        # Protection contre les callbacks malformés
        if '_' in callback_data:
            try:
                # Essayer de parser le callback pour voir s'il contient un index
                parts = callback_data.split('_')
                if parts and parts[-1].isdigit():
                    logger.warning(f"⚠️ Callback avec index numérique non reconnu: {callback_data}")
                    await query.answer("⚠️ Action non implémentée")
                    return MAIN_MENU
            except Exception as e:
                logger.error(f"❌ Unrecognized callback parsing error: {callback_data} - {e}")
        
        await query.edit_message_text(
            f"⚠️ Action {callback_data} not implemented. Back to main menu.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")]]
            )
        )
        return MAIN_MENU

    except Exception as e:
        logger.error(f"Erreur dans handle_callback : {e}")
        await query.edit_message_text(
            "❌ An error occurred.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")]]
            )
        )
        return MAIN_MENU


async def handle_edit_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Gère la modification de l'heure d'une publication.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Raises:
        CallbackError: Si la publication n'est pas trouvée
    """
    query = update.callback_query
    try:
        await query.answer()
        post_id = context.user_data.get('current_post_id')
        if not post_id:
            raise CallbackError("Aucune publication en cours")

        await query.edit_message_text(
            "🕒 Entrez la nouvelle date et heure (format: JJ/MM/AAAA HH:MM):"
        )
        context.user_data['waiting_for_time'] = True

    except CallbackError as e:
        logger.error(f"Time modification error: {str(e)}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        await query.edit_message_text("❌ An unexpected error occurred")


async def handle_send_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    FONCTION OBSOLÈTE - Remplacée par handle_send_now_unified
    Conservée temporairement pour compatibilité
    """
    logger.warning("⚠️ Utilisation de l'ancienne fonction handle_send_now. Redirection vers handle_send_now_unified")
    return await handle_send_now_unified(update, context)


async def handle_cancel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Gère l'annulation d'une publication.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Raises:
        CallbackError: Si la publication ne peut pas être annulée
    """
    query = update.callback_query
    try:
        await query.answer()
        if context.user_data.get('confirming_cancel'):
            post_id = context.user_data.get('current_post_id')
            if not post_id:
                raise CallbackError("Aucune publication à annuler")

            db_manager = context.bot_data.get('db_manager')
            if not db_manager or not db_manager.delete_post(post_id):
                raise CallbackError("Impossible d'annuler la publication")

            await query.edit_message_text("✅ Publication cancelled")
            context.user_data.pop('confirming_cancel', None)
        else:
            context.user_data['confirming_cancel'] = True
            await query.edit_message_text(
                "⚠️ Are you sure you want to cancel this publication?",
                reply_markup=[[
                    InlineKeyboardButton("Yes", callback_data="annuler_publication"),
                    InlineKeyboardButton("No", callback_data="retour")
                ]]
            )

    except CallbackError as e:
        logger.error(f"Cancellation error: {str(e)}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        await query.edit_message_text("❌ An unexpected error occurred")


async def handle_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Gère l'aperçu d'une publication.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Raises:
        CallbackError: Si la publication n'est pas trouvée
    """
    query = update.callback_query
    try:
        await query.answer()
        post_data = context.user_data.get('current_post')
        if not post_data:
            raise CallbackError("Aucune publication en cours")

        preview_text = (
            f"📝 Aperçu de la publication:\n\n"
            f"Type: {post_data['type']}\n"
            f"Contenu: {post_data['content'][:100]}...\n"
            f"Légende: {post_data.get('caption', 'Aucune')}\n"
            f"Horaire: {post_data.get('scheduled_time', 'Immédiat')}"
        )

        await query.edit_message_text(preview_text)

    except CallbackError as e:
        logger.error(f"Preview error: {str(e)}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        await query.edit_message_text("❌ An unexpected error occurred")


async def handle_post_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère le choix du type de publication.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Returns:
        int: L'état suivant de la conversation

    Raises:
        CallbackError: Si le type de publication est invalide
    """
    query = update.callback_query
    try:
        await query.answer()

        post_type = query.data.split('_')[-1]
        if post_type not in ['text', 'photo', 'video']:
            raise CallbackError("Type de publication invalide")

        context.user_data['post_type'] = post_type

        if post_type == 'text':
            await query.edit_message_text(
                "Entrez le texte de votre publication:"
            )
            return 4  # WAITING_TEXT

        await query.edit_message_text(
            "Send the photo or video:"
        )
        return 5  # WAITING_MEDIA

    except CallbackError as e:
        logger.error(f"Erreur de type de publication: {str(e)}")
        await query.edit_message_text(f"❌ Erreur: {str(e)}")
        return 1  # CREATE_PUBLICATION
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await query.edit_message_text("❌ Une erreur inattendue s'est produite")
        return 1  # CREATE_PUBLICATION


async def handle_schedule_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère le choix du type de publication à planifier.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Returns:
        int: L'état suivant de la conversation

    Raises:
        CallbackError: Si le type de publication est invalide
    """
    query = update.callback_query
    try:
        await query.answer()

        post_type = query.data.split('_')[-1]
        if post_type not in ['text', 'photo', 'video']:
            raise CallbackError("Type de publication invalide")

        context.user_data['post_type'] = post_type

        if post_type == 'text':
            await query.edit_message_text(
                "Entrez le texte de votre publication:"
            )
            return 6  # WAITING_SCHEDULE_TEXT

        await query.edit_message_text(
            "Send the photo or video:"
        )
        return 7  # WAITING_SCHEDULE_MEDIA

    except CallbackError as e:
        logger.error(f"Erreur de type de publication planifiée: {str(e)}")
        await query.edit_message_text(f"❌ Erreur: {str(e)}")
        return 2  # PLANIFIER_POST
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await query.edit_message_text("❌ Une erreur inattendue s'est produite")
        return 2  # PLANIFIER_POST


async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère les paramètres du bot.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Returns:
        int: L'état suivant de la conversation

    Raises:
        CallbackError: Si le type de paramètre est invalide
    """
    query = update.callback_query
    try:
        await query.answer()

        setting_type = query.data.split('_')[-1]
        if setting_type not in ['timezone', 'other']:
            raise CallbackError("Type de paramètre invalide")

        if setting_type == 'timezone':
            await query.edit_message_text(
                "Entrez votre fuseau horaire (ex: Europe/Paris):"
            )
            return 8  # WAITING_TIMEZONE

        await query.edit_message_text(
            "Autres paramètres à venir..."
        )
        return ConversationHandler.END

    except CallbackError as e:
        logger.error(f"Erreur de paramètres: {str(e)}")
        await query.edit_message_text(f"❌ Erreur: {str(e)}")
        return 3  # SETTINGS
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await query.edit_message_text("❌ Une erreur inattendue s'est produite")
        return 3  # SETTINGS


async def handle_schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère la planification effective des messages - VERSION FINALE CORRIGÉE"""
    try:
        # Vérifications de base
        if not update.message or not update.message.text:
            return SCHEDULE_SEND

        # Vérifier si un jour a été sélectionné
        if 'schedule_day' not in context.user_data:
            await update.message.reply_text(
                "❌ Please select a day first (Today or Tomorrow).",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Back", callback_data="schedule_send")
                ]])
            )
            return SCHEDULE_SEND

        # Vérifier si nous avons des posts à planifier
        posts = context.user_data.get("posts", [])
        if not posts and 'current_scheduled_post' not in context.user_data:
            await update.message.reply_text(
                "❌ No content to schedule. Please send content first.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        if await refuse_while_renaming(update, posts):      # the time can be typed again once it's done
            return SCHEDULE_SEND

        # Parser l'heure
        time_text = update.message.text.strip()
        try:
            if ':' in time_text:
                hour, minute = map(int, time_text.split(':'))
            else:
                    hour = int(time_text)
                    minute = 0
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid time format. Use HH:MM (ex: 14:30) or HH (ex: 14).",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Back", callback_data="schedule_send")
                ]])
            )
            return SCHEDULE_SEND

            # Validation de l'heure
        if not (0 <= hour <= 23) or not (0 <= minute <= 59):
            await update.message.reply_text(
                "❌ Invalid time. Use 24h format (00:00 to 23:59).",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Back", callback_data="schedule_send")
                ]])
            )
            return SCHEDULE_SEND

        # Calcul de l'heure cible (heure locale de l'utilisateur)
        user_id = update.effective_user.id
        from database.manager import DatabaseManager
        db_manager = DatabaseManager()
        
        # Récupérer le fuseau horaire de l'utilisateur
        user_timezone = db_manager.get_user_timezone(user_id)
        if not user_timezone:
            user_timezone = 'Europe/Paris'  # Fallback
            
        import pytz
        tz = pytz.timezone(user_timezone)
        local_now = datetime.now(tz)
        
        # The chosen day at that time, in the user's timezone (« Overmorrow » used to be today: sent 2 days early)
        day = local_now.date() + timedelta(days={'tomorrow': 1, 'overmorrow': 2}.get(context.user_data['schedule_day'], 0))
        target_date_local = tz.localize(datetime(day.year, day.month, day.day, hour, minute))

        # Vérifier que l'heure n'est pas dans le passé
        if target_date_local <= local_now:
            await update.message.reply_text(
                "❌ The selected time has already passed. Choose a future time.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Back", callback_data="schedule_send")
                ]])
            )
            return SCHEDULE_SEND

        success_count = 0
        reordered = False

        # Vérifier si on modifie un post existant
        editing_post_id = context.user_data.get('editing_post_id')
        current_scheduled_post = context.user_data.get('current_scheduled_post')
        
        logger.info(f"🔍 DEBUG handle_schedule_time: editing_post_id={editing_post_id}, current_scheduled_post={bool(current_scheduled_post)}")
        
        if editing_post_id and current_scheduled_post:
            # Mode modification : utiliser les infos du post existant
            channel_id = current_scheduled_post.get('channel_id')
            channel_name = current_scheduled_post.get('channel_name', str(channel_id))
            channel_username = None  # Pas besoin de résoudre l'username
            logger.info(f"✅ Mode modification du post {editing_post_id}, canal: {channel_name} (ID: {channel_id})")
        else:
            # Mode création normale : utiliser le canal sélectionné
            selected_channel = context.user_data.get("selected_channel", {})
            channel_username = selected_channel.get("username")
            channel_name = selected_channel.get("name", "Unknown channel")
            
            logger.info(f"🔍 Mode création: selected_channel={selected_channel}")
            
            if not channel_username:
                logger.error(f"❌ Aucun username de canal dans selected_channel: {selected_channel}")
                await update.message.reply_text(
                    "❌ Aucun canal sélectionné. Sélectionnez d'abord un canal."
                )
                return
            
        # Résoudre l'username en ID numérique Telegram (seulement en mode création)
        if not editing_post_id and channel_username:
            try:
                # Assurer que l'username a le format @username
                if not channel_username.startswith('@'):
                    channel_username = f"@{channel_username}"
                    
                # Utiliser Telegram Bot API pour résoudre l'ID
                chat = await context.bot.get_chat(channel_username)
                channel_id = chat.id
                logger.info(f"✅ Canal '{channel_name}' ({channel_username}) résolu: ID = {channel_id}")
                
            except Exception as resolve_error:
                logger.error(f"❌ Impossible de résoudre le canal {channel_username}: {resolve_error}")
                await update.message.reply_text(
                    f"❌ Impossible d'accéder au canal {channel_username}. Vérifiez que:\n"
                    f"• Le bot est admin du canal\n"
                    f"• Le nom du canal est correct\n"
                    f"• Le canal existe et est accessible"
                )
                return

        # Si nous modifions un post existant
        if 'current_scheduled_post' in context.user_data:
            try:
                post = context.user_data['current_scheduled_post']
                post_id = post['id']
                # Mettre à jour la date planifiée en base
                from utils.scheduler_utils import ensure_schedule_columns, add_post_job, utc_text
                with sqlite3.connect(settings.db_config["path"]) as conn:
                    cursor = conn.cursor()
                    ensure_schedule_columns(cursor)
                    cursor.execute(
                        "UPDATE posts SET scheduled_time = ?, run_at = ?, owner_id = COALESCE(owner_id, ?), "
                        "status = 'pending' WHERE id = ?",
                        (target_date_local.strftime('%Y-%m-%d %H:%M:%S'), utc_text(target_date_local), user_id, post_id)
                    )
                    conn.commit()

                # Replanifier le job
                scheduler_manager = get_scheduler_manager()
                job_id = f"post_{post_id}"
                if scheduler_manager:
                    add_post_job(scheduler_manager.scheduler, post_id, target_date_local)
                    logger.info(f"✅ Job {job_id} replanifié pour {target_date_local}")
                else:
                    logger.error("❌ Scheduler manager introuvable pour replanifier")

                success_count += 1
            except Exception as edit_err:
                logger.error(f"❌ Erreur lors de la modification de l'heure: {edit_err}")
            
        else:
            # Planifier chaque nouveau post. The ids follow the list (episodes put back in order first): at the
            # scheduled time the posts of a channel go out lowest id first.
            from utils.scheduler_utils import ensure_schedule_columns, add_post_job, utc_text
            from utils.episode_order import in_episode_order
            scheduler_manager = get_scheduler_manager()
            posts, reordered = in_episode_order(posts)

            for post in posts:
                try:
                    # Sauvegarder le post en base de données
                    with sqlite3.connect(settings.db_config["path"]) as conn:
                        cursor = conn.cursor()
                        ensure_schedule_columns(cursor)

                        # Valider/normaliser le type de post
                        post_type = post.get('type')
                        if not post_type:
                            logger.warning(f"Type manquant pour le post, fallback -> 'document' | post={post}")
                            post_type = 'document'

                        # Préparer les champs optionnels
                        buttons_data = post.get('buttons')
                        reactions_data = post.get('reactions')
                        # Sérialiser en JSON si nécessaire
                        if buttons_data is not None and not isinstance(buttons_data, str):
                            try:
                                buttons_data = json.dumps(buttons_data)
                            except Exception:
                                buttons_data = None
                        if reactions_data is not None and not isinstance(reactions_data, str):
                            try:
                                reactions_data = json.dumps(reactions_data)
                            except Exception:
                                reactions_data = None

                        # Compatibilité schéma: construire dynamiquement SQL + paramètres
                        cursor.execute("PRAGMA table_info(posts)")
                        cols = [c[1] for c in cursor.fetchall()]
                        has_type = 'type' in cols
                        has_buttons = 'buttons' in cols
                        has_reactions = 'reactions' in cols

                        insert_columns = ['channel_id']
                        params = [int(channel_id)]  # ✅ Forcer le type INTEGER
                        if has_type:
                            insert_columns += ['type', 'post_type']
                            params += [post_type, post_type]
                        else:
                            insert_columns += ['post_type']
                            params += [post_type]
                        insert_columns += ['content', 'caption']
                        params += [post['content'], post.get('caption')]
                        if has_buttons:
                            insert_columns.append('buttons')
                            params.append(buttons_data)
                        if has_reactions:
                            insert_columns.append('reactions')
                            params.append(reactions_data)
                        insert_columns += ['scheduled_time', 'status', 'run_at', 'owner_id']
                        params += [target_date_local.strftime('%Y-%m-%d %H:%M:%S'), 'pending',
                                   utc_text(target_date_local), user_id]

                        placeholders = ', '.join(['?'] * len(params))
                        sql = f"INSERT INTO posts ({', '.join(insert_columns)}) VALUES ({placeholders})"
                        cursor.execute(sql, params)
                        post_id = cursor.lastrowid
                        conn.commit()
                        
                        # ✅ VALIDATION : Vérifier que le post a été créé correctement
                        cursor.execute("SELECT id FROM posts WHERE id = ?", (post_id,))
                        if not cursor.fetchone():
                            logger.error(f"❌ Échec de la création du post {post_id} en base de données")
                            continue
                        
                        logger.info(f"✅ Post {post_id} créé avec succès en base de données")
                        
                        # ✅ LOG DE DIAGNOSTIC COMPLET
                        logger.info(f"📊 Post scheduling debug:")
                        logger.info(f"   post_id: {post_id} (type: {type(post_id)})")
                        logger.info(f"   channel_id: {channel_id} (type: {type(channel_id)})")
                        logger.info(f"   scheduled_time: {target_date_local.strftime('%Y-%m-%d %H:%M:%S')}")
                        logger.info(f"   db_path: {os.path.abspath(settings.db_config['path'])}")

                    # Créer le job de planification SEULEMENT si le post existe
                    job_id = f"post_{post_id}"

                    # Planifier le job
                    if scheduler_manager:
                        try:
                            add_post_job(scheduler_manager.scheduler, post_id, target_date_local)
                            logger.info(f"✅ Job {job_id} créé pour {target_date_local}")
                            logger.info(f"🔍 Scheduler running: {scheduler_manager.scheduler.running}")
                            logger.info(f"🔍 Jobs count: {len(scheduler_manager.scheduler.get_jobs())}")
                            success_count += 1
                        except Exception as job_error:
                            logger.error(f"❌ Erreur lors de l'ajout du job {job_id}: {job_error}")
                            logger.exception("Job creation traceback:")
                    else:
                        logger.error("❌ Scheduler manager introuvable")
                        logger.error("🔍 Tentative de récupération du scheduler manager...")
                        # Essayer de récupérer depuis le contexte
                        if hasattr(context, 'application') and context.application:
                            app_scheduler = context.application.bot_data.get('scheduler_manager')
                            if app_scheduler:
                                logger.info("✅ Scheduler manager trouvé dans context.application")
                                try:
                                    add_post_job(app_scheduler.scheduler, post_id, target_date_local)
                                    logger.info(f"✅ Job {job_id} créé via context.application")
                                    success_count += 1
                                except Exception as fallback_error:
                                    logger.error(f"❌ Erreur avec le scheduler de fallback: {fallback_error}")
                            else:
                                logger.error("❌ Aucun scheduler manager trouvé dans context.application")
                        else:
                            logger.error("❌ Context.application non disponible")

                except Exception as e:
                    logger.error(f"❌ Erreur lors de la planification du post: {e}")

        # Message de confirmation
        if success_count > 0:
            time_display = target_date_local.strftime("%H:%M")
            day_text = {"today": "today", "tomorrow": "tomorrow"}.get(context.user_data['schedule_day'],
                                                                     target_date_local.strftime("%A %d %B"))
            
            # Afficher le fuseau horaire utilisé
            timezone_display = user_timezone.split('/')[-1] if '/' in user_timezone else user_timezone
            
            reorder_note = ""
            if reordered:
                from i18n import get_user_lang, t
                reorder_note = "\n\n" + t(get_user_lang(user_id), "send.reordered")
            await update.message.reply_text(
                f"✅ {success_count} file(s) scheduled for {day_text} at {time_display}\n"
                f"🌍 Timezone: {timezone_display} ({user_timezone})" + reorder_note,
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
        else:
            await update.message.reply_text(
                "❌ Error while scheduling.",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )

        # Nettoyage du contexte
        context.user_data.clear()
        return MAIN_MENU

    except Exception as e:
        logger.error(f"❌ Error in handle_schedule_time: {e}")
        logger.exception("Full traceback:")
        try:
            await update.message.reply_text(
                "❌ An error occurred while scheduling.",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
        except:
            pass
        return MAIN_MENU
async def handle_edit_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère la modification de l'heure d'une publication planifiée"""
    try:
        query = update.callback_query
        await query.answer()

        logger.info("🔍 DEBUG handle_edit_time: début de la fonction")
        
        post = context.user_data.get('current_scheduled_post')
        logger.info(f"🔍 DEBUG handle_edit_time: post trouvé = {bool(post)}")
        
        if not post:
            logger.error("❌ DEBUG handle_edit_time: aucun post trouvé dans current_scheduled_post")
            await query.edit_message_text(
                "❌ Publication introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        keyboard = [
            [
                InlineKeyboardButton("Today", callback_data="schedule_today"),
                InlineKeyboardButton("Tomorrow", callback_data="schedule_tomorrow"),
                InlineKeyboardButton("Overmorrow", callback_data="schedule_overmorrow"),
            ],
            [InlineKeyboardButton("↩️ Back", callback_data="retour")]
        ]

        message_text = (
            "📅 Choose the new date for your post:\n\n"
            "1️⃣ Select the day (Today, Tomorrow, or Overmorrow)\n"
            "2️⃣ Send the time in one of these formats:\n"
            "   • '15:30' or '1530' (24h)\n"
            "   • '6' (06:00)\n"
            "   • '5 3' (05:03)\n\n"
            "❌ No day selected"
        )

        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        context.user_data['editing_post_id'] = post['id']
        logger.info(f"✅ DEBUG handle_edit_time: editing_post_id défini à {post['id']}, retour SCHEDULE_SEND")
        return SCHEDULE_SEND

    except Exception as e:
        logger.error(f"❌ Erreur dans handle_edit_time : {e}")
        logger.exception("Traceback complet:")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de la modification de l'heure.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_cancel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Annule une publication planifiée"""
    try:
        query = update.callback_query
        await query.answer()

        post = context.user_data.get('current_scheduled_post')
        if not post:
            await query.edit_message_text(
                "❌ Publication introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        keyboard = [
            [
                InlineKeyboardButton("✅ Oui, annuler", callback_data="confirm_cancel"),
                InlineKeyboardButton("❌ No, keep", callback_data="retour")
            ]
        ]

        await query.edit_message_text(
            "⚠️ Êtes-vous sûr de vouloir annuler cette publication ?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SCHEDULE_SELECT_CHANNEL

    except Exception as e:
        logger.error(f"Erreur dans handle_cancel_post : {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de l'annulation.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_confirm_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirme et supprime une publication planifiée"""
    query = update.callback_query
    await query.answer()
    
    try:
        if 'current_scheduled_post' not in context.user_data:
            await query.message.reply_text("❌ No scheduled post selected.")
            return MAIN_MENU
            
        post = context.user_data['current_scheduled_post']
        
        # Supprimer de la base de données
        with sqlite3.connect(settings.db_config["path"]) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM posts WHERE id = ?", (post['id'],))
            conn.commit()
            
        # Supprimer le job du scheduler
        job_id = f"post_{post['id']}"
        # Utiliser l'application depuis le contexte
        if context.application and hasattr(context.application, 'job_queue'):
            try:
                context.application.job_queue.remove_job(job_id)
            except Exception:
                pass  # Le job n'existe peut-être pas
                
        await query.message.reply_text(
            "✅ Publication planifiée supprimée avec succès!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        
        # Nettoyer les données
        context.user_data.pop('current_scheduled_post', None)
        return MAIN_MENU
        
    except Exception as e:
        logger.error(f"Erreur lors de la suppression: {e}")
        await query.message.reply_text(
            "❌ Erreur lors de la suppression de la publication.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU



async def manage_channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Affiche le menu de gestion des canaux"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    # Only channels where user linked (bot+user admin)
    repo_channels = list_user_channels(user_id)
    channels = [
        { 'name': ch.get('title') or (ch.get('username') or ''), 'username': ch.get('username') }
        for ch in repo_channels if ch.get('username')
    ]
    
    keyboard = []
    
    if channels:
        for channel in channels:
            keyboard.append([
                InlineKeyboardButton(
                    f"📺 {channel['name']} (@{channel['username']})",
                    callback_data=f"channel_{channel['username']}"
                )
            ])
    
    keyboard.extend([
        [InlineKeyboardButton("➕ Add channel", callback_data="add_channel")],
        [InlineKeyboardButton("↩️ Back", callback_data="settings")]
    ])
    
    message_text = "🌐 **Channel management**\n\n"
    if channels:
        message_text += "Select a channel to manage it or add a new one."
    else:
        message_text += "You don't have any channels configured yet. Add one to get started."
    
    await query.edit_message_text(
        message_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    return SETTINGS


async def add_channel_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Demande à l'utilisateur d'entrer les informations du canal"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "➕ **Add channel**\n\n"
        "Send the channel name followed by its @username.\n"
        "Format: `Channel name @username`\n\n"
        "Example: `My Channel @mychannel`\n\n"
        "⚠️ Make sure you are an admin of the channel.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[ 
            InlineKeyboardButton("❌ Cancel", callback_data="manage_channels")
        ]])
    )
    
    context.user_data['waiting_for_channel_info'] = True
    return WAITING_CHANNEL_INFO





async def select_channel(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_username: str) -> int:
    """Sélectionne un canal pour créer une publication"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    db_manager = DatabaseManager()
    
    # Resolve from repo first; fallback to legacy DB if needed
    repo_matches = [c for c in list_user_channels(user_id) if (c.get('username') == channel_username or f"@{c.get('username')}" == channel_username)]
    channel = None
    if repo_matches:
        first = repo_matches[0]
        channel = { 'name': first.get('title') or (first.get('username') or ''), 'username': first.get('username') }
    else:
        db_manager = DatabaseManager()
        channel = db_manager.get_channel_by_username(channel_username, user_id)

    if not channel:
        await query.edit_message_text(
            "❌ Channel not found.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU
    
    # Stocker le canal sélectionné
    context.user_data['selected_channel'] = channel
    
    await query.edit_message_text(
        f"📺 Selected channel: **{channel['name']}**\n\n"
        f"Now send your content:\n"
        f"• 📝 Text\n"
        f"• 🖼️ Photo\n"
        f"• 🎥 Video\n"
        f"• 📄 Document",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data="create_publication")
        ]])
    )
    
    return WAITING_PUBLICATION_CONTENT


async def show_channel_options(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_username: str) -> int:
    """Affiche les options pour un canal spécifique"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    db_manager = DatabaseManager()
    
    channel = db_manager.get_channel_by_username(channel_username, user_id)
    
    if not channel:
        await query.edit_message_text(
            "❌ Channel not found.",
            reply_markup=InlineKeyboardMarkup([[ 
                InlineKeyboardButton("↩️ Back", callback_data="manage_channels")
            ]])
        )
        return SETTINGS
    
    keyboard = [
        [InlineKeyboardButton("⚙️ Custom settings", callback_data=f"custom_channel_{channel_username}")],
        [InlineKeyboardButton("📝 Create a post", callback_data=f"select_channel_{channel_username}")],
        [InlineKeyboardButton("🗑️ Delete channel", callback_data=f"delete_channel_{channel['id']}")],
        [InlineKeyboardButton("↩️ Back", callback_data="manage_channels")]
    ]
    
    await query.edit_message_text(
        f"📺 **{channel['name']}** (@{channel['username']})\n\n"
        f"What do you want to do with this channel?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    return SETTINGS


async def custom_channel_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_username: str) -> int:
    """Affiche les paramètres personnalisés d'un canal"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    db_manager = DatabaseManager()
    
    channel = db_manager.get_channel_by_username(channel_username, user_id)
    
    if not channel:
        await query.edit_message_text(
            "❌ Channel not found.",
            reply_markup=InlineKeyboardMarkup([[ 
                InlineKeyboardButton("↩️ Back", callback_data="manage_channels")
            ]])
        )
        return SETTINGS
    
    # Récupérer les infos du tag
    db_manager = DatabaseManager()
    tag = db_manager.get_channel_tag(channel_username, user_id)
    
    keyboard = [
        [InlineKeyboardButton("🏷️ Add a hashtag", callback_data=f"edit_tag_{channel_username}")],
        [InlineKeyboardButton("↩️ Back", callback_data=f"channel_{channel_username}")]
    ]
    
    message_text = f"⚙️ **Settings for {channel['name']}**\n\n"
    message_text += f"🏷️ Tag: {tag if tag else 'No tag set'}\n"
    
    # Stocker le canal dans le contexte pour les opérations suivantes
    context.user_data['custom_channel'] = channel_username
    
    await query.edit_message_text(
        message_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    return SETTINGS


async def handle_edit_tag(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_username: str) -> int:
    """Gère l'ajout/modification de hashtags pour un canal"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    # Stocker le canal dans le contexte pour la prochaine étape
    context.user_data['editing_tag_for_channel'] = channel_username
    context.user_data['awaiting_username'] = True
    
    message_text = (
        "Send me the text/tag to add to your files.\n\n"
        "You can send:\n"
        "• @username\n"
        "• #hashtag\n"
        "• [📢 @channel]\n"
        "• 🔥 @fire\n"
        "• Any text with emojis!"
    )
    
    keyboard = [
        [InlineKeyboardButton("❌ Cancel", callback_data=f"custom_channel_{channel_username}")]
    ]
    
    await query.edit_message_text(
        text=message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return WAITING_TAG_INPUT


async def custom_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Menu des paramètres personnalisés généraux"""
    query = update.callback_query
    await query.answer()
    
    # Importer i18n pour la localisation
    from i18n import get_user_lang, t, SUPPORTED
    
    user_id = update.effective_user.id
    user_lang = get_user_lang(user_id, update.effective_user.language_code)
    
    keyboard = [
        [InlineKeyboardButton("🌐 Manage channels", callback_data="manage_channels")],
        [InlineKeyboardButton("🕐 Timezone", callback_data="timezone_settings")],
        [InlineKeyboardButton(t(user_lang, "settings.language"), callback_data="language_settings")],
        [InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")]
    ]
    
    await query.edit_message_text(
        "⚙️ **Custom settings**\n\n"
        "Choose an option:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    return SETTINGS


async def delete_channel(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: str) -> int:
    """Demande confirmation pour supprimer un canal"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Oui, supprimer", callback_data=f"confirm_delete_channel_{channel_id}"),
            InlineKeyboardButton("❌ Non, annuler", callback_data="manage_channels")
        ]
    ]
    
    await query.edit_message_text(
        "⚠️ **Êtes-vous sûr de vouloir supprimer ce canal ?**\n\n"
        "Cette action supprimera également toutes les publications associées.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    return SETTINGS


async def confirm_delete_channel(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: str) -> int:
    """Confirme et supprime le canal"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    db_manager = DatabaseManager()
    
    try:
        channel_id_int = int(channel_id)
        success = db_manager.delete_channel(channel_id_int, user_id)
        
        if success:
            await query.edit_message_text(
                "✅ Channel deleted successfully!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Back", callback_data="manage_channels")
                ]])
            )
        else:
            await query.edit_message_text(
                "❌ Error deleting channel.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Back", callback_data="manage_channels")
                ]])
            )
    except Exception as e:
        logger.error(f"Error deleting channel: {e}")
        await query.edit_message_text(
            "❌ An error occurred.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Back", callback_data="manage_channels")
            ]])
        )
    
    return SETTINGS


async def handle_timezone_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gère les paramètres de fuseau horaire"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    db_manager = DatabaseManager()
    
    # Récupérer le fuseau horaire actuel
    current_timezone = db_manager.get_user_timezone(user_id) or "UTC"
    
    # Liste des fuseaux horaires courants
    popular_timezones = [
        ("Europe/Paris", "🇫🇷 Paris (UTC+1/+2)"),
        ("Europe/London", "🇬🇧 Londres (UTC+0/+1)"),
        ("America/New_York", "🇺🇸 New York (UTC-5/-4)"),
        ("America/Los_Angeles", "🇺🇸 Los Angeles (UTC-8/-7)"),
        ("Asia/Tokyo", "🇯🇵 Tokyo (UTC+9)"),
        ("Asia/Shanghai", "🇨🇳 Shanghai (UTC+8)"),
        ("Australia/Sydney", "🇦🇺 Sydney (UTC+10/+11)"),
        ("UTC", "🌐 UTC (Temps universel)")
    ]
    
    keyboard = []
    for tz_code, tz_name in popular_timezones:
        # Marquer le fuseau actuel
        if tz_code == current_timezone:
            button_text = f"✅ {tz_name}"
        else:
            button_text = tz_name
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"set_timezone_{tz_code}")])
    
    # Bouton pour saisir manuellement
    keyboard.append([InlineKeyboardButton("✏️ Saisir manuellement", callback_data="manual_timezone")])
    keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="custom_settings")])
    
    # Obtenir l'heure actuelle dans le fuseau de l'utilisateur
    from datetime import datetime
    import pytz
    
    try:
        user_tz = pytz.timezone(current_timezone)
        local_time = datetime.now(user_tz)
        time_display = local_time.strftime("%H:%M")
        date_display = local_time.strftime("%d/%m/%Y")
    except:
        time_display = "Erreur"
        date_display = ""
    
    message = (
        f"🕐 Configuration du fuseau horaire\n\n"
        f"Fuseau actuel : {current_timezone}\n"
        f"Heure locale : {time_display} ({date_display})\n\n"
        f"Sélectionnez votre fuseau horaire pour que les messages soient planifiés selon votre heure locale :"
    )
    
    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return SETTINGS


async def handle_set_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE, timezone_code: str) -> int:
    """Définit le fuseau horaire sélectionné"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    db_manager = DatabaseManager()
    
    try:
        # Valider que le fuseau horaire existe
        import pytz
        if timezone_code not in pytz.all_timezones:
            await query.edit_message_text(
                "❌ Invalid timezone.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Back", callback_data="timezone_settings")
                ]])
            )
            return SETTINGS
        
        # Sauvegarder le fuseau horaire
        success = db_manager.set_user_timezone(user_id, timezone_code)
        
        if success:
            # Afficher l'heure dans le nouveau fuseau
            from datetime import datetime
            user_tz = pytz.timezone(timezone_code)
            local_time = datetime.now(user_tz)
            
            # Message sans Markdown pour éviter les erreurs de parsing
            await query.edit_message_text(
                f"✅ Fuseau horaire mis à jour !\n\n"
                f"Nouveau fuseau : {timezone_code}\n"
                f"Heure locale : {local_time.strftime('%H:%M')} ({local_time.strftime('%d/%m/%Y')})\n\n"
                f"Vos futures publications seront planifiées selon ce fuseau horaire.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Back to Settings", callback_data="settings")
                ]])
            )
        else:
            await query.edit_message_text(
                "❌ Error updating timezone.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Back", callback_data="timezone_settings")
                ]])
            )
            
    except Exception as e:
        logger.error(f"Error updating timezone: {e}")
        await query.edit_message_text(
            "❌ An error occurred.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Back", callback_data="timezone_settings")
            ]])
        )
    
    return SETTINGS


async def handle_manual_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Permet la saisie manuelle du fuseau horaire"""
    query = update.callback_query
    await query.answer()
    
    # Stocker qu'on attend une saisie de fuseau horaire
    context.user_data['waiting_for_timezone'] = True
    
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="timezone_settings")]]
    
    await query.edit_message_text(
        "✏️ Type your timezone\n\n"
        "Send me your timezone in the standard format.\n\n"
        "Examples:\n"
        "• Europe/Paris\n"
        "• America/New_York\n"
        "• Asia/Tokyo\n"
        "• Africa/Cairo\n\n"
        "💡 The full list:\n"
        "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    # Importer l'état pour attendre la saisie
    from conversation_states import WAITING_TAG_INPUT
    return WAITING_TAG_INPUT  # On réutilise cet état pour la saisie de texte


async def handle_create_publication(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gère la création d'une nouvelle publication"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    try:
        await query.answer()
        logger.info(f"handle_create_publication appelé par l'utilisateur {user_id}")
        
        # Load connected channels only (bot+user admins)
        repo_channels = list_user_channels(user_id)
        channels = [
            { 'name': ch.get('title') or (ch.get('username') or ''), 'username': ch.get('username') }
            for ch in repo_channels if ch.get('username')
        ]
        
        # Si aucun canal n'est configuré
        if not channels:
            keyboard = [
                [InlineKeyboardButton("➕ Add channel", callback_data="add_channel")],
                [InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")]
            ]
            
            message_text = (
                "⚠️ No channels configured\n\n"
                "To publish content, you must first configure a Telegram channel.\n"
                "You can add an existing channel where you are an admin."
            )
            
            await query.edit_message_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return WAITING_CHANNEL_SELECTION
        
        # Construction du clavier avec les canaux
        keyboard = []
        current_row = []
        
        for i, channel in enumerate(channels):
            current_row.append(InlineKeyboardButton(
                channel['name'],
                callback_data=f"select_channel_{channel['username']}"
            ))
            
            # Nouvelle ligne tous les 2 boutons
            if len(current_row) == 2 or i == len(channels) - 1:
                keyboard.append(current_row)
                current_row = []
        
        # Add action buttons
        keyboard.append([
            InlineKeyboardButton("➕ Add channel", callback_data="add_channel")
        ])
        keyboard.append([
            InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
        ])
        
        message_text = (
            "📝 Select a channel for your post:\n\n"
            "• Choose an existing channel, or\n"
            "• Add a new channel"
        )
        
        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return WAITING_CHANNEL_SELECTION
        
    except Exception as e:
        logger.error(f"Erreur lors de l'affichage des canaux: {e}")
        
        # Vérifier si c'est un problème de base de données
        if "no such table" in str(e).lower() or "database" in str(e).lower():
            error_message = "❌ Erreur de base de données. Veuillez contacter l'administrateur."
        elif "connection" in str(e).lower():
            error_message = "❌ Erreur de connexion. Veuillez réessayer plus tard."
        else:
            error_message = "❌ Une erreur est survenue lors de la récupération des canaux."
        
        keyboard = [
            [InlineKeyboardButton("🔄 Retry", callback_data="create_publication")],
            [InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")]
        ]
        
        try:
            await query.edit_message_text(
                error_message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as edit_error:
            logger.error(f"Erreur lors de l'édition du message: {edit_error}")
            # Essayer d'envoyer un nouveau message
            try:
                await query.message.reply_text(
                    error_message,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as reply_error:
                logger.error(f"Erreur lors de l'envoi du message: {reply_error}")
        
        return MAIN_MENU


async def planifier_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche les publications planifiées par chaîne."""
    try:
        # Initialiser le gestionnaire de base de données
        db_manager = DatabaseManager()
        
        with sqlite3.connect(settings.db_config["path"]) as conn:
            cursor = conn.cursor()
            # Détecter les colonnes présentes dans channels
            cursor.execute("PRAGMA table_info(channels)")
            ch_cols = [r[1] for r in cursor.fetchall()]
            has_name = 'name' in ch_cols
            has_title = 'title' in ch_cols
            has_user_col = 'user_id' in ch_cols
            # Détecter table channel_members
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channel_members'")
            has_members = cursor.fetchone() is not None

            # Détecter les colonnes présentes dans posts pour éviter de référencer des colonnes inexistantes
            cursor.execute("PRAGMA table_info(posts)")
            p_cols = [r[1] for r in cursor.fetchall()]
            has_post_type_col = 'post_type' in p_cols
            has_legacy_type_col = 'type' in p_cols
            if has_post_type_col and has_legacy_type_col:
                post_type_expr = "COALESCE(NULLIF(p.post_type, ''), p.type) AS post_type"
            elif has_post_type_col:
                post_type_expr = "p.post_type AS post_type"
            elif has_legacy_type_col:
                post_type_expr = "p.type AS post_type"
            else:
                post_type_expr = "'' AS post_type"

            # ✅ CORRECTION CRITIQUE : Éviter la jointure channels car les IDs ne correspondent pas
            # Les posts contiennent channel_id = -1002225408564 (ID Telegram réel)
            # Mais channels.id = 1,2,3... (clés primaires locales) 
            # → La jointure échoue et aucun résultat n'est retourné
            # Solution : récupérer les posts sans jointure
            
            sql = f"""
                SELECT p.id,
                       {post_type_expr},
                       p.content,
                       p.caption,
                       p.scheduled_time,
                       p.channel_id
                FROM posts p
                WHERE p.status = 'pending'
                  AND p.scheduled_time IS NOT NULL
                  AND p.owner_id = ?
                ORDER BY p.scheduled_time
            """
            # only the caller's own posts (every user saw, and could edit or delete, the next post of anyone)
            from utils.scheduler_utils import ensure_schedule_columns
            ensure_schedule_columns(cursor)
            cursor.execute(sql, (update.effective_user.id,))
            scheduled_posts = cursor.fetchall()

        if not scheduled_posts:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    "❌ No scheduled posts found.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                    ]])
                )
            else:
                await update.message.reply_text("❌ No scheduled posts found.")
            return MAIN_MENU

        # Filtrer par l'heure locale de l'utilisateur: ne montrer que les posts futurs
        user_id = update.effective_user.id
        user_timezone = db_manager.get_user_timezone(user_id) or "UTC"
        local_tz = pytz.timezone(user_timezone)
        now_local = datetime.now(local_tz)

        # Conserver uniquement le prochain post à venir (le plus proche dans le futur)
        filtered_posts = []
        for post in scheduled_posts:
            try:
                st_str = post[4]
                dt_naive = datetime.strptime(st_str, '%Y-%m-%d %H:%M:%S')
                dt_local = local_tz.localize(dt_naive)
                if dt_local > now_local:
                    filtered_posts.append(post)
            except Exception:
                # En cas de format inattendu, afficher quand même
                filtered_posts.append(post)

        # The next ones, in send order (only the very next one was shown: 12 episodes scheduled, 1 visible)
        SHOWN = 10
        try:
            filtered_posts.sort(key=lambda p: (datetime.strptime(p[4], '%Y-%m-%d %H:%M:%S'), p[0]))
        except Exception:
            pass
        more = max(0, len(filtered_posts) - SHOWN)
        filtered_posts = filtered_posts[:SHOWN]

        if not filtered_posts:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    "❌ No scheduled posts found.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")]])
                )
            else:
                await update.message.reply_text("❌ No scheduled posts found.")
            return MAIN_MENU

        # The channel of each post (posts keep its Telegram id). It showed the first channel of the table, whoever's.
        names = {}

        async def channel_label(channel_id):
            if channel_id in names:
                return names[channel_id]
            label = None
            try:
                with sqlite3.connect(settings.db_config["path"]) as conn2:
                    cols = [r[1] for r in conn2.execute("PRAGMA table_info(channels)")]
                    if "tg_chat_id" in cols:
                        row = conn2.execute("SELECT title, username FROM channels WHERE tg_chat_id = ?",
                                            (channel_id,)).fetchone()
                        label = row and (row[0] or (f"@{row[1]}" if row[1] else None))
            except sqlite3.Error:
                pass
            if not label:
                try:
                    chat = await context.bot.get_chat(channel_id)
                    label = chat.title or (f"@{chat.username}" if chat.username else None)
                except Exception:
                    pass
            names[channel_id] = label or f"channel {channel_id}"
            return names[channel_id]

        keyboard = []
        message = "📅 Scheduled posts:\n\n"
        for post in filtered_posts:
            post_id, post_type, content, caption, scheduled_time, channel_id = post
            button_text = f"{scheduled_time[:16]} - {await channel_label(channel_id)}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"show_post_{post_id}")])
            message += f"• {button_text}\n"
        if more:
            message += f"… and {more} more\n"

        keyboard.append([InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")])

        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return SCHEDULE_SELECT_CHANNEL

    except Exception as e:
        logger.error(f"Error in planifier_post: {e}")
        error_message = "❌ An error occurred while listing scheduled posts."
        if update.callback_query:
            await update.callback_query.edit_message_text(
                error_message,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
        else:
            await update.message.reply_text(error_message)
        return MAIN_MENU


async def show_scheduled_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche les détails d'une publication planifiée"""
    try:
        query = update.callback_query
        await query.answer()

        post_id = query.data.split('_')[-1]

        with sqlite3.connect(settings.db_config["path"]) as conn:
            cursor = conn.cursor()
            # Récupérer directement les données du post sans jointure problématique
            cursor.execute("""
                SELECT id, post_type, content, caption, scheduled_time, channel_id
                FROM posts
                WHERE id = ?
            """, (post_id,))
            post_data = cursor.fetchone()

        if not post_data:
            await query.edit_message_text(
                "❌ Publication introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        # Décomposer les données du post
        post_id, post_type, content, caption, scheduled_time_str, channel_id = post_data
        scheduled_time = datetime.strptime(scheduled_time_str, '%Y-%m-%d %H:%M:%S')

        # Résoudre le nom du canal depuis channel_id
        channel_name = str(channel_id)  # Par défaut, utiliser l'ID
        try:
            # Essayer de récupérer des informations sur le canal si disponible
            cursor.execute("SELECT username, title FROM channels WHERE id = ?", (channel_id,))
            channel_info = cursor.fetchone()
            if channel_info:
                username, title = channel_info
                channel_name = title or username or str(channel_id)
        except:
            # Si la requête échoue, utiliser l'ID du canal
            pass

        post = {
            'id': post_id,
            'type': post_type,
            'content': content,
            'caption': caption,
            'scheduled_time': scheduled_time_str,
            'channel_name': channel_name,
            'channel_id': channel_id,
            'scheduled_date': scheduled_time
        }

        context.user_data['current_scheduled_post'] = post

        keyboard = [
            [InlineKeyboardButton("🕒 Edit time", callback_data="modifier_heure")],
            [InlineKeyboardButton("🚀 Send now", callback_data="envoyer_maintenant")],
            [InlineKeyboardButton("❌ Cancel scheduled post", callback_data="annuler_publication")],
            [InlineKeyboardButton("↩️ Back", callback_data="retour")]
        ]

        try:
            # Nettoyer la caption pour éviter les erreurs de formatage
            safe_caption = None
            if post.get('caption'):
                safe_caption = str(post['caption'])
                # Supprimer les entités de formatage problématiques
                safe_caption = safe_caption.replace('*', '').replace('_', '').replace('`', '').replace('[', '').replace(']', '')
            
            if post['type'] == "photo":
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=post['content'],
                    caption=safe_caption,
                    reply_markup=None
                )
            elif post['type'] == "video":
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=post['content'],
                    caption=safe_caption,
                    reply_markup=None
                )
            elif post['type'] == "document":
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=post['content'],
                    caption=safe_caption,
                    reply_markup=None
                )
            elif post['type'] == "text":
                # Nettoyer le texte aussi
                safe_text = str(post['content']).replace('*', '').replace('_', '').replace('`', '').replace('[', '').replace(']', '')
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=safe_text,
                    reply_markup=None
                )
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du contenu : {e}")
            # En cas d'erreur, on continue sans afficher le contenu

        # Récupérer le fuseau horaire de l'utilisateur
        user_id = update.effective_user.id
        db_manager = DatabaseManager()
        user_timezone = db_manager.get_user_timezone(user_id) or "UTC"
        local_tz = pytz.timezone(user_timezone)
        
        # Convertir l'heure en local
        utc_time = scheduled_time.replace(tzinfo=pytz.UTC)
        local_time = utc_time.astimezone(local_tz)

        # Sécuriser les chaînes pour éviter les problèmes de formatage
        safe_channel_name = str(post.get('channel_name', 'Inconnu')).replace('_', '-').replace('*', '-').replace('`', '-')
        safe_type = str(post.get('type', 'Inconnu')).replace('_', '-').replace('*', '-').replace('`', '-')
        
        message = (
            f"📝 Scheduled post:\n\n"
            f"📅 Date: {local_time.strftime('%d/%m/%Y')}\n"
            f"⏰ Time: {local_time.strftime('%H:%M')} ({user_timezone})\n"
            f"🌐 UTC time: {scheduled_time.strftime('%H:%M')}\n"
            f"📍 Channel: {safe_channel_name}\n"
            f"📎 Type: {safe_type}\n"
        )

        await query.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return SCHEDULE_SELECT_CHANNEL

    except Exception as e:
        logger.error(f"Erreur dans show_scheduled_post : {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de l'affichage de la publication.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def show_edit_file_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, post_index: int) -> int:
    """Affiche le menu d'édition de fichier avec les 3 options"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    try:
        await query.answer()
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            from utils.message_utils import safe_edit_message_text
            await safe_edit_message_text(
                query,
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        post = context.user_data['posts'][post_index]
        
        # Menu d'édition exactement comme dans l'image
        keyboard = [
            [InlineKeyboardButton("✏️ Rename", callback_data=f"rename_post_{post_index}", api_kwargs={"style": "success"})],

        ]
        
        from utils.message_utils import safe_edit_message_text
        await safe_edit_message_text(
            query,
            f"✏️ **Edit file {post_index + 1}**\n\n"
            f"Type: {post['type']}\n"
            f"Choose an action:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
        return MAIN_MENU
        
    except Exception as e:
        logger.error(f"Erreur dans show_edit_file_menu: {e}")
        from utils.message_utils import safe_edit_message_text
        await safe_edit_message_text(
            query,
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_rename_post(update: Update, context: ContextTypes.DEFAULT_TYPE, post_index: int) -> int:
    """Gère le renommage d'un post"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await safe_edit_callback_message(
                query,
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Supprimer le message du menu 'Edit File' pour nettoyer l'UI
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
        except Exception:
            pass
        
        # Stocker les variables nécessaires pour le gestionnaire existant
        context.user_data['waiting_for_rename'] = True
        context.user_data['current_post_index'] = post_index
        
        # Envoyer un nouveau message de prompt (au lieu d'éditer)
        prompt_text = (
            f"✏️ **Rename file {post_index + 1}**\n\n"
            "Send the new name/title for this file:"
        )
        ask_msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=prompt_text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_rename_{post_index}")
            ]]),
            parse_mode="Markdown"
        )
        
        # Stocker l'ID du nouveau message de prompt pour suppression ultérieure
        context.user_data['rename_prompt_message_id'] = ask_msg.message_id
        context.user_data['rename_prompt_chat_id'] = ask_msg.chat_id
        
        from conversation_states import WAITING_RENAME_INPUT
        return WAITING_RENAME_INPUT
        
    except Exception as e:
        logger.error(f"Erreur dans handle_rename_post: {e}")
        from utils.message_utils import safe_edit_message_text
        await safe_edit_message_text(
            query,
            "❌ Une erreur est survenue."
        )
        return MAIN_MENU








async def handle_delete_post(update: Update, context: ContextTypes.DEFAULT_TYPE, post_index: int) -> int:
    """Supprime un post spécifique"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            # Envoyer un nouveau message au lieu d'éditer (évite l'erreur "no text to edit")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Post introuvable."
            )
            return WAITING_PUBLICATION_CONTENT
        
        # Supprimer le message de prévisualisation s'il est mémorisé
        prev_map = context.user_data.get('preview_messages', {}) or {}
        prev = prev_map.get(post_index)
        if prev:
            try:
                await context.bot.delete_message(chat_id=prev['chat_id'], message_id=prev['message_id'])
            except Exception:
                pass
            # Retirer l'entrée
            prev_map.pop(post_index, None)
        
        # Supprimer aussi le message courant (celui contenant les boutons) si possible
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
        except Exception:
            pass
        
        # Récupérer les informations du post avant suppression (pour feedback)
        deleted_post = context.user_data['posts'][post_index]
        post_type = deleted_post.get('type', 'contenu')
        
        # Supprimer le post de la liste
        context.user_data['posts'].pop(post_index)
        
        # Réindexer les messages d'aperçu restants (les clés > post_index diminuent de 1)
        if prev_map:
            new_prev = {}
            for idx, info in prev_map.items():
                try:
                    idx_int = int(idx)
                except Exception:
                    idx_int = idx
                if isinstance(idx_int, int) and idx_int > post_index:
                    new_prev[idx_int - 1] = info
                elif isinstance(idx_int, int) and idx_int < post_index:
                    new_prev[idx_int] = info
            context.user_data['preview_messages'] = new_prev
        
        # Message de confirmation simple (auto-suppression)
        remaining_posts = len(context.user_data.get('posts', []))
        message = f"✅ Post {post_index + 1} supprimé\n\n"
        message += f"📝 Type: {post_type}\n\n"
        message += f"Il vous reste {remaining_posts} post(s) en attente"
        
        # Envoyer un nouveau message puis auto-supprimer après 2s
        try:
            confirm_msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=message
        )
            # Auto-destruction après 2 secondes
            try:
                schedule_auto_destruction(context, confirm_msg.chat_id, confirm_msg.message_id, 2)
            except Exception:
                pass
        except Exception:
            pass
        
        return WAITING_PUBLICATION_CONTENT
        
    except Exception as e:
        logger.error(f"Erreur dans handle_delete_post: {e}")
        # Envoyer un nouveau message en cas d'erreur
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Erreur lors de la suppression du post."
        )
        return WAITING_PUBLICATION_CONTENT

async def schedule_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Interface de planification des messages"""
    try:
        query = update.callback_query
        await query.answer()

        # NETTOYAGE : Supprimer les anciennes données de planification pour éviter les conflits
        context.user_data.pop('schedule_day', None)
        logger.info("🧹 Contexte de planification nettoyé")

        # Récupérer le jour sélectionné s'il existe (après nettoyage, ce sera None)
        selected_day = context.user_data.get('schedule_day', None)

        # Create buttons
        keyboard = [
            [
                InlineKeyboardButton(
                    f"Today {'✅' if selected_day == 'today' else ''}",
                    callback_data="schedule_today"
                ),
                InlineKeyboardButton(
                    f"Tomorrow {'✅' if selected_day == 'tomorrow' else ''}",
                    callback_data="schedule_tomorrow"
                ),
                InlineKeyboardButton(
                    f"Overmorrow {'✅' if selected_day == 'overmorrow' else ''}",
                    callback_data="schedule_overmorrow"
                ),
            ],
            [InlineKeyboardButton("↩️ Back", callback_data="send_post")],
        ]

        # Message
        day_status = "✅ Selected day: " + (
            ("Today" if selected_day == "today" else ("Tomorrow" if selected_day == "tomorrow" else "Overmorrow"))
        ) if selected_day else "❌ No day selected"

        message_text = (
            "📅 Choose when to send your post:\n\n"
            "1️⃣ Select the day (Today, Tomorrow, or Overmorrow)\n"
            "2️⃣ Send the time in one of these formats:\n"
            "   • '15:30' or '1530' (24h)\n"
            "   • '6' (06:00)\n"
            "   • '5 3' (05:03)\n\n"
            f"{day_status}"
        )

        await safe_edit_callback_message(
            query,
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SCHEDULE_SEND
    except Exception as e:
        logger.error(f"Erreur lors de la planification de l'envoi : {e}")
        await safe_edit_callback_message(
            query,
            "❌ Erreur lors de la planification.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="main_menu")]])
        )
        return MAIN_MENU

async def refuse_while_renaming(update, posts) -> bool:
    """True (and the user told) when a file of the batch is still being sent again under its new name."""
    busy = [str(i + 1) for i, p in enumerate(posts or []) if p.get('renaming')]
    if not busy:
        return False
    from i18n import get_user_lang, t
    text = t(get_user_lang(update.effective_user.id), "send.renaming", files=", ".join(busy))
    target = update.message or (update.callback_query.message if update.callback_query else None)
    if target:
        await target.reply_text(text)
    return True


async def send_post_now(update, context, scheduled_post=None):
    """Envoie le post immédiatement en utilisant le meilleur client disponible."""
    try:
        # start send_now
        
        # 🔍 DIAGNOSTIC - Vérifier l'état des clients
        try:
            from utils.clients import client_manager
            # check clients status
            
            # Vérifier Pyrogram
            try:
                pyro_client = await client_manager.get_pyrogram_client()
                pyro_status = "ok" if pyro_client and hasattr(pyro_client, 'me') else "not connected"
            except Exception as e:
                logger.warning(f"📱 Pyrogram: ❌ Erreur - {e}")
                
            # Vérifier API Bot
            try:
                await context.bot.get_me()
            except Exception as e:
                logger.warning(f"📱 API Bot: ❌ Erreur - {e}")
                
        except Exception as diagnostic_error:
            logger.debug(f"Client diagnostic check failed: {diagnostic_error}")
        
        if scheduled_post:
            # Mode post planifié : récupérer les données depuis la base
            logger.info(f"📋 Mode envoi immédiat d'un post planifié (ID: {scheduled_post.get('id')})")
            
            # Créer un pseudo-post depuis les données planifiées
            post_data = {
                'type': scheduled_post.get('type'),
                'content': scheduled_post.get('content'),
                'caption': scheduled_post.get('caption'),
                'file_path': scheduled_post.get('content')  # Le content contient le chemin du fichier
            }
            
            posts = [post_data]
            channel_id = scheduled_post.get('channel_id')
            
        else:
            # Mode nouveau post : utiliser les données du contexte
            posts = context.user_data.get("posts", [])
            # logger.debug(f"Posts to send: {len(posts)}")
            
            if not posts:
                # No posts to send
                logger.warning("❌ Aucun post à envoyer (ni nouveau ni planifié)")
                if update.message:
                    await update.message.reply_text(
                        "❌ Il n'y a pas de fichiers à envoyer.",
                        reply_markup=InlineKeyboardMarkup([[ 
                            InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                        ]])
                    )
                elif hasattr(update, 'callback_query') and update.callback_query:
                    await update.callback_query.message.reply_text(
                        "❌ Il n'y a pas de fichiers à envoyer.",
                        reply_markup=InlineKeyboardMarkup([[ 
                            InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                        ]])
                    )
                return MAIN_MENU
            
            # A file being renamed is still the old one: wait for it
            if await refuse_while_renaming(update, posts):
                return WAITING_PUBLICATION_CONTENT

            # ✅ VALIDATION DU CANAL - Vérifier qu'un canal valide est sélectionné
            selected_channel = context.user_data.get('selected_channel', {})
            channel = selected_channel.get('username') or selected_channel.get('channel_id')
            
            # DEBUG - Afficher les informations du canal
            logger.info(f"🔍 DEBUG CANAL - selected_channel: {selected_channel}")
            logger.info(f"🔍 DEBUG CANAL - channel extrait: {channel}")
            logger.info(f"🔍 DEBUG CANAL - posts[0] channel: {posts[0].get('channel') if posts else 'N/A'}")
        
        # Pour les posts planifiés, on utilise le channel_id du post
        if scheduled_post:
            channel = channel_id  # Utiliser l'ID du canal du post planifié
            logger.info(f"🔍 DEBUG CANAL - Mode planifié, channel: {channel}")
        
        # Si pas de canal dans selected_channel, essayer de le récupérer depuis le post
        if not channel and posts:
            channel = posts[0].get("channel")
            logger.info(f"🔍 DEBUG CANAL - Récupéré depuis posts[0]: {channel}")
        
        if not channel or channel == '@default_channel':
            logger.warning(f"⚠️ No valid channel selected for posts. Selected: {selected_channel}")
            if update.message:
                await update.message.reply_text(
                    "⚠️ **No channel is selected for this post.**\n\n"
                    "👉 Choose a channel first, then try again.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📺 Choose channel", callback_data="choose_channel")],
                        [InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")]
                    ])
                )
            elif hasattr(update, 'callback_query') and update.callback_query:
                await update.callback_query.message.reply_text(
                    "⚠️ **No channel is selected for this post.**\n\n"
                    "👉 Choose a channel first, then try again.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📺 Choose channel", callback_data="choose_channel")],
                        [InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")]
                    ])
                )
            return MAIN_MENU
        
        # Si pas de post planifié, récupérer le canal du premier post ou du canal sélectionné  
        if not scheduled_post:
            selected_channel = context.user_data.get('selected_channel', {})
            if not channel:  # Si pas de canal défini plus haut
                channel = posts[0].get("channel") or selected_channel.get('username', '@default_channel')

        # logger.debug(f"Target channel: {channel}")

        # Correction : ajouter @ si besoin pour les canaux publics
        if isinstance(channel, str) and not channel.startswith('@') and not channel.startswith('-100'):
            channel = '@' + channel

        # logger.debug(f"Resolved channel: {channel}")

        # ✅ Tenter de résoudre le chat_id numérique (plus fiable que @username)
        channel_to_send = channel
        channel_label = channel
        # Récupérer le délai d'auto-destruction configuré (0 par défaut)
        auto_destruction_time = context.user_data.get('auto_destruction_time', 0)
        try:
            if isinstance(channel, str) and channel.startswith('@'):
                chat_info = await context.bot.get_chat(channel)
                channel_to_send = chat_info.id
                channel_label = f"@{chat_info.username}" if getattr(chat_info, 'username', None) else str(chat_info.id)
                # logger.debug(f"Resolved channel: {channel_label} (id={channel_to_send})")
        except Exception as resolve_err:
            logger.warning(f"⚠️ Impossible de résoudre le chat_id pour {channel}: {resolve_err}. Utilisation de la valeur fournie.")

        success_count = 0  # Initialisation du compteur de succès
        failed = []        # (index, post, error): reported at the end, and kept to be sent again
        # Utilitaires anti-flood/timeout
        import asyncio
        from utils.telegram_retry import send_with_retry as try_send_with_retry
        from utils.episode_order import in_episode_order

        # Files picked together on a phone often reach the bot shuffled: episodes of one series go out in order
        reordered = False
        if not scheduled_post:
            posts, reordered = in_episode_order(posts)

        for post_index, post in enumerate(posts):
            # logger.debug(f"Sending post {post_index + 1}/{len(posts)}")
            
            post_type = post.get("type")
            content = post.get("content")
            caption = post.get("caption") or ""
            filename = post.get("filename")
            thumbnail = post.get('thumbnail')

            # logger.debug(f"Post type: {post_type} | thumb: {thumbnail}")

            # === Build inline keyboard (reactions + URL buttons) ===
            keyboard = []
            
            # Générer un post_id unique basé sur le timestamp et l'index
            import time
            post_id = int(time.time() * 1000) + post_index  # Timestamp millisecondes + index

            # Reactions (can be list or JSON string)
            reactions = post.get('reactions')
            if not reactions:
                # Fallback to current_post in user_data (immediate flow often stores here)
                reactions = context.user_data.get('current_post', {}).get('reactions', [])
                logger.info(f"Fallback reactions from current_post: {reactions}")
            try:
                if isinstance(reactions, str):
                    try:
                        reactions = json.loads(reactions)
                        logger.info(f"✅ Reactions parsed from JSON: {reactions}")
                    except json.JSONDecodeError:
                        logger.warning(f"❌ Could not parse reactions JSON: {reactions}")
                        reactions = []
                if reactions:
                    # Normalize potential dict items to emoji string
                    normalized_reactions = []
                    for r in reactions:
                        if isinstance(r, dict):
                            emoji = r.get('emoji') or r.get('text') or r.get('label')
                            if emoji:
                                normalized_reactions.append(emoji)
                        else:
                            normalized_reactions.append(r)

                    # NOUVEAU SYSTÈME : Utiliser le nouveau build_react_keyboard
                    from handlers.reaction_system import build_react_keyboard
                    reactions_keyboard = build_react_keyboard(normalized_reactions, post_id)
                    keyboard.extend(reactions_keyboard.inline_keyboard)
            except Exception as e:
                logger.warning(f"Reaction keyboard build error: {e}")

            # URL buttons (can be list of dicts or JSON string)
            buttons = post.get('buttons')
            if not buttons:
                buttons = context.user_data.get('current_post', {}).get('buttons', [])
                logger.info(f"Fallback URL buttons from current_post: {buttons}")
            try:
                if isinstance(buttons, str):
                    try:
                        buttons = json.loads(buttons)
                        logger.info(f"✅ URL buttons parsed from JSON: {buttons}")
                    except json.JSONDecodeError:
                        logger.warning(f"❌ Could not parse buttons JSON: {buttons}")
                        buttons = []
                for btn in buttons or []:
                    if isinstance(btn, dict):
                        text = btn.get('text') or btn.get('label') or btn.get('title')
                        url = btn.get('url') or btn.get('link')
                        if text and url:
                            keyboard.append([InlineKeyboardButton(text, url=url)])
            except Exception as e:
                logger.warning(f"URL buttons build error: {e}")

            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            logger.info(f"Inline keyboard for post {post_index+1}: rows={len(keyboard)}, has_reply_markup={reply_markup is not None}")

            # Ajout du texte custom si défini pour ce canal
            custom_usernames = context.user_data.get('custom_usernames', {})
            channel_username = post.get("channel")
            custom_text = custom_usernames.get(channel_username)
            if custom_text:
                caption = f"{caption}\n{custom_text}" if caption else custom_text

            # Cas 1 : Envoi avec thumbnail personnalisé
            if post_type in ("photo", "video", "document") and post.get('has_custom_thumbnail'):
                # logger.debug("Send with applied thumbnail")
                try:
                    # Envoyer avec le type approprié
                    sent_message = None
                    if post_type == "photo":
                        async def do_send():
                            return await context.bot.send_photo(chat_id=channel_to_send, photo=content, caption=caption, reply_markup=reply_markup)
                        sent_message = await try_send_with_retry(do_send, f"photo #{post_index+1}")
                    elif post_type == "video":
                        async def do_send():
                            return await context.bot.send_video(chat_id=channel_to_send, video=content, caption=caption, reply_markup=reply_markup)
                        sent_message = await try_send_with_retry(do_send, f"video #{post_index+1}")
                    elif post_type == "document":
                        async def do_send():
                            return await context.bot.send_document(chat_id=channel_to_send, document=content, caption=caption, reply_markup=reply_markup)
                        sent_message = await try_send_with_retry(do_send, f"document #{post_index+1}")
                    if sent_message:
                        logger.info(f"✅ Envoi réussi du post {post_index + 1} avec thumbnail personnalisé")
                        success_count += 1
                        
                        # NOUVEAU SYSTÈME : Sauvegarder le mapping post_id -> message
                        if reactions:  # Seulement si le post a des réactions
                            from handlers.reaction_system import save_post_mapping
                            save_post_mapping(post_id, channel_to_send, sent_message.message_id)
                            logger.debug(f"📍 Mapping sauvé: post_id={post_id} → msg_id={sent_message.message_id}")
                        
                        # Programmer l'auto-destruction si configurée
                        if auto_destruction_time and auto_destruction_time > 0:
                            schedule_auto_destruction(context, channel_to_send, sent_message.message_id, auto_destruction_time)
                except Exception as e:
                    logger.error(f"❌ Erreur envoi du post avec thumbnail personnalisé: {e}")
                    failed.append((post_index, post, str(e)))
                    continue
            else:
                # Cas 2 : Envoi simple (pas de thumbnail appliqué)
                try:
                    sent_message = None
                    if post_type == "photo":
                        async def do_send():
                            return await context.bot.send_photo(chat_id=channel_to_send, photo=content, caption=caption, reply_markup=reply_markup)
                        sent_message = await try_send_with_retry(do_send, f"photo #{post_index+1}")
                    elif post_type == "video":
                        async def do_send():
                            return await context.bot.send_video(chat_id=channel_to_send, video=content, caption=caption, reply_markup=reply_markup)
                        sent_message = await try_send_with_retry(do_send, f"video #{post_index+1}")
                    elif post_type == "document":
                        async def do_send():
                            return await context.bot.send_document(chat_id=channel_to_send, document=content, caption=caption, reply_markup=reply_markup)
                        sent_message = await try_send_with_retry(do_send, f"document #{post_index+1}")
                    elif post_type == "text":
                        async def do_send():
                            return await context.bot.send_message(chat_id=channel_to_send, text=content, reply_markup=reply_markup)
                        sent_message = await try_send_with_retry(do_send, f"texte #{post_index+1}")
                    if sent_message:
                        success_count += 1
                        
                        # NOUVEAU SYSTÈME : Sauvegarder le mapping post_id -> message  
                        if reactions:  # Seulement si le post a des réactions
                            from handlers.reaction_system import save_post_mapping
                            save_post_mapping(post_id, channel_to_send, sent_message.message_id)
                            logger.debug(f"📍 Mapping sauvé: post_id={post_id} → msg_id={sent_message.message_id}")
                        
                        if auto_destruction_time and auto_destruction_time > 0:
                            schedule_auto_destruction(context, channel_to_send, sent_message.message_id, auto_destruction_time)
                except Exception as e:
                    logger.error(f"❌ Erreur envoi du post simple: {e}")
                    failed.append((post_index, post, str(e)))
                    continue

            # Pause fixe anti-flood entre les envois
            try:
                await asyncio.sleep(1)
            except Exception:
                pass

        # Nettoyage: the posts that failed stay (with their channel), « 🚀 Send » tries them again
        if failed and not scheduled_post:
            context.user_data['posts'] = [p for _, p, _ in failed]
        else:
            context.user_data['posts'] = []
            context.user_data.pop('selected_channel', None)

        # Si c'était un post planifié, le supprimer de la base et annuler le job (pas s'il n'est pas parti)
        if scheduled_post and scheduled_post.get('id') and not failed:
            try:
                post_id = scheduled_post.get('id')
                logger.info(f"🗑️ Suppression du post planifié ID {post_id} après envoi immédiat")
                
                # Supprimer de la base de données
                import sqlite3
                from config import settings
                with sqlite3.connect(settings.db_config["path"]) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM posts WHERE id = ?", (post_id,))
                    conn.commit()
                    
                # Annuler le job planifié s'il existe
                scheduler_manager = get_scheduler_manager()
                if scheduler_manager:
                    job_id = f"post_{post_id}"
                    if scheduler_manager.scheduler.get_job(job_id):
                        scheduler_manager.scheduler.remove_job(job_id)
                        logger.info(f"✅ Job planifié {job_id} annulé")
                
                # Nettoyer le contexte
                context.user_data.pop('current_scheduled_post', None)
                context.user_data.pop('editing_post_id', None)
                
                logger.info(f"✅ Post planifié ID {post_id} supprimé avec succès après envoi immédiat")
                
            except Exception as cleanup_error:
                logger.error(f"❌ Erreur lors du nettoyage du post planifié: {cleanup_error}")

        # Message de confirmation récapitulatif (éviter les entités markdown problématiques)
        from i18n import get_user_lang, t
        lang = get_user_lang(update.effective_user.id if update.effective_user else None)
        if failed:
            success_message = t(lang, "send.partial", sent=success_count, total=len(posts), channel=channel_label)
        else:
            success_message = t(lang, "send.done", sent=success_count, channel=channel_label)
        if reordered:
            success_message += "\n\n" + t(lang, "send.reordered")
        if failed:
            success_message += "\n\n" + t(lang, "send.failed")
            for index, post, error in failed[:10]:
                label = post.get("filename") or (post.get("caption") or "").strip().split("\n")[0][:40] or post.get("type", "")
                success_message += f"\n• #{index + 1} {label}: {error[:120]}"
            if len(failed) > 10:
                success_message += f"\n• … +{len(failed) - 10}"
            if not scheduled_post:
                success_message += "\n\n" + t(lang, "send.failed_kept")

        # Ajouter info auto-destruction si configurée
        if auto_destruction_time and auto_destruction_time > 0:
            if auto_destruction_time < 3600:
                time_str = f"{auto_destruction_time // 60} minute(s)"
            elif auto_destruction_time < 86400:
                time_str = f"{auto_destruction_time // 3600} hour(s)"
            else:
                time_str = f"{auto_destruction_time // 86400} day(s)"
            success_message += f"\n\n⏰ Auto-destruction on: {time_str}"

        if update.message:
            await update.message.reply_text(
                success_message,
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
        elif hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.message.reply_text(
                success_message,
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )

        logger.info("✅ === FIN send_post_now - SUCCÈS ===")
        return MAIN_MENU
        
    except Exception as e:
        logger.error(f"❌ ERREUR dans send_post_now: {e}")
        logger.exception("Traceback complet:")
        
        error_message = "❌ Une erreur est survenue lors de l'envoi."
        
        if update.message:
            await update.message.reply_text(
                error_message,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
        elif hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.message.reply_text(
                error_message,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            
        return MAIN_MENU


async def handle_send_scheduled_post(update: Update, context: ContextTypes.DEFAULT_TYPE, post: dict):
    """Gère l'envoi d'un post planifié spécifique"""
    query = update.callback_query
    
    try:
        # ✅ VALIDATION AMÉLIORÉE DU CANAL
        channel = post.get('channel_username')
        if not channel:
            # Récupérer depuis la base de données si manquant
            try:
                with sqlite3.connect(settings.db_config["path"]) as conn:
                    cursor = conn.cursor()
                    # Build schema-aware channel name expression
                    cursor.execute("PRAGMA table_info(channels)")
                    _cols = [r[1] for r in cursor.fetchall()]
                    _has_name = 'name' in _cols
                    _has_title = 'title' in _cols
                    if _has_name and _has_title:
                        _name_expr = "COALESCE(c.name, c.title) AS name"
                    elif _has_name:
                        _name_expr = "c.name AS name"
                    elif _has_title:
                        _name_expr = "c.title AS name"
                    else:
                        _name_expr = "c.username AS name"
                    cursor.execute(f"""
                        SELECT c.username, {_name_expr}
                        FROM posts p
                        JOIN channels c ON p.channel_id = c.id
                        WHERE p.id = ?
                    """, (post.get('id'),))
                    result = cursor.fetchone()
                    if result:
                        channel = result[0]
                        if not channel.startswith('@'):
                            channel = f"@{channel}"
                        post['channel_username'] = channel
                        logger.info(f"✅ Canal récupéré depuis la DB: {channel}")
                    else:
                        raise ValueError("Canal introuvable dans la base de données")
            except Exception as e:
                logger.error(f"Erreur récupération canal depuis DB: {e}")
                raise ValueError("Impossible de déterminer le canal de destination")
        
        # Valider le format du canal
        if not channel.startswith('@') and not channel.startswith('-'):
            channel = f"@{channel}"
        
        logger.info(f"📍 Canal validé: {channel}")
        
        # Construire le clavier avec boutons URL si présents
        keyboard = []
        if post.get('buttons'):
            try:
                if isinstance(post['buttons'], str):
                    try:
                        buttons = json.loads(post['buttons'])
                    except json.JSONDecodeError:
                        logger.warning("Impossible de décoder les boutons JSON")
                        buttons = post['buttons']
                else:
                    buttons = post['buttons']
                    
                for btn in buttons:
                    keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
            except Exception as e:
                logger.error(f"Erreur lors de la conversion des boutons : {e}")

        # Envoyer selon le type
        sent_message = None
        post_type = post.get('type')
        content = post.get('content')
        caption = post.get('caption')
        
        # ✅ VALIDATION DU CONTENU
        if not content:
            raise ValueError("Contenu du post manquant")
            
        if not post_type:
            raise ValueError("Type de post manquant")
            
        keyboard_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        logger.info(f"📤 Envoi vers {channel} - Type: {post_type}")
        
        if post_type == "photo":
            reactions = post.get("reactions", [])
            # Build persistent reaction keyboard using 'react_' callbacks
            reply_markup = None
            if reactions:
                keyboard = []
                row = []
                pid = str(post.get("id") or post.get("post_id") or "0")
                for reaction in reactions:
                    row.append(InlineKeyboardButton(reaction, callback_data=f"react_{pid}_{reaction}"))
                    if len(row) == 4:
                        keyboard.append(row)
                        row = []
                if row:
                    keyboard.append(row)
                reply_markup = InlineKeyboardMarkup(keyboard)

            sent_message = await context.bot.send_photo(
                chat_id=channel,
                photo=content,
                caption=caption,
                reply_markup=reply_markup
            )
        elif post_type == "video":
            reactions = post.get("reactions", [])
            # Build persistent reaction keyboard using 'react_' callbacks
            reply_markup = None
            if reactions:
                keyboard = []
                row = []
                pid = str(post.get("id") or post.get("post_id") or "0")
                for reaction in reactions:
                    row.append(InlineKeyboardButton(reaction, callback_data=f"react_{pid}_{reaction}"))
                    if len(row) == 4:
                        keyboard.append(row)
                        row = []
                if row:
                    keyboard.append(row)
                reply_markup = InlineKeyboardMarkup(keyboard)

            sent_message = await context.bot.send_video(
                chat_id=channel,
                video=content,
                caption=caption,
                reply_markup=reply_markup
            )
        elif post_type == "document":
            reactions = post.get("reactions", [])
            # Build persistent reaction keyboard using 'react_' callbacks
            reply_markup = None
            if reactions:
                keyboard = []
                row = []
                pid = str(post.get("id") or post.get("post_id") or "0")
                for reaction in reactions:
                    row.append(InlineKeyboardButton(reaction, callback_data=f"react_{pid}_{reaction}"))
                    if len(row) == 4:
                        keyboard.append(row)
                        row = []
                if row:
                    keyboard.append(row)
                reply_markup = InlineKeyboardMarkup(keyboard)

            sent_message = await context.bot.send_document(
                chat_id=channel,
                document=content,
                caption=caption,
                reply_markup=reply_markup
            )
        elif post_type == "text":
            reactions = post.get("reactions", [])
            # Build persistent reaction keyboard using 'react_' callbacks
            reply_markup = None
            if reactions:
                keyboard = []
                row = []
                # Use post_id to identify this message's reactions consistently
                pid = str(post.get("id") or post.get("post_id") or "0")
                for reaction in reactions:
                    row.append(InlineKeyboardButton(reaction, callback_data=f"react_{pid}_{reaction}"))
                    if len(row) == 4:
                        keyboard.append(row)
                        row = []
                if row:
                    keyboard.append(row)
                reply_markup = InlineKeyboardMarkup(keyboard)

            sent_message = await context.bot.send_message(
                chat_id=channel,
                text=content,
                reply_markup=reply_markup
            )
        else:
            raise ValueError(f"Type de post non supporté: {post_type}")

        if sent_message:
            # Supprimer de la base de données
            with sqlite3.connect(settings.db_config["path"]) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM posts WHERE id = ?", (post['id'],))
                conn.commit()

            # Supprimer le job du scheduler
            job_id = f"post_{post['id']}"
            try:
                # Utiliser le scheduler manager au lieu de job_queue
                scheduler_manager = get_scheduler_manager()
                if scheduler_manager:
                    if scheduler_manager.scheduler.get_job(job_id):
                        scheduler_manager.scheduler.remove_job(job_id)
                        logger.info(f"Job {job_id} supprimé du scheduler après envoi")
                else:
                    logger.warning("Scheduler manager non disponible pour suppression après envoi")
            except Exception as e:
                logger.warning(f"Job {job_id} non supprimé du scheduler: {e}")

            await query.edit_message_text(
                f"✅ **Post envoyé avec succès !**\n\n"
                f"📍 Canal : {channel}\n"
                f"📝 Type : {post_type}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]]),
                parse_mode='Markdown'
            )

            # Nettoyer les données
            context.user_data.pop('current_scheduled_post', None)
            logger.info("✅ Post planifié envoyé avec succès")
            return MAIN_MENU
        else:
            raise RuntimeError("Échec de l'envoi du message")

    except Exception as e:
        logger.error(f"❌ Erreur lors de l'envoi du post planifié : {e}")
        await query.edit_message_text(
            f"❌ **Erreur lors de l'envoi**\n\n"
            f"Détails: {str(e)}\n\n"
            f"Vérifiez que le bot est administrateur du canal.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]]),
            parse_mode='Markdown'
        )
        return MAIN_MENU

# Fin du fichier - Ancienne fonction send_post_now dupliquée supprimée
# La fonction send_post_now complète est définie plus haut dans le fichier (ligne 1760)

# Fonction supprimée - thumbnails non supportés
async def process_thumbnail_and_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, post_index: int) -> bool:
    """
    Fonction désactivée - thumbnails supprimés
    """
    return False
async def handle_language_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gère les paramètres de langue"""
    query = update.callback_query
    await query.answer()
    
    from i18n import get_user_lang, t, SUPPORTED
    
    user_id = update.effective_user.id
    user_lang = get_user_lang(user_id, update.effective_user.language_code)
    
    # Récupérer la langue actuelle
    current_lang = get_user_lang(user_id, update.effective_user.language_code)
    current_lang_info = SUPPORTED.get(current_lang, SUPPORTED["en"])
    
    # Construire le clavier avec toutes les langues disponibles
    keyboard = []
    for lang_code, lang_info in SUPPORTED.items():
        flag = lang_info["flag"]
        name = lang_info["name"]
        # Ajouter un indicateur pour la langue actuelle
        if lang_code == current_lang:
            keyboard.append([InlineKeyboardButton(f"{flag} {name} ✅", callback_data=f"set_language_{lang_code}")])
        else:
            keyboard.append([InlineKeyboardButton(f"{flag} {name}", callback_data=f"set_language_{lang_code}")])
    
    # Bouton retour
    keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="custom_settings")])
    
    await query.edit_message_text(
        f"{t(user_lang, 'language.title')}\n\n"
        f"{t(user_lang, 'language.current').format(lang_flag=current_lang_info['flag'], lang_name=current_lang_info['name'])}\n\n"
        f"{t(user_lang, 'language.choose')}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    return SETTINGS


async def handle_set_language(update: Update, context: ContextTypes.DEFAULT_TYPE, lang_code: str) -> int:
    """Gère le changement de langue"""
    query = update.callback_query
    await query.answer()
    
    from i18n import set_user_lang, get_user_lang, t, SUPPORTED
    
    user_id = update.effective_user.id
    
    try:
        # Vérifier que la langue est supportée
        if lang_code not in SUPPORTED:
            await query.edit_message_text(
                "❌ Langue non supportée.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Back", callback_data="language_settings")
                ]])
            )
            return SETTINGS
        
        # Changer la langue de l'utilisateur
        set_user_lang(user_id, lang_code)
        
        # Récupérer les informations de la nouvelle langue
        lang_info = SUPPORTED[lang_code]
        
        # Utiliser la nouvelle langue pour le message de confirmation
        await query.edit_message_text(
            t(lang_code, 'language.success').format(
                lang_flag=lang_info['flag'], 
                lang_name=lang_info['name']
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Back", callback_data="custom_settings")
            ]])
        )
        
        return SETTINGS
        
    except Exception as e:
        logger.error(f"Erreur lors du changement de langue: {e}")
        await query.edit_message_text(
            "❌ Erreur lors du changement de langue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Back", callback_data="language_settings")
            ]])
        )
        return SETTINGS


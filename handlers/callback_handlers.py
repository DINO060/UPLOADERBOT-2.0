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

from utils.message_utils import MessageError, PostType
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
    WAITING_THUMBNAIL_RENAME_INPUT,
)
from utils.error_handler import handle_error
from utils.scheduler import SchedulerManager
from utils.scheduler_utils import send_scheduled_file
from config import settings


logger = logging.getLogger(__name__)

# Variable globale pour le scheduler manager
_global_scheduler_manager = None

# Fonction pour définir le scheduler manager global
def set_global_scheduler_manager(scheduler_manager):
    """Sets the global scheduler manager"""
    global _global_scheduler_manager
    _global_scheduler_manager = scheduler_manager
    logger.info("✅ Global scheduler manager set")

# Fonction pour récupérer le gestionnaire de scheduler
def get_scheduler_manager():
    """Gets the scheduler manager instance"""
    global _global_scheduler_manager
    
    try:
        # Priorité 1 : Utiliser le scheduler global s'il est défini
        if _global_scheduler_manager is not None:
            logger.info("✅ Scheduler manager retrieved from global variable")
            return _global_scheduler_manager
        
        # Priorité 2 : Essayer de récupérer depuis le module bot
        try:
            import sys
            if 'bot' in sys.modules:
                bot_module = sys.modules['bot']
                if hasattr(bot_module, 'application') and hasattr(bot_module.application, 'scheduler_manager'):
                    current_app = bot_module.application
                    logger.info("✅ Scheduler manager retrieved from bot module")
                    return current_app.scheduler_manager
        except Exception as e:
            logger.debug(f"Unable to retrieve from bot module: {e}")
        
        # Priorité 3 : Fallback - créer une instance temporaire mais avec warning
        logger.warning("⚠️ Scheduler manager not found - creating temporary instance")
        logger.warning("⚠️ Scheduled tasks will not work properly!")
        return SchedulerManager("UTC")
    except Exception as e:
        logger.error(f"Error retrieving scheduler manager: {e}")
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

# Mapping des actions vers les gestionnaires
CALLBACK_HANDLERS: Dict[str, HandlerType] = {
    "main_menu": "start",
    "create_publication": "create_publication",
    "planifier_post": "planifier_post",
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

    # Minimal logging; noisy debug removed

    try:
        # Récupération du callback data complet
        callback_data = query.data
        await query.answer()
        

        # Cas spécifiques pour les callbacks
        if callback_data == "main_menu":
            # Back to main menu
            keyboard = [
                [InlineKeyboardButton("📝 New post", callback_data="create_publication")],
                [InlineKeyboardButton("📅 Scheduled posts", callback_data="planifier_post")],
                [InlineKeyboardButton("📊 Statistics", callback_data="channel_stats")],
                [InlineKeyboardButton("⚙️ Settings", callback_data="settings")]
            ]
            
            await safe_edit_callback_message(
                query,
                "Main menu:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return MAIN_MENU
            
        elif callback_data == "create_publication":
            # Aller directement à la sélection des canaux pour créer une publication
            return await handle_create_publication(update, context)
            
        elif callback_data == "planifier_post":
            return await planifier_post(update, context)
        
        elif callback_data == "channel_stats":
            # Redirection vers le site TELE-SITE
            site_url = "http://localhost:8888"  # À remplacer par l'URL de production
            await safe_edit_callback_message(
                query,
                "📊 **Statistiques**\n\n"
                "Cliquez sur le bouton ci-dessous pour accéder à vos statistiques détaillées sur TELE-SITE.\n\n"
                "Connectez-vous avec votre compte Telegram pour voir les stats de vos canaux.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🌐 Ouvrir TELE-SITE", url=site_url)],
                    [InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]
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
                [InlineKeyboardButton("1 heure", callback_data="auto_dest_3600")],
                [InlineKeyboardButton("6 heures", callback_data="auto_dest_21600")],
                [InlineKeyboardButton("24 heures", callback_data="auto_dest_86400")],
                [InlineKeyboardButton("❌ Désactiver", callback_data="auto_dest_0")],
                [InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]
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
                    "✅ **Auto-destruction désactivée**\n\n"
                    "Vos messages ne seront pas supprimés automatiquement.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour au menu d'envoi", callback_data="main_menu")
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
                    time_str = f"{seconds // 3600} heure(s)"
                else:
                    time_str = f"{seconds // 86400} jour(s)"
                
                await safe_edit_callback_message(
                    query,
                    f"✅ **Auto-destruction configurée**\n\n"
                    f"⏰ Durée : {time_str}\n\n"
                    f"Vos prochains messages se supprimeront automatiquement après {time_str}.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour au menu d'envoi", callback_data="main_menu")
                    ]]),
                    parse_mode='Markdown'
                )
            
            return MAIN_MENU
            
        elif callback_data in ("schedule_today", "schedule_tomorrow", "schedule_overmorrow"):
            # Stocker le jour sélectionné et rediriger vers handle_schedule_time
            if callback_data == "schedule_today":
                context.user_data['schedule_day'] = 'today'
            elif callback_data == "schedule_tomorrow":
                context.user_data['schedule_day'] = 'tomorrow'
            else:
                context.user_data['schedule_day'] = 'overmorrow'
            jour = "today" if context.user_data['schedule_day'] == 'today' else ("tomorrow" if context.user_data['schedule_day'] == 'tomorrow' else "overmorrow")
            
            logger.info(f"📅 Selected day: {jour}")

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
            # Unification : utilise la même fonction send_post_now
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
            
        elif callback_data.startswith("set_timezone_"):
            timezone_code = callback_data.replace("set_timezone_", "")
            return await handle_set_timezone(update, context, timezone_code)
            
        elif callback_data == "manual_timezone":
            return await handle_manual_timezone(update, context)
            
        elif callback_data == "add_channel":
            return await add_channel_prompt(update, context)
            
        elif callback_data == "use_default_channel":
            return await use_default_channel(update, context)
            
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
            
        elif callback_data == "thumbnail_menu":
            # Gestion du menu thumbnail
            from .thumbnail_handler import handle_thumbnail_functions
            return await handle_thumbnail_functions(update, context)
            
        elif callback_data == "view_thumbnail":
            # Afficher le thumbnail actuel
            from .thumbnail_handler import handle_view_thumbnail
            return await handle_view_thumbnail(update, context)
            
        elif callback_data == "delete_thumbnail":
            # Supprimer le thumbnail
            from .thumbnail_handler import handle_delete_thumbnail
            return await handle_delete_thumbnail(update, context)
            
        elif callback_data == "add_thumbnail":
            # Ajouter un thumbnail
            from .thumbnail_handler import handle_add_thumbnail
            return await handle_add_thumbnail(update, context)
            
        elif callback_data == "confirm_large_thumbnail":
            # Confirmer l'utilisation d'un thumbnail volumineux
            temp_thumbnail = context.user_data.get('temp_thumbnail')
            if temp_thumbnail:
                # Utiliser le thumbnail temporaire même s'il est volumineux
                selected_channel = context.user_data.get('selected_channel', {})
                channel_username = selected_channel.get('username')
                user_id = update.effective_user.id
                
                if channel_username:
                    clean_username = normalize_channel_username(channel_username)
                    db_manager = DatabaseManager()
                    try:
                        success = db_manager.save_thumbnail(clean_username, user_id, temp_thumbnail)
                        if success:
                            context.user_data['waiting_for_channel_thumbnail'] = False
                            context.user_data.pop('temp_thumbnail', None)
                            await query.edit_message_text(
                                f"✅ Large thumbnail saved for @{clean_username}!",
                                reply_markup=InlineKeyboardMarkup([[ 
                                    InlineKeyboardButton("↩️ Back", callback_data=f"custom_channel_{clean_username}")
                                ]])
                            )
                            return SETTINGS
                    except Exception as e:
                        logger.error(f"Error while saving large thumbnail: {e}")

            await query.edit_message_text(
                "❌ Error while saving thumbnail.",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Back", callback_data="thumbnail_menu")
                ]])
            )
            return SETTINGS
            
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
                    InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
            
        elif callback_data == "delete_all_posts":
            # Supprimer tous les posts mais garder le canal sélectionné
            if 'posts' in context.user_data:
                context.user_data['posts'] = []
            # Ne pas supprimer le canal : context.user_data.pop('selected_channel', None)
            
            await query.edit_message_text(
                "🗑️ **Tous les posts supprimés**\n\n"
                "📤 Envoyez maintenant vos nouveaux fichiers :"
            )
            return WAITING_PUBLICATION_CONTENT
            
        elif callback_data.startswith("rename_post_"):
            post_index = callback_data.replace("rename_post_", "")
            return await handle_rename_post(update, context, int(post_index))
            
        elif callback_data.startswith("edit_file_"):
            post_index = callback_data.replace("edit_file_", "")
            return await show_edit_file_menu(update, context, int(post_index))
            
        elif callback_data.startswith("add_thumbnail_"):
            post_index = callback_data.replace("add_thumbnail_", "")
            return await handle_add_thumbnail_to_post_callback(update, context, int(post_index))
            
        elif callback_data.startswith("add_thumb_"):
            # Reproduit la logique du renambot: afficher MEDIA INFO puis attendre le nouveau nom
            try:
                parts = callback_data.split('_')
                post_index = int(parts[-1])
            except Exception:
                await query.answer("❌ Erreur de format", show_alert=True)
                return MAIN_MENU

            # Valider le post
            if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
                await query.answer("❌ Post introuvable", show_alert=True)
                return MAIN_MENU

            post = context.user_data['posts'][post_index]
            file_name = post.get('filename', 'unnamed_file')
            file_size = post.get('file_size', 0)
            extension = os.path.splitext(file_name)[1] or "Unknown"
            mime_type = post.get('mime_type', 'Unknown')
            dc_id = post.get('dc_id', 'N/A')

            # Vérifier qu'un thumbnail est défini pour le canal sélectionné
            channel_username = post.get('channel', context.user_data.get('selected_channel', {}).get('username'))
            clean_username = normalize_channel_username(channel_username)
            db_manager = DatabaseManager()
            thumbnail_data = db_manager.get_thumbnail(clean_username, update.effective_user.id)
            if not thumbnail_data:
                await query.answer("❌ Aucun thumbnail défini pour ce canal", show_alert=True)
                return MAIN_MENU

            info_card = (
                "📁 <b>MEDIA INFO</b>\n\n"
                f"📁 <b>FILE NAME:</b> <code>{file_name}</code>\n"
                f"🧩 <b>EXTENSION:</b> <code>{extension}</code>\n"
                f"📦 <b>FILE SIZE:</b> {file_size}\n"
                f"🪄 <b>MIME TYPE:</b> {mime_type}\n"
                f"🧭 <b>DC ID:</b> {dc_id}\n\n"
                "<b>PLEASE ENTER THE NEW FILENAME WITH EXTENSION AND REPLY THIS MESSAGE.</b>"
            )

            # Supprimer le message du menu 'Edit File' puis envoyer un nouveau message
            try:
                await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
            except Exception:
                pass

            ask_msg = await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=info_card,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_thumbnail_rename_{post_index}")
                ]])
            )

            # Stocker l'action et l'index pour le flux de renommage
            context.user_data['awaiting_thumb_rename'] = True
            context.user_data['current_post_index'] = post_index
            context.user_data['thumbnail_rename_prompt_message_id'] = ask_msg.message_id
            return WAITING_THUMBNAIL_RENAME_INPUT
            
        elif callback_data.startswith("add_reactions_"):
            # Gestion de l'ajout de réactions
            try:
                post_index = int(callback_data.split('_')[-1])
            except Exception as e:
                logger.error(f"Erreur parsing add_reactions_: {callback_data} - {e}")
                await query.answer("❌ Erreur de format")
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
                await query.answer("❌ Erreur de format")
                return MAIN_MENU
            from .reaction_functions import add_url_button_to_post
            return await add_url_button_to_post(update, context)
            
        elif callback_data.startswith("remove_reactions_"):
            # Gestion de la suppression de réactions
            try:
                post_index = int(callback_data.split('_')[-1])
            except Exception as e:
                logger.error(f"Erreur parsing remove_reactions_: {callback_data} - {e}")
                await query.answer("❌ Erreur de format")
                return MAIN_MENU
            from .reaction_functions import remove_reactions
            return await remove_reactions(update, context)
            
        elif callback_data.startswith("remove_url_buttons_"):
            # Gestion de la suppression de boutons URL
            try:
                post_index = int(callback_data.split('_')[-1])
            except Exception as e:
                logger.error(f"Erreur parsing remove_url_buttons_: {callback_data} - {e}")
                await query.answer("❌ Erreur de format")
                return MAIN_MENU
            from .reaction_functions import remove_url_buttons
            return await remove_url_buttons(update, context)
            
        elif callback_data.startswith("delete_post_"):
            # Gestion de la suppression de posts
            try:
                post_index = int(callback_data.split('_')[-1])
            except Exception as e:
                logger.error(f"Erreur parsing delete_post_: {callback_data} - {e}")
                await query.answer("❌ Erreur de format")
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
            # Annuler le prompt MEDIA INFO (Add Thumbnail + Rename)
            try:
                context.user_data.pop('awaiting_thumb_rename', None)
                context.user_data.pop('current_post_index', None)
                context.user_data.pop('pending_rename_filename', None)
                context.user_data.pop('force_document_for_video', None)
                prompt_id = context.user_data.pop('thumbnail_rename_prompt_message_id', None)
                if prompt_id:
                    try:
                        await context.bot.delete_message(chat_id=query.message.chat_id, message_id=prompt_id)
                    except Exception:
                        pass
                try:
                    await query.delete_message()
                except Exception:
                    pass
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

        # ✅ GESTIONNAIRE POUR LES RÉACTIONS DANS LE CANAL
        elif callback_data.startswith("reaction_"):
            try:
                logger.info(f"🎯 GESTIONNAIRE RÉACTIONS ACTIVÉ - Callback: {callback_data}")
                
                # Format: reaction_{post_index}_{reaction}
                parts = callback_data.split("_")
                logger.info(f"🎯 Parts du callback: {parts}")
                
                if len(parts) >= 3:
                    post_index = parts[1]
                    reaction = "_".join(parts[2:])  # En cas de réaction avec underscore
                    
                    logger.info(f"⭐ Réaction cliquée: {reaction} pour le post {post_index}")
                    logger.info(f"⭐ Utilisateur: {user_id}")
                    logger.info(f"⭐ Chat: {query.message.chat_id if query.message else 'N/A'}")
                    
                    # Incrémenter le compteur de réactions
                    if 'reaction_counts' not in context.bot_data:
                        context.bot_data['reaction_counts'] = {}
                        logger.info("📊 Initialisation du dictionnaire reaction_counts")
                    
                    reaction_key = f"{post_index}_{reaction}"
                    current_count = context.bot_data['reaction_counts'].get(reaction_key, 0)
                    context.bot_data['reaction_counts'][reaction_key] = current_count + 1
                    
                    # Afficher une notification à l'utilisateur
                    notification_text = f"👍 {reaction} +1"
                    await query.answer(notification_text)
                    logger.info(f"✅ Notification envoyée: {notification_text}")
                    
                    logger.info(f"✅ Réaction {reaction} comptée pour le post {post_index} (total: {current_count + 1})")
                    
                else:
                    logger.warning(f"Format de callback de réaction invalide: {callback_data}")
                    logger.warning(f"Nombre de parts: {len(parts)}")
                    await query.answer("❌ Erreur de format")
                    
            except Exception as e:
                logger.error(f"Erreur lors du traitement de la réaction: {e}")
                logger.exception("🔍 Traceback complet:")
                await query.answer("❌ Erreur lors du traitement")

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
                logger.error(f"❌ Erreur parsing callback non reconnu: {callback_data} - {e}")
        
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
        post_id = context.user_data.get('current_post_id')
        if not post_id:
            raise CallbackError("Aucune publication en cours")

        await query.edit_message_text(
            "🕒 Entrez la nouvelle date et heure (format: JJ/MM/AAAA HH:MM):"
        )
        context.user_data['waiting_for_time'] = True

    except CallbackError as e:
        logger.error(f"Erreur de modification d'heure: {str(e)}")
        await query.edit_message_text(f"❌ Erreur: {str(e)}")
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await query.edit_message_text("❌ Une erreur inattendue s'est produite")


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
        if context.user_data.get('confirming_cancel'):
            post_id = context.user_data.get('current_post_id')
            if not post_id:
                raise CallbackError("Aucune publication à annuler")

            db_manager = context.bot_data.get('db_manager')
            if not db_manager or not db_manager.delete_post(post_id):
                raise CallbackError("Impossible d'annuler la publication")

            await query.edit_message_text("✅ Publication annulée")
            context.user_data.pop('confirming_cancel', None)
        else:
            context.user_data['confirming_cancel'] = True
            await query.edit_message_text(
                "⚠️ Êtes-vous sûr de vouloir annuler cette publication ?",
                reply_markup=[[
                    InlineKeyboardButton("Oui", callback_data="annuler_publication"),
                    InlineKeyboardButton("Non", callback_data="retour")
                ]]
            )

    except CallbackError as e:
        logger.error(f"Erreur d'annulation: {str(e)}")
        await query.edit_message_text(f"❌ Erreur: {str(e)}")
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await query.edit_message_text("❌ Une erreur inattendue s'est produite")


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
        logger.error(f"Erreur d'aperçu: {str(e)}")
        await query.edit_message_text(f"❌ Erreur: {str(e)}")
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await query.edit_message_text("❌ Une erreur inattendue s'est produite")


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
            "Envoyez la photo ou la vidéo:"
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
            "Envoyez la photo ou la vidéo:"
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
                "❌ Format d'heure invalide. Utilisez HH:MM (ex: 14:30) ou HH (ex: 14).",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="schedule_send")
                ]])
            )
            return SCHEDULE_SEND

            # Validation de l'heure
        if not (0 <= hour <= 23) or not (0 <= minute <= 59):
            await update.message.reply_text(
                "❌ Heure invalide. Utilisez un format 24h (00:00 à 23:59).",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="schedule_send")
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
        
        target_date_local = local_now.replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0
            )

        # Si c'est pour demain, ajouter un jour
        if context.user_data['schedule_day'] == 'tomorrow':
            target_date_local += timedelta(days=1)

        # Vérifier que l'heure n'est pas dans le passé
        if target_date_local <= local_now:
            await update.message.reply_text(
                "❌ L'heure sélectionnée est déjà passée. Choisissez une heure future.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="schedule_send")
                ]])
            )
            return SCHEDULE_SEND

        success_count = 0
        channel_id = context.user_data.get("selected_channel", {}).get("id")

        # Si nous modifions un post existant
        if 'current_scheduled_post' in context.user_data:
            try:
                post = context.user_data['current_scheduled_post']
                post_id = post['id']
                # Mettre à jour la date planifiée en base
                with sqlite3.connect(settings.db_config["path"]) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE posts SET scheduled_time = ?, status = 'pending' WHERE id = ?",
                        (target_date_local.strftime('%Y-%m-%d %H:%M:%S'), post_id)
                    )
                    conn.commit()

                # Replanifier le job
                scheduler_manager = get_scheduler_manager()
                job_id = f"post_{post_id}"
                if scheduler_manager:
                    if scheduler_manager.scheduler.get_job(job_id):
                        scheduler_manager.scheduler.remove_job(job_id)
                    
                    def send_post_job(post_id=post_id):
                        import asyncio
                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)

                            async def send_post_async():
                                from utils.scheduler_utils import send_scheduled_file
                                post_dict = {"id": post_id}
                                await send_scheduled_file(post_dict, context.application)

                            loop.run_until_complete(send_post_async())
                            loop.close()
                        except Exception as job_error:
                            logger.error(f"❌ Erreur dans le job {post_id}: {job_error}")
                            logger.exception("Traceback:")

                    scheduler_manager.scheduler.add_job(
                        func=send_post_job,
                        trigger="date",
                        run_date=target_date_local,
                        id=job_id,
                        replace_existing=True
                    )
                    logger.info(f"✅ Job {job_id} replanifié pour {target_date_local}")
                else:
                    logger.error("❌ Scheduler manager introuvable pour replanifier")

                success_count += 1
            except Exception as edit_err:
                logger.error(f"❌ Erreur lors de la modification de l'heure: {edit_err}")
            
        else:
            # Planifier chaque nouveau post
            scheduler_manager = get_scheduler_manager()
            
            for post in posts:
                try:
                    # Sauvegarder le post en base de données
                    with sqlite3.connect(settings.db_config["path"]) as conn:
                        cursor = conn.cursor()

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
                        params = [channel_id]
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
                        insert_columns += ['scheduled_time', 'status']
                        params += [target_date_local.strftime('%Y-%m-%d %H:%M:%S'), 'pending']

                        placeholders = ', '.join(['?'] * len(params))
                        sql = f"INSERT INTO posts ({', '.join(insert_columns)}) VALUES ({placeholders})"
                        cursor.execute(sql, params)
                        post_id = cursor.lastrowid
                        conn.commit()

                    # Créer le job de planification
                    job_id = f"post_{post_id}"
                    
                    # ✅ CORRECTION : Créer une fonction wrapper synchrone simple
                    def send_post_job(post_id=post_id):
                        """Fonction wrapper pour envoyer un post planifié"""
                        import asyncio
                        try:
                            # Créer une nouvelle boucle pour le job
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            
                            # Fonction asynchrone pour envoyer le post
                            async def send_post_async():
                                from utils.scheduler_utils import send_scheduled_file
                                post_dict = {"id": post_id}
                                await send_scheduled_file(post_dict, context.application)
                            
                            # Exécuter la fonction asynchrone
                            loop.run_until_complete(send_post_async())
                            loop.close()
                            
                            logger.info(f"✅ Post {post_id} envoyé avec succès")
                            
                        except Exception as job_error:
                            logger.error(f"❌ Erreur dans le job {post_id}: {job_error}")
                            logger.exception("Traceback:")

                    # Planifier le job
                    if scheduler_manager:
                        scheduler_manager.scheduler.add_job(
                            func=send_post_job,
                            trigger="date",
                            run_date=target_date_local,
                            id=job_id,
                            replace_existing=True
                        )
                        logger.info(f"✅ Job {job_id} créé pour {target_date_local}")
                        success_count += 1
                    else:
                        logger.error("❌ Scheduler manager introuvable")

                except Exception as e:
                    logger.error(f"❌ Erreur lors de la planification du post: {e}")

        # Message de confirmation
        if success_count > 0:
            time_display = target_date_local.strftime("%H:%M")
            day_text = "today" if context.user_data['schedule_day'] == 'today' else "tomorrow"
            
            # Afficher le fuseau horaire utilisé
            timezone_display = user_timezone.split('/')[-1] if '/' in user_timezone else user_timezone
            
            await update.message.reply_text(
                f"✅ {success_count} file(s) scheduled for {day_text} at {time_display}\n"
                f"🌍 Timezone: {timezone_display} ({user_timezone})",
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

        post = context.user_data.get('current_scheduled_post')
        if not post:
            await query.edit_message_text(
                "❌ Publication introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
        return SCHEDULE_SEND

    except Exception as e:
        logger.error(f"Erreur dans handle_edit_time : {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de la modification de l'heure.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        keyboard = [
            [
                InlineKeyboardButton("✅ Oui, annuler", callback_data="confirm_cancel"),
                InlineKeyboardButton("❌ Non, garder", callback_data="retour")
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
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_confirm_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirme et supprime une publication planifiée"""
    query = update.callback_query
    await query.answer()
    
    try:
        if 'current_scheduled_post' not in context.user_data:
            await query.message.reply_text("❌ Aucun post planifié sélectionné.")
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
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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


async def use_default_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Utilise le canal par défaut du bot"""
    query = update.callback_query
    await query.answer()
    
    # Créer un canal temporaire par défaut
    user_id = update.effective_user.id
    db_manager = DatabaseManager()
    
    try:
        # Vérifier si un canal par défaut existe déjà
        default_channel = db_manager.get_channel_by_username("@default_channel", user_id)
        
        if not default_channel:
            # Créer le canal par défaut
            channel_id = db_manager.add_channel("Canal par défaut", "@default_channel", user_id)
            
        await query.edit_message_text(
            "✅ Canal par défaut activé!\n\n"
            "Vous pouvez maintenant créer des publications.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 Créer une publication", callback_data="create_publication"),
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de la création du canal par défaut: {e}")
        await query.edit_message_text(
            "❌ Erreur lors de la création du canal par défaut.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
    
    return MAIN_MENU


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
            "❌ Canal non trouvé.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
    
    # Récupérer les infos du thumbnail et du tag
    db_manager = DatabaseManager()
    thumbnail_exists = db_manager.get_thumbnail(channel_username, user_id) is not None
    tag = db_manager.get_channel_tag(channel_username, user_id)
    
    keyboard = [
        [InlineKeyboardButton("🖼️ Manage thumbnail", callback_data="thumbnail_menu")],
        [InlineKeyboardButton("🏷️ Add a hashtag", callback_data=f"edit_tag_{channel_username}")],
        [InlineKeyboardButton("↩️ Back", callback_data=f"channel_{channel_username}")]
    ]
    
    message_text = f"⚙️ **Settings for {channel['name']}**\n\n"
    message_text += f"🖼️ Thumbnail: {'✅ Set' if thumbnail_exists else '❌ Not set'}\n"
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
    
    keyboard = [
        [InlineKeyboardButton("🌐 Manage channels", callback_data="manage_channels")],
        [InlineKeyboardButton("🕐 Timezone", callback_data="timezone_settings")],
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
                "✅ Canal supprimé avec succès!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="manage_channels")
                ]])
            )
        else:
            await query.edit_message_text(
                "❌ Erreur lors de la suppression du canal.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="manage_channels")
                ]])
            )
    except Exception as e:
        logger.error(f"Erreur lors de la suppression du canal: {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="manage_channels")
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
    keyboard.append([InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")])
    
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
                "❌ Fuseau horaire invalide.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="timezone_settings")
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
                    InlineKeyboardButton("↩️ Retour aux paramètres", callback_data="settings")
                ]])
            )
        else:
            await query.edit_message_text(
                "❌ Erreur lors de la mise à jour du fuseau horaire.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="timezone_settings")
                ]])
            )
            
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du fuseau horaire : {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="timezone_settings")
            ]])
        )
    
    return SETTINGS


async def handle_manual_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Permet la saisie manuelle du fuseau horaire"""
    query = update.callback_query
    await query.answer()
    
    # Stocker qu'on attend une saisie de fuseau horaire
    context.user_data['waiting_for_timezone'] = True
    
    keyboard = [[InlineKeyboardButton("❌ Annuler", callback_data="timezone_settings")]]
    
    await query.edit_message_text(
        "✏️ Saisie manuelle du fuseau horaire\n\n"
        "Envoyez-moi votre fuseau horaire au format standard.\n\n"
        "Exemples :\n"
        "• Europe/Paris\n"
        "• America/New_York\n"
        "• Asia/Tokyo\n"
        "• Africa/Cairo\n\n"
        "💡 Vous pouvez trouver la liste complète sur:\n"
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
                [InlineKeyboardButton("🔄 Use default channel", callback_data="use_default_channel")],
                [InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")]
            ]
            
            message_text = (
                "⚠️ No channels configured\n\n"
                "To publish content, you must first configure a Telegram channel.\n"
                "You can either:\n"
                "• Add an existing channel where you are an admin\n"
                "• Use the default channel (temporary)"
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
        
        keyboard = [[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]]
        error_message = "❌ Une erreur est survenue lors de la récupération des canaux."
        
        await query.edit_message_text(
            error_message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return MAIN_MENU


async def planifier_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche les publications planifiées par chaîne."""
    try:
        # Initialiser le gestionnaire de base de données
        db_manager = DatabaseManager()
        
        with sqlite3.connect(settings.db_config["path"]) as conn:
            cursor = conn.cursor()
            # Récupérer uniquement les posts en attente, avec une date planifiée, pour l'utilisateur courant
            # et être compatible avec schémas 'type' legacy ou 'post_type' récent
            cursor.execute(
                """
                SELECT p.id,
                       COALESCE(NULLIF(p.post_type, ''), p.type) AS post_type,
                       p.content,
                       p.caption,
                       p.scheduled_time,
                       c.name,
                       c.username
                FROM posts p
                JOIN channels c ON p.channel_id = c.id
                WHERE p.status = 'pending'
                  AND p.scheduled_time IS NOT NULL
                  AND c.user_id = ?
                ORDER BY p.scheduled_time
                """,
                (update.effective_user.id,)
            )
            scheduled_posts = cursor.fetchall()

        if not scheduled_posts:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    "❌ Aucun post planifié trouvé.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                    ]])
                )
            else:
                await update.message.reply_text("❌ Aucun post planifié trouvé.")
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

        # Trier par heure planifiée et ne garder que le premier
        try:
            filtered_posts.sort(key=lambda p: datetime.strptime(p[4], '%Y-%m-%d %H:%M:%S'))
            if len(filtered_posts) > 1:
                filtered_posts = filtered_posts[:1]
        except Exception:
            if len(filtered_posts) > 1:
                filtered_posts = filtered_posts[:1]

        if not filtered_posts:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    "❌ No scheduled posts found.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")]])
                )
            else:
                await update.message.reply_text("❌ No scheduled posts found.")
            return MAIN_MENU

        keyboard = []
        message = "📅 Scheduled posts:\n\n"

        for post in filtered_posts:
            post_id, post_type, content, caption, scheduled_time, channel_name, channel_username = post
            button_text = f"{scheduled_time} - {channel_name} (@{channel_username})"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"show_post_{post_id}")])
            message += f"• {button_text}\n"

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
            cursor.execute("""
                SELECT p.id, p.type, p.content, p.caption, p.scheduled_time, c.name, c.username
                FROM posts p
                JOIN channels c ON p.channel_id = c.id
                WHERE p.id = ?
            """, (post_id,))
            post_data = cursor.fetchone()

        if not post_data:
            await query.edit_message_text(
                "❌ Publication introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        scheduled_time = datetime.strptime(post_data[4], '%Y-%m-%d %H:%M:%S')

        post = {
            'id': post_data[0],
            'type': post_data[1],
            'content': post_data[2],
            'caption': post_data[3],
            'scheduled_time': post_data[4],
            'channel_name': post_data[5],
            'channel_username': post_data[6],
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
            if post['type'] == "photo":
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=post['content'],
                    caption=post.get('caption'),
                    reply_markup=None
                )
            elif post['type'] == "video":
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=post['content'],
                    caption=post.get('caption'),
                    reply_markup=None
                )
            elif post['type'] == "document":
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=post['content'],
                    caption=post.get('caption'),
                    reply_markup=None
                )
            elif post['type'] == "text":
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=post['content'],
                    reply_markup=None
                )
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du contenu : {e}")

        # Récupérer le fuseau horaire de l'utilisateur
        user_id = update.effective_user.id
        db_manager = DatabaseManager()
        user_timezone = db_manager.get_user_timezone(user_id) or "UTC"
        local_tz = pytz.timezone(user_timezone)
        
        # Convertir l'heure en local
        utc_time = scheduled_time.replace(tzinfo=pytz.UTC)
        local_time = utc_time.astimezone(local_tz)

        message = (
            f"📝 Scheduled post:\n\n"
            f"📅 Date: {local_time.strftime('%d/%m/%Y')}\n"
            f"⏰ Time: {local_time.strftime('%H:%M')} ({user_timezone})\n"
            f"🌐 UTC time: {scheduled_time.strftime('%H:%M')}\n"
            f"📍 Channel: {post['channel_name']}\n"
            f"📎 Type: {post['type']}\n"
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
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def show_edit_file_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, post_index: int) -> int:
    """Affiche le menu d'édition de fichier avec les 3 options"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    try:
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            from utils.message_utils import safe_edit_message_text
            await safe_edit_message_text(
                query,
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        post = context.user_data['posts'][post_index]
        
        # Menu d'édition exactement comme dans l'image
        keyboard = [
            [InlineKeyboardButton("✏️ Rename", callback_data=f"rename_post_{post_index}")],
            [InlineKeyboardButton("🖼️ Add Thumbnail", callback_data=f"add_thumbnail_{post_index}")],
            [InlineKeyboardButton("🖼️ Add Thumbnail + Rename", callback_data=f"add_thumb_{post_index}")]
        ]
        
        from utils.message_utils import safe_edit_message_text
        await safe_edit_message_text(
            query,
            f"✏️ **Édition du fichier {post_index + 1}**\n\n"
            f"Type: {post['type']}\n"
            f"Choisissez une action :",
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
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
            f"✏️ **Renommer le fichier {post_index + 1}**\n\n"
            "Envoyez le nouveau nom/titre pour ce fichier :"
        )
        ask_msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=prompt_text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_rename_{post_index}")
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


async def handle_add_thumbnail_to_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, post_index: int) -> int:
    """Ajoute un thumbnail à un post via callback"""
    query = update.callback_query
    
    try:
        # Envoyer un message de progression immédiat
        progress = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"⏳ Traitement du post {post_index + 1}… Téléchargement en cours…"
        )
        # Supprimer le message du menu 'Edit File' pour nettoyer l'UI
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
        except Exception:
            pass
        # Stocker l'ID du message actuel pour le supprimer plus tard (legacy)
        context.user_data['thumbnail_prompt_message_id'] = query.message.message_id
        
        # Utiliser la nouvelle fonction centralisée pour tout le traitement
        logger.info(f"🎯 handle_add_thumbnail_to_post_callback appelé pour post {post_index + 1}")
        
        # Préparer le renommage à partir de la légende et forcer l'envoi en document
        try:
            post = context.user_data.get('posts', [])[post_index]
            context.user_data['force_document_for_video'] = True
            original_filename = post.get('filename')
            caption_text = (post.get('caption') or "").strip()
            if caption_text:
                # Aplatis et nettoie la légende, enlève les @mentions
                import re, os
                flat_caption = " ".join(caption_text.splitlines()).strip()
                flat_caption = re.sub(r'(?:(?<=\s)|^)(@[A-Za-z0-9_]{5,32})\b', ' ', flat_caption)
                flat_caption = re.sub(r'\s+', ' ', flat_caption).strip()
                flat_caption = flat_caption.replace('/', '-').replace('\\', '-').replace(':', '-')
                ext = os.path.splitext(original_filename or "")[1]
                if not ext and (post.get('type') == 'video'):
                    ext = ".mp4"
                new_name = flat_caption or (original_filename or f"file_{post_index}")
                if ext and not new_name.lower().endswith(ext.lower()):
                    new_name = f"{new_name}{ext}"
                context.user_data['pending_rename_filename'] = new_name
            else:
                context.user_data.pop('pending_rename_filename', None)
        except Exception as prep_err:
            logger.warning(f"Préparation Add Thumbnail (rename/force doc) ignorée: {prep_err}")
        
        # Appeler la fonction centralisée qui fait tout le travail
        success = await process_thumbnail_and_upload(update, context, post_index)
        
        if success:
            logger.info(f"✅ Traitement thumbnail réussi pour post {post_index + 1}")
            # Supprimer le message de progression
            try:
                await context.bot.delete_message(chat_id=progress.chat_id, message_id=progress.message_id)
            except Exception:
                pass
            return WAITING_PUBLICATION_CONTENT
        else:
            logger.error(f"❌ Échec du traitement thumbnail pour post {post_index + 1}")
            try:
                await context.bot.edit_message_text(chat_id=progress.chat_id, message_id=progress.message_id, text="❌ Erreur lors du traitement.")
            except Exception:
                pass
            return MAIN_MENU
            
    except Exception as e:
        logger.error(f"Erreur dans handle_add_thumbnail_to_post_callback: {e}")
        try:
            await context.bot.send_message(chat_id=query.message.chat_id, text="❌ Une erreur est survenue lors de l'ajout du thumbnail.")
        except Exception:
            pass
        await safe_edit_callback_message(
            query,
            "❌ Une erreur est survenue lors de l'ajout du thumbnail.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
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
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]])
        )
        return MAIN_MENU

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
            posts = [scheduled_post]
            channel = scheduled_post.get('channel', '@default_channel')  # Correction: canal par défaut fixe
        else:
            posts = context.user_data.get("posts", [])
            # logger.debug(f"Posts to send: {len(posts)}")
            
            if not posts:
                # No posts to send
                if update.message:
                    await update.message.reply_text(
                        "❌ Il n'y a pas de fichiers à envoyer.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                        ]])
                    )
                elif hasattr(update, 'callback_query') and update.callback_query:
                    await update.callback_query.message.reply_text(
                        "❌ Il n'y a pas de fichiers à envoyer.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                        ]])
                    )
                return MAIN_MENU
            
            # Récupérer le canal du premier post ou du canal sélectionné
            selected_channel = context.user_data.get('selected_channel', {})
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
        # Utilitaires anti-flood/timeout
        import asyncio, re, os

        async def try_send_with_retry(coro_factory, description: str):
            max_attempts = 3
            attempt = 1
            wait_seconds = 0
            # Cap configurable pour le flood-wait (par défaut 2s)
            try:
                flood_cap = int(os.getenv('MAX_FLOOD_WAIT_SECONDS', '2'))
            except Exception:
                flood_cap = 2
            while attempt <= max_attempts:
                if wait_seconds > 0:
                    try:
                        await asyncio.sleep(wait_seconds)
                    except Exception:
                        pass
                try:
                    return await coro_factory()
                except Exception as send_err:
                    err = str(send_err)
                    # Flood control with retry window
                    match = re.search(r"Retry in (\d+) seconds", err)
                    if "Flood control exceeded" in err and match:
                        reported = int(match.group(1))
                        wait_seconds = min(reported, flood_cap)
                        logger.warning(f"⏳ Flood control – attente {wait_seconds}s (capée; reporté {reported}s) avant nouvelle tentative ({description})")
                        attempt += 1
                        continue
                    # Generic timeout handling
                    if "Timed out" in err or "timeout" in err.lower():
                        wait_seconds = min(2 * attempt, flood_cap)
                        logger.warning(f"⏳ Timeout – tentative {attempt+1}/{max_attempts} après {wait_seconds}s ({description})")
                        attempt += 1
                        continue
                    # Autres erreurs: ne pas insister
                    raise
        for post_index, post in enumerate(posts):
            # logger.debug(f"Sending post {post_index + 1}/{len(posts)}")
            
            post_type = post.get("type")
            content = post.get("content")
            caption = post.get("caption") or ""
            filename = post.get("filename")
            thumbnail = post.get('thumbnail')

            # logger.debug(f"Post type: {post_type} | thumb: {thumbnail}")

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
                            return await context.bot.send_photo(chat_id=channel_to_send, photo=content, caption=caption)
                        sent_message = await try_send_with_retry(do_send, f"photo #{post_index+1}")
                    elif post_type == "video":
                        async def do_send():
                            return await context.bot.send_video(chat_id=channel_to_send, video=content, caption=caption)
                        sent_message = await try_send_with_retry(do_send, f"video #{post_index+1}")
                    elif post_type == "document":
                        async def do_send():
                            return await context.bot.send_document(chat_id=channel_to_send, document=content, caption=caption)
                        sent_message = await try_send_with_retry(do_send, f"document #{post_index+1}")
                    if sent_message:
                        logger.info(f"✅ Envoi réussi du post {post_index + 1} avec thumbnail personnalisé")
                        success_count += 1
                        # Programmer l'auto-destruction si configurée
                        if auto_destruction_time and auto_destruction_time > 0:
                            schedule_auto_destruction(context, channel_to_send, sent_message.message_id, auto_destruction_time)
                except Exception as e:
                    logger.error(f"❌ Erreur envoi du post avec thumbnail personnalisé: {e}")
                    continue
            else:
                # Cas 2 : Envoi simple (pas de thumbnail appliqué)
                try:
                    sent_message = None
                    if post_type == "photo":
                        async def do_send():
                            return await context.bot.send_photo(chat_id=channel_to_send, photo=content, caption=caption)
                        sent_message = await try_send_with_retry(do_send, f"photo #{post_index+1}")
                    elif post_type == "video":
                        async def do_send():
                            return await context.bot.send_video(chat_id=channel_to_send, video=content, caption=caption)
                        sent_message = await try_send_with_retry(do_send, f"video #{post_index+1}")
                    elif post_type == "document":
                        async def do_send():
                            return await context.bot.send_document(chat_id=channel_to_send, document=content, caption=caption)
                        sent_message = await try_send_with_retry(do_send, f"document #{post_index+1}")
                    elif post_type == "text":
                        async def do_send():
                            return await context.bot.send_message(chat_id=channel_to_send, text=content)
                        sent_message = await try_send_with_retry(do_send, f"texte #{post_index+1}")
                    if sent_message:
                        success_count += 1
                        if auto_destruction_time and auto_destruction_time > 0:
                            schedule_auto_destruction(context, channel_to_send, sent_message.message_id, auto_destruction_time)
                except Exception as e:
                    logger.error(f"❌ Erreur envoi du post simple: {e}")
                    continue

            # Pause fixe anti-flood entre les envois
            try:
                await asyncio.sleep(1)
            except Exception:
                pass

        # Nettoyage et petit repos anti-flood avant le message de succès
        context.user_data['posts'] = []
        context.user_data.pop('selected_channel', None)

        # Message de confirmation récapitulatif
        success_message = f"✅ **Envoi réussi !**\n\n{success_count} post(s) envoyé(s) vers {channel_label}"

        # Ajouter info auto-destruction si configurée
        if auto_destruction_time and auto_destruction_time > 0:
            if auto_destruction_time < 3600:
                time_str = f"{auto_destruction_time // 60} minute(s)"
            elif auto_destruction_time < 86400:
                time_str = f"{auto_destruction_time // 3600} heure(s)"
            else:
                time_str = f"{auto_destruction_time // 86400} jour(s)"
            success_message += f"\n\n⏰ **Auto-destruction activée** : {time_str}"

        if update.message:
            await update.message.reply_text(
                success_message,
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]]),
                parse_mode='Markdown'
            )
        elif hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.message.reply_text(
                success_message,
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]]),
                parse_mode='Markdown'
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
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
        elif hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.message.reply_text(
                error_message,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
                    cursor.execute("""
                        SELECT c.username, c.name
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
            from mon_bot_telegram.handlers.reaction_functions import create_reactions_keyboard
            reply_markup = create_reactions_keyboard(reactions) if reactions else None

            sent_message = await context.bot.send_photo(
                chat_id=channel,
                photo=content,
                caption=caption,
                reply_markup=reply_markup
            )
        elif post_type == "video":
            reactions = post.get("reactions", [])
            from mon_bot_telegram.handlers.reaction_functions import create_reactions_keyboard
            reply_markup = create_reactions_keyboard(reactions) if reactions else None

            sent_message = await context.bot.send_video(
                chat_id=channel,
                video=content,
                caption=caption,
                reply_markup=reply_markup
            )
        elif post_type == "document":
            reactions = post.get("reactions", [])
            from mon_bot_telegram.handlers.reaction_functions import create_reactions_keyboard
            reply_markup = create_reactions_keyboard(reactions) if reactions else None

            sent_message = await context.bot.send_document(
                chat_id=channel,
                document=content,
                caption=caption,
                reply_markup=reply_markup
            )
        elif post_type == "text":
            reactions = post.get("reactions", [])
            from mon_bot_telegram.handlers.reaction_functions import create_reactions_keyboard
            reply_markup = create_reactions_keyboard(reactions) if reactions else None

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
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]]),
            parse_mode='Markdown'
        )
        return MAIN_MENU

async def handle_send_normal_posts(update: Update, context: ContextTypes.DEFAULT_TYPE, posts: list):
    """Gère l'envoi de posts normaux (non planifiés)"""
    query = update.callback_query
    
    try:
        # Récupérer les paramètres d'envoi avec validation améliorée
        selected_channel = context.user_data.get('selected_channel', {})
        channel = posts[0].get("channel") or selected_channel.get('username', '@default_channel')
        auto_destruction_time = context.user_data.get('auto_destruction_time', 0)
        
        # ✅ VALIDATION DU CANAL
        if not channel or channel == '@default_channel':
            # Essayer de récupérer un canal depuis la base de données
            user_id = update.effective_user.id
            repo_channels = list_user_channels(user_id)
            if repo_channels:
                channel = (repo_channels[0].get('username') or '@default_channel')
                if not channel.startswith('@'):
                    channel = f"@{channel}"
            else:
                logger.warning("Aucun canal configuré, utilisation du canal par défaut")
        
        # Valider le format du canal
        if not channel.startswith('@') and not channel.startswith('-'):
            channel = f"@{channel}"
        
        logger.info(f"📍 Envoi vers le canal: {channel}")
        
        sent_count = 0
        for post_index, post in enumerate(posts):
            try:
                post_type = post.get('type')
                content = post.get('content')
                caption = post.get('caption', '')
                
                # ✅ VALIDATION DU CONTENU
                if not content:
                    logger.warning(f"Post {post_index + 1} ignoré: contenu manquant")
                    continue
                    
                if not post_type:
                    logger.warning(f"Post {post_index + 1} ignoré: type manquant")
                    continue
                
                logger.info(f"📤 Envoi du post {post_index + 1}/{len(posts)} - Type: {post_type}")
                
                # ✅ CONSTRUIRE LE CLAVIER AVEC RÉACTIONS ET BOUTONS
                keyboard = []
                
                # DEBUG: Afficher le contenu complet du post
                logger.info(f"🔍 DEBUG POST {post_index + 1}:")
                logger.info(f"   📝 Type: {post.get('type')}")
                logger.info(f"   📄 Content: {str(post.get('content'))[:50]}...")
                logger.info(f"   📝 Caption: {post.get('caption', 'None')}")
                logger.info(f"   ⭐ Réactions: {post.get('reactions', 'None')}")
                logger.info(f"   🔘 Boutons: {post.get('buttons', 'None')}")
                logger.info(f"   🔍 Type réactions: {type(post.get('reactions'))}")
                logger.info(f"   🔍 Type boutons: {type(post.get('buttons'))}")
                
                # Ajouter les réactions en ligne
                reactions = post.get('reactions', [])
                logger.info(f"🎯 Traitement réactions pour post {post_index + 1}: {reactions}")
                
                if reactions:
                    # Si c'est une string JSON, la parser
                    if isinstance(reactions, str):
                        try:
                            reactions = json.loads(reactions)
                            logger.info(f"✅ Réactions parsées depuis JSON: {reactions}")
                        except json.JSONDecodeError:
                            logger.warning(f"❌ Impossible de parser les réactions JSON: {reactions}")
                            reactions = []
                    
                    if reactions:
                        current_row = []
                        for reaction in reactions:
                            logger.info(f"⭐ Ajout réaction: {reaction}")
                            current_row.append(InlineKeyboardButton(
                                reaction,
                                callback_data=f"reaction_{post_index}_{reaction}"
                            ))
                            # 4 réactions par ligne maximum
                            if len(current_row) == 4:
                                keyboard.append(current_row)
                                current_row = []
                        # Ajouter la dernière ligne si elle n'est pas vide
                        if current_row:
                            keyboard.append(current_row)
                
                # Ajouter les boutons URL
                buttons = post.get('buttons', [])
                logger.info(f"🎯 Traitement boutons pour post {post_index + 1}: {buttons}")
                
                if buttons:
                    # Si c'est une string JSON, la parser
                    if isinstance(buttons, str):
                        try:
                            buttons = json.loads(buttons)
                            logger.info(f"✅ Boutons parsés depuis JSON: {buttons}")
                        except json.JSONDecodeError:
                            logger.warning(f"❌ Impossible de parser les boutons JSON: {buttons}")
                            buttons = []
                    
                    for button in buttons:
                        if isinstance(button, dict) and 'text' in button and 'url' in button:
                            logger.info(f"🔘 Ajout bouton: {button['text']} → {button['url']}")
                            keyboard.append([InlineKeyboardButton(button['text'], url=button['url'])])
                
                # Créer le markup si on a des boutons/réactions
                reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
                
                logger.info(f"🎯 Post {post_index + 1} - Réactions: {len(reactions) if isinstance(reactions, list) else 0}, Boutons: {len(buttons) if isinstance(buttons, list) else 0}")
                logger.info(f"🎯 Clavier créé: {len(keyboard)} ligne(s) de boutons")
                logger.info(f"🎯 Reply markup créé: {reply_markup is not None}")
                if reply_markup:
                    logger.info(f"🎯 Contenu du reply_markup: {reply_markup.inline_keyboard}")
                
                sent_message = None
                logger.info(f"📤 Envoi vers {channel} avec reply_markup: {reply_markup is not None}")
                
                if post_type == "photo":
                    sent_message = await context.bot.send_photo(
                        chat_id=channel,
                        photo=content,
                        caption=caption,
                        reply_markup=reply_markup
                    )
                elif post_type == "video":
                    sent_message = await context.bot.send_video(
                        chat_id=channel,
                        video=content,
                        caption=caption,
                        reply_markup=reply_markup
                    )
                elif post_type == "document":
                    sent_message = await context.bot.send_document(
                        chat_id=channel,
                        document=content,
                        caption=caption,
                        reply_markup=reply_markup
                    )
                elif post_type == "text":
                    sent_message = await context.bot.send_message(
                        chat_id=channel,
                        text=content,
                        reply_markup=reply_markup
                    )
                else:
                    logger.warning(f"Type de post non supporté: {post_type}")
                    continue
                
                if sent_message:
                    sent_count += 1
                    logger.info(f"✅ Post {post_index + 1} envoyé avec succès")
                    
                    # Programmer l'auto-destruction si configurée
                    if auto_destruction_time > 0:
                        schedule_auto_destruction(context, channel, sent_message.message_id, auto_destruction_time)
                
            except Exception as e:
                logger.error(f"Erreur envoi post {post_index + 1}: {e}")
                continue

        # Nettoyer les données après envoi
        context.user_data['posts'] = []
        context.user_data.pop('selected_channel', None)
        context.user_data.pop('auto_destruction_time', None)
        
        # Message de confirmation
        success_message = f"✅ **Envoi terminé !**\n\n"
        success_message += f"📊 {sent_count}/{len(posts)} post(s) envoyé(s)\n"
        success_message += f"📍 Canal : {channel}"
        
        if auto_destruction_time > 0:
            if auto_destruction_time < 3600:
                time_str = f"{auto_destruction_time // 60} minute(s)"
            elif auto_destruction_time < 86400:
                time_str = f"{auto_destruction_time // 3600} heure(s)"
            else:
                time_str = f"{auto_destruction_time // 86400} jour(s)"
            success_message += f"\n\n⏰ Auto-destruction : {time_str}"
        
        await query.edit_message_text(
            success_message,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]]),
            parse_mode='Markdown'
        )
        
        logger.info("✅ === FIN handle_send_normal_posts - SUCCÈS ===")
        return MAIN_MENU
        
    except Exception as e:
        logger.error(f"❌ Erreur dans handle_send_normal_posts: {e}")
        await query.edit_message_text(
            f"❌ **Erreur lors de l'envoi**\n\n"
            f"Détails: {str(e)}\n\n"
            f"Vérifiez que le bot est administrateur du canal.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]]),
            parse_mode='Markdown'
        )
        return MAIN_MENU

# Fin du fichier - Ancienne fonction send_post_now dupliquée supprimée
# La fonction send_post_now complète est définie plus haut dans le fichier (ligne 1760)

async def process_thumbnail_and_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, post_index: int) -> bool:
    """
    Fonction centralisée pour traiter l'ajout de thumbnail ET le renommage à un post.
    """
    query = update.callback_query
    user_id = update.effective_user.id
    temp_files = []
        
    try:
        # Récupérer le post et ses infos
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            logger.error("❌ Post introuvable dans le contexte")
            return False
            
        post = context.user_data['posts'][post_index]
        post_type = post.get('type')
        content = post.get('content')
        caption = post.get('caption', '')
        
        # IMPORTANT: Récupérer le nouveau nom s'il existe
        new_filename = context.user_data.get('pending_rename_filename')
        if not new_filename:
            new_filename = post.get('filename', f"file_{post_index}")
        # Sécuriser l'extension pour les vidéos afin d'assurer la lecture inline
        try:
            if post.get('type') == 'video':
                original_ext = os.path.splitext(post.get('filename') or "")[1]
                if not original_ext:
                    original_ext = ".mp4"
                if not new_filename.lower().endswith(original_ext.lower()):
                    new_filename += original_ext
        except Exception:
            pass
            
        # Récupérer le canal et le thumbnail
        channel_username = post.get('channel', context.user_data.get('selected_channel', {}).get('username'))
        clean_username = normalize_channel_username(channel_username)
        
        # Récupérer le thumbnail
        db_manager = DatabaseManager()
        thumbnail_data = db_manager.get_thumbnail(clean_username, user_id)
        
        if not thumbnail_data:
            logger.error(f"❌ Aucun thumbnail trouvé pour @{clean_username}")
            return False
        
        # Récupérer ou télécharger le fichier original (robuste)
        file_path = None
        local_path = post.get('local_path')
        if local_path and os.path.exists(local_path) and os.path.isfile(local_path) and os.path.getsize(local_path) > 0 and os.access(local_path, os.R_OK):
            file_path = local_path
        else:
            try:
                # Tentative Bot API (rapide, mais limité)
                file_obj = await context.bot.get_file(content)
                file_path = await file_obj.download_to_drive()
                if not file_path or not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                    raise Exception("Fichier téléchargé invalide via API Bot")
                temp_files.append(file_path)
            except Exception as e:
                err = str(e)
                # Fallback vers Pyrogram pour gros fichiers ou références expirées
                if ("File is too big" in err or "file is too big" in err.lower() or
                    "FILE_REFERENCE_EXPIRED" in err or "file reference" in err.lower()):
                    from utils.clients import client_manager
                    client_info = await client_manager.get_best_client(100*1024*1024, "download")
                    client = client_info["client"]
                    import time
                    file_path = await client.download_media(content, file_name=f"temp_{user_id}_{int(time.time())}")
                    if not file_path or not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                        raise Exception("Fichier téléchargé invalide via client avancé")
                    temp_files.append(file_path)
                else:
                    raise
        
        # Préparer le thumbnail avec fallback fiable (chemin local si valide, sinon file_id)
        if isinstance(thumbnail_data, dict):
            local_thumb_path = thumbnail_data.get('local_path')
            file_id_thumb = thumbnail_data.get('file_id')
            thumb_to_use = local_thumb_path if (local_thumb_path and os.path.exists(local_thumb_path)) else file_id_thumb
        else:
            thumb_to_use = thumbnail_data
        
        # IMPORTANT: Utiliser send_file_smart avec le nouveau nom
        from .media_handler import send_file_smart
        
        # Forcer l'envoi en document pour la vidéo si demandé (cas Add Thumbnail + Rename)
        # OU pour tous les types si force_document_for_video est True (cas Add Thumbnail simple)
        force_doc = (post_type == "document") or (bool(context.user_data.get('force_document_for_video')))

        # Pour remplacer la légende par le nom de fichier, on définit la caption au nouveau nom
        # et on ajoute le tag du canal sur la même ligne si disponible
        name_caption = f"{new_filename}"
        try:
            db_mgr_for_tag = db_manager if 'db_manager' in locals() else DatabaseManager()
            tag = db_mgr_for_tag.get_channel_tag(clean_username, user_id)
            if tag and str(tag).strip():
                name_caption = f"{new_filename} {str(tag).strip()}"
        except Exception:
            pass

        result = await send_file_smart(
            chat_id=update.effective_user.id,
            file_path=file_path,
            caption=name_caption,
            thumb_id=thumb_to_use,
            file_name=new_filename,
            force_document=force_doc,
            context=context,
            progress_chat_id=update.effective_chat.id,
            progress_prefix=f"Post {post_index + 1}: "
        )
        
        if result["success"]:
            new_file_id = result.get("file_id")
            if new_file_id:
                # Mettre à jour le post avec le nouveau file_id et le nouveau nom
                post['content'] = new_file_id
                post['has_custom_thumbnail'] = True
                post['filename'] = new_filename  # Sauvegarder le nouveau nom
                post['original_file_id'] = content
                # Si on a forcé un envoi en document, aligner le type
                if force_doc:
                    post['type'] = 'document'
                
                # Supprimer le message brut renvoyé par send_file_smart
                msg_id = result.get("message_id")
                if msg_id:
                    try:
                        await context.bot.delete_message(chat_id=update.effective_user.id, message_id=msg_id)
                    except Exception:
                        pass

                # Supprimer l'ancien message d'aperçu si présent
                prev = context.user_data.get('preview_messages', {}).get(post_index)
                if prev:
                    try:
                        await context.bot.delete_message(chat_id=prev['chat_id'], message_id=prev['message_id'])
                    except Exception:
                        pass

                # Construire les boutons essentiels
                buttons = [
                    [InlineKeyboardButton("✨ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
                    [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
                    [InlineKeyboardButton("✏️ Edit File", callback_data=f"edit_file_{post_index}")],
                    [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")]
                ]
                reply_markup = InlineKeyboardMarkup(buttons)

                # Réenvoyer le média final avec boutons, SANS légende
                sent_message = None
                final_type = post.get('type') or post_type
                if final_type == 'photo':
                    sent_message = await context.bot.send_photo(update.effective_chat.id, new_file_id, caption=name_caption, reply_markup=reply_markup)
                elif final_type == 'video':
                    sent_message = await context.bot.send_video(update.effective_chat.id, new_file_id, caption=name_caption, reply_markup=reply_markup)
                elif final_type == 'document':
                    sent_message = await context.bot.send_document(update.effective_chat.id, new_file_id, caption=name_caption, reply_markup=reply_markup)

                # Enregistrer le nouvel aperçu
                if sent_message:
                    if 'preview_messages' not in context.user_data:
                        context.user_data['preview_messages'] = {}
                    context.user_data['preview_messages'][post_index] = {
                        'message_id': sent_message.message_id,
                        'chat_id': update.effective_chat.id
                    }

                # Nettoyer le contexte
                context.user_data.pop('pending_rename_filename', None)
                context.user_data.pop('awaiting_thumb_rename', None)
                context.user_data.pop('force_document_for_video', None)

                # Supprimer le message de progression s'il existe
                try:
                    pmid = context.user_data.pop('progress_message_id', None)
                    if pmid:
                        await context.bot.delete_message(update.effective_chat.id, pmid)
                except Exception:
                    pass

                logger.info(f"✅ Post {post_index + 1} mis à jour avec thumbnail")
                return True
                
        return False
            
    except Exception as e:
        logger.error(f"❌ Erreur dans process_thumbnail_and_upload: {e}")
        return False
    finally:
        # Nettoyer les fichiers temporaires
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except:
                pass


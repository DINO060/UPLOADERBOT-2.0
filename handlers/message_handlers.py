from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from typing import Optional, Dict, Any
import logging
from datetime import datetime
import os
import asyncio
import time

from database.manager import DatabaseManager
from database.channel_repo import get_channel_by_username as repo_get_channel_by_username, add_channel as repo_add_channel
from utils.message_utils import PostType, MessageError
from utils.validators import InputValidator
from conversation_states import MAIN_MENU, WAITING_PUBLICATION_CONTENT, WAITING_TAG_INPUT, SETTINGS
import pytz

# Constants
MAIN_MENU = 0
WAITING_TIMEZONE = 8
WAITING_CHANNEL_INFO = 9

logger = logging.getLogger(__name__)




async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère les messages texte dans l'état MAIN_MENU.
    
    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation
        
    Returns:
        int: L'état suivant de la conversation
    """
    try:
        text = update.message.text
        
        # Les boutons ReplyKeyboard sont maintenant gérés par le handler contextuel
        # Ce handler ne traite que le texte générique - rediriger vers menu principal
        keyboard = [
            [InlineKeyboardButton("📝 New post", callback_data="create_publication")],
            [InlineKeyboardButton("⏰ Schedule a post", callback_data="schedule_publication")],
            [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
            [InlineKeyboardButton("❓ Help", callback_data="help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "Main menu:",
            reply_markup=reply_markup
        )
        return MAIN_MENU

    except MessageError as e:
        logger.error(f"Message error: {str(e)}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
        return 4  # WAITING_TEXT
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        await update.message.reply_text("❌ An unexpected error occurred")
        return 4  # WAITING_TEXT


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère la réception d'un média (photo/vidéo).

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Returns:
        int: L'état suivant de la conversation

    Raises:
        MessageError: Si le média n'est pas supporté
    """
    try:
        if update.message.photo:
            context.user_data['media'] = update.message.photo[-1].file_id
            context.user_data['media_type'] = 'photo'
        elif update.message.video:
            context.user_data['media'] = update.message.video.file_id
            context.user_data['media_type'] = 'video'
        else:
            raise MessageError("Unsupported format. Please send a photo or video.")

        keyboard = [
            [InlineKeyboardButton("✅ Publish", callback_data="publish")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "Media received. What would you like to do?",
            reply_markup=reply_markup
        )
        return 9  # WAITING_CONFIRMATION

    except MessageError as e:
        logger.error(f"Media error: {str(e)}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
        return 5  # WAITING_MEDIA
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        await update.message.reply_text("❌ An unexpected error occurred")
        return 5  # WAITING_MEDIA


async def handle_schedule_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère la réception du texte d'une publication planifiée.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Returns:
        int: L'état suivant de la conversation

    Raises:
        MessageError: Si le texte est invalide ou trop long
    """
    try:
        text = update.message.text
        
        # Les boutons ReplyKeyboard sont maintenant gérés par le handler contextuel
        if not InputValidator.sanitize_text(text):
            raise MessageError("Text contains forbidden characters")

        context.user_data['text'] = text

        await update.message.reply_text(
            "Enter the publish date and time (format: DD/MM/YYYY HH:MM):"
        )
        return 10  # WAITING_SCHEDULE_TIME

    except MessageError as e:
        logger.error(f"Scheduled message error: {str(e)}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
        return 6  # WAITING_SCHEDULE_TEXT
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        await update.message.reply_text("❌ An unexpected error occurred")
        return 6  # WAITING_SCHEDULE_TEXT


async def handle_schedule_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère la réception d'un média pour une publication planifiée.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Returns:
        int: L'état suivant de la conversation

    Raises:
        MessageError: Si le média n'est pas supporté
    """
    try:
        if update.message.photo:
            context.user_data['media'] = update.message.photo[-1].file_id
            context.user_data['media_type'] = 'photo'
        elif update.message.video:
            context.user_data['media'] = update.message.video.file_id
            context.user_data['media_type'] = 'video'
        else:
            raise MessageError("Unsupported format. Please send a photo or video.")

        await update.message.reply_text(
            "Enter the publish date and time (format: DD/MM/YYYY HH:MM):"
        )
        return 10  # WAITING_SCHEDULE_TIME

    except MessageError as e:
        logger.error(f"Scheduled media error: {str(e)}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
        return 7  # WAITING_SCHEDULE_MEDIA
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        await update.message.reply_text("❌ An unexpected error occurred")
        return 7  # WAITING_SCHEDULE_MEDIA


async def handle_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère la configuration du fuseau horaire.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Returns:
        int: L'état suivant de la conversation

    Raises:
        MessageError: Si le fuseau horaire est invalide
    """
    try:
        timezone = update.message.text.strip()

        # Vérifier si le fuseau horaire est valide
        import pytz
        pytz.timezone(timezone)

        # Sauvegarder le fuseau horaire
        db = DatabaseManager()
        db.set_user_timezone(update.effective_user.id, timezone)

        await update.message.reply_text(
            f"✅ Timezone configured: {timezone}"
        )
        return ConversationHandler.END

    except pytz.exceptions.UnknownTimeZoneError:
        logger.error(f"Invalid timezone: {timezone}")
        await update.message.reply_text(
            "❌ Invalid timezone. Please try again."
        )
        return 8  # WAITING_TIMEZONE
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        await update.message.reply_text("❌ An unexpected error occurred")
        return 8  # WAITING_TIMEZONE


async def handle_timezone_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère l'entrée du fuseau horaire par l'utilisateur.
    
    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation
        
    Returns:
        int: L'état suivant de la conversation
    """
    try:
        user_input = update.message.text.strip()
        user_id = update.effective_user.id
        
        # Les boutons ReplyKeyboard sont maintenant gérés par le handler contextuel
        
        # Validation et traitement du fuseau horaire
        if user_input.upper() == 'FRANCE':
            user_input = 'Europe/Paris'
        
        # Vérifier si le fuseau horaire est valide
        try:
            pytz.timezone(user_input)
        except pytz.exceptions.UnknownTimeZoneError:
            await update.message.reply_text(
                "❌ Invalid timezone. Valid examples:\n"
                "• Europe/Paris\n"
                "• America/New_York\n"
                "• Asia/Tokyo\n"
                "• UTC\n"
                "You can also type 'France' for Europe/Paris."
            )
            return WAITING_TIMEZONE
        
        # Sauvegarder le fuseau horaire
        db_manager = DatabaseManager()
        success = db_manager.set_user_timezone(user_id, user_input)
        
        if success:
            await update.message.reply_text(
                f"✅ Timezone set: {user_input}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Retour aux paramètres", callback_data="settings")]
                ])
            )
        else:
            await update.message.reply_text(
                "❌ Error saving timezone.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Retour aux paramètres", callback_data="settings")]
                ])
            )
        
        return SETTINGS
        
    except Exception as e:
        logger.error(f"Error processing timezone: {e}")
        await update.message.reply_text(
            "❌ An error occurred while configuring the timezone.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ Retour aux paramètres", callback_data="settings")]
            ])
        )
        return SETTINGS

async def handle_channel_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère la réception d'informations sur un canal.
    
    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation
        
    Returns:
        int: L'état suivant de la conversation
    """
    try:
        user_input = update.message.text.strip()
        user_id = update.effective_user.id
        
        # Les boutons ReplyKeyboard sont maintenant gérés par le handler contextuel
        
        # Vérifier si on attend une entrée de canal suite à add_channel_prompt
        if context.user_data.get('waiting_for_channel_info'):
            # Traitement de l'ajout de canal
            context.user_data.pop('waiting_for_channel_info', None)
            
            # Validation du format - accepter "Nom @username" ou juste "@username" ou lien t.me
            channel_username = None
            display_name = None
            
            if user_input.startswith('https://t.me/'):
                # Format: https://t.me/username
                channel_username = user_input.replace('https://t.me/', '')
                display_name = channel_username  # Utiliser le username comme nom par défaut
            elif user_input.startswith('@'):
                # Format: @username
                channel_username = user_input.lstrip('@')
                display_name = channel_username  # Utiliser le username comme nom par défaut
            elif '@' in user_input:
                # Format: "Nom du canal @username"
                parts = user_input.rsplit('@', 1)  # Diviser sur le dernier @
                if len(parts) == 2:
                    display_name = parts[0].strip()
                    channel_username = parts[1].strip()
                    # Vérifier que le username n'est pas vide
                    if not channel_username:
                        channel_username = None
            
            # Validation finale
            if not channel_username:
                await update.message.reply_text(
                    "❌ Invalid format. Use one of these formats:\n"
                    "• `Nom du canal @username`\n"
                    "• `@username`\n"
                    "• `https://t.me/username`\n\n"
                    "Exemple : `Mon Canal @monchannel`",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Réessayer", callback_data="add_channel")],
                        [InlineKeyboardButton("↩️ Retour", callback_data="manage_channels")]
                    ])
                )
                return SETTINGS
            
            # Vérifier si le canal existe déjà (via repository)
            if repo_get_channel_by_username(channel_username, user_id):
                await update.message.reply_text(
                    "❌ This channel is already registered.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 Gérer les canaux", callback_data="manage_channels")],
                        [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
                    ])
                )
                return SETTINGS
            
            # Si on a déjà un nom d'affichage, enregistrer directement
            if display_name and display_name != channel_username:
                try:
                    # Utiliser le dépôt pour gérer l'ajout (schéma et membership)
                    repo_add_channel(display_name, channel_username, user_id)
                    
                    await update.message.reply_text(
                        f"✅ Channel added successfully!\n\n"
                        f"📺 **{display_name}** (@{channel_username})",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📋 Gérer les canaux", callback_data="manage_channels")],
                            [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
                        ]),
                        parse_mode='Markdown'
                    )
                    
                    return SETTINGS
                    
                except Exception as e:
                    logger.error(f"Error adding channel: {e}")
                    await update.message.reply_text(
                        "❌ Error adding channel.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Réessayer", callback_data="add_channel")],
                            [InlineKeyboardButton("↩️ Retour", callback_data="manage_channels")]
                        ])
                    )
                    return SETTINGS
            
            # Auto-use default channel name/title without prompting
            final_display_name = display_name or channel_username
            try:
                chat_ident = f"@{channel_username}" if not channel_username.startswith('@') else channel_username
                chat = await context.bot.get_chat(chat_ident)
                if getattr(chat, 'title', None):
                    final_display_name = chat.title
            except Exception:
                pass

            try:
                # Utiliser le dépôt pour gérer l'ajout (schéma et membership)
                repo_add_channel(final_display_name, channel_username, user_id)
                await update.message.reply_text(
                    f"✅ Channel added successfully!\n\n"
                    f"📺 **{final_display_name}** (@{channel_username})",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 Gérer les canaux", callback_data="manage_channels")],
                        [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
                    ]),
                    parse_mode='Markdown'
                )
                return SETTINGS
            except Exception as e:
                logger.error(f"Error adding channel: {e}")
                await update.message.reply_text(
                    "❌ Error adding channel.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Réessayer", callback_data="add_channel")],
                        [InlineKeyboardButton("↩️ Retour", callback_data="manage_channels")]
                    ])
                )
                return SETTINGS
        
        # If we reach here, no add-channel context remains; redirect back
        
        # Si aucun contexte, rediriger vers les paramètres
        await update.message.reply_text(
            "❌ No configuration in progress.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Paramètres", callback_data="settings")],
                [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
            ])
        )
        return SETTINGS
        
    except Exception as e:
        logger.error(f"Error in handle_channel_info: {e}")
        await update.message.reply_text(
            "❌ An error occurred.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
            ])
        )
        return MAIN_MENU


async def handle_post_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère la réception de contenu pour une publication (texte, photo, vidéo, document).
    Cette fonction reconstitue le comportement original qui était dispersé.
    """
    try:
        # Logs de debug pour identifier le problème
        logger.info(f"=== DEBUG handle_post_content ===")
        logger.info(f"Message reçu: '{update.message.text}'")
        logger.info(f"User ID: {update.effective_user.id}")
        logger.info(f"Chat ID: {update.effective_chat.id}")
        
        # Les boutons ReplyKeyboard sont maintenant gérés par le handler contextuel
        # Cette fonction ne traite que le contenu réel (texte, médias)
        
        # Traitement du contenu normal (texte, média)
        logger.info("📝 TRAITEMENT: Contenu normal")
        posts = context.user_data.get('posts', [])
        selected_channel = context.user_data.get('selected_channel')
        
        logger.info(f"Posts existants: {len(posts)}")
        logger.info(f"Canal sélectionné: {selected_channel}")
        
        if not selected_channel:
            logger.info("❌ No channel selected")
            await update.message.reply_text(
                "❌ No channel selected. Please select a channel first.",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("🔄 Select a channel", callback_data="create_publication")
                ]])
            )
            return MAIN_MENU
        
        # Limite de 24 posts
        if len(posts) >= 15:
            logger.info("❌ Limit of 15 posts reached")
            try:
                warn = await update.message.reply_text(
                    "❌ Limit of 15 posts reached. Send current posts or delete some."
                )
                # Auto-suppression après 2 secondes
                try:
                    from handlers.callback_handlers import schedule_auto_destruction
                    schedule_auto_destruction(context, warn.chat_id, warn.message_id, 2)
                except Exception:
                    # Fallback simple si job_queue non dispo
                    try:
                        await asyncio.sleep(2)
                        await context.bot.delete_message(chat_id=warn.chat_id, message_id=warn.message_id)
                    except Exception:
                        pass
            except Exception:
                pass
            return WAITING_PUBLICATION_CONTENT
        
        # Déterminer le type de contenu et créer le post
        post_data = {
            'channel': selected_channel.get('username'),
            'channel_name': selected_channel.get('name')
        }
        
        if update.message.text:
            logger.info("📝 Type: Texte")
            post_data.update({
                'type': 'text',
                'content': update.message.text,
                'caption': None
            })
        elif update.message.photo:
            logger.info("🖼️ Type: Photo - quick recording without download")
            photo = update.message.photo[-1]
            post_data.update({
                'type': 'photo',
                'content': photo.file_id,
                'caption': update.message.caption or '',
                'file_size': photo.file_size or 0,
                'local_path': None
            })
        elif update.message.video:
            logger.info("🎥 Type: Video - quick recording without download")
            video = update.message.video
            post_data.update({
                'type': 'video',
                'content': video.file_id,
                'caption': update.message.caption or '',
                'file_size': video.file_size or 0,
                'duration': video.duration or 0,
                'local_path': None
            })
            
        elif update.message.document:
            logger.info("📄 Type: Document - ⚡ SIMPLE REPLY")
            document = update.message.document
            filename = document.file_name or f"document_{document.file_id}"
            
            # ✅ SIMPLE ET RAPIDE : Juste stocker les infos basiques
            post_data.update({
                'type': 'document',
                'content': document.file_id,
                'caption': update.message.caption or '',
                'file_size': document.file_size or 0,
                'filename': filename,
                'local_path': None  # Pas de téléchargement
            })
            
            logger.info(f"✅ Document added instantly - {filename}")
        else:
            logger.info("❌ Unsupported file type")
            await update.message.reply_text("❌ Unsupported file type.")
            return WAITING_PUBLICATION_CONTENT
        
        # Ajouter le post à la liste
        post_index = len(posts)
        posts.append(post_data)
        context.user_data['posts'] = posts
        
        logger.info(f"✅ Post added - Index: {post_index}, Total posts: {len(posts)}")
        
        # Renvoyer le contenu avec les boutons de modification
        await _send_post_with_buttons(update, context, post_index, post_data)
        
        logger.info("=== FIN DEBUG handle_post_content ===")
        return WAITING_PUBLICATION_CONTENT
        
    except Exception as e:
        logger.error(f"❌ ERROR in handle_post_content: {e}")
        logger.exception("Traceback complet:")
        await update.message.reply_text(
            "❌ An error occurred while processing the content.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def _send_post_with_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE, post_index: int, post_data: dict) -> None:
    """Envoie le post avec tous les boutons de modification inline."""
    try:
        # Interface simplifiée avec seulement les boutons essentiels
        keyboard = [
            [InlineKeyboardButton("✨ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
            [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
            [InlineKeyboardButton("✏️ Edit File", callback_data=f"edit_file_{post_index}")],
            [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Envoyer le contenu selon son type SANS les messages "Post X ajouté"
        sent_message = None
        if post_data['type'] == 'text':
            sent_message = await update.message.reply_text(
                post_data['content'],
                reply_markup=reply_markup
            )
        elif post_data['type'] == 'photo':
            sent_message = await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=post_data['content'],
                caption=post_data.get('caption', ''),
                reply_markup=reply_markup
            )
        elif post_data['type'] == 'video':
            sent_message = await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=post_data['content'],
                caption=post_data.get('caption', ''),
                reply_markup=reply_markup
            )
        elif post_data['type'] == 'document':
            sent_message = await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=post_data['content'],
                caption=post_data.get('caption', ''),
                reply_markup=reply_markup
            )
        
        # Stocker l'aperçu initial pour pouvoir le remplacer à la prochaine modification
        if sent_message:
            # Ancien stockage (conservé si utilisé ailleurs)
            context.user_data['original_file_message_id'] = sent_message.message_id
            # Nouveau stockage standardisé
            if 'preview_messages' not in context.user_data:
                context.user_data['preview_messages'] = {}
            context.user_data['preview_messages'][post_index] = {
                'message_id': sent_message.message_id,
                'chat_id': update.effective_chat.id
            }
        
        # Message de statut discret avec actions globales
        total_posts = len(context.user_data.get('posts', []))
        
        # Clavier reply (bottom buttons)
        reply_keyboard = ReplyKeyboardMarkup([
            ["📋 Preview", "🚀 Send"],
            ["🗑️ Delete all", "❌ Cancel"]
        ], resize_keyboard=True, one_time_keyboard=False)
        
        await update.message.reply_text(
            f"✅ {total_posts}/15 • Channel: {post_data['channel_name']}",
            reply_markup=reply_keyboard
        )
        
    except Exception as e:
        logger.error(f"Error in _send_post_with_buttons: {e}")
        await update.message.reply_text(
            f"✅ Post {post_index + 1} added but display error. Use the keyboard to continue."
        )


async def _send_post_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, post_index: int, post_data: dict) -> None:
    """Envoie un aperçu d'un post spécifique."""
    try:
        # Message simple comme demandé
        preview_text = "The post preview sent above.\n\n"
        preview_text += "You have 1 message in this post:\n"
        
        # Déterminer le type d'icône selon le type de fichier
        if post_data['type'] == 'photo':
            preview_text += "1. 📸 Photo"
        elif post_data['type'] == 'video':
            preview_text += "1. 📹 Video"
        elif post_data['type'] == 'document':
            preview_text += "1. 📄 Document"
        else:
            preview_text += "1. 📝 Text"
        
        # Ajouter l'heure actuelle
        from datetime import datetime
        current_time = datetime.now().strftime("%I:%M %p")
        preview_text += f" {current_time}"
        
        if post_data['type'] == 'text':
            await update.message.reply_text(preview_text)
        else:
            # Envoyer d'abord le fichier sans caption
            if post_data['type'] == 'photo':
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=post_data['content']
                )
            elif post_data['type'] == 'video':
                await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=post_data['content']
                )
            elif post_data['type'] == 'document':
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=post_data['content']
                )
            
            # Puis envoyer le message texte séparément
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=preview_text
            )
        
    except Exception as e:
        logger.error(f"Erreur dans _send_post_preview: {e}")
        await update.message.reply_text(f"❌ Erreur lors de l'aperçu du post {post_index + 1}")


async def handle_tag_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère la saisie des hashtags pour un canal ou du fuseau horaire.
    
    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation
        
    Returns:
        int: L'état suivant de la conversation
    """
    try:
        user_id = update.effective_user.id
        text = update.message.text.strip()
        
        # Vérifier si on attend une saisie de fuseau horaire
        if context.user_data.get('waiting_for_timezone'):
            # Nettoyer le flag
            context.user_data.pop('waiting_for_timezone', None)
            
            # Valider le fuseau horaire
            import pytz
            try:
                pytz.timezone(text)
                
                # Sauvegarder le fuseau horaire
                from database.manager import DatabaseManager
                db_manager = DatabaseManager()
                success = db_manager.set_user_timezone(user_id, text)
                
                if success:
                    # Afficher l'heure dans le nouveau fuseau
                    from datetime import datetime
                    user_tz = pytz.timezone(text)
                    local_time = datetime.now(user_tz)
                    
                    await update.message.reply_text(
                        f"✅ **Fuseau horaire mis à jour !**\n\n"
                        f"Nouveau fuseau : **{text}**\n"
                        f"Heure locale : **{local_time.strftime('%H:%M')}** ({local_time.strftime('%d/%m/%Y')})\n\n"
                        f"Vos futures publications seront planifiées selon ce fuseau horaire.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("↩️ Retour aux paramètres", callback_data="custom_settings")
                        ]]),
                        parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text(
                        "❌ Erreur lors de la mise à jour du fuseau horaire.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("↩️ Retour", callback_data="timezone_settings")
                        ]])
                    )
                
            except pytz.exceptions.UnknownTimeZoneError:
                await update.message.reply_text(
                    f"❌ **Fuseau horaire invalide**\n\n"
                    f"`{text}` n'est pas un fuseau horaire reconnu.\n\n"
                    f"**Exemples valides :**\n"
                    f"• `Europe/Paris`\n"
                    f"• `America/New_York`\n"
                    f"• `Asia/Tokyo`\n"
                    f"• `UTC`\n\n"
                    f"💡 Consultez la liste complète sur:\n"
                    f"https://en.wikipedia.org/wiki/List_of_tz_database_time_zones",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔄 Réessayer", callback_data="manual_timezone"),
                        InlineKeyboardButton("↩️ Retour", callback_data="timezone_settings")
                    ]]),
                    parse_mode="Markdown"
                )
                return WAITING_TAG_INPUT
            
            return SETTINGS
        
        # Gestion username/hashtag (comme dans Pdfbot)
        if context.user_data.get('awaiting_username'):
            username = text
            
            # Accepter n'importe quel texte (hashtag, emoji, username, etc.)
            if username:
                channel_username = context.user_data.get('editing_tag_for_channel')
                if channel_username:
                    from database.manager import DatabaseManager
                    db_manager = DatabaseManager()
                    
                    # Sauvegarder le tag
                    success = db_manager.set_channel_tag(channel_username, user_id, username)
                    
                    if success:
                        await update.message.reply_text(f"✅ Tag saved: {username}")
                    else:
                        await update.message.reply_text(f"✅ Tag saved in session: {username}\n⚠️ (Could not save to file)")
                    
                    logger.info(f"🔧 Tag registered for user {user_id}: {username}")
                else:
                    await update.message.reply_text("❌ Error: Channel not found.")
            else:
                await update.message.reply_text("❌ Please send some text to use as your tag.")
            
            # Nettoyer le contexte
            context.user_data.pop('awaiting_username', None)
            context.user_data.pop('editing_tag_for_channel', None)
            
            return MAIN_MENU
        
        # Sinon, traiter comme une saisie de hashtags (ancienne logique)
        channel_username = context.user_data.get('editing_tag_for_channel')
        
        if not channel_username:
            logger.error("Canal non trouvé pour l'édition de tag")
            await update.message.reply_text(
                "❌ Erreur: Canal introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        from database.manager import DatabaseManager
        db_manager = DatabaseManager()
        
        # Si l'utilisateur envoie un point, supprimer tous les hashtags
        if text == ".":
            success = db_manager.set_channel_tag(channel_username, user_id, "")
            if success:
                message_text = f"✅ **Hashtags supprimés**\n\nTous les hashtags pour @{channel_username} ont été supprimés."
            else:
                message_text = "❌ **Erreur**\n\nImpossible de supprimer les hashtags."
        else:
            # Valider et nettoyer les hashtags
            hashtags = []
            words = text.split()
            
            for word in words:
                # Nettoyer le mot (enlever espaces et caractères indésirables)
                clean_word = word.strip()
                
                # Ajouter # si ce n'est pas déjà présent
                if clean_word and not clean_word.startswith('#'):
                    clean_word = '#' + clean_word
                
                # Vérifier que c'est un hashtag valide
                if clean_word and len(clean_word) > 1 and clean_word not in hashtags:
                    hashtags.append(clean_word)
            
            if not hashtags:
                await update.message.reply_text(
                    "❌ **Hashtags invalides**\n\n"
                    "Veuillez envoyer au moins un hashtag valide.\n"
                    "Exemple : `#tech #python #dev`",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔄 Réessayer", callback_data=f"edit_tag_{channel_username}"),
                        InlineKeyboardButton("❌ Annuler", callback_data=f"custom_channel_{channel_username}")
                    ]]),
                    parse_mode="Markdown"
                )
                return WAITING_TAG_INPUT
            
            # Limiter à 10 hashtags maximum
            if len(hashtags) > 10:
                hashtags = hashtags[:10]
                await update.message.reply_text(
                    "⚠️ **Limite atteinte**\n\n"
                    "Maximum 10 hashtags autorisés. Les 10 premiers seront utilisés."
                )
            
            # Enregistrer les hashtags
            hashtag_string = " ".join(hashtags)
            success = db_manager.set_channel_tag(channel_username, user_id, hashtag_string)
            
            if success:
                message_text = (
                    f"✅ **Hashtags enregistrés**\n\n"
                    f"**Canal :** @{channel_username}\n"
                    f"**Hashtags :** {hashtag_string}\n\n"
                    f"Ces hashtags seront automatiquement ajoutés à vos publications sur ce canal."
                )
            else:
                message_text = (
                    f"❌ **Erreur**\n\n"
                    f"Impossible d'enregistrer les hashtags pour @{channel_username}."
                )
        
        # Boutons de retour
        keyboard = [
            [InlineKeyboardButton("↩️ Paramètres du canal", callback_data=f"custom_channel_{channel_username}")],
            [InlineKeyboardButton("🏠 Menu principal", callback_data="main_menu")]
        ]
        
        await update.message.reply_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
        # Nettoyer le contexte
        context.user_data.pop('editing_tag_for_channel', None)
        
        return MAIN_MENU
        
    except Exception as e:
        logger.error(f"Erreur dans handle_tag_input: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors de l'enregistrement des hashtags.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU
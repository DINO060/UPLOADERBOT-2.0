from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from typing import Optional, Dict, Any
import logging
from datetime import datetime
import os

from database.manager import DatabaseManager
from utils.message_utils import PostType, MessageError
from utils.validators import InputValidator
from conversation_states import MAIN_MENU, WAITING_PUBLICATION_CONTENT, WAITING_TAG_INPUT

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
            [InlineKeyboardButton("📝 Créer une publication", callback_data="create_publication")],
            [InlineKeyboardButton("⏰ Planifier une publication", callback_data="schedule_publication")],
            [InlineKeyboardButton("⚙️ Paramètres", callback_data="settings")],
            [InlineKeyboardButton("❓ Aide", callback_data="help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "Menu principal :",
            reply_markup=reply_markup
        )
        return MAIN_MENU

    except MessageError as e:
        logger.error(f"Erreur de message: {str(e)}")
        await update.message.reply_text(f"❌ Erreur: {str(e)}")
        return 4  # WAITING_TEXT
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await update.message.reply_text("❌ Une erreur inattendue s'est produite")
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
            raise MessageError("Format non supporté. Veuillez envoyer une photo ou une vidéo.")

        keyboard = [
            [InlineKeyboardButton("✅ Publier", callback_data="publish")],
            [InlineKeyboardButton("❌ Annuler", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "Média reçu. Que souhaitez-vous faire ?",
            reply_markup=reply_markup
        )
        return 9  # WAITING_CONFIRMATION

    except MessageError as e:
        logger.error(f"Erreur de média: {str(e)}")
        await update.message.reply_text(f"❌ Erreur: {str(e)}")
        return 5  # WAITING_MEDIA
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await update.message.reply_text("❌ Une erreur inattendue s'est produite")
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
            raise MessageError("Le texte contient des caractères non autorisés")

        context.user_data['text'] = text

        await update.message.reply_text(
            "Entrez la date et l'heure de publication (format: JJ/MM/AAAA HH:MM):"
        )
        return 10  # WAITING_SCHEDULE_TIME

    except MessageError as e:
        logger.error(f"Erreur de message planifié: {str(e)}")
        await update.message.reply_text(f"❌ Erreur: {str(e)}")
        return 6  # WAITING_SCHEDULE_TEXT
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await update.message.reply_text("❌ Une erreur inattendue s'est produite")
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
            raise MessageError("Format non supporté. Veuillez envoyer une photo ou une vidéo.")

        await update.message.reply_text(
            "Entrez la date et l'heure de publication (format: JJ/MM/AAAA HH:MM):"
        )
        return 10  # WAITING_SCHEDULE_TIME

    except MessageError as e:
        logger.error(f"Erreur de média planifié: {str(e)}")
        await update.message.reply_text(f"❌ Erreur: {str(e)}")
        return 7  # WAITING_SCHEDULE_MEDIA
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await update.message.reply_text("❌ Une erreur inattendue s'est produite")
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
            f"✅ Fuseau horaire configuré: {timezone}"
        )
        return ConversationHandler.END

    except pytz.exceptions.UnknownTimeZoneError:
        logger.error(f"Fuseau horaire invalide: {timezone}")
        await update.message.reply_text(
            "❌ Fuseau horaire invalide. Veuillez réessayer."
        )
        return 8  # WAITING_TIMEZONE
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await update.message.reply_text("❌ Une erreur inattendue s'est produite")
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
                "❌ Fuseau horaire invalide. Exemples valides :\n"
                "• Europe/Paris\n"
                "• America/New_York\n"
                "• Asia/Tokyo\n"
                "• UTC\n"
                "Vous pouvez aussi taper 'France' pour Europe/Paris."
            )
            return WAITING_TIMEZONE
        
        # Sauvegarder le fuseau horaire
        db_manager = DatabaseManager()
        success = db_manager.set_user_timezone(user_id, user_input)
        
        if success:
            await update.message.reply_text(
                f"✅ Fuseau horaire défini : {user_input}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Retour aux paramètres", callback_data="settings")]
                ])
            )
        else:
            await update.message.reply_text(
                "❌ Erreur lors de la sauvegarde du fuseau horaire.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Retour aux paramètres", callback_data="settings")]
                ])
            )
        
        return SETTINGS
        
    except Exception as e:
        logger.error(f"Erreur lors du traitement du fuseau horaire: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors de la configuration du fuseau horaire.",
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
            
            # Validation du format
            if not user_input.startswith('@') and not user_input.startswith('https://t.me/'):
                await update.message.reply_text(
                    "❌ Format invalide. Le nom doit commencer par @ ou être un lien t.me/",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Réessayer", callback_data="add_channel")],
                        [InlineKeyboardButton("↩️ Retour", callback_data="manage_channels")]
                    ])
                )
                return SETTINGS
            
            # Normaliser le nom d'utilisateur
            if user_input.startswith('https://t.me/'):
                channel_username = user_input.replace('https://t.me/', '')
            else:
                channel_username = user_input.lstrip('@')
            
            # Vérifier si le canal existe déjà
            from ..database.manager import DatabaseManager
            db_manager = DatabaseManager()
            
            if db_manager.get_channel_by_username(channel_username, user_id):
                await update.message.reply_text(
                    "❌ Ce canal est déjà enregistré.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 Gérer les canaux", callback_data="manage_channels")],
                        [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
                    ])
                )
                return SETTINGS
            
            # Demander le nom d'affichage
            context.user_data['temp_channel_username'] = channel_username
            
            await update.message.reply_text(
                f"✅ Nom d'utilisateur enregistré: @{channel_username}\n\n"
                f"Maintenant, donnez un nom d'affichage pour ce canal:"
            )
            
            return WAITING_CHANNEL_INFO  # Attendre le nom d'affichage
        
        # Si on arrive ici, c'est pour le nom d'affichage
        temp_username = context.user_data.get('temp_channel_username')
        if temp_username:
            display_name = user_input
            
            # Enregistrer le canal
            from ..database.manager import DatabaseManager
            db_manager = DatabaseManager()
            
            try:
                db_manager.add_channel(temp_username, display_name, user_id)
                context.user_data.pop('temp_channel_username', None)
                
                await update.message.reply_text(
                    f"✅ Canal ajouté avec succès !\n\n"
                    f"📺 **{display_name}** (@{temp_username})",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 Gérer les canaux", callback_data="manage_channels")],
                        [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
                    ]),
                    parse_mode='Markdown'
                )
                
                return SETTINGS
                
            except Exception as e:
                logger.error(f"Erreur lors de l'ajout du canal: {e}")
                await update.message.reply_text(
                    "❌ Erreur lors de l'ajout du canal.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Réessayer", callback_data="add_channel")],
                        [InlineKeyboardButton("↩️ Retour", callback_data="manage_channels")]
                    ])
                )
                return SETTINGS
        
        # Si aucun contexte, rediriger vers les paramètres
        await update.message.reply_text(
            "❌ Aucune configuration en cours.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Paramètres", callback_data="settings")],
                [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
            ])
        )
        return SETTINGS
        
    except Exception as e:
        logger.error(f"Erreur dans handle_channel_info: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue.",
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
            logger.info("❌ Aucun canal sélectionné")
            await update.message.reply_text(
                "❌ Aucun canal sélectionné. Veuillez d'abord sélectionner un canal.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Sélectionner un canal", callback_data="create_publication")
                ]])
            )
            return MAIN_MENU
        
        # Limite de 24 posts
        if len(posts) >= 24:
            logger.info("❌ Limite de 24 posts atteinte")
            await update.message.reply_text(
                "❌ Limite de 24 posts atteinte. Envoyez les posts actuels ou supprimez-en quelques-uns."
            )
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
            logger.info("🖼️ Type: Photo")
            photo = update.message.photo[-1]
            # Sauvegarde locale immédiate avec fallback
            try:
                file_obj = await context.bot.get_file(photo.file_id)
                local_path = await file_obj.download_to_drive(f"downloads/photo_{photo.file_id}.jpg")
            except Exception as e:
                error_str = str(e)
                if "File is too big" in error_str or "file is too big" in error_str.lower():
                    try:
                        from utils.clients import client_manager
                        client_info = await client_manager.get_best_client(photo.file_size or 0, "download")
                        client = client_info["client"]
                        client_type = client_info["type"]
                        import time
                        user_id = update.effective_user.id
                        if client_type == "pyrogram":
                            local_path = await client.download_media(
                                photo.file_id,
                                file_name=f"downloads/photo_{photo.file_id}_{int(time.time())}.jpg"
                            )
                        elif client_type == "telethon":
                            local_path = await client.download_media(
                                photo.file_id,
                                file=f"downloads/photo_{photo.file_id}_{int(time.time())}.jpg"
                            )
                        else:
                            raise Exception("Aucun client avancé disponible")
                    except Exception as client_error:
                        logger.error(f"❌ Impossible de télécharger la photo via client avancé: {client_error}")
                        await update.message.reply_text(
                            "❌ Impossible de sauvegarder cette photo (trop volumineuse ou inaccessible). Merci de l'envoyer directement au bot, pas en forward.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
                        )
                        return MAIN_MENU
                else:
                    logger.error(f"❌ Erreur inattendue lors du téléchargement: {error_str}")
                    await update.message.reply_text(
                        "❌ Erreur inattendue lors de la sauvegarde de la photo.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
                    )
                    return MAIN_MENU
            post_data.update({
                'type': 'photo',
                'content': photo.file_id,
                'caption': update.message.caption or '',
                'file_size': photo.file_size or 0,
                'local_path': local_path
            })
        elif update.message.video:
            logger.info("🎥 Type: Vidéo")
            video = update.message.video
            # ✅ SAUVEGARDE LOCALE AVEC GESTION FILE_REFERENCE_EXPIRED AMÉLIORÉE
            local_path = None
            try:
                logger.info(f"📥 Tentative téléchargement vidéo via API Bot...")
                file_obj = await context.bot.get_file(video.file_id)
                local_path = await file_obj.download_to_drive(f"downloads/video_{video.file_id}.mp4")
                logger.info(f"✅ Vidéo téléchargée via API Bot: {local_path}")
            except Exception as e:
                error_str = str(e)
                logger.warning(f"⚠️ Échec API Bot: {error_str}")
                
                # ✅ GESTION SPÉCIFIQUE DES ERREURS
                if ("File is too big" in error_str or "file is too big" in error_str.lower() or 
                    "FILE_REFERENCE_EXPIRED" in error_str or "file reference" in error_str.lower()):
                    
                    logger.info("🔄 Fallback vers clients avancés...")
                    try:
                        from utils.clients import client_manager
                        client_info = await client_manager.get_best_client(video.file_size or 0, "download")
                        client = client_info["client"]
                        client_type = client_info["type"]
                        
                        if not client:
                            raise Exception("Aucun client avancé disponible")
                            
                        import time
                        user_id = update.effective_user.id
                        timestamp = int(time.time())
                        
                        logger.info(f"📥 Téléchargement via {client_type}...")
                        
                        if client_type == "pyrogram":
                            local_path = await client.download_media(
                                video.file_id,
                                file_name=f"downloads/video_{user_id}_{timestamp}.mp4"
                            )
                        elif client_type == "telethon":
                            local_path = await client.download_media(
                                video.file_id,
                                file=f"downloads/video_{user_id}_{timestamp}.mp4"
                            )
                        else:
                            raise Exception(f"Client {client_type} non supporté")
                            
                        if not local_path or not os.path.exists(local_path) or os.path.getsize(local_path) == 0:
                            raise Exception("Fichier téléchargé invalide ou vide")
                            
                        logger.info(f"✅ Vidéo téléchargée via {client_type}: {local_path}")
                        
                    except Exception as client_error:
                        logger.error(f"❌ Échec téléchargement avancé: {client_error}")
                        await update.message.reply_text(
                            f"❌ **Impossible de sauvegarder cette vidéo**\n\n"
                            f"**Cause possible :**\n"
                            f"• Fichier transféré (forward) avec file_id expiré\n"
                            f"• Fichier trop volumineux\n"
                            f"• Fichier corrompu\n\n"
                            f"**💡 Solutions :**\n"
                            f"• Envoyez le fichier directement (pas en forward)\n"
                            f"• Vérifiez que le fichier n'est pas corrompu\n"
                            f"• Réduisez la taille si nécessaire\n\n"
                            f"**Détails technique :** {client_error}",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]]),
                            parse_mode='Markdown'
                        )
                        return MAIN_MENU
                else:
                    logger.error(f"❌ Erreur inattendue lors du téléchargement: {error_str}")
                    await update.message.reply_text(
                        f"❌ **Erreur lors de la sauvegarde de la vidéo**\n\n"
                        f"**Erreur :** {error_str}\n\n"
                        f"Veuillez réessayer ou contacter le support.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]]),
                        parse_mode='Markdown'
                    )
                    return MAIN_MENU
                    
            # ✅ VALIDATION FINALE DU FICHIER TÉLÉCHARGÉ
            if not local_path or not os.path.exists(local_path):
                logger.error("❌ Aucun fichier vidéo téléchargé")
                await update.message.reply_text(
                    "❌ Impossible de traiter cette vidéo. Veuillez réessayer.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
                )
                return MAIN_MENU
                
            file_size_check = os.path.getsize(local_path)
            if file_size_check == 0:
                logger.error("❌ Fichier vidéo téléchargé vide")
                try:
                    os.remove(local_path)
                except:
                    pass
                await update.message.reply_text(
                    "❌ Le fichier vidéo téléchargé est vide. Veuillez renvoyer le fichier.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
                )
                return MAIN_MENU
                
            post_data.update({
                'type': 'video',
                'content': video.file_id,
                'caption': update.message.caption or '',
                'file_size': video.file_size or file_size_check,
                'duration': video.duration or 0,
                'local_path': local_path
            })
            
        elif update.message.document:
            logger.info("📄 Type: Document")
            document = update.message.document
            # ✅ SAUVEGARDE LOCALE AVEC GESTION FILE_REFERENCE_EXPIRED AMÉLIORÉE
            local_path = None
            filename = document.file_name or f"document_{document.file_id}"
            
            try:
                logger.info(f"📥 Tentative téléchargement document via API Bot...")
                file_obj = await context.bot.get_file(document.file_id)
                local_path = await file_obj.download_to_drive(f"downloads/{filename}")
                logger.info(f"✅ Document téléchargé via API Bot: {local_path}")
            except Exception as e:
                error_str = str(e)
                logger.warning(f"⚠️ Échec API Bot: {error_str}")
                
                # ✅ GESTION SPÉCIFIQUE DES ERREURS
                if ("File is too big" in error_str or "file is too big" in error_str.lower() or 
                    "FILE_REFERENCE_EXPIRED" in error_str or "file reference" in error_str.lower()):
                    
                    logger.info("🔄 Fallback vers clients avancés...")
                    try:
                        from utils.clients import client_manager
                        client_info = await client_manager.get_best_client(document.file_size or 0, "download")
                        client = client_info["client"]
                        client_type = client_info["type"]
                        
                        if not client:
                            raise Exception("Aucun client avancé disponible")
                            
                        import time
                        user_id = update.effective_user.id
                        timestamp = int(time.time())
                        safe_filename = f"{filename}_{user_id}_{timestamp}"
                        
                        logger.info(f"📥 Téléchargement via {client_type}...")
                        
                        if client_type == "pyrogram":
                            local_path = await client.download_media(
                                document.file_id,
                                file_name=f"downloads/{safe_filename}"
                            )
                        elif client_type == "telethon":
                            local_path = await client.download_media(
                                document.file_id,
                                file=f"downloads/{safe_filename}"
                            )
                        else:
                            raise Exception(f"Client {client_type} non supporté")
                            
                        if not local_path or not os.path.exists(local_path) or os.path.getsize(local_path) == 0:
                            raise Exception("Fichier téléchargé invalide ou vide")
                            
                        logger.info(f"✅ Document téléchargé via {client_type}: {local_path}")
                        
                    except Exception as client_error:
                        logger.error(f"❌ Échec téléchargement avancé: {client_error}")
                        await update.message.reply_text(
                            f"❌ **Impossible de sauvegarder ce document**\n\n"
                            f"**Cause possible :**\n"
                            f"• Fichier transféré (forward) avec file_id expiré\n"
                            f"• Fichier trop volumineux (>2GB)\n"
                            f"• Fichier corrompu ou inaccessible\n\n"
                            f"**💡 Solutions :**\n"
                            f"• Envoyez le fichier directement (pas en forward)\n"
                            f"• Vérifiez que le fichier n'est pas corrompu\n"
                            f"• Réduisez la taille si nécessaire\n\n"
                            f"**Détails technique :** {client_error}",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]]),
                            parse_mode='Markdown'
                        )
                        return MAIN_MENU
                else:
                    logger.error(f"❌ Erreur inattendue lors du téléchargement: {error_str}")
                    await update.message.reply_text(
                        f"❌ **Erreur lors de la sauvegarde du document**\n\n"
                        f"**Erreur :** {error_str}\n\n"
                        f"Veuillez réessayer ou contacter le support.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]]),
                        parse_mode='Markdown'
                    )
                    return MAIN_MENU
                    
            # ✅ VALIDATION FINALE DU FICHIER TÉLÉCHARGÉ
            if not local_path or not os.path.exists(local_path):
                logger.error("❌ Aucun fichier document téléchargé")
                await update.message.reply_text(
                    "❌ Impossible de traiter ce document. Veuillez réessayer.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
                )
                return MAIN_MENU
                
            file_size_check = os.path.getsize(local_path)
            if file_size_check == 0:
                logger.error("❌ Fichier document téléchargé vide")
                try:
                    os.remove(local_path)
                except:
                    pass
                await update.message.reply_text(
                    "❌ Le fichier document téléchargé est vide. Veuillez renvoyer le fichier.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
                )
                return MAIN_MENU
                
            post_data.update({
                'type': 'document',
                'content': document.file_id,
                'caption': document.caption or '',
                'file_size': document.file_size or file_size_check,
                'filename': filename,
                'local_path': local_path
            })
        else:
            logger.info("❌ Type de fichier non supporté")
            await update.message.reply_text("❌ Type de fichier non supporté.")
            return WAITING_PUBLICATION_CONTENT
        
        # Ajouter le post à la liste
        post_index = len(posts)
        posts.append(post_data)
        context.user_data['posts'] = posts
        
        logger.info(f"✅ Post ajouté - Index: {post_index}, Total posts: {len(posts)}")
        
        # Renvoyer le contenu avec les boutons de modification
        await _send_post_with_buttons(update, context, post_index, post_data)
        
        logger.info("=== FIN DEBUG handle_post_content ===")
        return WAITING_PUBLICATION_CONTENT
        
    except Exception as e:
        logger.error(f"❌ ERREUR dans handle_post_content: {e}")
        logger.exception("Traceback complet:")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors du traitement du contenu.",
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
        if post_data['type'] == 'text':
            await update.message.reply_text(
                post_data['content'],
                reply_markup=reply_markup
            )
        elif post_data['type'] == 'photo':
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=post_data['content'],
                caption=post_data.get('caption', ''),
                reply_markup=reply_markup
            )
        elif post_data['type'] == 'video':
            await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=post_data['content'],
                caption=post_data.get('caption', ''),
                reply_markup=reply_markup
            )
        elif post_data['type'] == 'document':
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=post_data['content'],
                caption=post_data.get('caption', ''),
                reply_markup=reply_markup
            )
        
        # Message de statut discret avec actions globales
        total_posts = len(context.user_data.get('posts', []))
        
        # Clavier reply (boutons en bas de l'écran)
        reply_keyboard = ReplyKeyboardMarkup([
            ["📋 Aperçu", "🚀 Envoyer"],
            ["🗑️ Tout supprimer", "❌ Annuler"]
        ], resize_keyboard=True, one_time_keyboard=False)
        
        await update.message.reply_text(
            f"✅ {total_posts}/24 • Canal: {post_data['channel_name']}",
            reply_markup=reply_keyboard
        )
        
    except Exception as e:
        logger.error(f"Erreur dans _send_post_with_buttons: {e}")
        await update.message.reply_text(
            f"✅ Post {post_index + 1} ajouté mais erreur d'affichage. Utilisez le clavier pour continuer."
        )


async def _send_post_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, post_index: int, post_data: dict) -> None:
    """Envoie un aperçu d'un post spécifique."""
    try:
        preview_text = f"📋 **Aperçu post {post_index + 1}**\n\n"
        preview_text += f"Type: {post_data['type']}\n"
        preview_text += f"Canal: {post_data['channel_name']}\n"
        
        if post_data['type'] == 'text':
            preview_text += f"Contenu: {post_data['content'][:200]}{'...' if len(post_data['content']) > 200 else ''}"
            await update.message.reply_text(preview_text, parse_mode="Markdown")
        else:
            caption_preview = post_data.get('caption', '')
            if caption_preview:
                preview_text += f"Légende: {caption_preview[:100]}{'...' if len(caption_preview) > 100 else ''}"
            
            if post_data['type'] == 'photo':
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=post_data['content'],
                    caption=preview_text,
                    parse_mode="Markdown"
                )
            elif post_data['type'] == 'video':
                await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=post_data['content'],
                    caption=preview_text,
                    parse_mode="Markdown"
                )
            elif post_data['type'] == 'document':
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=post_data['content'],
                    caption=preview_text,
                    parse_mode="Markdown"
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
        
        # Sinon, traiter comme une saisie de hashtags
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
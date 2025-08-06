from typing import Optional, List, Dict
from enum import Enum
import logging
from telegram import Update, Message, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

logger = logging.getLogger(__name__)

class PostType(Enum):
    """Types de messages supportés"""
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    TEXT = "text"

class MessageError(Exception):
    """Exception pour les erreurs d'envoi de messages"""
    pass

async def send_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    post_type: PostType,
    content: str,
    caption: Optional[str] = None,
    buttons: Optional[List[Dict]] = None
) -> Message:
    """
    Envoie un message de n'importe quel type avec gestion d'erreurs
    
    Args:
        update: Objet Update de Telegram
        context: Contexte de la conversation
        chat_id: ID du chat destinataire
        post_type: Type de message à envoyer
        content: Contenu du message
        caption: Légende optionnelle
        buttons: Boutons optionnels
        
    Returns:
        Message: L'objet message envoyé
        
    Raises:
        MessageError: Si l'envoi échoue
    """
    try:
        if post_type == PostType.PHOTO:
            return await context.bot.send_photo(
                chat_id=chat_id,
                photo=content,
                caption=caption,
                reply_markup=buttons
            )
        elif post_type == PostType.VIDEO:
            return await context.bot.send_video(
                chat_id=chat_id,
                video=content,
                caption=caption,
                reply_markup=buttons
            )
        elif post_type == PostType.DOCUMENT:
            return await context.bot.send_document(
                chat_id=chat_id,
                document=content,
                caption=caption,
                reply_markup=buttons
            )
        elif post_type == PostType.TEXT:
            return await context.bot.send_message(
                chat_id=chat_id,
                text=content,
                reply_markup=buttons
            )
        else:
            raise MessageError(f"Type de message non supporté: {post_type}")
            
    except Exception as e:
        logger.error(f"Erreur d'envoi de message: {e}")
        raise MessageError(f"Impossible d'envoyer le message: {str(e)}")

async def edit_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    message_id: int,
    chat_id: int,
    text: str,
    buttons: Optional[List[Dict]] = None
) -> Message:
    """
    Modifie un message existant
    
    Args:
        update: Objet Update de Telegram
        context: Contexte de la conversation
        message_id: ID du message à modifier
        chat_id: ID du chat
        text: Nouveau texte
        buttons: Nouveaux boutons optionnels
        
    Returns:
        Message: Le message modifié
    """
    try:
        return await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=buttons
        )
    except Exception as e:
        logger.error(f"Erreur de modification de message: {e}")
        raise MessageError(f"Impossible de modifier le message: {str(e)}")

async def delete_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    message_id: int,
    chat_id: int
) -> bool:
    """
    Supprime un message
    
    Args:
        update: Objet Update de Telegram
        context: Contexte de la conversation
        message_id: ID du message à supprimer
        chat_id: ID du chat
        
    Returns:
        bool: True si la suppression a réussi
    """
    try:
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )
        return True
    except Exception as e:
        logger.error(f"Erreur de suppression de message: {e}")
        raise MessageError(f"Impossible de supprimer le message: {str(e)}")

async def safe_edit_message_text(
    query_or_update, 
    text: str, 
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = None
) -> bool:
    """
    Édite un message de manière sûre en gérant l'erreur 'There is no text in the message to edit'
    
    Args:
        query_or_update: CallbackQuery ou Update
        text: Le nouveau texte
        reply_markup: Clavier inline optionnel
        parse_mode: Mode de parsing (Markdown, HTML, etc.)
    
    Returns:
        bool: True si l'édition a réussi, False sinon
    """
    try:
        # Déterminer si c'est un CallbackQuery ou Update
        if hasattr(query_or_update, 'edit_message_text'):
            # C'est un CallbackQuery
            await query_or_update.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        elif hasattr(query_or_update, 'callback_query'):
            # C'est un Update
            await query_or_update.callback_query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        else:
            logger.error("Type d'objet non supporté pour safe_edit_message_text")
            return False
        
        return True
        
    except BadRequest as e:
        if "There is no text in the message to edit" in str(e):
            logger.warning("Impossible d'éditer le message (pas de texte). Envoi d'un nouveau message.")
            try:
                # Essayer d'envoyer un nouveau message à la place
                if hasattr(query_or_update, 'message'):
                    # C'est un CallbackQuery
                    chat_id = query_or_update.message.chat.id
                    bot = query_or_update.get_bot()
                elif hasattr(query_or_update, 'callback_query'):
                    # C'est un Update
                    chat_id = query_or_update.callback_query.message.chat.id
                    bot = query_or_update.callback_query.get_bot()
                else:
                    logger.error("Impossible de déterminer le chat_id")
                    return False
                
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
                return True
            except Exception as send_error:
                logger.error(f"Erreur lors de l'envoi du nouveau message: {send_error}")
                return False
        else:
            logger.error(f"Erreur BadRequest lors de l'édition: {e}")
            return False
    except Exception as e:
        logger.error(f"Erreur inattendue lors de l'édition: {e}")
        return False 
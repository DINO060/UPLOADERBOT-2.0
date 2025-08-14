"""
Thumbnail functions handler for Telegram bot
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from conversation_states import (
    SETTINGS, WAITING_THUMBNAIL, WAITING_RENAME_INPUT, 
    MAIN_MENU, WAITING_PUBLICATION_CONTENT
)

# Import de la fonction de normalisation globale
from .callback_handlers import normalize_channel_username

logger = logging.getLogger('UploaderBot')


async def handle_thumbnail_functions(update, context):
    """Displays thumbnail management options for a channel"""
    query = update.callback_query
    await query.answer()
    
    # Récupérer le canal sélectionné
    channel_username = context.user_data.get('custom_channel')
    if not channel_username:
        selected_channel = context.user_data.get('selected_channel', {})
        channel_username = selected_channel.get('username')
    
    if not channel_username:
        await query.edit_message_text(
            "❌ No channel selected.",
            reply_markup=InlineKeyboardMarkup([[ 
                InlineKeyboardButton("↩️ Back", callback_data="custom_settings")
            ]])
        )
        return SETTINGS
    
    user_id = update.effective_user.id
    
    # Nettoyer le nom d'utilisateur du canal (enlever @ s'il est présent)
    clean_username = normalize_channel_username(channel_username)
    
    # Vérifier si un thumbnail existe déjà - utiliser DatabaseManager() directement
    from database.manager import DatabaseManager
    db_manager = DatabaseManager()
    try:
        existing_thumbnail = db_manager.get_thumbnail(clean_username, user_id)
    except Exception as e:
        logger.error(f"Error retrieving thumbnail: {e}")
        existing_thumbnail = None
    
    keyboard = []
    
    if existing_thumbnail:
        keyboard.append([InlineKeyboardButton("👁️ View current thumbnail", callback_data="view_thumbnail")])
        keyboard.append([InlineKeyboardButton("🔄 Change thumbnail", callback_data="add_thumbnail")])
        keyboard.append([InlineKeyboardButton("🗑️ Delete thumbnail", callback_data="delete_thumbnail")])
    else:
        keyboard.append([InlineKeyboardButton("➕ Add thumbnail", callback_data="add_thumbnail")])

    keyboard.append([InlineKeyboardButton("↩️ Back", callback_data=f"custom_channel_{clean_username}")])

    message = f"🖼️ Thumbnail management for @{clean_username}\n\n"
    message += "✅ Thumbnail set" if existing_thumbnail else "❌ No thumbnail set"
    
    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return SETTINGS


async def handle_add_thumbnail_to_post(update, context):
    """Automatically applies the saved thumbnail to a post and sends it as a document"""
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
        
        # Retrieve the saved thumbnail with extra debug logs
        from database.manager import DatabaseManager
        db_manager = DatabaseManager()
        # Reduced verbose debug logging
        try:
            thumbnail_data = db_manager.get_thumbnail(clean_username, user_id)
        except Exception as e:
            logger.error(f"Error retrieving thumbnail: {e}")
            thumbnail_data = None
        # logger.debug(f"Thumbnail fetch result: {thumbnail_data}")
        
        # DEBUG: If not found, log diagnostics
        if not thumbnail_data:
            logger.warning(f"⚠️ No thumbnail found for channel @{clean_username} (user_id: {user_id})")
        
        # DEBUG: Vérifier quels thumbnails existent pour cet utilisateur
        # logger.debug(f"Checking thumbnails for user_id={user_id}")
        
        if not thumbnail_data:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ No thumbnail saved for @{clean_username}.\n"
                     "Please save a thumbnail first in Settings.",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("⚙️ Go to settings", callback_data="custom_settings"),
                    InlineKeyboardButton("↩️ Back", callback_data="main_menu")
                ]])
            )
            return WAITING_PUBLICATION_CONTENT
        
        # Appliquer le thumbnail au post
        post['thumbnail'] = thumbnail_data
        post['has_custom_thumbnail'] = True

        # Progress message
        progress_msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="🖼️ **Processing with thumbnail...**"
        )

        try:
            # Utiliser la fonction process_thumbnail_and_upload pour traiter le fichier
            from .callback_handlers import process_thumbnail_and_upload
            
            # Forcer l'envoi en document pour tous les types de fichiers
            context.user_data['force_document_for_video'] = True
 
            # Déterminer le nouveau nom de fichier à partir de la légende existante
            try:
                original_filename = post.get('filename')
                caption_text = (post.get('caption') or "").strip()
                if caption_text:
                    # Aplatir les retours à la ligne et nettoyer quelques caractères problématiques
                    flat_caption = " ".join(caption_text.splitlines()).strip()
                    # Retirer les @mentions Telegram (sans toucher aux emails)
                    import re
                    flat_caption = re.sub(r'(?:(?<=\s)|^)(@[A-Za-z0-9_]{5,32})\b', ' ', flat_caption)
                    # Normaliser les espaces
                    flat_caption = re.sub(r'\s+', ' ', flat_caption).strip()
                    flat_caption = flat_caption.replace("/", "-").replace("\\", "-").replace(":", "-")
                    import os
                    ext = os.path.splitext(original_filename or "")[1]
                    if not ext and (post.get('type') == 'video'):
                        ext = ".mp4"
                    new_name = flat_caption
                    # Si la légende devient vide après nettoyage, fallback au nom original
                    if not new_name:
                        new_name = (original_filename or f"file_{post_index}")
                    if ext and not new_name.lower().endswith(ext.lower()):
                        new_name = f"{new_name}{ext}"
                    context.user_data['pending_rename_filename'] = new_name
                else:
                    # Aucune légende: ne pas forcer de renommage explicite ici
                    context.user_data.pop('pending_rename_filename', None)
            except Exception:
                pass
            
            # Appeler la fonction de traitement
            success = await process_thumbnail_and_upload(update, context, post_index)
            
            if success:
                # Le média final a déjà été renvoyé avec boutons par process_thumbnail_and_upload
                # Supprimer le message de progression
                try:
                    await context.bot.delete_message(chat_id=query.message.chat_id, message_id=progress_msg.message_id)
                except Exception:
                    pass
                
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"✅ **Thumbnail applied and file sent as a document!**\n\n"
                         f"The saved thumbnail for @{clean_username} was applied to your {post['type']} "
                         f"and the file was re-sent as a document with edit buttons.",
                    reply_markup=InlineKeyboardMarkup([[ 
                        InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                    ]])
                )
                
                return WAITING_PUBLICATION_CONTENT
            else:
                # En cas d'échec, afficher un message d'erreur
                await context.bot.edit_message_text(
                    chat_id=query.message.chat_id,
                    message_id=progress_msg.message_id,
                    text="❌ **Processing error**\n\nAn error occurred while applying the thumbnail."
                )
                return WAITING_PUBLICATION_CONTENT
                
        except Exception as process_error:
            logger.error(f"Error processing thumbnail: {process_error}")
            await context.bot.edit_message_text(
                chat_id=query.message.chat_id,
                message_id=progress_msg.message_id,
                text=f"❌ **Processing error**\n\n{str(process_error)}"
            )
            return WAITING_PUBLICATION_CONTENT

    except Exception as e:
        logger.error(f"Error in handle_add_thumbnail_to_post: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ An error occurred.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_set_thumbnail_and_rename(update, context):
    """Applies the thumbnail AND lets you rename the file"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Extraire l'index du post
        post_index = int(query.data.split("_")[-1])
        
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Post not found.",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
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
                text="❌ Unable to determine the target channel.",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Récupérer et appliquer le thumbnail
        from database.manager import DatabaseManager
        db_manager = DatabaseManager()
        try:
            thumbnail_file_id = db_manager.get_thumbnail(clean_username, user_id)
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du thumbnail: {e}")
            thumbnail_file_id = None
        
        if thumbnail_file_id:
            post['thumbnail'] = thumbnail_file_id
            thumbnail_status = "✅ Thumbnail applied"
        else:
            thumbnail_status = "⚠️ No thumbnail saved for this channel"
        
        # Stocker l'index pour le renommage
        context.user_data['waiting_for_rename'] = True
        context.user_data['current_post_index'] = post_index
        
        # Demander le nouveau nom
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"🖼️✏️ Thumbnail + Rename\n\n"
                 f"{thumbnail_status}\n\n"
                 f"Now send the new filename (with extension).\n"
                 f"Example: my_document.pdf",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_rename_{post_index}")
            ]])
        )
        
        return WAITING_RENAME_INPUT
        
    except Exception as e:
        logger.error(f"Error in handle_set_thumbnail_and_rename: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ An error occurred.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_view_thumbnail(update, context):
    """Displays the saved thumbnail for a channel"""
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
    
    # Utiliser la fonction de normalisation
    clean_username = normalize_channel_username(channel_username)
    
    from database.manager import DatabaseManager
    import os
    
    db_manager = DatabaseManager()
    try:
        thumbnail_data = db_manager.get_thumbnail(clean_username, user_id)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du thumbnail: {e}")
        thumbnail_data = None
    
    if thumbnail_data:
        try:
            # Essayer d'abord le fichier local s'il existe
            local_path = None
            file_id = None
    
            if isinstance(thumbnail_data, dict):
                local_path = thumbnail_data.get('local_path')
                file_id = thumbnail_data.get('file_id')
            else:
                # Ancien format (juste file_id)
                file_id = thumbnail_data
            
            # Prefer local file if present
            if local_path and os.path.exists(local_path):
                # logger.debug(f"Using local thumbnail file: {local_path}")
                with open(local_path, 'rb') as f:
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=f,
                    caption=f"🖼️ Current thumbnail for @{clean_username} (local file)"
                    )
            elif file_id:
                # logger.debug("Using thumbnail file_id")
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=file_id,
                    caption=f"🖼️ Current thumbnail for @{clean_username} (file_id)"
                )
            else:
                raise Exception("No valid thumbnail found")
            
            keyboard = [
                [InlineKeyboardButton("🔄 Changer", callback_data="add_thumbnail")],
                [InlineKeyboardButton("🗑️ Supprimer", callback_data="delete_thumbnail")],
                [InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")]
            ]
            
            await query.message.reply_text(
                "What would you like to do with this thumbnail?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Error while displaying thumbnail: {e}")
            await query.edit_message_text(
                "❌ Unable to display the thumbnail.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Back", callback_data="thumbnail_menu")
                ]])
            )
    else:
        await query.edit_message_text(
                "❌ No thumbnail saved for this channel.",
            reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Back", callback_data="thumbnail_menu")
            ]])
        )
    
    return SETTINGS


async def handle_delete_thumbnail(update, context):
    """Deletes the saved thumbnail for a channel"""
    query = update.callback_query
    await query.answer()
    
    channel_username = context.user_data.get('custom_channel')
    if not channel_username:
        selected_channel = context.user_data.get('selected_channel', {})
        channel_username = selected_channel.get('username')
    
    if not channel_username:
        await query.edit_message_text(
            "❌ No channel selected.",
            reply_markup=InlineKeyboardMarkup([[ 
                InlineKeyboardButton("↩️ Back", callback_data="custom_settings")
            ]])
        )
        return SETTINGS
    
    user_id = update.effective_user.id
    
    # Utiliser la fonction de normalisation
    clean_username = normalize_channel_username(channel_username)
    
    from database.manager import DatabaseManager
    import os
    
    db_manager = DatabaseManager()
    try:
        # Récupérer le chemin local avant suppression
        thumbnail_data = db_manager.get_thumbnail(clean_username, user_id)
        local_path = None
        if thumbnail_data and isinstance(thumbnail_data, dict):
            local_path = thumbnail_data.get('local_path')
        
        # Supprimer de la base de données
        success = db_manager.delete_thumbnail(clean_username, user_id)
        
        # Supprimer le fichier local s'il existe
        if success and local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
                # logger.debug(f"Local thumbnail file deleted: {local_path}")
            except Exception as file_error:
                logger.warning(f"⚠️ Impossible de supprimer le fichier thumbnail: {file_error}")
                
    except Exception as e:
        logger.error(f"Erreur lors de la suppression du thumbnail: {e}")
        success = False
    
    if success:
        await query.edit_message_text(
            f"✅ Thumbnail deleted for @{clean_username}",
            reply_markup=InlineKeyboardMarkup([[ 
                InlineKeyboardButton("↩️ Back", callback_data="thumbnail_menu")
            ]])
        )
    else:
        await query.edit_message_text(
            "❌ Error while deleting thumbnail.",
            reply_markup=InlineKeyboardMarkup([[ 
                InlineKeyboardButton("↩️ Back", callback_data="thumbnail_menu")
            ]])
        )
    
    return SETTINGS


async def handle_thumbnail_input(update, context):
    """Gère la réception d'une image à utiliser comme thumbnail"""
    try:
        # Vérifier si on attend un thumbnail pour un canal
        if context.user_data.get('waiting_for_channel_thumbnail', False):
            selected_channel = context.user_data.get('selected_channel', {})
            if not selected_channel:
                await update.message.reply_text(
                    "❌ No channel selected.",
                    reply_markup=InlineKeyboardMarkup([[ 
                        InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                    ]])
                )
                return MAIN_MENU
            
            if not update.message.photo:
                await update.message.reply_text(
                    "❌ Please send a photo image for the thumbnail.",
                    reply_markup=InlineKeyboardMarkup([[ 
                        InlineKeyboardButton("↩️ Back", callback_data="thumbnail_menu")
                    ]])
                )
                return WAITING_THUMBNAIL
            
            channel_username = selected_channel.get('username')
            user_id = update.effective_user.id
            
            # Utiliser la fonction de normalisation
            clean_username = normalize_channel_username(channel_username)
            
            if not clean_username:
                await update.message.reply_text(
                    "❌ Error: unable to determine the target channel.",
                    reply_markup=InlineKeyboardMarkup([[ 
                        InlineKeyboardButton("↩️ Back", callback_data="thumbnail_menu")
                    ]])
                )
                return SETTINGS
            
            photo = update.message.photo[-1]  # Prendre la meilleure qualité
            file_size = photo.file_size
            
            # Vérifier la taille du thumbnail
            if file_size > 200 * 1024:
                await update.message.reply_text(
                    f"⚠️ Ce thumbnail fait {file_size / 1024:.1f} KB, ce qui dépasse la limite recommandée de 200 KB.\n"
                    f"Il pourrait ne pas s'afficher correctement.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Utiliser quand même", callback_data="confirm_large_thumbnail")],
                        [InlineKeyboardButton("❌ Réessayer", callback_data="add_thumbnail")]
                    ])
                )
                context.user_data['temp_thumbnail'] = photo.file_id
                return WAITING_THUMBNAIL
            
            # Télécharger le thumbnail localement
            import os
            import time
            
            # Créer le répertoire thumbnails s'il n'existe pas
            thumbnails_dir = os.path.join(os.path.dirname(__file__), '..', 'thumbnails')
            os.makedirs(thumbnails_dir, exist_ok=True)
            
            # Générer un nom de fichier unique
            timestamp = int(time.time())
            local_filename = f"thumb_{user_id}_{clean_username}_{timestamp}.jpg"
            local_path = os.path.join(thumbnails_dir, local_filename)
            
            try:
                # Télécharger le fichier
                file_obj = await context.bot.get_file(photo.file_id)
                await file_obj.download_to_drive(local_path)
                
                # logger.debug(f"Thumbnail downloaded: {local_path}")
                
                # Enregistrer le thumbnail dans la base de données (file_id + local_path)
                from database.manager import DatabaseManager
                db_manager = DatabaseManager()
                success = db_manager.save_thumbnail(clean_username, user_id, photo.file_id, local_path)
                
            except Exception as e:
                logger.error(f"Erreur lors du téléchargement/enregistrement du thumbnail: {e}")
                success = False
                
            if success:
                # logger.debug(f"Thumbnail saved: user_id={user_id}, channel={clean_username}")
                context.user_data['waiting_for_channel_thumbnail'] = False
                
                await update.message.reply_text(
                    f"✅ Thumbnail saved successfully for @{clean_username}!",
                    reply_markup=InlineKeyboardMarkup([[ 
                        InlineKeyboardButton("↩️ Back", callback_data=f"custom_channel_{clean_username}")
                    ]])
                )
                
                return SETTINGS
            else:
                await update.message.reply_text(
                    "❌ Error while saving the thumbnail.",
                    reply_markup=InlineKeyboardMarkup([[ 
                        InlineKeyboardButton("↩️ Back", callback_data=f"custom_channel_{clean_username}")
                    ]])
                )
                return SETTINGS
        
        # Ancien code pour la compatibilité
        elif context.user_data.get('waiting_for_thumbnail', False):
            # Code existant pour l'ancien système global
            photo = update.message.photo[-1]
            context.user_data['user_thumbnail'] = photo.file_id
            context.user_data['waiting_for_thumbnail'] = False
            
            await update.message.reply_text(
                "✅ Thumbnail saved!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Back", callback_data="custom_settings")
                ]])
            )
            return SETTINGS
        
        else:
            await update.message.reply_text(
                "❌ I am not expecting a thumbnail right now.",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
    
    except Exception as e:
        logger.error(f"Error while processing thumbnail: {e}")
        await update.message.reply_text(
            "❌ An error occurred while processing your image.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_add_thumbnail(update, context):
    """Ajoute un nouveau thumbnail pour un canal"""
    channel_username = context.user_data.get('custom_channel')
    if not channel_username:
        # Fallback vers selected_channel
        selected_channel = context.user_data.get('selected_channel', {})
        channel_username = selected_channel.get('username')
        
    if not channel_username:
        await update.callback_query.edit_message_text("No channel selected.")
        return SETTINGS
    
    user_id = update.effective_user.id
    # Nettoyer le nom d'utilisateur du canal (enlever @ s'il est présent)
    clean_username = normalize_channel_username(channel_username)
    
    # **NOUVELLE VÉRIFICATION** : Empêcher l'ajout de plusieurs thumbnails
    from database.manager import DatabaseManager
    db_manager = DatabaseManager()
    existing_thumbnail = db_manager.get_thumbnail(clean_username, user_id)
    if existing_thumbnail:
        await update.callback_query.edit_message_text(
        f"⚠️ A thumbnail is already saved for @{clean_username}.\n\n"
        f"To change the thumbnail, you must first delete the existing one via the thumbnail management menu.",
            reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Back", callback_data=f"custom_channel_{clean_username}")
            ]])
        )
        return SETTINGS
    
    # Stocker le canal pour le traitement du thumbnail
    context.user_data['selected_channel'] = {'username': channel_username}
    context.user_data['waiting_for_channel_thumbnail'] = True
    
    await update.callback_query.edit_message_text(
        f"📷 Send the image to use as the thumbnail for @{channel_username}.\n\n"
        "The image must be under 200 KB.",
        reply_markup=InlineKeyboardMarkup([[ 
            InlineKeyboardButton("❌ Cancel", callback_data=f"custom_channel_{clean_username}")
        ]])
    )
    return WAITING_THUMBNAIL 
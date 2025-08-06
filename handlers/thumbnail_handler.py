"""
Gestionnaire des fonctions de thumbnail pour le bot Telegram
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
    """Affiche les options de gestion des thumbnails pour un canal"""
    query = update.callback_query
    await query.answer()
    
    # Récupérer le canal sélectionné
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
    
    # Nettoyer le nom d'utilisateur du canal (enlever @ s'il est présent)
    clean_username = normalize_channel_username(channel_username)
    
    # Vérifier si un thumbnail existe déjà - utiliser DatabaseManager() directement
    from database.manager import DatabaseManager
    db_manager = DatabaseManager()
    try:
        existing_thumbnail = db_manager.get_thumbnail(clean_username, user_id)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du thumbnail: {e}")
        existing_thumbnail = None
    
    keyboard = []
    
    if existing_thumbnail:
        keyboard.append([InlineKeyboardButton("👁️ Voir le thumbnail actuel", callback_data="view_thumbnail")])
        keyboard.append([InlineKeyboardButton("🔄 Changer le thumbnail", callback_data="add_thumbnail")])
        keyboard.append([InlineKeyboardButton("🗑️ Supprimer le thumbnail", callback_data="delete_thumbnail")])
    else:
        keyboard.append([InlineKeyboardButton("➕ Ajouter un thumbnail", callback_data="add_thumbnail")])
    
    keyboard.append([InlineKeyboardButton("↩️ Retour", callback_data=f"custom_channel_{clean_username}")])
    
    message = f"🖼️ Gestion du thumbnail pour @{clean_username}\n\n"
    message += "✅ Thumbnail enregistré" if existing_thumbnail else "❌ Aucun thumbnail enregistré"
    
    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return SETTINGS


async def handle_add_thumbnail_to_post(update, context):
    """Applique automatiquement le thumbnail enregistré à un post"""
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
        
        # Récupérer le thumbnail enregistré avec logs de debug améliorés
        from database.manager import DatabaseManager
        db_manager = DatabaseManager()
        logger.info(f"RECHERCHE THUMBNAIL: user_id={user_id}, canal_original='{channel_username}', canal_nettoye='{clean_username}'")
        try:
            thumbnail_file_id = db_manager.get_thumbnail(clean_username, user_id)
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du thumbnail: {e}")
            thumbnail_file_id = None
        logger.info(f"RESULTAT THUMBNAIL: {thumbnail_file_id}")
        
        # DEBUG: Si pas trouvé, faire un diagnostic complet
        if not thumbnail_file_id:
            logger.warning(f"⚠️ Aucun thumbnail trouvé pour le canal @{clean_username} (user_id: {user_id})")
        
        # DEBUG: Vérifier quels thumbnails existent pour cet utilisateur
        logger.info(f"DEBUG: Vérification de tous les thumbnails pour user_id={user_id}")
        
        if not thumbnail_file_id:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ Aucun thumbnail enregistré pour @{clean_username}.\n"
                     "Veuillez d'abord enregistrer un thumbnail via les paramètres.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⚙️ Aller aux paramètres", callback_data="custom_settings"),
                    InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
                ]])
            )
            return WAITING_PUBLICATION_CONTENT
        
        # Appliquer le thumbnail au post
        post['thumbnail'] = thumbnail_file_id

        # Envoyer l'aperçu à jour avec une fonction de prévisualisation simplifiée
        try:
            # Créer un aperçu simple sans import circulaire
            if post['type'] == 'photo':
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=post['content'],
                    caption=f"✅ Thumbnail appliqué!\nType: {post['type']}"
                )
            elif post['type'] == 'video':
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=post['content'],
                    caption=f"✅ Thumbnail appliqué!\nType: {post['type']}"
                )
            elif post['type'] == 'document':
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=post['content'],
                    caption=f"✅ Thumbnail appliqué!\nType: {post['type']}"
                )
        except Exception as preview_error:
            logger.warning(f"Erreur aperçu: {preview_error}")

        # Mettre à jour le message pour confirmer
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"✅ Thumbnail appliqué au post!\n\n"
                 f"Le thumbnail enregistré pour @{clean_username} a été ajouté à votre {post['type']}.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        
        return WAITING_PUBLICATION_CONTENT
        
    except Exception as e:
        logger.error(f"Erreur dans handle_add_thumbnail_to_post: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


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
        from database.manager import DatabaseManager
        db_manager = DatabaseManager()
        try:
            thumbnail_file_id = db_manager.get_thumbnail(clean_username, user_id)
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du thumbnail: {e}")
            thumbnail_file_id = None
        
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
            
            # Priorité au fichier local
            if local_path and os.path.exists(local_path):
                logger.info(f"📁 Utilisation du fichier local: {local_path}")
                with open(local_path, 'rb') as f:
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=f,
                        caption=f"🖼️ Thumbnail actuel pour @{clean_username} (fichier local)"
                    )
            elif file_id:
                logger.info(f"📱 Utilisation du file_id: {file_id[:30]}...")
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=file_id,
                    caption=f"🖼️ Thumbnail actuel pour @{clean_username} (file_id)"
                )
            else:
                raise Exception("Aucun thumbnail valide trouvé")
            
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
                logger.info(f"✅ Fichier thumbnail supprimé: {local_path}")
            except Exception as file_error:
                logger.warning(f"⚠️ Impossible de supprimer le fichier thumbnail: {file_error}")
                
    except Exception as e:
        logger.error(f"Erreur lors de la suppression du thumbnail: {e}")
        success = False
    
    if success:
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


async def handle_thumbnail_input(update, context):
    """Gère la réception d'une image à utiliser comme thumbnail"""
    try:
        # Vérifier si on attend un thumbnail pour un canal
        if context.user_data.get('waiting_for_channel_thumbnail', False):
            selected_channel = context.user_data.get('selected_channel', {})
            if not selected_channel:
                await update.message.reply_text(
                    "❌ Aucun canal sélectionné.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                    ]])
                )
                return MAIN_MENU
            
            if not update.message.photo:
                await update.message.reply_text(
                    "❌ Merci d'envoyer une photo (image) pour la miniature.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
                    ]])
                )
                return WAITING_THUMBNAIL
            
            channel_username = selected_channel.get('username')
            user_id = update.effective_user.id
            
            # Utiliser la fonction de normalisation
            clean_username = normalize_channel_username(channel_username)
            
            if not clean_username:
                await update.message.reply_text(
                    "❌ Erreur: impossible de déterminer le canal cible.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
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
                
                logger.info(f"✅ Thumbnail téléchargé localement: {local_path}")
                
                # Enregistrer le thumbnail dans la base de données (file_id + local_path)
                from database.manager import DatabaseManager
                db_manager = DatabaseManager()
                success = db_manager.save_thumbnail(clean_username, user_id, photo.file_id, local_path)
                
            except Exception as e:
                logger.error(f"Erreur lors du téléchargement/enregistrement du thumbnail: {e}")
                success = False
                
            if success:
                logger.info(f"ENREGISTREMENT: user_id={user_id}, channel={clean_username}, file_id={photo.file_id}")
                context.user_data['waiting_for_channel_thumbnail'] = False
                
                await update.message.reply_text(
                    f"✅ Thumbnail enregistré avec succès pour @{clean_username}!",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data=f"custom_channel_{clean_username}")
                    ]])
                )
                
                return SETTINGS
            else:
                await update.message.reply_text(
                    "❌ Erreur lors de l'enregistrement du thumbnail.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data=f"custom_channel_{clean_username}")
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
                "✅ Thumbnail enregistré!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")
                ]])
            )
            return SETTINGS
        
        else:
            await update.message.reply_text(
                "❌ Je n'attends pas de thumbnail actuellement.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
    
    except Exception as e:
        logger.error(f"Erreur lors du traitement du thumbnail: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors du traitement de votre image.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
        await update.callback_query.edit_message_text("Aucun canal sélectionné.")
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
            f"⚠️ Un thumbnail est déjà enregistré pour @{clean_username}.\n\n"
            f"Pour changer le thumbnail, vous devez d'abord supprimer l'ancien via le menu de gestion des thumbnails.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data=f"custom_channel_{clean_username}")
            ]])
        )
        return SETTINGS
    
    # Stocker le canal pour le traitement du thumbnail
    context.user_data['selected_channel'] = {'username': channel_username}
    context.user_data['waiting_for_channel_thumbnail'] = True
    
    await update.callback_query.edit_message_text(
        f"📷 Envoyez-moi l'image à utiliser comme thumbnail pour @{channel_username}.\n\n"
        "L'image doit faire moins de 200 KB.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Annuler", callback_data=f"custom_channel_{clean_username}")
        ]])
    )
    return WAITING_THUMBNAIL 
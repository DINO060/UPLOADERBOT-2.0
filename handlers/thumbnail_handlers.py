"""
THUMBNAIL HANDLERS
==================
Handlers for thumbnail management (view, add, delete, apply).
Extracted from bot.py for better code organization.
"""

import os
import logging
import tempfile
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from conversation_states import MAIN_MENU, SETTINGS, WAITING_RENAME_INPUT, WAITING_THUMBNAIL_RENAME_INPUT, WAITING_PUBLICATION_CONTENT
from database.manager import DatabaseManager

logger = logging.getLogger("handlers.thumbnail")


# ============================================================
# UTILITAIRES
# ============================================================

def normalize_channel_username(channel_username: str) -> str:
    """
    Normalise le nom d'utilisateur d'un canal en enlevant le @ s'il est présent.

    Args:
        channel_username: Nom du canal (avec ou sans @)

    Returns:
        str: Nom du canal sans @, ou None si vide
    """
    if not channel_username:
        return None
    username = str(channel_username).strip()
    if username.startswith('@'):
        return username[1:]
    elif username.startswith('t.me/'):
        return username[5:]
    return username


def is_valid_channel_username(username: str) -> bool:
    """
    Vérifie que le username est valide (commence par @ ou t.me/).

    Args:
        username: Nom du canal à valider

    Returns:
        bool: True si valide
    """
    if not username:
        return False
    username = username.strip()
    return (username.startswith('@') or username.startswith('t.me/')) and ' ' not in username


# ============================================================
# DATABASE TABLE SETUP
# ============================================================

def ensure_channel_thumbnails_table(db_manager: DatabaseManager) -> bool:
    """
    S'assure que la table channel_thumbnails existe dans la base de données.

    Args:
        db_manager: Instance du DatabaseManager

    Returns:
        bool: True si la table existe ou a été créée
    """
    try:
        cursor = db_manager.connection.cursor()

        # Vérifier si la table existe
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='channel_thumbnails'"
        )
        table_exists = cursor.fetchone() is not None

        if not table_exists:
            logger.info("Table channel_thumbnails manquante - création...")
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
            logger.info("Table channel_thumbnails créée!")
        else:
            logger.debug("Table channel_thumbnails existe déjà")

        return True
    except Exception as e:
        logger.error(f"Erreur lors de la vérification de channel_thumbnails: {e}")
        return False


# ============================================================
# HANDLERS PRINCIPAUX
# ============================================================

async def handle_view_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Affiche le thumbnail enregistré pour un canal.

    Returns:
        int: SETTINGS state
    """
    query = update.callback_query
    await query.answer()

    # Récupérer le canal
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
    clean_username = normalize_channel_username(channel_username)

    db_manager = DatabaseManager()
    thumbnail_file_id = db_manager.get_thumbnail(clean_username, user_id)

    if thumbnail_file_id:
        try:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=thumbnail_file_id,
                caption=f"🖼️ Current thumbnail for @{clean_username}"
            )

            keyboard = [
                [InlineKeyboardButton("🔄 Change", callback_data="add_thumbnail")],
                [InlineKeyboardButton("🗑️ Delete", callback_data="delete_thumbnail")],
                [InlineKeyboardButton("↩️ Back", callback_data="thumbnail_menu")]
            ]

            await query.message.reply_text(
                "What would you like to do with this thumbnail?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Error displaying thumbnail: {e}")
            await query.edit_message_text(
                "❌ Unable to display thumbnail.",
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


async def handle_delete_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Supprime le thumbnail enregistré pour un canal.

    Returns:
        int: SETTINGS state
    """
    query = update.callback_query
    await query.answer()

    # Récupérer le canal
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
    clean_username = normalize_channel_username(channel_username)

    db_manager = DatabaseManager()
    if db_manager.delete_thumbnail(clean_username, user_id):
        await query.edit_message_text(
            f"✅ Thumbnail deleted for @{clean_username}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Back", callback_data="thumbnail_menu")
            ]])
        )
    else:
        await query.edit_message_text(
            "❌ Error deleting thumbnail.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Back", callback_data="thumbnail_menu")
            ]])
        )

    return SETTINGS


async def handle_set_thumbnail_and_rename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Applique le thumbnail ET permet de renommer le fichier.

    Returns:
        int: WAITING_RENAME_INPUT ou MAIN_MENU
    """
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

        clean_username = normalize_channel_username(channel_username)

        if not clean_username:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Unable to determine target channel.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        # Récupérer et appliquer le thumbnail
        db_manager = DatabaseManager()
        thumbnail_file_id = db_manager.get_thumbnail(clean_username, user_id)

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
                 f"Please send the new filename (with extension).\n"
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


async def handle_add_thumbnail_and_rename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère le bouton 'Add Thumbnail + Rename'.
    Reproduit la fonctionnalité du renambot avec affichage MEDIA INFO.

    Returns:
        int: WAITING_THUMBNAIL_RENAME_INPUT ou MAIN_MENU
    """
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

        clean_username = normalize_channel_username(channel_username)

        if not clean_username:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Unable to determine target channel.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        # Récupérer le thumbnail
        db_manager = DatabaseManager()
        thumbnail_file_id = db_manager.get_thumbnail(clean_username, user_id)

        if not thumbnail_file_id:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ **No thumbnail registered**\n\n"
                     f"No thumbnail found for @{clean_username}.\n"
                     f"Please configure a thumbnail in settings first.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]]),
                parse_mode="Markdown"
            )
            return MAIN_MENU

        # Créer la carte MEDIA INFO (comme renambot)
        file_type = post.get('type', 'unknown')
        filename = post.get('filename', 'unnamed_file')
        file_size = post.get('file_size', 'Unknown')
        extension = os.path.splitext(filename)[1] or "Unknown"
        mime_type = post.get('mime_type', 'Unknown')
        dc_id = post.get('dc_id', 'N/A')

        info_card = f"""📁 <b>MEDIA INFO</b>

📁 <b>FILE NAME:</b> <code>{filename}</code>
🧩 <b>EXTENSION:</b> <code>{extension}</code>
📦 <b>FILE SIZE:</b> {file_size}
🪄 <b>MIME TYPE:</b> {mime_type}
🧭 <b>DC ID:</b> {dc_id}

<b>PLEASE ENTER THE NEW FILENAME WITH EXTENSION AND REPLY THIS MESSAGE.</b>"""

        # Stocker l'index pour le traitement
        context.user_data['awaiting_thumb_rename'] = True
        context.user_data['current_post_index'] = post_index
        context.user_data['waiting_for_rename'] = True

        # Envoyer le message
        ask_msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=info_card,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_thumbnail_rename_{post_index}")
            ]])
        )

        # Stocker l'ID du message
        context.user_data['thumbnail_rename_prompt_message_id'] = ask_msg.message_id
        context.user_data['rename_prompt_message_id'] = ask_msg.message_id
        context.user_data['rename_prompt_chat_id'] = query.message.chat_id

        return WAITING_THUMBNAIL_RENAME_INPUT

    except Exception as e:
        logger.error(f"Error in handle_add_thumbnail_and_rename: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ An error occurred.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


# ============================================================
# DOWNLOAD & UPLOAD WITH THUMBNAIL
# ============================================================

async def download_and_upload_with_thumbnail(
    context: ContextTypes.DEFAULT_TYPE,
    file_id: str,
    new_filename: str,
    thumbnail_path: str,
    chat_id: int,
    post_type: str
):
    """
    Télécharge un fichier et le re-upload avec thumbnail et nouveau nom.

    Args:
        context: Contexte Telegram
        file_id: ID du fichier à télécharger
        new_filename: Nouveau nom du fichier
        thumbnail_path: Chemin vers le thumbnail
        chat_id: ID du chat
        post_type: Type de fichier (photo, video, document)

    Returns:
        Message: Le message envoyé avec le fichier
    """
    temp_file = None
    progress_msg = None

    try:
        # Créer un nom de fichier temporaire unique
        temp_filename = f"temp_{uuid.uuid4().hex[:8]}"
        temp_file = os.path.join(tempfile.gettempdir(), temp_filename)

        # Message de progression
        progress_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="🖼️ **Processing with thumbnail...**"
        )

        # Étape 1: Télécharger
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=progress_msg.message_id,
            text="📥 **Downloading file...**"
        )

        file_info = await context.bot.get_file(file_id)
        downloaded_path = await file_info.download_to_drive(temp_file)

        if not downloaded_path or not os.path.exists(downloaded_path):
            raise Exception("File download failed")

        # Étape 2: Upload avec thumbnail
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=progress_msg.message_id,
            text="📤 **Uploading with thumbnail...**"
        )

        # Ouvrir le thumbnail si disponible
        thumb = None
        if thumbnail_path and os.path.exists(thumbnail_path):
            thumb = open(thumbnail_path, 'rb')

        try:
            if post_type == 'photo':
                sent_message = await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=open(downloaded_path, 'rb'),
                    caption=f"<code>{new_filename}</code>",
                    parse_mode="HTML",
                    filename=new_filename
                )
            elif post_type == 'video':
                sent_message = await context.bot.send_video(
                    chat_id=chat_id,
                    video=open(downloaded_path, 'rb'),
                    caption=f"<code>{new_filename}</code>",
                    parse_mode="HTML",
                    filename=new_filename,
                    thumbnail=thumb
                )
            elif post_type == 'document':
                sent_message = await context.bot.send_document(
                    chat_id=chat_id,
                    document=open(downloaded_path, 'rb'),
                    caption=f"<code>{new_filename}</code>",
                    parse_mode="HTML",
                    filename=new_filename,
                    thumbnail=thumb
                )
            else:
                # Type par défaut: document
                sent_message = await context.bot.send_document(
                    chat_id=chat_id,
                    document=open(downloaded_path, 'rb'),
                    caption=f"<code>{new_filename}</code>",
                    parse_mode="HTML",
                    filename=new_filename,
                    thumbnail=thumb
                )
        finally:
            if thumb:
                thumb.close()

        # Supprimer le message de progression
        await context.bot.delete_message(chat_id=chat_id, message_id=progress_msg.message_id)

        return sent_message

    except Exception as e:
        logger.error(f"Error in download_and_upload_with_thumbnail: {e}")
        if progress_msg:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_msg.message_id,
                    text=f"❌ **Error during processing**\n\n{str(e)}"
                )
            except:
                pass
        raise e
    finally:
        # Nettoyer le fichier temporaire
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "normalize_channel_username",
    "is_valid_channel_username",
    "ensure_channel_thumbnails_table",
    "handle_view_thumbnail",
    "handle_delete_thumbnail",
    "handle_set_thumbnail_and_rename",
    "handle_add_thumbnail_and_rename",
    "download_and_upload_with_thumbnail",
]

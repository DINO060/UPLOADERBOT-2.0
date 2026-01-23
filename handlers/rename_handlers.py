"""
RENAME HANDLERS
===============
Handlers for file renaming functionality.
Extracted from bot.py for better code organization.
"""

import os
import logging
import json
import asyncio
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from conversation_states import MAIN_MENU, WAITING_RENAME_INPUT, WAITING_THUMBNAIL_RENAME_INPUT, WAITING_PUBLICATION_CONTENT
from database.manager import DatabaseManager

logger = logging.getLogger("handlers.rename")

# Chemin pour les statistiques de renommage
BASE_DIR = Path(__file__).resolve().parent.parent
RENAME_STATS_PATH = BASE_DIR / "rename_stats.json"

# Lock pour accès concurrent
rename_stats_lock = asyncio.Lock()


# ============================================================
# STATISTIQUES DE RENOMMAGE
# ============================================================

def _ensure_rename_stats_file():
    """S'assure que le fichier de stats existe."""
    if not RENAME_STATS_PATH.exists():
        data = {"total_files_renamed": 0, "total_storage_bytes": 0}
        RENAME_STATS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def load_rename_stats() -> dict:
    """
    Charge les statistiques de renommage depuis le fichier JSON.

    Returns:
        dict: Statistiques avec total_files_renamed et total_storage_bytes
    """
    _ensure_rename_stats_file()
    try:
        return json.loads(RENAME_STATS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"total_files_renamed": 0, "total_storage_bytes": 0}


async def add_rename_stat(file_size_bytes: int) -> None:
    """
    Ajoute une statistique de renommage.

    Args:
        file_size_bytes: Taille du fichier renommé en bytes
    """
    _ensure_rename_stats_file()
    async with rename_stats_lock:
        try:
            data = json.loads(RENAME_STATS_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {"total_files_renamed": 0, "total_storage_bytes": 0}

        data["total_files_renamed"] = int(data.get("total_files_renamed", 0)) + 1
        inc = int(file_size_bytes or 0)
        data["total_storage_bytes"] = int(data.get("total_storage_bytes", 0)) + max(0, inc)

        RENAME_STATS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def format_bytes(num_bytes: float) -> str:
    """
    Formate une taille en bytes en format lisible.

    Args:
        num_bytes: Nombre de bytes

    Returns:
        str: Taille formatée (ex: "1.5 GB")
    """
    try:
        num = float(num_bytes or 0)
    except Exception:
        num = 0.0
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while num >= 1024 and idx < len(units) - 1:
        num /= 1024.0
        idx += 1
    return f"{num:.2f} {units[idx]}"


# ============================================================
# HANDLER PRINCIPAL
# ============================================================

async def handle_rename_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère la saisie du nouveau nom de fichier.

    Flow:
        1. Vérifie qu'un renommage est en cours
        2. Valide le nom de fichier
        3. Applique le nouveau nom au post
        4. Met à jour l'aperçu avec le nouveau nom
        5. Enregistre les statistiques

    Returns:
        int: WAITING_PUBLICATION_CONTENT ou MAIN_MENU
    """
    try:
        # Vérifier qu'un renommage est en cours
        if not context.user_data.get('waiting_for_rename') or 'current_post_index' not in context.user_data:
            await update.message.reply_text(
                "❌ No rename in progress.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        post_index = context.user_data['current_post_index']
        new_filename = update.message.text.strip()
        user_message_id = update.message.message_id
        user_chat_id = update.effective_chat.id

        # Validation du nom de fichier
        if not new_filename:
            await update.message.reply_text(
                "❌ Please provide a valid filename.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_rename_{post_index}")
                ]])
            )
            return WAITING_RENAME_INPUT

        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await update.message.reply_text(
                "❌ Post not found.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        post = context.user_data['posts'][post_index]
        post['filename'] = new_filename

        # Construire les boutons dynamiques
        keyboard = _build_post_keyboard(post, post_index)
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Supprimer l'ancien aperçu si présent
        preview_info = context.user_data.get('preview_messages', {}).get(post_index)
        if preview_info:
            try:
                await context.bot.delete_message(
                    chat_id=preview_info['chat_id'],
                    message_id=preview_info['message_id']
                )
            except Exception:
                pass

        # Construire la légende avec tag si disponible
        caption_text = _build_caption_with_tag(
            new_filename,
            post,
            context,
            update.effective_user.id
        )

        # Envoyer le média avec nouvelle légende
        sent_message = await _send_renamed_media(
            context,
            update.effective_chat.id,
            post,
            caption_text,
            reply_markup
        )

        # Enregistrer le nouvel aperçu
        if sent_message:
            if 'preview_messages' not in context.user_data:
                context.user_data['preview_messages'] = {}
            context.user_data['preview_messages'][post_index] = {
                'message_id': sent_message.message_id,
                'chat_id': update.effective_chat.id
            }

        # Message de confirmation
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ File renamed: <code>{new_filename}</code>",
                parse_mode="HTML"
            )
        except Exception:
            pass

        # Supprimer le prompt et le message utilisateur
        _cleanup_rename_messages(context, user_chat_id, user_message_id)

        # Mettre à jour les stats si c'est un document
        if post.get('type') == 'document':
            try:
                file_size = int(post.get('file_size') or 0)
                await add_rename_stat(file_size)
            except Exception:
                pass

        # Nettoyer les variables temporaires
        context.user_data.pop('waiting_for_rename', None)
        context.user_data.pop('current_post_index', None)

        return WAITING_PUBLICATION_CONTENT

    except Exception as e:
        logger.error(f"Error in handle_rename_input: {e}")
        await update.message.reply_text(
            "❌ An error occurred.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_thumbnail_rename_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère la saisie du nouveau nom avec thumbnail.
    Redirige vers handle_rename_input pour compatibilité.

    Returns:
        int: Résultat de handle_rename_input
    """
    try:
        return await handle_rename_input(update, context)
    except Exception as e:
        logger.error(f"Error in handle_thumbnail_rename_input: {e}")
        await update.message.reply_text(
            "❌ An error occurred.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


# ============================================================
# FONCTIONS UTILITAIRES
# ============================================================

def _build_post_keyboard(post: dict, post_index: int) -> list:
    """
    Construit le clavier inline pour un post.

    Args:
        post: Données du post
        post_index: Index du post

    Returns:
        list: Liste de boutons pour InlineKeyboardMarkup
    """
    keyboard = []

    # Réactions existantes
    reactions = post.get('reactions') or []
    if reactions:
        current_row = []
        for reaction in reactions:
            current_row.append(
                InlineKeyboardButton(reaction, callback_data=f"r:{reaction}:{post_index}")
            )
            if len(current_row) == 4:
                keyboard.append(current_row)
                current_row = []
        if current_row:
            keyboard.append(current_row)
        keyboard.append([
            InlineKeyboardButton("🗑️ Remove Reactions", callback_data=f"remove_reactions_{post_index}")
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("✨ Add Reactions", callback_data=f"add_reactions_{post_index}")
        ])

    # Boutons URL existants
    for btn in post.get('buttons', []) or []:
        if isinstance(btn, dict) and 'text' in btn and 'url' in btn:
            keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])

    # Boutons d'action
    keyboard.extend([
        [InlineKeyboardButton("🔗 Add URL Button", callback_data=f"add_url_button_{post_index}")],
        [InlineKeyboardButton("✏️ Edit File", callback_data=f"edit_file_{post_index}")],
        [InlineKeyboardButton("❌ Delete", callback_data=f"delete_post_{post_index}")]
    ])

    return keyboard


def _build_caption_with_tag(
    filename: str,
    post: dict,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int
) -> str:
    """
    Construit la légende avec le tag du canal si disponible.

    Args:
        filename: Nom du fichier
        post: Données du post
        context: Contexte Telegram
        user_id: ID de l'utilisateur

    Returns:
        str: Légende avec tag si disponible
    """
    caption_text = filename
    try:
        dbm = DatabaseManager()
        channel_username = post.get('channel') or context.user_data.get('selected_channel', {}).get('username')
        clean_channel = channel_username.lstrip('@') if isinstance(channel_username, str) else None
        tag = dbm.get_channel_tag(clean_channel, user_id) if clean_channel else None
        if tag and str(tag).strip():
            caption_text = f"{filename} {str(tag).strip()}"
    except Exception:
        pass
    return caption_text


async def _send_renamed_media(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    post: dict,
    caption: str,
    reply_markup: InlineKeyboardMarkup
):
    """
    Envoie le média renommé.

    Args:
        context: Contexte Telegram
        chat_id: ID du chat
        post: Données du post
        caption: Légende
        reply_markup: Boutons inline

    Returns:
        Message: Le message envoyé
    """
    post_type = post.get('type', 'text')
    content = post.get('content')

    if post_type == 'photo':
        return await context.bot.send_photo(
            chat_id=chat_id,
            photo=content,
            caption=caption,
            reply_markup=reply_markup
        )
    elif post_type == 'video':
        return await context.bot.send_video(
            chat_id=chat_id,
            video=content,
            caption=caption,
            reply_markup=reply_markup
        )
    elif post_type == 'document':
        return await context.bot.send_document(
            chat_id=chat_id,
            document=content,
            caption=caption,
            reply_markup=reply_markup
        )
    elif post_type == 'text':
        return await context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            reply_markup=reply_markup
        )
    return None


def _cleanup_rename_messages(
    context: ContextTypes.DEFAULT_TYPE,
    user_chat_id: int,
    user_message_id: int
):
    """
    Nettoie les messages temporaires du renommage.

    Args:
        context: Contexte Telegram
        user_chat_id: ID du chat utilisateur
        user_message_id: ID du message utilisateur
    """
    try:
        prompt_msg_id = context.user_data.pop('rename_prompt_message_id', None)
        prompt_chat_id = context.user_data.pop('rename_prompt_chat_id', None)

        async def cleanup():
            if prompt_msg_id and prompt_chat_id:
                try:
                    await context.bot.delete_message(chat_id=prompt_chat_id, message_id=prompt_msg_id)
                except Exception:
                    pass
            try:
                await context.bot.delete_message(chat_id=user_chat_id, message_id=user_message_id)
            except Exception:
                pass

        # Planifier le nettoyage
        asyncio.create_task(cleanup())
    except Exception:
        pass


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "load_rename_stats",
    "add_rename_stat",
    "format_bytes",
    "handle_rename_input",
    "handle_thumbnail_rename_input",
]

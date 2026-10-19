"""
RENAME HANDLERS
===============
Handlers for file renaming functionality.
Extracted from bot.py for better code organization.
"""

import os
import html
import logging
import json
import asyncio
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from conversation_states import MAIN_MENU, WAITING_RENAME_INPUT, WAITING_THUMBNAIL_RENAME_INPUT, WAITING_PUBLICATION_CONTENT
from database.manager import DatabaseManager
from i18n import get_user_lang, t
from utils.file_rename import reupload, with_extension

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

        # The caption is what the preview shows: the new name + the channel's tag (it used to stay the old one)
        caption_text = _build_caption_with_tag(
            new_filename,
            post,
            context,
            update.effective_user.id
        )
        if post.get('type') == 'text':
            post['content'] = caption_text
        else:
            post['caption'] = caption_text

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

        lang = get_user_lang(update.effective_user.id)
        if post.get('type') in ('document', 'video'):
            # The file itself is sent again under its new name, in the background (a big file takes minutes)
            start_rename(context.bot, user_chat_id, context.user_data, post_index, post,
                         with_extension(new_filename, post.get('filename')), lang)
        else:
            post['filename'] = new_filename
            await show_preview(context.bot, user_chat_id, context.user_data, post_index, post)
            await _say(context.bot, user_chat_id, t(lang, "rename.done", name=html.escape(new_filename)))

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
# RENOMMAGE RÉEL (en arrière-plan)
# ============================================================

_running = set()     # renames in progress (a task nobody holds can be garbage-collected)


def start_rename(bot, chat_id: int, user_data: dict, post_index: int, post: dict, file_name: str, lang: str):
    """The file is sent again under its new name in the background; until then the post is marked « renaming »
    and « 🚀 Send » waits for it."""
    post['renaming'] = True
    task = asyncio.create_task(_rename(bot, chat_id, user_data, post_index, post, file_name, lang))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return task


async def _rename(bot, chat_id: int, user_data: dict, post_index: int, post: dict, file_name: str, lang: str):
    number = post_index + 1
    status = None
    try:
        status = await bot.send_message(chat_id=chat_id, text=t(lang, "rename.download", index=number, pct=0))
    except Exception:
        pass

    async def on_progress(phase, pct):
        if status:
            try:
                await status.edit_text(t(lang, f"rename.{phase}", index=number, pct=pct))
            except Exception:
                pass

    old_name = post.get('filename')
    try:
        post['content'] = await reupload(bot, chat_id, post, file_name, on_progress)
        post['filename'] = file_name
        done = t(lang, "rename.done", name=html.escape(file_name))
    except Exception as e:
        logger.exception(f"Rename of file {number} failed: {e}")
        post['filename'] = old_name
        done = t(lang, "rename.failed", index=number, error=html.escape(str(e)[:200]))
    finally:
        post['renaming'] = False
    if status:
        try:
            await status.delete()
        except Exception:
            pass
    # where the post is now (another one may have been deleted meanwhile); gone → nothing to show
    index = next((i for i, p in enumerate(user_data.get('posts') or []) if p is post), None)
    if index is None:
        return
    await show_preview(bot, chat_id, user_data, index, post)
    await _say(bot, chat_id, done)


async def show_preview(bot, chat_id: int, user_data: dict, post_index: int, post: dict):
    """The post shown again, as it will be published, in place of its previous preview."""
    preview_info = user_data.get('preview_messages', {}).get(post_index)
    if preview_info:
        try:
            await bot.delete_message(chat_id=preview_info['chat_id'], message_id=preview_info['message_id'])
        except Exception:
            pass
    text = post.get('content') if post.get('type') == 'text' else post.get('caption')
    try:
        sent = await _send_renamed_media(bot, chat_id, post, text or '',
                                         InlineKeyboardMarkup(_build_post_keyboard(post, post_index)))
    except Exception as e:
        logger.warning(f"Preview of file {post_index + 1} not sent: {e}")
        return None
    if sent:
        user_data.setdefault('preview_messages', {})[post_index] = {'message_id': sent.message_id, 'chat_id': chat_id}
    return sent


async def _say(bot, chat_id: int, text: str):
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception:
        pass


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
    bot,
    chat_id: int,
    post: dict,
    caption: str,
    reply_markup: InlineKeyboardMarkup
):
    """
    Envoie le média renommé.

    Args:
        bot: le bot Telegram
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
        return await bot.send_photo(
            chat_id=chat_id,
            photo=content,
            caption=caption,
            reply_markup=reply_markup
        )
    elif post_type == 'video':
        return await bot.send_video(
            chat_id=chat_id,
            video=content,
            caption=caption,
            reply_markup=reply_markup
        )
    elif post_type == 'document':
        return await bot.send_document(
            chat_id=chat_id,
            document=content,
            caption=caption,
            reply_markup=reply_markup
        )
    elif post_type == 'text':
        return await bot.send_message(
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

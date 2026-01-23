"""
KEYBOARD HANDLERS
=================
Handlers for ReplyKeyboard buttons (Preview, Send, Delete All, Cancel).
Extracted from bot.py for better code organization.
"""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes, filters

from conversation_states import MAIN_MENU, WAITING_PUBLICATION_CONTENT

logger = logging.getLogger("handlers.keyboard")


# ============================================================
# CONFIGURATION DES BOUTONS
# ============================================================

# Labels des boutons ReplyKeyboard (anglais)
REPLY_KEYBOARD_BUTTONS = ["📋 Preview", "🚀 Send", "🗑️ Delete all", "❌ Cancel"]


# ============================================================
# FILTRE POUR LES BOUTONS
# ============================================================

class ReplyKeyboardButtonFilter(filters.MessageFilter):
    """Filtre intelligent pour détecter les boutons ReplyKeyboard (FR et EN)."""

    def filter(self, message):
        if not message.text:
            return False
        text = message.text.strip().lower()
        # Mots-clés en français et anglais
        keywords = [
            "aperçu", "envoyer", "tout supprimer", "annuler",
            "preview", "send", "delete all", "cancel"
        ]
        return any(keyword in text for keyword in keywords)


# Instance du filtre
reply_keyboard_filter = filters.TEXT & ReplyKeyboardButtonFilter()


# ============================================================
# CRÉATION DU CLAVIER
# ============================================================

def create_reply_keyboard() -> ReplyKeyboardMarkup:
    """
    Crée le clavier de réponse standard pour la publication.

    Layout:
        [📋 Preview] [🚀 Send]
        [🗑️ Delete all] [❌ Cancel]
    """
    keyboard = [
        [KeyboardButton("📋 Preview"), KeyboardButton("🚀 Send")],
        [KeyboardButton("🗑️ Delete all"), KeyboardButton("❌ Cancel")]
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False
    )


# ============================================================
# HANDLER PRINCIPAL
# ============================================================

async def handle_reply_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère TOUS les boutons ReplyKeyboard de manière intelligente.

    Boutons supportés:
        - Preview / Aperçu: Affiche un aperçu des posts en attente
        - Send / Envoyer: Ouvre le menu d'envoi
        - Delete all / Tout supprimer: Supprime tous les posts
        - Cancel / Annuler: Annule l'opération en cours

    Returns:
        int: Le prochain état de la conversation
    """
    try:
        user_text = update.message.text.strip()

        # Récupérer le contexte utilisateur
        posts = context.user_data.get("posts", [])
        selected_channel = context.user_data.get('selected_channel', {})

        # ===== PREVIEW =====
        if any(k in user_text.lower() for k in ["aperçu", "preview"]):
            return await _handle_preview(update, context, posts)

        # ===== SEND =====
        elif any(k in user_text.lower() for k in ["envoyer", "send"]):
            return await handle_send_button(update, context)

        # ===== DELETE ALL =====
        elif any(k in user_text.lower() for k in ["tout supprimer", "delete all"]):
            return await _handle_delete_all(update, context, posts)

        # ===== CANCEL =====
        elif any(k in user_text.lower() for k in ["annuler", "cancel"]):
            return await _handle_cancel(update, context)

        # ===== FALLBACK =====
        await update.message.reply_text(
            "❓ **Unknown button**\n\nUse the available buttons below.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

    except Exception as e:
        logger.error(f"Error in handle_reply_keyboard: {e}")
        await update.message.reply_text(
            "❌ An error occurred.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


# ============================================================
# SOUS-HANDLERS
# ============================================================

async def _handle_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, posts: list) -> int:
    """Gère le bouton Preview."""
    if not posts:
        await update.message.reply_text(
            "🔍 **Preview unavailable**\n\nNo draft posts are currently being created.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]]),
            parse_mode='Markdown'
        )
        return MAIN_MENU

    # Afficher l'aperçu détaillé des posts
    for i, post in enumerate(posts):
        try:
            preview_text = "The post preview sent above.\n\n"
            preview_text += "You have 1 message in this post:\n"

            # Déterminer le type d'icône selon le type de fichier
            post_type = post.get('type', 'text')
            type_icons = {
                'photo': '📸 Photo',
                'video': '📹 Video',
                'document': '📄 Document',
                'text': '📝 Text'
            }
            preview_text += f"1. {type_icons.get(post_type, '📝 Text')}"

            # Ajouter l'heure actuelle
            current_time = datetime.now().strftime("%I:%M %p")
            preview_text += f" {current_time}"

            if post_type == 'text':
                await update.message.reply_text(preview_text)
            else:
                # Envoyer le fichier sans caption
                chat_id = update.effective_chat.id
                content = post.get('content')

                if post_type == 'photo':
                    await context.bot.send_photo(chat_id=chat_id, photo=content)
                elif post_type == 'video':
                    await context.bot.send_video(chat_id=chat_id, video=content)
                elif post_type == 'document':
                    await context.bot.send_document(chat_id=chat_id, document=content)

                # Puis envoyer le message texte
                await context.bot.send_message(chat_id=chat_id, text=preview_text)

        except Exception as e:
            logger.error(f"Preview error for post {i}: {e}")
            await update.message.reply_text(f"❌ Preview error post {i + 1}")

    return WAITING_PUBLICATION_CONTENT


async def _handle_delete_all(update: Update, context: ContextTypes.DEFAULT_TYPE, posts: list) -> int:
    """Gère le bouton Delete All."""
    if not posts:
        await update.message.reply_text(
            "🗑️ **Trash is empty**\n\nNo posts to delete.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]]),
            parse_mode='Markdown'
        )
        return MAIN_MENU

    # Supprimer tous les posts mais garder le canal sélectionné
    post_count = len(posts)
    context.user_data['posts'] = []

    await update.message.reply_text(
        f"🗑️ **Posts deleted**\n\n{post_count} post(s) removed successfully.\n\n📤 Now send your new files:",
        reply_markup=create_reply_keyboard()
    )
    return WAITING_PUBLICATION_CONTENT


async def _handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gère le bouton Cancel."""
    # Nettoyer toutes les données utilisateur
    context.user_data.clear()

    await update.message.reply_text(
        "❌ **Operation cancelled**\n\nAll temporary data has been cleared.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
        ]]),
        parse_mode='Markdown'
    )
    return MAIN_MENU


# ============================================================
# HANDLER SEND BUTTON
# ============================================================

async def handle_send_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère le bouton 'Send' du ReplyKeyboard.

    Vérifie:
        - S'il y a un post planifié en cours
        - S'il y a des posts en attente
        - Si un canal est sélectionné

    Returns:
        int: Le prochain état de la conversation
    """
    try:
        # Import ici pour éviter les imports circulaires
        from handlers.callback_handlers import send_post_now, ensure_post_has_channel

        # Vérifier si un post planifié est sélectionné
        if 'current_scheduled_post' in context.user_data:
            scheduled_post = context.user_data['current_scheduled_post']
            return await send_post_now(update, context, scheduled_post=scheduled_post)

        # Vérifier s'il y a des posts en attente
        posts = context.user_data.get("posts", [])
        if not posts:
            await update.message.reply_text(
                "❌ There are no files to send yet.\n"
                "Please add content first (text, photo, video, document).",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📝 New post", callback_data="create_publication")
                ], [
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return WAITING_PUBLICATION_CONTENT

        # Validation des posts en base de données
        try:
            valid_posts = []
            for post in posts:
                if 'id' in post:
                    ok, reason, channel = await ensure_post_has_channel(
                        'bot.db', post['id'], update.effective_user.id
                    )
                    if ok:
                        valid_posts.append(post)
                        logger.info(f"✅ Post {post['id']} validated with channel: {channel}")
                    else:
                        logger.warning(f"⚠️ Post {post['id']} validation failed: {reason}")
                else:
                    # Post sans ID (nouveau), on le garde
                    valid_posts.append(post)

            posts = valid_posts
            context.user_data['posts'] = posts

        except Exception as e:
            logger.error(f"❌ Error validating posts in database: {e}")

        # Vérifier après nettoyage
        if not posts:
            await update.message.reply_text(
                "❌ No valid posts found.\nPlease create new content.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📝 New post", callback_data="create_publication")
                ], [
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return WAITING_PUBLICATION_CONTENT

        # Obtenir les informations du canal
        selected_channel = context.user_data.get('selected_channel', {})
        channel = posts[0].get("channel") or selected_channel.get('username', '@default_channel')

        # Validation du canal
        if not channel or channel == '@default_channel' or not selected_channel:
            logger.warning(f"⚠️ No valid channel for posts. Channel: {channel}")
            await update.message.reply_text(
                "⚠️ **No channel selected for this post.**\n\n"
                "👉 Please select a channel first, then try again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📺 Choose channel", callback_data="choose_channel")],
                    [InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")]
                ])
            )
            return WAITING_PUBLICATION_CONTENT

        # Menu d'envoi
        keyboard = [
            [InlineKeyboardButton("⏱️ Set auto-destruction time", callback_data="auto_destruction")],
            [InlineKeyboardButton("📤 Send now", callback_data="send_now")],
            [InlineKeyboardButton("📅 Schedule", callback_data="schedule_send")],
            [InlineKeyboardButton("↩️ Back", callback_data="main_menu")]
        ]

        message = f"Your {len(posts)} files are ready to be sent to {channel}.\nWhen would you like to send them?"

        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        logger.info(f"Send menu displayed for {len(posts)} files to {channel}")
        return WAITING_PUBLICATION_CONTENT

    except Exception as e:
        logger.error(f"Error in handle_send_button: {e}")
        await update.message.reply_text(
            "❌ An error occurred while preparing to send.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


# ============================================================
# ANALYSE DES POSTS
# ============================================================

def analyze_posts_content(posts: list) -> str:
    """
    Analyse et résume le contenu des posts.

    Args:
        posts: Liste des posts à analyser

    Returns:
        str: Résumé du contenu
    """
    try:
        type_counts = {
            "photo": 0,
            "video": 0,
            "document": 0,
            "text": 0
        }

        total_reactions = 0
        total_buttons = 0

        for post in posts:
            post_type = post.get("type", "unknown")
            if post_type in type_counts:
                type_counts[post_type] += 1

            reactions = post.get("reactions", [])
            buttons = post.get("buttons", [])
            total_reactions += len(reactions)
            total_buttons += len(buttons)

        # Construire le résumé
        summary_parts = []
        total_files = sum(type_counts.values())

        type_names = {
            "photo": "📸 Photo",
            "video": "🎥 Video",
            "document": "📄 Document",
            "text": "📝 Text"
        }

        if total_files == 1:
            for file_type, count in type_counts.items():
                if count > 0:
                    summary_parts.append(type_names.get(file_type, file_type))
                    break
        else:
            for file_type, count in type_counts.items():
                if count > 0:
                    summary_parts.append(f"{count}x {type_names.get(file_type, file_type)}")

        summary = ", ".join(summary_parts) if summary_parts else "No content"

        if total_reactions > 0:
            summary += f" + {total_reactions} reaction(s)"
        if total_buttons > 0:
            summary += f" + {total_buttons} button(s)"

        return summary

    except Exception as e:
        logger.error(f"Error analyzing posts: {e}")
        return "Content analysis failed"


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "REPLY_KEYBOARD_BUTTONS",
    "reply_keyboard_filter",
    "ReplyKeyboardButtonFilter",
    "create_reply_keyboard",
    "handle_reply_keyboard",
    "handle_send_button",
    "analyze_posts_content",
]

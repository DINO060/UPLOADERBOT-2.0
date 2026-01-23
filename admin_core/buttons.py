"""
ADMIN CORE - Buttons
====================
Gestion des boutons de redirection configurables.
"""

import logging
from typing import List, Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .config import AdminConfig
from .database import AdminDatabase

logger = logging.getLogger("admin_core.buttons")

# \u00c9tats de conversation
WAITING_BUTTON_TEXT = 200
WAITING_BUTTON_URL = 201


class ButtonManager:
    """
    Gestionnaire des boutons de redirection.

    Commandes:
        /addbutton - Ajouter un bouton
        /delbutton - Supprimer un bouton
        /buttons - Lister les boutons
        /editbutton - Modifier un bouton
    """

    def __init__(self, config: AdminConfig, db: AdminDatabase):
        self.config = config
        self.db = db

    def register_handlers(self, application):
        """Enregistre les handlers pour les boutons."""
        # ConversationHandler pour ajouter un bouton
        add_button_handler = ConversationHandler(
            entry_points=[CommandHandler("addbutton", self.add_button_cmd)],
            states={
                WAITING_BUTTON_TEXT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_button_text)
                ],
                WAITING_BUTTON_URL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_button_url)
                ],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_add)],
        )

        application.add_handler(add_button_handler)
        application.add_handler(CommandHandler("delbutton", self.del_button_cmd))
        application.add_handler(CommandHandler("buttons", self.list_buttons_cmd))
        application.add_handler(
            CallbackQueryHandler(self.delete_button_callback, pattern=r"^del_btn_")
        )

        logger.info("Button handlers registered")

    # ==================== COMMANDS ====================

    async def add_button_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Commande /addbutton pour ajouter un bouton."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return ConversationHandler.END

        await update.message.reply_text(
            "**Add New Button**\n\n"
            "Send me the button text (what users will see).\n\n"
            "Example: `Join Channel`\n\n"
            "Send /cancel to abort.",
            parse_mode="Markdown"
        )

        return WAITING_BUTTON_TEXT

    async def receive_button_text(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Re\u00e7oit le texte du bouton."""
        text = update.message.text.strip()

        if len(text) > 64:
            await update.message.reply_text(
                "Button text too long (max 64 characters). Try again."
            )
            return WAITING_BUTTON_TEXT

        context.user_data["new_button_text"] = text

        await update.message.reply_text(
            f"Button text: **{text}**\n\n"
            f"Now send me the URL for this button.\n\n"
            f"Example: `https://t.me/yourchannel`",
            parse_mode="Markdown"
        )

        return WAITING_BUTTON_URL

    async def receive_button_url(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Re\u00e7oit l'URL du bouton."""
        url = update.message.text.strip()
        button_text = context.user_data.get("new_button_text", "Button")

        # Valider l'URL
        if not url.startswith(("http://", "https://", "tg://")):
            await update.message.reply_text(
                "Invalid URL. It must start with http://, https://, or tg://\n"
                "Try again."
            )
            return WAITING_BUTTON_URL

        # G\u00e9n\u00e9rer une cl\u00e9 unique
        button_key = f"btn_{len(self.db.get_buttons()) + 1}"

        # Ajouter le bouton
        self.db.add_button(
            key=button_key,
            text=button_text,
            url=url,
            position=len(self.db.get_buttons())
        )

        await update.message.reply_text(
            f"Button added successfully!\n\n"
            f"**Text:** {button_text}\n"
            f"**URL:** {url}\n\n"
            f"Use /buttons to see all buttons.",
            parse_mode="Markdown"
        )

        # Nettoyer
        context.user_data.pop("new_button_text", None)

        return ConversationHandler.END

    async def cancel_add(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Annule l'ajout de bouton."""
        context.user_data.pop("new_button_text", None)
        await update.message.reply_text("Button creation cancelled.")
        return ConversationHandler.END

    async def del_button_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /delbutton pour supprimer un bouton."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        buttons = self.db.get_buttons(active_only=False)

        if not buttons:
            await update.message.reply_text("No buttons configured.")
            return

        # Cr\u00e9er le clavier avec les boutons \u00e0 supprimer
        keyboard = []
        for btn in buttons:
            keyboard.append([
                InlineKeyboardButton(
                    f"X {btn['button_text']}",
                    callback_data=f"del_btn_{btn['button_key']}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton("Cancel", callback_data="del_btn_cancel")
        ])

        await update.message.reply_text(
            "**Delete a Button**\n\n"
            "Select the button to delete:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    async def delete_button_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Callback pour supprimer un bouton."""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        if not self.config.is_admin(user_id):
            return

        data = query.data

        if data == "del_btn_cancel":
            await query.edit_message_text("Deletion cancelled.")
            return

        button_key = data.replace("del_btn_", "")

        if self.db.remove_button(button_key):
            await query.edit_message_text(
                f"Button `{button_key}` deleted successfully!",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("Button not found.")

    async def list_buttons_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /buttons pour lister les boutons."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        buttons = self.db.get_buttons(active_only=False)

        if not buttons:
            await update.message.reply_text(
                "**No buttons configured.**\n\n"
                "Use /addbutton to add one.",
                parse_mode="Markdown"
            )
            return

        text = "**Configured Buttons**\n\n"

        for i, btn in enumerate(buttons, 1):
            status = "Active" if btn.get("is_active", True) else "Inactive"
            text += f"{i}. **{btn['button_text']}**\n"
            text += f"   URL: `{btn['button_url']}`\n"
            text += f"   Status: {status}\n\n"

        text += f"**Total:** {len(buttons)} button(s)\n\n"
        text += "Use /addbutton to add, /delbutton to remove."

        await update.message.reply_text(text, parse_mode="Markdown")

    # ==================== UTILITIES ====================

    def get_buttons_keyboard(
        self,
        additional_buttons: List[List[InlineKeyboardButton]] = None
    ) -> Optional[InlineKeyboardMarkup]:
        """
        Construit un clavier avec les boutons configur\u00e9s.

        Args:
            additional_buttons: Boutons suppl\u00e9mentaires \u00e0 ajouter

        Returns:
            InlineKeyboardMarkup ou None si pas de boutons
        """
        db_buttons = self.db.get_buttons()
        config_buttons = self.config.default_buttons

        keyboard = []

        # Ajouter les boutons de la config
        for btn in config_buttons:
            keyboard.append([
                InlineKeyboardButton(btn["text"], url=btn["url"])
            ])

        # Ajouter les boutons de la DB
        for btn in db_buttons:
            keyboard.append([
                InlineKeyboardButton(btn["button_text"], url=btn["button_url"])
            ])

        # Ajouter les boutons suppl\u00e9mentaires
        if additional_buttons:
            keyboard.extend(additional_buttons)

        if not keyboard:
            return None

        return InlineKeyboardMarkup(keyboard)

    def get_buttons_list(self) -> List[Dict[str, str]]:
        """
        Retourne tous les boutons (config + DB).

        Returns:
            Liste de dict {"text": ..., "url": ...}
        """
        buttons = []

        # Config buttons
        for btn in self.config.default_buttons:
            buttons.append({"text": btn["text"], "url": btn["url"]})

        # DB buttons
        for btn in self.db.get_buttons():
            buttons.append({
                "text": btn["button_text"],
                "url": btn["button_url"]
            })

        return buttons


def create_inline_keyboard(
    buttons: List[Dict[str, str]],
    columns: int = 1
) -> InlineKeyboardMarkup:
    """
    Cr\u00e9e un clavier inline \u00e0 partir d'une liste de boutons.

    Args:
        buttons: Liste de {"text": ..., "url": ...} ou {"text": ..., "callback_data": ...}
        columns: Nombre de colonnes

    Returns:
        InlineKeyboardMarkup
    """
    keyboard = []
    row = []

    for btn in buttons:
        if "url" in btn:
            button = InlineKeyboardButton(btn["text"], url=btn["url"])
        elif "callback_data" in btn:
            button = InlineKeyboardButton(btn["text"], callback_data=btn["callback_data"])
        else:
            continue

        row.append(button)

        if len(row) >= columns:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    return InlineKeyboardMarkup(keyboard)

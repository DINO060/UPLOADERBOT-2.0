"""
ADMIN CORE - Force Join (FSub)
==============================
Syst\u00e8me de Force Subscribe pour obliger les utilisateurs
\u00e0 rejoindre des canaux avant d'utiliser le bot.
"""

import logging
from typing import List, Tuple, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
)
from telegram.error import TelegramError

from .config import AdminConfig
from .database import AdminDatabase

logger = logging.getLogger("admin_core.force_join")


class ForceJoinManager:
    """
    Gestionnaire du syst\u00e8me Force Join.

    Commandes:
        /addfsub <channel> - Ajouter un canal
        /delfsub <channel> - Retirer un canal
        /fsub - Lister les canaux
    """

    def __init__(self, config: AdminConfig, db: AdminDatabase):
        self.config = config
        self.db = db

    def register_handlers(self, application):
        """Enregistre les handlers pour les commandes Force Join."""
        # Commandes admin
        application.add_handler(CommandHandler("addfsub", self.add_channel_cmd))
        application.add_handler(CommandHandler("delfsub", self.remove_channel_cmd))
        application.add_handler(CommandHandler("fsub", self.list_channels_cmd))
        application.add_handler(CommandHandler("channels", self.list_channels_cmd))

        # Callback pour la v\u00e9rification
        application.add_handler(
            CallbackQueryHandler(self.verify_callback, pattern=r"^fsub_verify$")
        )

        logger.info("Force Join handlers registered")

    async def check_membership(
        self, bot: Bot, user_id: int, channels: List[str] = None
    ) -> Tuple[bool, List[str]]:
        """
        V\u00e9rifie si un utilisateur est membre de tous les canaux requis.

        Args:
            bot: Instance du bot
            user_id: ID de l'utilisateur
            channels: Liste des canaux (utilise config si None)

        Returns:
            (is_member_of_all, list_of_missing_channels)
        """
        channels_to_check = channels or self.config.force_join_channels

        # Ajouter les canaux de la DB
        db_channels = self.db.get_force_join_channels()
        all_channels = list(set(channels_to_check + db_channels))

        if not all_channels:
            return True, []

        missing_channels = []

        for channel in all_channels:
            try:
                # Normaliser le channel ID
                channel_id = channel
                if not channel.startswith("-") and not channel.startswith("@"):
                    channel_id = f"@{channel}"

                member = await bot.get_chat_member(channel_id, user_id)

                if member.status in ["left", "kicked"]:
                    missing_channels.append(channel)

            except TelegramError as e:
                logger.warning(f"Error checking membership for {channel}: {e}")
                # En cas d'erreur, on consid\u00e8re que l'utilisateur n'est pas membre
                # sauf si c'est une erreur de permission du bot
                if "Chat not found" not in str(e):
                    missing_channels.append(channel)

        return len(missing_channels) == 0, missing_channels

    async def send_join_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        missing_channels: List[str]
    ):
        """
        Envoie le message demandant \u00e0 l'utilisateur de rejoindre les canaux.

        Args:
            update: Update Telegram
            context: Context
            missing_channels: Canaux manquants
        """
        # Cr\u00e9er les boutons pour chaque canal
        buttons = []

        for channel in missing_channels:
            # Nettoyer le nom du canal
            channel_name = channel.lstrip("@")
            if channel.startswith("-"):
                # C'est un ID num\u00e9rique, essayer de r\u00e9cup\u00e9rer les infos
                try:
                    chat = await context.bot.get_chat(channel)
                    channel_name = chat.title or channel
                    invite_link = chat.invite_link
                    if invite_link:
                        buttons.append([
                            InlineKeyboardButton(f"Join {channel_name}", url=invite_link)
                        ])
                    continue
                except TelegramError:
                    pass

            # Canal avec username
            buttons.append([
                InlineKeyboardButton(
                    f"Join @{channel_name}",
                    url=f"https://t.me/{channel_name}"
                )
            ])

        # Bouton de v\u00e9rification
        buttons.append([
            InlineKeyboardButton(
                self.config.force_join_button_text,
                callback_data="fsub_verify"
            )
        ])

        keyboard = InlineKeyboardMarkup(buttons)

        # Envoyer le message
        if update.callback_query:
            await update.callback_query.answer(
                "Please join the required channels first!",
                show_alert=True
            )
            try:
                await update.callback_query.edit_message_text(
                    self.config.force_join_message,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except TelegramError:
                await context.bot.send_message(
                    update.effective_chat.id,
                    self.config.force_join_message,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
        else:
            await update.message.reply_text(
                self.config.force_join_message,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

    async def verify_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Callback pour le bouton de v\u00e9rification."""
        query = update.callback_query
        user_id = update.effective_user.id

        is_member, missing = await self.check_membership(context.bot, user_id)

        if is_member:
            await query.answer("Verification successful!", show_alert=True)
            await query.edit_message_text(
                "You have successfully joined all required channels!\n\n"
                "You can now use the bot. Send /start to begin.",
                parse_mode="Markdown"
            )
        else:
            await query.answer(
                f"You haven't joined all channels yet! Missing: {len(missing)}",
                show_alert=True
            )
            # R\u00e9afficher le message avec les canaux manquants
            await self.send_join_message(update, context, missing)

    # ==================== ADMIN COMMANDS ====================

    async def add_channel_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /addfsub pour ajouter un canal."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        if not context.args:
            await update.message.reply_text(
                "**Usage:** `/addfsub @channel` or `/addfsub -100123456`",
                parse_mode="Markdown"
            )
            return

        channel = context.args[0].strip()

        # Valider le canal
        try:
            chat = await context.bot.get_chat(channel)

            # V\u00e9rifier que le bot est admin
            bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
            if bot_member.status not in ["administrator", "creator"]:
                await update.message.reply_text(
                    f"The bot must be an admin in **{chat.title}** to use Force Join.",
                    parse_mode="Markdown"
                )
                return

            # Ajouter \u00e0 la config et DB
            channel_id = f"@{chat.username}" if chat.username else str(chat.id)
            self.config.add_force_join_channel(channel_id)
            self.db.add_force_join_channel(
                channel_id=channel_id,
                channel_name=chat.title,
                added_by=user_id
            )

            await update.message.reply_text(
                f"**{chat.title}** added to Force Join channels!",
                parse_mode="Markdown"
            )
            logger.info(f"Force Join channel added: {channel_id} by {user_id}")

        except TelegramError as e:
            await update.message.reply_text(f"Error: {e}")

    async def remove_channel_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /delfsub pour retirer un canal."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        if not context.args:
            await update.message.reply_text(
                "**Usage:** `/delfsub @channel`",
                parse_mode="Markdown"
            )
            return

        channel = context.args[0].strip()

        # Normaliser
        if not channel.startswith("@") and not channel.startswith("-"):
            channel = f"@{channel}"

        # Retirer de la config et DB
        removed_config = self.config.remove_force_join_channel(channel)
        removed_db = self.db.remove_force_join_channel(channel)

        if removed_config or removed_db:
            await update.message.reply_text(
                f"**{channel}** removed from Force Join channels!",
                parse_mode="Markdown"
            )
            logger.info(f"Force Join channel removed: {channel} by {user_id}")
        else:
            await update.message.reply_text(
                f"Channel **{channel}** not found in Force Join list.",
                parse_mode="Markdown"
            )

    async def list_channels_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /fsub pour lister les canaux."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        # R\u00e9cup\u00e9rer tous les canaux
        config_channels = self.config.force_join_channels
        db_channels = self.db.get_force_join_channels()

        all_channels = list(set(config_channels + db_channels))

        if not all_channels:
            await update.message.reply_text(
                "**No Force Join channels configured.**\n\n"
                "Use `/addfsub @channel` to add one.",
                parse_mode="Markdown"
            )
            return

        # Construire la liste
        text = "**Force Join Channels**\n\n"

        for i, channel in enumerate(all_channels, 1):
            text += f"{i}. `{channel}`\n"

        text += f"\n**Total:** {len(all_channels)} channel(s)"
        text += "\n\nUse `/delfsub @channel` to remove."

        await update.message.reply_text(text, parse_mode="Markdown")


async def check_force_join(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Fonction utilitaire pour v\u00e9rifier le Force Join.
    Retourne True si l'utilisateur peut continuer, False sinon.

    Usage:
        if not await check_force_join(update, context):
            return  # L'utilisateur doit rejoindre les canaux
    """
    config = context.bot_data.get("admin_config")
    managers = context.bot_data.get("admin_managers", {})
    force_join = managers.get("force_join")

    if not config or not force_join:
        return True

    if not config.force_join_enabled:
        return True

    user_id = update.effective_user.id

    # Bypass admins
    if config.force_join_bypass_admins and config.is_admin(user_id):
        return True

    is_member, missing = await force_join.check_membership(context.bot, user_id)

    if not is_member:
        await force_join.send_join_message(update, context, missing)
        return False

    return True

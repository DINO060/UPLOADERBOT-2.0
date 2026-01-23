"""
ADMIN CORE - Ban System
=======================
Syst\u00e8me de gestion des utilisateurs bannis.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from .config import AdminConfig
from .database import AdminDatabase

logger = logging.getLogger("admin_core.ban_system")


class BanManager:
    """
    Gestionnaire du syst\u00e8me de ban.

    Commandes:
        /ban <user_id> [reason] - Bannir un utilisateur
        /unban <user_id> - D\u00e9bannir un utilisateur
        /banlist - Liste des utilisateurs bannis
        /tempban <user_id> <duration> [reason] - Ban temporaire
    """

    def __init__(self, config: AdminConfig, db: AdminDatabase):
        self.config = config
        self.db = db

    def register_handlers(self, application):
        """Enregistre les handlers pour le syst\u00e8me de ban."""
        application.add_handler(CommandHandler("ban", self.ban_cmd))
        application.add_handler(CommandHandler("unban", self.unban_cmd))
        application.add_handler(CommandHandler("banlist", self.banlist_cmd))
        application.add_handler(CommandHandler("tempban", self.tempban_cmd))
        application.add_handler(CommandHandler("checkban", self.checkban_cmd))

        logger.info("Ban system handlers registered")

    async def ban_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /ban pour bannir un utilisateur."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        if not context.args:
            await update.message.reply_text(
                "**Usage:** `/ban <user_id> [reason]`\n\n"
                "Example: `/ban 123456789 Spam`",
                parse_mode="Markdown"
            )
            return

        try:
            target_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Invalid user ID. Must be a number.")
            return

        # V\u00e9rifier qu'on ne banni pas un admin
        if self.config.is_admin(target_id):
            await update.message.reply_text("You cannot ban an admin!")
            return

        # Raison (optionnel)
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else None

        # Bannir
        self.db.ban_user(target_id, user_id, reason)

        # R\u00e9cup\u00e9rer les infos de l'utilisateur banni
        target_user = self.db.get_user(target_id)
        target_name = "Unknown"
        if target_user:
            target_name = target_user.get("first_name") or target_user.get("username") or str(target_id)

        text = f"**User Banned**\n\n"
        text += f"User: `{target_id}` ({target_name})\n"
        if reason:
            text += f"Reason: {reason}\n"
        text += f"Banned by: {update.effective_user.first_name}"

        await update.message.reply_text(text, parse_mode="Markdown")
        logger.info(f"User {target_id} banned by {user_id}. Reason: {reason}")

    async def unban_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /unban pour d\u00e9bannir un utilisateur."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        if not context.args:
            await update.message.reply_text(
                "**Usage:** `/unban <user_id>`\n\n"
                "Example: `/unban 123456789`",
                parse_mode="Markdown"
            )
            return

        try:
            target_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Invalid user ID. Must be a number.")
            return

        # D\u00e9bannir
        if self.db.unban_user(target_id):
            await update.message.reply_text(
                f"User `{target_id}` has been unbanned.",
                parse_mode="Markdown"
            )
            logger.info(f"User {target_id} unbanned by {user_id}")
        else:
            await update.message.reply_text(
                f"User `{target_id}` was not banned.",
                parse_mode="Markdown"
            )

    async def tempban_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /tempban pour un ban temporaire."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        if len(context.args) < 2:
            await update.message.reply_text(
                "**Usage:** `/tempban <user_id> <duration> [reason]`\n\n"
                "Duration formats:\n"
                "- `30m` = 30 minutes\n"
                "- `2h` = 2 hours\n"
                "- `1d` = 1 day\n"
                "- `1w` = 1 week\n\n"
                "Example: `/tempban 123456789 24h Spam`",
                parse_mode="Markdown"
            )
            return

        try:
            target_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Invalid user ID.")
            return

        # V\u00e9rifier qu'on ne banni pas un admin
        if self.config.is_admin(target_id):
            await update.message.reply_text("You cannot ban an admin!")
            return

        # Parser la dur\u00e9e
        duration_str = context.args[1].lower()
        duration_seconds = self._parse_duration(duration_str)

        if duration_seconds is None:
            await update.message.reply_text(
                "Invalid duration format. Use: 30m, 2h, 1d, 1w"
            )
            return

        # Raison (optionnel)
        reason = " ".join(context.args[2:]) if len(context.args) > 2 else None

        # Bannir temporairement
        self.db.ban_user(target_id, user_id, reason, duration_seconds)

        # Calculer la date d'expiration
        expires_at = datetime.now() + timedelta(seconds=duration_seconds)

        text = f"**User Temporarily Banned**\n\n"
        text += f"User: `{target_id}`\n"
        text += f"Duration: {duration_str}\n"
        text += f"Expires: `{expires_at.strftime('%Y-%m-%d %H:%M')}`\n"
        if reason:
            text += f"Reason: {reason}\n"

        await update.message.reply_text(text, parse_mode="Markdown")
        logger.info(f"User {target_id} temp-banned for {duration_str} by {user_id}")

    async def banlist_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /banlist pour lister les utilisateurs bannis."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        banned_users = self.db.get_banned_users()

        if not banned_users:
            await update.message.reply_text("No banned users.")
            return

        text = "**Banned Users**\n\n"

        for i, user in enumerate(banned_users[:20], 1):  # Limiter \u00e0 20
            name = user.get("first_name") or user.get("username") or "Unknown"
            text += f"{i}. `{user['user_id']}` - {name}\n"

            if user.get("reason"):
                text += f"   Reason: {user['reason']}\n"

            if user.get("expires_at"):
                text += f"   Expires: {user['expires_at']}\n"

        if len(banned_users) > 20:
            text += f"\n_...and {len(banned_users) - 20} more_"

        text += f"\n\n**Total:** {len(banned_users)} banned user(s)"

        await update.message.reply_text(text, parse_mode="Markdown")

    async def checkban_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /checkban pour v\u00e9rifier si un utilisateur est banni."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        if not context.args:
            await update.message.reply_text(
                "**Usage:** `/checkban <user_id>`",
                parse_mode="Markdown"
            )
            return

        try:
            target_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Invalid user ID.")
            return

        is_banned, reason = self.db.is_banned(target_id)

        if is_banned:
            text = f"User `{target_id}` is **BANNED**."
            if reason:
                text += f"\nReason: {reason}"
        else:
            text = f"User `{target_id}` is **NOT banned**."

        await update.message.reply_text(text, parse_mode="Markdown")

    # ==================== HELPERS ====================

    def _parse_duration(self, duration_str: str) -> Optional[int]:
        """
        Parse une dur\u00e9e en secondes.

        Args:
            duration_str: "30m", "2h", "1d", "1w"

        Returns:
            Dur\u00e9e en secondes ou None
        """
        multipliers = {
            "m": 60,           # minutes
            "h": 3600,         # heures
            "d": 86400,        # jours
            "w": 604800,       # semaines
        }

        try:
            unit = duration_str[-1].lower()
            if unit not in multipliers:
                return None

            value = int(duration_str[:-1])
            return value * multipliers[unit]

        except (ValueError, IndexError):
            return None

    def is_banned(self, user_id: int) -> Tuple[bool, Optional[str]]:
        """
        V\u00e9rifie si un utilisateur est banni.

        Returns:
            (is_banned, reason)
        """
        return self.db.is_banned(user_id)


async def check_ban(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Fonction utilitaire pour v\u00e9rifier si l'utilisateur est banni.
    Retourne True si l'utilisateur peut continuer, False s'il est banni.

    Usage:
        if not await check_ban(update, context):
            return  # User est banni
    """
    db = context.bot_data.get("admin_db")

    if not db:
        return True

    user_id = update.effective_user.id
    is_banned, reason = db.is_banned(user_id)

    if is_banned:
        message = "You are banned from using this bot."
        if reason:
            message += f"\n\nReason: {reason}"
        await update.message.reply_text(message)
        return False

    return True

"""
ADMIN CORE - Broadcast
======================
Syst\u00e8me de diffusion de messages \u00e0 tous les utilisateurs.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable
from telegram import Update, Message
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
)
from telegram.error import TelegramError, Forbidden, RetryAfter

from .config import AdminConfig
from .database import AdminDatabase

logger = logging.getLogger("admin_core.broadcast")

# \u00c9tats de conversation
WAITING_BROADCAST_MESSAGE = 100


class BroadcastManager:
    """
    Gestionnaire des broadcasts.

    Commandes:
        /broadcast - D\u00e9marrer un broadcast
        /cancel_broadcast - Annuler un broadcast en cours
        /broadcast_stats - Stats du dernier broadcast
    """

    def __init__(self, config: AdminConfig, db: AdminDatabase):
        self.config = config
        self.db = db
        self._running_broadcast = False
        self._cancel_requested = False

    def register_handlers(self, application):
        """Enregistre les handlers pour le broadcast."""
        # ConversationHandler pour le broadcast
        broadcast_handler = ConversationHandler(
            entry_points=[CommandHandler("broadcast", self.start_broadcast_cmd)],
            states={
                WAITING_BROADCAST_MESSAGE: [
                    MessageHandler(
                        filters.ALL & ~filters.COMMAND,
                        self.receive_broadcast_message
                    )
                ]
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel_broadcast_setup)
            ],
        )

        application.add_handler(broadcast_handler)
        application.add_handler(
            CommandHandler("cancel_broadcast", self.cancel_running_broadcast)
        )
        application.add_handler(
            CommandHandler("broadcast_stats", self.broadcast_stats_cmd)
        )

        logger.info("Broadcast handlers registered")

    async def start_broadcast_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Commande /broadcast pour d\u00e9marrer un broadcast."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return ConversationHandler.END

        if self._running_broadcast:
            await update.message.reply_text(
                "A broadcast is already running!\n"
                "Use /cancel_broadcast to stop it."
            )
            return ConversationHandler.END

        # Compter les utilisateurs
        user_count = self.db.get_users_count(active_only=True)

        await update.message.reply_text(
            f"**Broadcast Mode**\n\n"
            f"Users: **{user_count}**\n\n"
            f"Send me the message you want to broadcast.\n"
            f"It can be text, photo, video, document, etc.\n\n"
            f"Send /cancel to abort.",
            parse_mode="Markdown"
        )

        return WAITING_BROADCAST_MESSAGE

    async def receive_broadcast_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Re\u00e7oit le message \u00e0 diffuser."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            return ConversationHandler.END

        message = update.message

        # Confirmation
        user_count = self.db.get_users_count(active_only=True)

        await message.reply_text(
            f"Starting broadcast to **{user_count}** users...\n"
            f"Use /cancel_broadcast to stop.",
            parse_mode="Markdown"
        )

        # Lancer le broadcast en arri\u00e8re-plan
        asyncio.create_task(
            self._do_broadcast(message, context, user_id)
        )

        return ConversationHandler.END

    async def cancel_broadcast_setup(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Annule la configuration du broadcast."""
        await update.message.reply_text("Broadcast cancelled.")
        return ConversationHandler.END

    async def cancel_running_broadcast(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Annule un broadcast en cours."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        if not self._running_broadcast:
            await update.message.reply_text("No broadcast is currently running.")
            return

        self._cancel_requested = True
        await update.message.reply_text(
            "Cancellation requested. The broadcast will stop after the current batch."
        )

    async def broadcast_stats_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Affiche les stats du dernier broadcast."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        last_broadcast = self.db.get_last_broadcast()

        if not last_broadcast:
            await update.message.reply_text("No broadcast history found.")
            return

        status_emoji = {
            "running": "Running...",
            "completed": "Completed",
            "cancelled": "Cancelled",
            "failed": "Failed"
        }.get(last_broadcast["status"], last_broadcast["status"])

        text = (
            f"**Last Broadcast Stats**\n\n"
            f"Status: **{status_emoji}**\n"
            f"Total Users: **{last_broadcast['total_users']}**\n"
            f"Success: **{last_broadcast['success_count']}**\n"
            f"Failed: **{last_broadcast['failed_count']}**\n"
            f"Started: `{last_broadcast['started_at']}`\n"
        )

        if last_broadcast["completed_at"]:
            text += f"Completed: `{last_broadcast['completed_at']}`\n"

        # Calculer le taux de r\u00e9ussite
        total = last_broadcast["success_count"] + last_broadcast["failed_count"]
        if total > 0:
            rate = (last_broadcast["success_count"] / total) * 100
            text += f"\nSuccess Rate: **{rate:.1f}%**"

        await update.message.reply_text(text, parse_mode="Markdown")

    async def _do_broadcast(
        self,
        message: Message,
        context: ContextTypes.DEFAULT_TYPE,
        started_by: int
    ):
        """Ex\u00e9cute le broadcast."""
        self._running_broadcast = True
        self._cancel_requested = False

        # R\u00e9cup\u00e9rer tous les utilisateurs actifs
        users = self.db.get_all_users(active_only=True)
        total_users = len(users)

        # Cr\u00e9er l'entr\u00e9e dans l'historique
        broadcast_id = self.db.create_broadcast(
            started_by=started_by,
            message_type=self._get_message_type(message),
            total_users=total_users
        )

        success_count = 0
        failed_count = 0

        # Envoyer un message de progression
        progress_msg = await context.bot.send_message(
            message.chat_id,
            f"Broadcasting: 0/{total_users}"
        )

        last_update = datetime.now()

        for i, user_id in enumerate(users):
            # V\u00e9rifier l'annulation
            if self._cancel_requested:
                self.db.update_broadcast(
                    broadcast_id, success_count, failed_count, "cancelled"
                )
                break

            try:
                # Copier le message
                await message.copy(user_id)
                success_count += 1

            except Forbidden:
                # L'utilisateur a bloqu\u00e9 le bot
                self.db.set_user_inactive(user_id)
                failed_count += 1

            except RetryAfter as e:
                # Rate limit
                logger.warning(f"Rate limited, sleeping for {e.retry_after}s")
                await asyncio.sleep(e.retry_after)
                # R\u00e9essayer
                try:
                    await message.copy(user_id)
                    success_count += 1
                except Exception:
                    failed_count += 1

            except TelegramError as e:
                logger.warning(f"Failed to send to {user_id}: {e}")
                failed_count += 1

            # Mettre \u00e0 jour la progression toutes les 2 secondes
            now = datetime.now()
            if (now - last_update).seconds >= 2:
                try:
                    await progress_msg.edit_text(
                        f"Broadcasting: {i + 1}/{total_users}\n"
                        f"Success: {success_count} | Failed: {failed_count}"
                    )
                except Exception:
                    pass
                last_update = now

                # Mettre \u00e0 jour la DB
                self.db.update_broadcast(
                    broadcast_id, success_count, failed_count, "running"
                )

            # D\u00e9lai entre les messages
            await asyncio.sleep(self.config.broadcast_delay)

            # Pause entre les batches
            if (i + 1) % self.config.broadcast_batch_size == 0:
                await asyncio.sleep(self.config.broadcast_sleep_between_batches)

        # Terminer
        self._running_broadcast = False

        status = "cancelled" if self._cancel_requested else "completed"
        self.db.update_broadcast(broadcast_id, success_count, failed_count, status)

        # Message final
        try:
            await progress_msg.edit_text(
                f"**Broadcast {status.capitalize()}!**\n\n"
                f"Total: {total_users}\n"
                f"Success: {success_count}\n"
                f"Failed: {failed_count}\n"
                f"Success Rate: {(success_count/total_users*100):.1f}%",
                parse_mode="Markdown"
            )
        except Exception:
            pass

        logger.info(
            f"Broadcast {status}: {success_count}/{total_users} success, "
            f"{failed_count} failed"
        )

    def _get_message_type(self, message: Message) -> str:
        """D\u00e9termine le type de message."""
        if message.text:
            return "text"
        elif message.photo:
            return "photo"
        elif message.video:
            return "video"
        elif message.document:
            return "document"
        elif message.audio:
            return "audio"
        elif message.voice:
            return "voice"
        elif message.animation:
            return "animation"
        elif message.sticker:
            return "sticker"
        else:
            return "other"


async def broadcast_message(
    context: ContextTypes.DEFAULT_TYPE,
    message: Message,
    users: list = None,
    progress_callback: Callable = None
) -> dict:
    """
    Fonction utilitaire pour envoyer un broadcast programmatique.

    Args:
        context: Context Telegram
        message: Message \u00e0 diffuser
        users: Liste d'IDs (si None, utilise tous les users actifs)
        progress_callback: Callback appel\u00e9 avec (current, total, success, failed)

    Returns:
        dict avec success_count, failed_count, total
    """
    db = context.bot_data.get("admin_db")
    config = context.bot_data.get("admin_config")

    if not db:
        return {"success_count": 0, "failed_count": 0, "total": 0}

    if users is None:
        users = db.get_all_users(active_only=True)

    success_count = 0
    failed_count = 0
    total = len(users)

    for i, user_id in enumerate(users):
        try:
            await message.copy(user_id)
            success_count += 1
        except Exception:
            failed_count += 1

        if progress_callback:
            await progress_callback(i + 1, total, success_count, failed_count)

        await asyncio.sleep(config.broadcast_delay if config else 0.05)

    return {
        "success_count": success_count,
        "failed_count": failed_count,
        "total": total
    }

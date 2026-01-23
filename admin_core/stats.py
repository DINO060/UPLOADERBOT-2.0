"""
ADMIN CORE - Stats
==================
Statistiques d\u00e9taill\u00e9es des utilisateurs et de l'utilisation.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from .config import AdminConfig
from .database import AdminDatabase

logger = logging.getLogger("admin_core.stats")


class StatsManager:
    """
    Gestionnaire des statistiques d\u00e9taill\u00e9es.

    Commandes:
        /stats - Statistiques g\u00e9n\u00e9rales
        /userstats - Stats utilisateurs
        /topusers - Top utilisateurs
        /dailystats - Stats quotidiennes
    """

    def __init__(self, config: AdminConfig, db: AdminDatabase):
        self.config = config
        self.db = db

    def register_handlers(self, application):
        """Enregistre les handlers pour les stats."""
        application.add_handler(CommandHandler("userstats", self.user_stats_cmd))
        application.add_handler(CommandHandler("topusers", self.top_users_cmd))
        application.add_handler(CommandHandler("dailystats", self.daily_stats_cmd))
        application.add_handler(CommandHandler("userinfo", self.user_info_cmd))

        logger.info("Stats handlers registered")

    async def user_stats_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /userstats pour les statistiques utilisateurs."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        stats = self.db.get_stats()

        # Calculer des stats suppl\u00e9mentaires
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Users cette semaine
            cursor.execute("""
                SELECT COUNT(*) FROM users
                WHERE date(first_seen) >= date('now', '-7 days')
            """)
            users_week = cursor.fetchone()[0]

            # Users ce mois
            cursor.execute("""
                SELECT COUNT(*) FROM users
                WHERE date(first_seen) >= date('now', '-30 days')
            """)
            users_month = cursor.fetchone()[0]

            # Users actifs derni\u00e8res 24h
            cursor.execute("""
                SELECT COUNT(*) FROM users
                WHERE datetime(last_seen) >= datetime('now', '-1 day')
            """)
            active_24h = cursor.fetchone()[0]

            # Langues les plus utilis\u00e9es
            cursor.execute("""
                SELECT language_code, COUNT(*) as count
                FROM users
                GROUP BY language_code
                ORDER BY count DESC
                LIMIT 5
            """)
            languages = cursor.fetchall()

        text = "**User Statistics**\n\n"

        text += "**Overview**\n"
        text += f"  Total Users: `{stats['total_users']}`\n"
        text += f"  Active: `{stats['active_users']}`\n"
        text += f"  Banned: `{stats['banned_users']}`\n"

        text += "\n**Growth**\n"
        text += f"  Today: `+{stats['users_today']}`\n"
        text += f"  This Week: `+{users_week}`\n"
        text += f"  This Month: `+{users_month}`\n"

        text += "\n**Activity**\n"
        text += f"  Active (24h): `{active_24h}`\n"
        text += f"  Total Messages: `{stats['total_messages']}`\n"

        if languages:
            text += "\n**Top Languages**\n"
            for lang, count in languages:
                lang_name = self._get_language_name(lang)
                text += f"  {lang_name}: `{count}`\n"

        await update.message.reply_text(text, parse_mode="Markdown")

    async def top_users_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /topusers pour les utilisateurs les plus actifs."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT user_id, username, first_name, total_messages
                FROM users
                WHERE is_active = 1
                ORDER BY total_messages DESC
                LIMIT 10
            """)
            top_users = cursor.fetchall()

        if not top_users:
            await update.message.reply_text("No user data available.")
            return

        text = "**Top 10 Active Users**\n\n"

        for i, (uid, username, first_name, messages) in enumerate(top_users, 1):
            name = first_name or username or f"User {uid}"
            medal = ["", "", ""][i-1] if i <= 3 else f"{i}."
            text += f"{medal} **{name}**\n"
            text += f"   Messages: `{messages}`\n"

        await update.message.reply_text(text, parse_mode="Markdown")

    async def daily_stats_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /dailystats pour les stats quotidiennes."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Stats des 7 derniers jours
            cursor.execute("""
                SELECT date(first_seen) as day, COUNT(*) as count
                FROM users
                WHERE date(first_seen) >= date('now', '-7 days')
                GROUP BY day
                ORDER BY day DESC
            """)
            daily_new = cursor.fetchall()

        text = "**Daily Statistics (Last 7 Days)**\n\n"
        text += "New Users per Day:\n"

        for day, count in daily_new:
            # Cr\u00e9er une barre de progression simple
            bar_length = min(count, 20)
            bar = "" * bar_length
            text += f"`{day}`: {bar} **{count}**\n"

        if not daily_new:
            text += "_No data available_\n"

        await update.message.reply_text(text, parse_mode="Markdown")

    async def user_info_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /userinfo pour les infos d'un utilisateur sp\u00e9cifique."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        # Si pas d'argument, montrer l'aide
        if not context.args:
            await update.message.reply_text(
                "**Usage:** `/userinfo <user_id>`\n\n"
                "Example: `/userinfo 123456789`",
                parse_mode="Markdown"
            )
            return

        try:
            target_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Invalid user ID.")
            return

        user = self.db.get_user(target_id)

        if not user:
            await update.message.reply_text(f"User `{target_id}` not found in database.", parse_mode="Markdown")
            return

        # V\u00e9rifier le ban
        is_banned, ban_reason = self.db.is_banned(target_id)

        text = f"**User Information**\n\n"
        text += f"**ID:** `{user['user_id']}`\n"

        if user.get('username'):
            text += f"**Username:** @{user['username']}\n"

        if user.get('first_name'):
            text += f"**Name:** {user['first_name']}"
            if user.get('last_name'):
                text += f" {user['last_name']}"
            text += "\n"

        text += f"**Language:** {self._get_language_name(user.get('language_code', 'en'))}\n"
        text += f"**Status:** {'Banned' if is_banned else 'Active' if user.get('is_active') else 'Inactive'}\n"

        if is_banned and ban_reason:
            text += f"**Ban Reason:** {ban_reason}\n"

        text += f"\n**First Seen:** `{user.get('first_seen', 'Unknown')}`\n"
        text += f"**Last Seen:** `{user.get('last_seen', 'Unknown')}`\n"
        text += f"**Messages:** `{user.get('total_messages', 0)}`\n"

        await update.message.reply_text(text, parse_mode="Markdown")

    # ==================== HELPERS ====================

    def _get_language_name(self, code: str) -> str:
        """Convertit un code langue en nom."""
        languages = {
            "en": "English",
            "fr": "Fran\u00e7ais",
            "es": "Espa\u00f1ol",
            "de": "Deutsch",
            "it": "Italiano",
            "pt": "Portugu\u00eas",
            "ru": "\u0420\u0443\u0441\u0441\u043a\u0438\u0439",
            "ar": "\u0627\u0644\u0639\u0631\u0628\u064a\u0629",
            "zh": "\u4e2d\u6587",
            "ja": "\u65e5\u672c\u8a9e",
            "ko": "\ud55c\uad6d\uc5b4",
        }
        return languages.get(code, code.upper() if code else "Unknown")

    def get_summary(self) -> Dict[str, Any]:
        """Retourne un r\u00e9sum\u00e9 des stats pour usage programmatique."""
        return self.db.get_stats()


def track_user_activity(db: AdminDatabase, user_id: int):
    """
    Fonction utilitaire pour tracker l'activit\u00e9 d'un utilisateur.

    Usage:
        track_user_activity(db, update.effective_user.id)
    """
    db.increment_user_messages(user_id)


async def get_user_count(context: ContextTypes.DEFAULT_TYPE) -> int:
    """Retourne le nombre total d'utilisateurs."""
    db = context.bot_data.get("admin_db")
    if db:
        return db.get_users_count()
    return 0


async def get_active_user_count(context: ContextTypes.DEFAULT_TYPE) -> int:
    """Retourne le nombre d'utilisateurs actifs."""
    db = context.bot_data.get("admin_db")
    if db:
        return db.get_users_count(active_only=True)
    return 0

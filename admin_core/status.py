"""
ADMIN CORE - Status
===================
Statistiques et informations sur le bot.
"""

import os
import time
import platform
import logging
from datetime import datetime, timedelta
from typing import Optional
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from .config import AdminConfig
from .database import AdminDatabase

logger = logging.getLogger("admin_core.status")

# Temps de d\u00e9marrage
START_TIME = datetime.now()


class StatusManager:
    """
    Gestionnaire des statistiques du bot.

    Commandes:
        /status - Statistiques compl\u00e8tes (admin)
        /ping - V\u00e9rifier si le bot r\u00e9pond (public)
        /stats - Statistiques rapides (admin)
    """

    def __init__(self, config: AdminConfig, db: AdminDatabase):
        self.config = config
        self.db = db

    def register_handlers(self, application):
        """Enregistre les handlers pour les commandes status."""
        application.add_handler(CommandHandler("status", self.status_cmd))
        application.add_handler(CommandHandler("ping", self.ping_cmd))
        application.add_handler(CommandHandler("stats", self.quick_stats_cmd))
        application.add_handler(CommandHandler("sysinfo", self.sysinfo_cmd))

        logger.info("Status handlers registered")

    async def ping_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /ping - V\u00e9rifie la r\u00e9activit\u00e9 du bot."""
        start = time.time()
        msg = await update.message.reply_text("Pong!")
        end = time.time()

        latency = (end - start) * 1000  # En millisecondes

        await msg.edit_text(f"Pong! `{latency:.0f}ms`", parse_mode="Markdown")

    async def status_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /status - Statistiques compl\u00e8tes."""
        user_id = update.effective_user.id

        # V\u00e9rifier si admin pour les infos compl\u00e8tes
        is_admin = self.config.is_admin(user_id)

        # Calculer l'uptime
        uptime = datetime.now() - START_TIME
        uptime_str = self._format_uptime(uptime)

        # Ping
        start = time.time()
        msg = await update.message.reply_text("Collecting stats...")
        ping = (time.time() - start) * 1000

        # Stats de base
        text = "**Bot Status**\n\n"
        text += f"Ping: `{ping:.0f}ms`\n"

        if self.config.status_show_uptime:
            text += f"Uptime: `{uptime_str}`\n"

        # Stats utilisateurs (admin only)
        if is_admin:
            db_stats = self.db.get_stats()

            if self.config.status_show_users:
                text += f"\n**Users**\n"
                text += f"Total: `{db_stats['total_users']}`\n"
                text += f"Active: `{db_stats['active_users']}`\n"
                text += f"Today: `{db_stats['users_today']}`\n"
                text += f"Banned: `{db_stats['banned_users']}`\n"

            # Infos syst\u00e8me
            text += f"\n**System**\n"

            if self.config.status_show_cpu:
                cpu = self._get_cpu_usage()
                text += f"CPU: `{cpu}`\n"

            if self.config.status_show_ram:
                ram = self._get_ram_usage()
                text += f"RAM: `{ram}`\n"

            if self.config.status_show_disk:
                disk = self._get_disk_usage()
                text += f"Disk: `{disk}`\n"

            # Force Join
            if db_stats['force_join_channels'] > 0:
                text += f"\n**Force Join:** `{db_stats['force_join_channels']}` channel(s)\n"

        else:
            text += "\n_More details available for admins._"

        await msg.edit_text(text, parse_mode="Markdown")

    async def quick_stats_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /stats - Statistiques rapides."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        db_stats = self.db.get_stats()

        text = (
            f"**Quick Stats**\n\n"
            f"Users: `{db_stats['total_users']}` "
            f"(Active: `{db_stats['active_users']}`)\n"
            f"New Today: `{db_stats['users_today']}`\n"
            f"Banned: `{db_stats['banned_users']}`\n"
            f"Total Messages: `{db_stats['total_messages']}`"
        )

        await update.message.reply_text(text, parse_mode="Markdown")

    async def sysinfo_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Commande /sysinfo - Informations syst\u00e8me d\u00e9taill\u00e9es."""
        user_id = update.effective_user.id

        if not self.config.is_admin(user_id):
            await update.message.reply_text("You don't have permission.")
            return

        # Infos Python
        python_version = platform.python_version()

        # Infos OS
        os_info = f"{platform.system()} {platform.release()}"

        # Infos machine
        machine = platform.machine()
        processor = platform.processor() or "Unknown"

        # RAM d\u00e9taill\u00e9e
        ram_info = self._get_ram_detailed()

        # Disk d\u00e9taill\u00e9
        disk_info = self._get_disk_detailed()

        text = (
            f"**System Information**\n\n"
            f"**OS:** `{os_info}`\n"
            f"**Machine:** `{machine}`\n"
            f"**Processor:** `{processor}`\n"
            f"**Python:** `{python_version}`\n\n"
            f"**RAM:**\n{ram_info}\n\n"
            f"**Disk:**\n{disk_info}"
        )

        await update.message.reply_text(text, parse_mode="Markdown")

    # ==================== HELPERS ====================

    def _format_uptime(self, delta: timedelta) -> str:
        """Formate le temps d'uptime."""
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")

        return " ".join(parts)

    def _get_cpu_usage(self) -> str:
        """R\u00e9cup\u00e8re l'utilisation CPU."""
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=0.1)
            return f"{cpu_percent}%"
        except ImportError:
            # Fallback sans psutil
            try:
                load = os.getloadavg()
                return f"{load[0]:.2f} (1min avg)"
            except (OSError, AttributeError):
                return "N/A"

    def _get_ram_usage(self) -> str:
        """R\u00e9cup\u00e8re l'utilisation RAM."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            used_gb = mem.used / (1024 ** 3)
            total_gb = mem.total / (1024 ** 3)
            return f"{used_gb:.1f}/{total_gb:.1f} GB ({mem.percent}%)"
        except ImportError:
            return "N/A (install psutil)"

    def _get_disk_usage(self) -> str:
        """R\u00e9cup\u00e8re l'utilisation disque."""
        try:
            import psutil
            disk = psutil.disk_usage("/")
            used_gb = disk.used / (1024 ** 3)
            total_gb = disk.total / (1024 ** 3)
            return f"{used_gb:.1f}/{total_gb:.1f} GB ({disk.percent}%)"
        except ImportError:
            return "N/A (install psutil)"

    def _get_ram_detailed(self) -> str:
        """Informations RAM d\u00e9taill\u00e9es."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            return (
                f"  Total: `{mem.total / (1024**3):.2f} GB`\n"
                f"  Used: `{mem.used / (1024**3):.2f} GB`\n"
                f"  Free: `{mem.available / (1024**3):.2f} GB`\n"
                f"  Usage: `{mem.percent}%`"
            )
        except ImportError:
            return "  N/A (install psutil)"

    def _get_disk_detailed(self) -> str:
        """Informations disque d\u00e9taill\u00e9es."""
        try:
            import psutil
            disk = psutil.disk_usage("/")
            return (
                f"  Total: `{disk.total / (1024**3):.2f} GB`\n"
                f"  Used: `{disk.used / (1024**3):.2f} GB`\n"
                f"  Free: `{disk.free / (1024**3):.2f} GB`\n"
                f"  Usage: `{disk.percent}%`"
            )
        except ImportError:
            return "  N/A (install psutil)"


def get_uptime() -> timedelta:
    """Retourne l'uptime du bot."""
    return datetime.now() - START_TIME


def get_uptime_str() -> str:
    """Retourne l'uptime format\u00e9 en string."""
    delta = get_uptime()
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"

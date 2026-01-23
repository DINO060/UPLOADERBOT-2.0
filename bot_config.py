"""
BOT CONFIGURATION
=================
Configuration centralis\u00e9e pour le bot Uploader.
Utilise admin_core pour les fonctionnalit\u00e9s admin.
"""

import os
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Import admin_core
from admin_core import AdminConfig

# ============================================================
# CONFIGURATION DU BOT
# ============================================================

# Token du bot
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# API Telegram (pour Pyrogram)
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

# ============================================================
# CONFIGURATION ADMIN CORE
# ============================================================

def get_admin_ids() -> list:
    """Parse les ADMIN_IDS depuis l'environnement."""
    admin_str = os.getenv("ADMIN_IDS", "")
    ids = []
    for x in admin_str.replace(" ", "").split(","):
        if x:
            try:
                ids.append(int(x))
            except ValueError:
                pass
    return ids


def get_force_join_channels() -> list:
    """Parse les canaux Force Join depuis l'environnement."""
    channels_str = os.getenv("FORCE_JOIN_CHANNELS", "")
    return [ch.strip() for ch in channels_str.split(",") if ch.strip()]


# Configuration Admin Core
admin_config = AdminConfig(
    # === ADMINS ===
    admin_ids=get_admin_ids(),
    owner_id=int(os.getenv("OWNER_ID", "0")) or None,

    # === DATABASE ===
    db_path="data/admin_core.db",

    # === FORCE JOIN ===
    force_join_enabled=os.getenv("FORCE_JOIN_ENABLED", "true").lower() == "true",
    force_join_channels=get_force_join_channels(),
    force_join_bypass_admins=True,
    force_join_message=(
        "**You must join our channels to use this bot.**\n\n"
        "Join the channels below and click **Verify**."
    ),
    force_join_button_text="Verify",

    # === BROADCAST ===
    broadcast_delay=0.05,
    broadcast_batch_size=25,

    # === SHORT LINKS ===
    shortlink_enabled=os.getenv("SHORTLINK_ENABLED", "false").lower() == "true",
    shortlink_provider=os.getenv("SHORTLINK_PROVIDER", "shorte.st"),
    shortlink_api_key=os.getenv("SHORTLINK_API_KEY", ""),

    # === RATE LIMIT ===
    rate_limit_enabled=True,
    rate_limit_messages=30,
    rate_limit_window=60,

    # === BUTTONS PAR D\u00c9FAUT ===
    default_buttons=[
        # Ajoutez vos boutons par d\u00e9faut ici
        # {"text": "Channel", "url": "https://t.me/yourchannel"},
    ],

    # === STATUS ===
    status_show_cpu=True,
    status_show_ram=True,
    status_show_disk=True,
    status_show_uptime=True,
    status_show_users=True,
)

# ============================================================
# CONFIGURATION DES WORKERS
# ============================================================

class WorkerConfig:
    """Configuration pour le syst\u00e8me de workers."""

    # Nombre de workers pour le traitement parall\u00e8le
    MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4"))

    # Taille de la queue des t\u00e2ches
    QUEUE_SIZE = int(os.getenv("QUEUE_SIZE", "100"))

    # Timeout pour les t\u00e2ches (secondes)
    TASK_TIMEOUT = int(os.getenv("TASK_TIMEOUT", "300"))

    # Intervalle de v\u00e9rification des workers (secondes)
    HEALTH_CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", "30"))

    # Retry en cas d'\u00e9chec
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_DELAY = int(os.getenv("RETRY_DELAY", "5"))


worker_config = WorkerConfig()

# ============================================================
# CONFIGURATION DES FICHIERS
# ============================================================

class FileConfig:
    """Configuration pour la gestion des fichiers."""

    # Limites de taille
    MAX_FILE_SIZE_BOT_API = 50 * 1024 * 1024  # 50 MB
    MAX_FILE_SIZE_USER_API = 2000 * 1024 * 1024  # 2 GB

    # Thumbnail
    THUMBNAIL_MAX_SIZE = 200 * 1024  # 200 KB
    THUMBNAIL_DIMENSIONS = (320, 320)
    THUMBNAIL_QUALITY = 90

    # Dossiers
    TEMP_DIR = os.getenv("TEMP_DIR", "temp")
    DATA_DIR = os.getenv("DATA_DIR", "data")
    LOGS_DIR = os.getenv("LOGS_DIR", "logs")

    # Limites utilisateur
    DAILY_LIMIT_BYTES = int(os.getenv("DAILY_LIMIT_GB", "50")) * 1024 * 1024 * 1024
    COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "0"))
    MAX_FILES_PER_POST = int(os.getenv("MAX_FILES_PER_POST", "30"))


file_config = FileConfig()

# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "BOT_TOKEN",
    "API_ID",
    "API_HASH",
    "admin_config",
    "worker_config",
    "file_config",
    "get_admin_ids",
]

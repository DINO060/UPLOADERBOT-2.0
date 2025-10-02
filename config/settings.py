from typing import Dict, List, Optional
import os
from pathlib import Path
import logging
from dotenv import load_dotenv

# Chargement des variables d'environnement
load_dotenv(override=True)  # S'assure de charger les variables même si elles existent déjà

# Configuration du logging
logger = logging.getLogger(__name__)

# Variables d'environnement obligatoires
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not all([BOT_TOKEN, API_ID, API_HASH]):
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not API_ID:
        missing.append("API_ID")
    if not API_HASH:
        missing.append("API_HASH")
    raise ValueError(f"Les variables d'environnement suivantes sont manquantes: {', '.join(missing)}")

# Chemins des dossiers
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
TEMP_DIR = BASE_DIR / "temp"

# Création des dossiers s'ils n'existent pas
for directory in [DATA_DIR, LOGS_DIR, TEMP_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# Configuration de la base de données
db_config = {
    "path": str(DATA_DIR / "bot.db"),
    "timeout": 30,
    "check_same_thread": False
}

# Configuration du bot
bot_config = {
    "token": os.getenv("BOT_TOKEN", ""),
    "api_id": int(os.getenv("API_ID", "0")),
    "api_hash": os.getenv("API_HASH", ""),
    "session_name": "bot_session",
    "admin_ids": [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id],
    "max_file_size": 2000 * 1024 * 1024,  # 2GB en bytes
    "allowed_extensions": {
        "image": [".jpg", ".jpeg", ".png", ".gif", ".webp"],
        "video": [".mp4", ".avi", ".mov", ".mkv", ".webm"],
        "document": [".pdf", ".doc", ".docx", ".txt", ".zip", ".rar"]
    }
}

# Configuration des logs
logging_config = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "level": "INFO"
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "default",
            "filename": str(LOGS_DIR / "bot.log"),
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "level": "DEBUG"
        }
    },
    "root": {
        "level": "INFO",
        "handlers": ["console", "file"]
    }
}

# États de la conversation
class ConversationStates:
    MAIN_MENU = 0
    CHANNEL_SELECTION = 1
    POST_TYPE = 2
    POST_CONTENT = 3
    POST_ACTIONS = 4
    SCHEDULE_TIME = 5
    REACTIONS = 6
    URL_BUTTONS = 7
    CONFIRMATION = 8

# Configuration des limites des groupes de médias
MAX_FILES_PER_MEDIA_GROUP = 30  # Nombre maximum de fichiers par post
DELAY_BETWEEN_GROUPS = 1.0  # Délai d'attente entre les envois de sous-groupes (en secondes)
MAX_MEDIA_GROUP_SIZE = 50 * 1024 * 1024  # 50MB en octets (limite de l'API Telegram)

# Configuration des limites générales
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 Mo
MAX_STORAGE_SIZE = 1000 * 1024 * 1024  # 1 Go
MAX_BACKUP_FILES = 5

# Messages d'erreur
ERROR_MESSAGES = {
    "invalid_time": "Format d'heure invalide. Utilisez HH:MM",
    "file_too_large": "Le fichier est trop volumineux",
    "storage_full": "L'espace de stockage est plein",
    "database_error": "Erreur de base de données",
    "permission_denied": "Permission refusée"
}

# Configuration des timezones
DEFAULT_TIMEZONE = "UTC"
SUPPORTED_TIMEZONES = [
    "UTC",
    "Europe/Paris",
    "America/New_York",
    "Asia/Tokyo"
]

# Configuration des types de fichiers autorisés
ALLOWED_FILE_TYPES = {
    "photo": [".jpg", ".jpeg", ".png", ".gif"],
    "video": [".mp4", ".mov", ".avi"],
    "document": [".pdf", ".doc", ".docx", ".txt"]
}

# Configuration des réactions
DEFAULT_REACTIONS = ["👍", "❤️", "🔥", "🎉", "🤔"]

# Configuration des boutons
MAX_BUTTONS_PER_ROW = 3
MAX_BUTTONS_TOTAL = 8

# Configuration des tâches planifiées
CLEANUP_INTERVAL = 3600  # 1 heure
BACKUP_INTERVAL = 86400  # 24 heures

# Classe pour gérer les paramètres
class Settings:
    def __init__(self):
        # Variables d'environnement
        self.BOT_TOKEN = os.getenv("BOT_TOKEN", "")
        self.API_ID = int(os.getenv("API_ID", "0"))
        self.API_HASH = os.getenv("API_HASH", "")
        
        # Configuration du bot
        self.bot_token = self.BOT_TOKEN  # Pour la rétrocompatibilité
        self.api_id = self.API_ID
        self.api_hash = self.API_HASH
        self.db_config = db_config
        self.max_file_size = bot_config["max_file_size"]
        self.max_storage_size = MAX_STORAGE_SIZE
        self.max_backup_files = MAX_BACKUP_FILES
        self.error_messages = ERROR_MESSAGES
        self.default_timezone = DEFAULT_TIMEZONE
        self.supported_timezones = SUPPORTED_TIMEZONES
        self.allowed_file_types = bot_config["allowed_extensions"]
        self.default_reactions = DEFAULT_REACTIONS
        self.max_buttons_per_row = MAX_BUTTONS_PER_ROW
        self.max_buttons_total = MAX_BUTTONS_TOTAL
        self.cleanup_interval = CLEANUP_INTERVAL
        self.backup_interval = BACKUP_INTERVAL
        
        # Configuration pour les clients avancés
        self.pyrogram_session = "pyrogram_session"
        self.telethon_session = "telethon_session"
        self.bot_max_size = 50 * 1024 * 1024  # 50MB limite de l'API Bot
        
        # Configuration des dossiers
        self.temp_folder = str(TEMP_DIR)
        
        # Délai d'attente (en secondes) pour la disponibilité de Pyrogram au démarrage
        # Peut être surchargé via la variable d'environnement PYRO_STARTUP_WAIT
        self.pyro_startup_wait = int(os.getenv("PYRO_STARTUP_WAIT", "8"))

# Instance unique des paramètres
settings = Settings()
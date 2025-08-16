"""
Configuration pour le bot multi-clients (Bot API, Pyrogram, Telethon)
"""
import os
import logging
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

# Setup logger
logger = logging.getLogger(__name__)

load_dotenv()

@dataclass
class ClientConfig:
    type: str
    max_size: int
    session: Optional[str]
    use_for: List[str]

@dataclass
class Settings:
    # API Telegram
    api_id: str = os.getenv('API_ID')
    api_hash: str = os.getenv('API_HASH')
    bot_token: str = os.getenv('BOT_TOKEN')
    
    # Admin IDs
    admin_ids: List[int] = None
    
    # Sessions
    pyrogram_session: str = "pyro_user"
    telethon_session: str = "telethon_user"
    session_name: str = os.getenv('SESSION_NAME', 'uploader_session')
    
    # Dossiers
    download_folder: str = os.getenv('DOWNLOAD_FOLDER', 'downloads/')
    temp_folder: str = os.path.join(download_folder, 'temp')
    
    # Database
    db_path: str = os.getenv('DB_PATH', 'bot.db')
    db_config: Dict[str, Any] = None
    
    # Limites
    bot_max_size: int = 50 * 1024 * 1024  # 50 MB (Bot API limit)
    userbot_max_size: int = 2 * 1024 * 1024 * 1024  # 2 GB (User API limit)
    
    # Thumbnail settings
    thumb_size: tuple = (320, 320)  # Taille recommandée pour les miniatures
    thumb_quality: int = 90  # Qualité JPEG
    max_thumb_size: int = 200 * 1024  # 200 KB (limite Telegram)
    
    # Default channel
    default_channel: str = os.getenv('DEFAULT_CHANNEL', 'https://t.me/sheweeb')
    
    # Client settings
    clients: Dict[str, ClientConfig] = None
    
    def __post_init__(self):
        # Parse admin IDs from environment variable
        admin_ids_str = os.getenv('ADMIN_IDS')
        if admin_ids_str:
            try:
                self.admin_ids = [int(id.strip()) for id in admin_ids_str.strip('[]').split(',') if id.strip()]
            except ValueError:
                logger.warning("Invalid ADMIN_IDS format in .env file")
                self.admin_ids = []
        else:
            self.admin_ids = []
        
        # Create download folder if it doesn't exist
        os.makedirs(self.download_folder, exist_ok=True)
        
        # Initialize database configuration
        self.db_config = {
            "path": self.db_path,
            "timeout": 30.0,  # Timeout en secondes pour les opérations de base de données
            "check_same_thread": False  # Permet l'accès depuis différents threads
        }
        
        # Initialize clients
        self.clients = {
            "bot": ClientConfig(
                type="bot",
                max_size=self.bot_max_size,
                session=None,  # Bot API n'utilise pas de session
                use_for=[]
            ),
            "pyrogram": ClientConfig(
                type="user",
                max_size=self.userbot_max_size,
                session=self.pyrogram_session,
                use_for=["thumbnails", "small_files", "rename"]
            ),
            "telethon": ClientConfig(
                type="user",
                max_size=self.userbot_max_size,
                session=self.telethon_session,
                use_for=["large_files", "mass_actions"]
            )
        }
        
        # Validate required settings
        if not all([self.api_id, self.api_hash, self.bot_token]):
            raise ValueError("Incomplete configuration: API_ID, API_HASH and BOT_TOKEN are required")

# Create a global settings instance
settings = Settings()

# Export admin IDs for compatibility with bot.py
ADMIN_IDS = ",".join(str(id) for id in settings.admin_ids) 
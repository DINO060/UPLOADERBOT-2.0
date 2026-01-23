"""
ADMIN CORE MODULE
=================
Module r\u00e9utilisable pour toutes les fonctionnalit\u00e9s admin de vos bots Telegram.

Fonctionnalit\u00e9s incluses:
- Force Join (FSub) : Canaux obligatoires
- Broadcast : Diffusion de messages \u00e0 tous les utilisateurs
- Status : Statistiques du bot (uptime, RAM, CPU, etc.)
- Short Links : Int\u00e9gration APIs de raccourcissement
- Buttons : Boutons de redirection configurables
- Ban System : Gestion des utilisateurs bannis
- Stats : Statistiques d\u00e9taill\u00e9es des utilisateurs
- Decorators : @admin_only, @ban_check, etc.

Usage:
------
```python
from admin_core import setup_admin, AdminConfig

config = AdminConfig(
    admin_ids=[123456789, 987654321],
    force_join_channels=["@mychannel", "@mychannel2"],
    shortlink_api="your_api_key",
    shortlink_provider="shorte.st"
)

app = Application.builder().token(BOT_TOKEN).build()
setup_admin(app, config)
```

Author: Renan
Version: 1.0.0
"""

__version__ = "1.0.0"
__author__ = "Renan"

# Imports principaux
from .config import AdminConfig
from .database import AdminDatabase
from .decorators import admin_only, owner_only, ban_check, rate_limit
from .force_join import ForceJoinManager
from .broadcast import BroadcastManager
from .status import StatusManager
from .shortlinks import ShortLinkManager
from .buttons import ButtonManager
from .ban_system import BanManager
from .stats import StatsManager

# Liste des modules exportés
__all__ = [
    # Config
    "AdminConfig",
    "AdminDatabase",

    # Managers
    "ForceJoinManager",
    "BroadcastManager",
    "StatusManager",
    "ShortLinkManager",
    "ButtonManager",
    "BanManager",
    "StatsManager",

    # Decorators
    "admin_only",
    "owner_only",
    "ban_check",
    "rate_limit",

    # Setup function
    "setup_admin",
]


def setup_admin(application, config: AdminConfig):
    """
    Configure toutes les fonctionnalit\u00e9s admin pour votre bot.

    Args:
        application: L'application Telegram (python-telegram-bot)
        config: Configuration AdminConfig

    Returns:
        dict: Dictionnaire contenant tous les managers initialis\u00e9s

    Example:
        ```python
        from admin_core import setup_admin, AdminConfig

        config = AdminConfig(
            admin_ids=[123456789],
            force_join_channels=["@mychannel"],
            db_path="data/admin.db"
        )

        managers = setup_admin(app, config)

        # Acc\u00e8s aux managers individuels
        force_join = managers["force_join"]
        broadcast = managers["broadcast"]
        ```
    """
    import logging
    logger = logging.getLogger("admin_core")
    logger.info("Initialisation du module Admin Core...")

    # Initialiser la base de donn\u00e9es
    db = AdminDatabase(config.db_path)
    db.setup()

    # Stocker la config et la DB dans bot_data
    application.bot_data["admin_config"] = config
    application.bot_data["admin_db"] = db

    # Initialiser les managers
    managers = {}

    # 1. Force Join
    if config.force_join_enabled:
        force_join = ForceJoinManager(config, db)
        force_join.register_handlers(application)
        managers["force_join"] = force_join
        logger.info(f"Force Join activ\u00e9 avec {len(config.force_join_channels)} canaux")

    # 2. Broadcast
    broadcast = BroadcastManager(config, db)
    broadcast.register_handlers(application)
    managers["broadcast"] = broadcast
    logger.info("Broadcast Manager activ\u00e9")

    # 3. Status
    status = StatusManager(config, db)
    status.register_handlers(application)
    managers["status"] = status
    logger.info("Status Manager activ\u00e9")

    # 4. Short Links
    if config.shortlink_enabled:
        shortlinks = ShortLinkManager(config)
        managers["shortlinks"] = shortlinks
        logger.info(f"Short Links activ\u00e9 avec {config.shortlink_provider}")

    # 5. Buttons
    buttons = ButtonManager(config, db)
    buttons.register_handlers(application)
    managers["buttons"] = buttons
    logger.info("Button Manager activ\u00e9")

    # 6. Ban System
    ban = BanManager(config, db)
    ban.register_handlers(application)
    managers["ban"] = ban
    logger.info("Ban System activ\u00e9")

    # 7. Stats
    stats = StatsManager(config, db)
    stats.register_handlers(application)
    managers["stats"] = stats
    logger.info("Stats Manager activ\u00e9")

    # Stocker les managers dans bot_data
    application.bot_data["admin_managers"] = managers

    logger.info("Admin Core initialis\u00e9 avec succ\u00e8s!")

    return managers


def get_manager(application, manager_name: str):
    """
    R\u00e9cup\u00e8re un manager sp\u00e9cifique depuis l'application.

    Args:
        application: L'application Telegram
        manager_name: Nom du manager ("force_join", "broadcast", etc.)

    Returns:
        Le manager demand\u00e9 ou None
    """
    managers = application.bot_data.get("admin_managers", {})
    return managers.get(manager_name)

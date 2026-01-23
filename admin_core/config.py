"""
ADMIN CORE - Configuration
==========================
Configuration centralis\u00e9e pour le module Admin Core.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import os


@dataclass
class AdminConfig:
    """
    Configuration principale du module Admin Core.

    Attributes:
        admin_ids: Liste des IDs des administrateurs
        owner_id: ID du propri\u00e9taire principal (super admin)
        db_path: Chemin vers la base de donn\u00e9es SQLite

        # Force Join
        force_join_enabled: Activer le syst\u00e8me Force Join
        force_join_channels: Liste des canaux obligatoires
        force_join_bypass_admins: Les admins bypass le force join

        # Broadcast
        broadcast_delay: D\u00e9lai entre chaque message (secondes)
        broadcast_batch_size: Nombre de messages par batch

        # Short Links
        shortlink_enabled: Activer les liens courts
        shortlink_provider: Fournisseur (shorte.st, etc.)
        shortlink_api_key: Cl\u00e9 API

        # Rate Limit
        rate_limit_enabled: Activer le rate limiting
        rate_limit_messages: Nombre de messages max
        rate_limit_window: Fen\u00eatre de temps (secondes)

        # Buttons
        default_buttons: Boutons par d\u00e9faut \u00e0 ajouter

    Example:
        ```python
        config = AdminConfig(
            admin_ids=[123456789, 987654321],
            owner_id=123456789,
            force_join_channels=["@mychannel", "@mychannel2"],
            shortlink_enabled=True,
            shortlink_provider="shorte.st",
            shortlink_api_key="your_api_key"
        )
        ```
    """

    # === ADMINS ===
    admin_ids: List[int] = field(default_factory=list)
    owner_id: Optional[int] = None

    # === DATABASE ===
    db_path: str = "data/admin_core.db"

    # === FORCE JOIN ===
    force_join_enabled: bool = True
    force_join_channels: List[str] = field(default_factory=list)
    force_join_bypass_admins: bool = True
    force_join_message: str = (
        "\u26a0\ufe0f **Vous devez rejoindre nos canaux pour utiliser ce bot.**\n\n"
        "Rejoignez les canaux ci-dessous puis cliquez sur **V\u00e9rifier**."
    )
    force_join_button_text: str = "\u2705 V\u00e9rifier"

    # === BROADCAST ===
    broadcast_delay: float = 0.05  # 50ms entre chaque message
    broadcast_batch_size: int = 25  # Messages par batch
    broadcast_sleep_between_batches: float = 1.0  # Pause entre batches

    # === SHORT LINKS ===
    shortlink_enabled: bool = False
    shortlink_provider: str = "shorte.st"  # shorte.st, linkvertise, etc.
    shortlink_api_key: str = ""
    shortlink_base_urls: Dict[str, str] = field(default_factory=lambda: {
        "shorte.st": "https://api.shorte.st/v1/data/url",
        "linkvertise": "https://publisher.linkvertise.com/api/v1/redirect/link/new",
        "gplinks": "https://gplinks.co/api",
        "shrinkme": "https://shrinkme.io/api",
        "urlshortx": "https://urlshortx.com/api",
    })

    # === RATE LIMIT ===
    rate_limit_enabled: bool = True
    rate_limit_messages: int = 30  # Max messages
    rate_limit_window: int = 60  # Par minute
    rate_limit_ban_duration: int = 300  # 5 minutes de ban

    # === DEFAULT BUTTONS ===
    default_buttons: List[Dict[str, str]] = field(default_factory=lambda: [
        # {"text": "\ud83d\udcac Channel", "url": "https://t.me/yourchannel"},
        # {"text": "\ud83d\udc65 Support", "url": "https://t.me/yoursupport"},
    ])

    # === STATUS ===
    status_show_cpu: bool = True
    status_show_ram: bool = True
    status_show_disk: bool = True
    status_show_uptime: bool = True
    status_show_users: bool = True
    status_show_ping: bool = True

    # === LOGGING ===
    log_level: str = "INFO"
    log_commands: bool = True  # Logger les commandes admin

    def __post_init__(self):
        """Validation et traitement apr\u00e8s initialisation."""
        # Si owner_id n'est pas d\u00e9fini, utiliser le premier admin
        if self.owner_id is None and self.admin_ids:
            self.owner_id = self.admin_ids[0]

        # S'assurer que owner_id est dans admin_ids
        if self.owner_id and self.owner_id not in self.admin_ids:
            self.admin_ids.insert(0, self.owner_id)

        # Cr\u00e9er le dossier pour la DB si n\u00e9cessaire
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        # Nettoyer les canaux (enlever les espaces, etc.)
        self.force_join_channels = [
            ch.strip() for ch in self.force_join_channels if ch.strip()
        ]

    def is_admin(self, user_id: int) -> bool:
        """V\u00e9rifie si un utilisateur est admin."""
        return user_id in self.admin_ids

    def is_owner(self, user_id: int) -> bool:
        """V\u00e9rifie si un utilisateur est le propri\u00e9taire."""
        return user_id == self.owner_id

    def add_admin(self, user_id: int) -> bool:
        """Ajoute un admin."""
        if user_id not in self.admin_ids:
            self.admin_ids.append(user_id)
            return True
        return False

    def remove_admin(self, user_id: int) -> bool:
        """Retire un admin (sauf owner)."""
        if user_id in self.admin_ids and user_id != self.owner_id:
            self.admin_ids.remove(user_id)
            return True
        return False

    def add_force_join_channel(self, channel: str) -> bool:
        """Ajoute un canal Force Join."""
        channel = channel.strip()
        if not channel.startswith("@") and not channel.startswith("-"):
            channel = f"@{channel}"
        if channel not in self.force_join_channels:
            self.force_join_channels.append(channel)
            return True
        return False

    def remove_force_join_channel(self, channel: str) -> bool:
        """Retire un canal Force Join."""
        channel = channel.strip()
        if not channel.startswith("@") and not channel.startswith("-"):
            channel = f"@{channel}"
        if channel in self.force_join_channels:
            self.force_join_channels.remove(channel)
            return True
        return False

    @classmethod
    def from_env(cls) -> "AdminConfig":
        """
        Cr\u00e9e une configuration depuis les variables d'environnement.

        Variables support\u00e9es:
            ADMIN_IDS: "123,456,789"
            OWNER_ID: "123"
            FORCE_JOIN_CHANNELS: "@chan1,@chan2"
            SHORTLINK_API_KEY: "your_key"
            SHORTLINK_PROVIDER: "shorte.st"
            DB_PATH: "data/admin.db"
        """
        # Parser ADMIN_IDS
        admin_ids_str = os.getenv("ADMIN_IDS", "")
        admin_ids = []
        if admin_ids_str:
            for id_str in admin_ids_str.split(","):
                try:
                    admin_ids.append(int(id_str.strip()))
                except ValueError:
                    pass

        # Parser OWNER_ID
        owner_id = None
        owner_id_str = os.getenv("OWNER_ID", "")
        if owner_id_str:
            try:
                owner_id = int(owner_id_str.strip())
            except ValueError:
                pass

        # Parser FORCE_JOIN_CHANNELS
        channels_str = os.getenv("FORCE_JOIN_CHANNELS", "")
        channels = [ch.strip() for ch in channels_str.split(",") if ch.strip()]

        return cls(
            admin_ids=admin_ids,
            owner_id=owner_id,
            db_path=os.getenv("ADMIN_DB_PATH", "data/admin_core.db"),
            force_join_channels=channels,
            force_join_enabled=os.getenv("FORCE_JOIN_ENABLED", "true").lower() == "true",
            shortlink_enabled=os.getenv("SHORTLINK_ENABLED", "false").lower() == "true",
            shortlink_provider=os.getenv("SHORTLINK_PROVIDER", "shorte.st"),
            shortlink_api_key=os.getenv("SHORTLINK_API_KEY", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convertit la configuration en dictionnaire."""
        return {
            "admin_ids": self.admin_ids,
            "owner_id": self.owner_id,
            "db_path": self.db_path,
            "force_join_enabled": self.force_join_enabled,
            "force_join_channels": self.force_join_channels,
            "shortlink_enabled": self.shortlink_enabled,
            "shortlink_provider": self.shortlink_provider,
            "rate_limit_enabled": self.rate_limit_enabled,
        }

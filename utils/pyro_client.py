"""
Client Pyrogram singleton (mode BOT) démarré à la demande.
Expose deux fonctions:
- get_pyro(): démarre et retourne l'unique client Pyrogram
- ensure_pyro_started(): démarre au boot pour fail-fast si variables manquent
"""

import asyncio
import atexit
from typing import Optional
import logging
from pyrogram import Client

from config.settings import settings as app_settings

logger = logging.getLogger(__name__)

_PYRO: Optional[Client] = None
_LOCK = asyncio.Lock()

async def get_pyro() -> Optional[Client]:
    """
    Démarre et retourne un unique client Pyrogram (mode BOT).
    Retourne None si variables manquantes.
    """
    global _PYRO
    async with _LOCK:
        if _PYRO and _PYRO.is_connected:
            return _PYRO

        # Vérifier les variables requises (depuis l'instance Settings)
        api_id = int(getattr(app_settings, 'api_id', 0) or 0)
        api_hash = getattr(app_settings, 'api_hash', '') or ''
        bot_token = getattr(app_settings, 'bot_token', '') or ''
        missing = [k for k, v in {
            "API_ID": api_id,
            "API_HASH": api_hash,
            "BOT_TOKEN": bot_token,
        }.items() if not v]
        if missing:
            logger.error(f"❌ Pyrogram non initialisé: variables manquantes: {', '.join(missing)}")
            return None

        _PYRO = Client(
            name="uploader_bot",
            api_id=api_id,
            api_hash=api_hash,
            bot_token=bot_token,   # MODE BOT
            no_updates=True,       # pas d'updates
            in_memory=True,        # pas de session fichier
        )
        await _PYRO.start()

        # Enregistrer l'arrêt propre à la sortie du process
        try:
            atexit.register(lambda: asyncio.get_event_loop().create_task(_PYRO.stop()))
        except Exception:
            pass
        logger.info("✅ Client Pyrogram global démarré avec succès")
        return _PYRO


async def ensure_pyro_started() -> None:
    """Démarre Pyrogram au boot pour fail-fast si variables manquent."""
    client = await get_pyro()
    if not client:
        logger.warning("⚠️ Pyrogram indisponible: opérations avancées (download/upload) désactivées.")


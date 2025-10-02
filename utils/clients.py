"""
Gestionnaire des clients Telegram (Bot API + Pyrogram uniquement)
Utilise maintenant le client Pyrogram global géré par PTB
"""
import logging
import asyncio
from typing import Optional, Dict, Any
from config import settings

logger = logging.getLogger(__name__)

class ClientManager:
    def __init__(self):
        self._active = False

    async def start_clients(self):
        """Utilise le client Pyrogram global au lieu de créer un nouveau"""
        if self._active:
            return

        try:
            logger.info("🔄 Initialisation du client Pyrogram (singleton)…")
            from utils.pyro_client import get_pyro
            client = await get_pyro()
            if client:
                self._active = True
                logger.info("✅ Client Pyrogram disponible")
            else:
                logger.warning("⚠️ Client Pyrogram non disponible")
                logger.warning("⚠️ Bot continuera en mode dégradé (API Bot seulement)")

        except Exception as e:
            logger.error(f"❌ Erreur lors de la vérification du client global: {e}")
            logger.warning("⚠️ Bot continuera en mode dégradé (API Bot seulement)")

    async def stop_clients(self):
        """Le client global est arrêté automatiquement par PTB"""
        logger.info("✅ Client Pyrogram global géré automatiquement par PTB")
        self._active = False
            

    async def get_best_client(self, file_size: int, operation: str) -> Dict[str, Any]:
        """
        Retourne le meilleur client pour une opération donnée.
        Utilise maintenant le client Pyrogram global.
        
        Args:
            file_size: Taille du fichier en bytes
            operation: Type d'opération ('upload', 'thumbnail', 'rename', etc.)
        
        Returns:
            Dict contenant le client et son type
        """
        logger.info(f"🔍 get_best_client: operation={operation}, file_size={file_size/1024/1024:.1f}MB")
        
        # Récupérer le client singleton
        from utils.pyro_client import get_pyro
        max_wait = getattr(settings, 'pyro_startup_wait', 8)  # secondes
        interval = 0.5
        waited = 0.0
        pyro_client = await get_pyro()
        if not pyro_client:
            logger.info("⏳ Attente de la disponibilité du client Pyrogram…")
            while waited < max_wait and not pyro_client:
                await asyncio.sleep(interval)
                waited += interval
                pyro_client = await get_pyro()
        if not pyro_client:
            logger.error(f"❌ Client Pyrogram non disponible pour {operation}")
            raise Exception(f"Client Pyrogram non disponible pour {operation}")
        logger.info(f"✅ Utilisation du client Pyrogram global pour {operation}")
        return {"client": pyro_client, "type": "pyrogram"}

    async def get_pyrogram_client(self):
        """
        Retourne le client Pyrogram global s'il est disponible.
        
        Returns:
            Client Pyrogram global ou None
        """
        from utils.pyro_client import get_pyro
        max_wait = getattr(settings, 'pyro_startup_wait', 5)
        interval = 0.5
        waited = 0.0
        pyro_client = await get_pyro()
        while not pyro_client and waited < max_wait:
            await asyncio.sleep(interval)
            waited += interval
            pyro_client = await get_pyro()
        return pyro_client

    async def handle_peer_error(self, client_type: str, error: Exception):
        """
        Gère les erreurs de Peer ID invalide et autres erreurs critiques.
        
        Args:
            client_type: Type de client ('pyrogram')
            error: Exception reçue
        """
        error_str = str(error)
        
        if "Peer id invalid" in error_str or "peer id invalid" in error_str.lower():
            logger.warning(f"⚠️ {client_type}: Peer ID invalide détecté - {error_str}")
            logger.info("💡 Solution: Vérifiez que le bot a accès au canal/groupe cible")
            
        elif "FILE_REFERENCE_EXPIRED" in error_str:
            logger.warning(f"⚠️ {client_type}: Référence de fichier expirée - {error_str}")
            logger.info("💡 Solution: Le fichier doit être renvoyé directement au bot")
            
        else:
            logger.error(f"❌ {client_type}: Erreur non gérée - {error_str}")

# Instance globale du gestionnaire de clients
client_manager = ClientManager() 
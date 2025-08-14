"""
Gestionnaire des clients Telegram (Bot API + Pyrogram uniquement)
"""
import logging
from typing import Optional, Dict, Any
from pyrogram import Client as PyrogramClient
from config import settings

logger = logging.getLogger(__name__)

class ClientManager:
    def __init__(self):
        self.pyro_user: Optional[PyrogramClient] = None
        self._active = False
        self._pyro_failed = False

    async def start_clients(self):
        """Starts all clients with robust error handling"""
        if self._active:
            return

        try:
            logger.info("🔄 Attempting to start clients...")
            
            # Vérifier les configurations
            if not settings.api_id or not settings.api_hash:
                logger.error("❌ API_ID or API_HASH missing in configuration")
                logger.error("💡 Add these values to your .env file:")
                logger.error("   API_ID=your_api_id")
                logger.error("   API_HASH=your_api_hash")
                logger.error("👉 Get them at https://my.telegram.org")
                raise ValueError("Missing configuration: API_ID/API_HASH")
                
            logger.info(f"📋 Configuration: API_ID={settings.api_id}, Session Pyrogram={settings.pyrogram_session}")
            
            # ✅ DÉMARRAGE SÉCURISÉ DE PYROGRAM
            if not self._pyro_failed:
                try:
                    self.pyro_user = PyrogramClient(
                        settings.pyrogram_session,
                        api_id=settings.api_id,
                        api_hash=settings.api_hash,
                        bot_token=settings.bot_token,
                        in_memory=True  # ✅ Éviter les problèmes de session
                    )
                    logger.info("🔄 Starting Pyrogram client...")
                    await self.pyro_user.start()
                    
                    # ✅ TEST DE CONNECTIVITÉ
                    try:
                        me = await self.pyro_user.get_me()
                        logger.info(f"✅ Pyrogram client (BOT) started: @{me.username}")
                    except Exception as test_error:
                        logger.warning(f"⚠️ Pyrogram connectivity test failed: {test_error}")
                        
                except Exception as pyro_error:
                    logger.error(f"❌ Pyrogram startup failed: {pyro_error}")
                    self._pyro_failed = True
                    self.pyro_user = None

            # ✅ VÉRIFICATION FINALE
            if self.pyro_user:
                self._active = True
                available_clients = []
                if self.pyro_user:
                    available_clients.append("Pyrogram")
                logger.info(f"✅ Clients disponibles: {', '.join(available_clients)}")
            else:
                logger.error("❌ No client could be started")
                raise Exception("All clients failed")

        except Exception as e:
            logger.error(f"❌ Critical error during client startup: {e}")
            await self.stop_clients()
            # Ne pas relancer l'erreur pour permettre au bot de fonctionner en mode dégradé
            logger.warning("⚠️ Bot will continue in degraded mode (API Bot only)")

    async def stop_clients(self):
        """Stops all clients with error handling"""
        try:
            if self.pyro_user:
                try:
                    await self.pyro_user.stop()
                    logger.info("✅ Pyrogram client stopped")
                except Exception as e:
                    logger.warning(f"⚠️ Pyrogram stop error: {e}")

        except Exception as e:
            logger.error(f"❌ Error stopping clients: {e}")
        finally:
            self._active = False
            self.pyro_user = None
            

    async def get_best_client(self, file_size: int, operation: str) -> Dict[str, Any]:
        """
        Retourne le meilleur client pour une opération donnée.
        
        Args:
            file_size: Taille du fichier en bytes
            operation: Type d'opération ('upload', 'thumbnail', 'rename', etc.)
        
        Returns:
            Dict contenant le client et son type
        """
        logger.info(f"🔍 get_best_client: operation={operation}, file_size={file_size/1024/1024:.1f}MB")
        
        if not self._active:
            logger.info("⚠️ Clients non actifs, tentative de démarrage...")
            await self.start_clients()

        # ✅ SÉLECTION INTELLIGENTE AVEC FALLBACK
        if operation in ["thumbnail", "rename", "download"]:
            # Priorité Pyrogram pour ces opérations
            if self.pyro_user and not self._pyro_failed:
                logger.info(f"✅ Sélection Pyrogram pour {operation}")
                return {"client": self.pyro_user, "type": "pyrogram"}
            else:
                logger.error(f"❌ Aucun client disponible pour {operation}")
                raise Exception(f"Aucun client disponible pour {operation}")
                
        elif operation == "upload":
            if file_size <= settings.bot_max_size:  # ≤ 50 MB
                # Préférer Pyrogram pour les petits fichiers
                if self.pyro_user and not self._pyro_failed:
                    logger.info(f"✅ Pyrogram pour upload ≤ 50MB")
                    return {"client": self.pyro_user, "type": "pyrogram"}
            else:
                # Fallback Pyrogram aussi pour >50MB (selon quotas)
                if self.pyro_user and not self._pyro_failed:
                    logger.info(f"✅ Fallback Pyrogram pour upload > 50MB")
                    return {"client": self.pyro_user, "type": "pyrogram"}
        
        # ✅ FALLBACK GÉNÉRAL
        if self.pyro_user and not self._pyro_failed:
            logger.info(f"✅ Pyrogram par défaut pour {operation}")
            return {"client": self.pyro_user, "type": "pyrogram"}
        else:
            logger.error(f"❌ Aucun client fonctionnel disponible")
            raise Exception("Aucun client fonctionnel disponible")

    async def get_pyrogram_client(self) -> Optional[PyrogramClient]:
        """
        Retourne le client Pyrogram s'il est disponible.
        
        Returns:
            Client Pyrogram ou None
        """
        if not self._active:
            await self.start_clients()
        return self.pyro_user if not self._pyro_failed else None

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
            
            if client_type == "pyrogram":
                logger.warning("⚠️ Désactivation temporaire du client Pyrogram")
                self._pyro_failed = True
                
            logger.info("💡 Solution: Vérifiez que le bot a accès au canal/groupe cible")
            
        elif "FILE_REFERENCE_EXPIRED" in error_str:
            logger.warning(f"⚠️ {client_type}: Référence de fichier expirée - {error_str}")
            logger.info("💡 Solution: Le fichier doit être renvoyé directement au bot")
            
        else:
            logger.error(f"❌ {client_type}: Erreur non gérée - {error_str}")

# Instance globale du gestionnaire de clients
client_manager = ClientManager() 
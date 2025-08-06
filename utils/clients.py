"""
Gestionnaire des clients Telegram (Bot API, Pyrogram, Telethon)
"""
import logging
from typing import Optional, Dict, Any
from pyrogram import Client as PyrogramClient
from telethon import TelegramClient as TelethonClient
from config import settings

logger = logging.getLogger(__name__)

class ClientManager:
    def __init__(self):
        self.pyro_user: Optional[PyrogramClient] = None
        self.telethon_user: Optional[TelethonClient] = None
        self._active = False
        self._pyro_failed = False
        self._telethon_failed = False

    async def start_clients(self):
        """Démarre tous les clients avec gestion d'erreurs robuste"""
        if self._active:
            return

        try:
            logger.info("🔄 Tentative de démarrage des clients...")
            
            # Vérifier les configurations
            if not settings.api_id or not settings.api_hash:
                logger.error("❌ API_ID ou API_HASH manquant dans la configuration")
                logger.error("💡 Ajoutez ces valeurs dans votre fichier .env:")
                logger.error("   API_ID=votre_api_id")
                logger.error("   API_HASH=votre_api_hash")
                logger.error("👉 Obtenez-les sur https://my.telegram.org")
                raise ValueError("Configuration manquante: API_ID/API_HASH")
                
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
                    logger.info("🔄 Démarrage client Pyrogram...")
                    await self.pyro_user.start()
                    
                    # ✅ TEST DE CONNECTIVITÉ
                    try:
                        me = await self.pyro_user.get_me()
                        logger.info(f"✅ Client Pyrogram (BOT) démarré: @{me.username}")
                    except Exception as test_error:
                        logger.warning(f"⚠️ Test connectivité Pyrogram échoué: {test_error}")
                        
                except Exception as pyro_error:
                    logger.error(f"❌ Échec démarrage Pyrogram: {pyro_error}")
                    self._pyro_failed = True
                    self.pyro_user = None

            # ✅ DÉMARRAGE SÉCURISÉ DE TELETHON
            if not self._telethon_failed:
                try:
                    self.telethon_user = TelethonClient(
                        settings.telethon_session,
                        settings.api_id,
                        settings.api_hash,
                        auto_reconnect=True,  # ✅ Reconnexion automatique
                        connection_retries=3  # ✅ Limite les tentatives
                    )
                    logger.info("🔄 Démarrage client Telethon...")
                    await self.telethon_user.start(bot_token=settings.bot_token)
                    
                    # ✅ TEST DE CONNECTIVITÉ
                    try:
                        me = await self.telethon_user.get_me()
                        logger.info(f"✅ Client Telethon (BOT) démarré: @{me.username}")
                    except Exception as test_error:
                        logger.warning(f"⚠️ Test connectivité Telethon échoué: {test_error}")
                        
                except Exception as tele_error:
                    logger.error(f"❌ Échec démarrage Telethon: {tele_error}")
                    self._telethon_failed = True
                    self.telethon_user = None

            # ✅ VÉRIFICATION FINALE
            if self.pyro_user or self.telethon_user:
                self._active = True
                available_clients = []
                if self.pyro_user:
                    available_clients.append("Pyrogram")
                if self.telethon_user:
                    available_clients.append("Telethon")
                logger.info(f"✅ Clients disponibles: {', '.join(available_clients)}")
            else:
                logger.error("❌ Aucun client n'a pu être démarré")
                raise Exception("Tous les clients ont échoué")

        except Exception as e:
            logger.error(f"❌ Erreur critique lors du démarrage des clients: {e}")
            await self.stop_clients()
            # Ne pas relancer l'erreur pour permettre au bot de fonctionner en mode dégradé
            logger.warning("⚠️ Bot continuera en mode dégradé (API Bot seulement)")

    async def stop_clients(self):
        """Arrête tous les clients avec gestion d'erreurs"""
        try:
            if self.pyro_user:
                try:
                    await self.pyro_user.stop()
                    logger.info("✅ Client Pyrogram arrêté")
                except Exception as e:
                    logger.warning(f"⚠️ Erreur arrêt Pyrogram: {e}")

            if self.telethon_user:
                try:
                    await self.telethon_user.disconnect()
                    logger.info("✅ Client Telethon arrêté")
                except Exception as e:
                    logger.warning(f"⚠️ Erreur arrêt Telethon: {e}")

        except Exception as e:
            logger.error(f"❌ Erreur lors de l'arrêt des clients: {e}")
        finally:
            self._active = False
            self.pyro_user = None
            self.telethon_user = None

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
            elif self.telethon_user and not self._telethon_failed:
                logger.info(f"✅ Fallback Telethon pour {operation}")
                return {"client": self.telethon_user, "type": "telethon"}
            else:
                logger.error(f"❌ Aucun client disponible pour {operation}")
                raise Exception(f"Aucun client disponible pour {operation}")
                
        elif operation == "upload":
            if file_size <= settings.bot_max_size:  # ≤ 50 MB
                # Préférer Pyrogram pour les petits fichiers
                if self.pyro_user and not self._pyro_failed:
                    logger.info(f"✅ Pyrogram pour upload ≤ 50MB")
                    return {"client": self.pyro_user, "type": "pyrogram"}
                elif self.telethon_user and not self._telethon_failed:
                    logger.info(f"✅ Fallback Telethon pour upload ≤ 50MB")
                    return {"client": self.telethon_user, "type": "telethon"}
            else:
                # Préférer Telethon pour les gros fichiers
                if self.telethon_user and not self._telethon_failed:
                    logger.info(f"✅ Telethon pour upload > 50MB")
                    return {"client": self.telethon_user, "type": "telethon"}
                elif self.pyro_user and not self._pyro_failed:
                    logger.info(f"✅ Fallback Pyrogram pour upload > 50MB")
                    return {"client": self.pyro_user, "type": "pyrogram"}
        
        # ✅ FALLBACK GÉNÉRAL
        if self.telethon_user and not self._telethon_failed:
            logger.info(f"✅ Telethon par défaut pour {operation}")
            return {"client": self.telethon_user, "type": "telethon"}
        elif self.pyro_user and not self._pyro_failed:
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

    async def get_telethon_client(self) -> Optional[TelethonClient]:
        """
        Retourne le client Telethon s'il est disponible.
        
        Returns:
            Client Telethon ou None
        """
        if not self._active:
            await self.start_clients()
        return self.telethon_user if not self._telethon_failed else None

    async def handle_peer_error(self, client_type: str, error: Exception):
        """
        Gère les erreurs de Peer ID invalide et autres erreurs critiques.
        
        Args:
            client_type: Type de client ('pyrogram' ou 'telethon')
            error: Exception reçue
        """
        error_str = str(error)
        
        if "Peer id invalid" in error_str or "peer id invalid" in error_str.lower():
            logger.warning(f"⚠️ {client_type}: Peer ID invalide détecté - {error_str}")
            
            if client_type == "pyrogram":
                logger.warning("⚠️ Désactivation temporaire du client Pyrogram")
                self._pyro_failed = True
            elif client_type == "telethon":
                logger.warning("⚠️ Désactivation temporaire du client Telethon")
                self._telethon_failed = True
                
            logger.info("💡 Solution: Vérifiez que le bot a accès au canal/groupe cible")
            
        elif "FILE_REFERENCE_EXPIRED" in error_str:
            logger.warning(f"⚠️ {client_type}: Référence de fichier expirée - {error_str}")
            logger.info("💡 Solution: Le fichier doit être renvoyé directement au bot")
            
        else:
            logger.error(f"❌ {client_type}: Erreur non gérée - {error_str}")

# Instance globale du gestionnaire de clients
client_manager = ClientManager() 
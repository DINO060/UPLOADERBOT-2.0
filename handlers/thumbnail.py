"""
Handler pour la gestion des miniatures avec Pyrogram
"""
import os
import logging
from typing import Optional
from utils.clients import client_manager
from utils.thumb_utils import optimize_thumbnail
from config import settings

logger = logging.getLogger(__name__)

async def handle_thumbnail_pyrogram(thumb_id: str, operation: str = "set", context=None) -> Optional[str]:
    """
    Gère les opérations sur les miniatures avec Pyrogram.
    
    Args:
        thumb_id: ID du fichier miniature Telegram ou chemin local
        operation: Type d'opération ('set', 'get', 'delete')
        context: Contexte Telegram optionnel pour utiliser l'API Bot
    
    Returns:
        str: Chemin local de la miniature optimisée ou None en cas d'erreur
    """
    try:
        logger.info(f"🖼️ HANDLE_THUMBNAIL: thumb_id={thumb_id[:50] if len(thumb_id) > 50 else thumb_id}, operation={operation}")
        
        if operation == "set":
            # Créer le dossier temporaire si nécessaire
            os.makedirs(settings.temp_folder, exist_ok=True)
            
            # ✅ VÉRIFICATION PRIORITAIRE : FICHIER LOCAL
            if os.path.exists(thumb_id):
                logger.info(f"📁 Utilisation directe du fichier local: {thumb_id}")
                
                # Valider le fichier local
                if os.path.getsize(thumb_id) == 0:
                    logger.error(f"❌ Fichier thumbnail local vide: {thumb_id}")
                    return None
                    
                # Optimiser directement le fichier local
                optimized_path = optimize_thumbnail(thumb_id)
                if optimized_path:
                    logger.info(f"✅ Thumbnail local optimisé: {optimized_path}")
                    return optimized_path
                else:
                    logger.error(f"❌ Échec optimisation du fichier local: {thumb_id}")
                    return None
            
            # ✅ TÉLÉCHARGEMENT VIA FILE_ID AVEC GESTION ROBUSTE DES ERREURS
            downloaded_path = None
            
            # STRATÉGIE 1 : Essayer d'abord avec l'API Bot (plus fiable pour les petits fichiers)
            if context and hasattr(context, 'bot'):
                logger.info(f"📥 Tentative 1/3: Téléchargement via API Bot...")
                try:
                    temp_path = os.path.join(settings.temp_folder, f"thumb_api_{os.urandom(4).hex()}.jpg")
                    file_obj = await context.bot.get_file(thumb_id)
                    downloaded_path = await file_obj.download_to_drive(temp_path)
                    
                    if downloaded_path and os.path.exists(downloaded_path) and os.path.getsize(downloaded_path) > 0:
                        logger.info(f"✅ Thumbnail téléchargé via API Bot: {downloaded_path}")
                    else:
                        raise Exception("Fichier téléchargé invalide via API Bot")
                        
                except Exception as api_error:
                    error_str = str(api_error)
                    logger.warning(f"⚠️ Échec API Bot: {error_str}")
                    downloaded_path = None
                    
                    # Ne pas continuer si c'est une erreur de taille (API Bot ne peut pas gérer les gros fichiers)
                    if "File is too big" in error_str or "file is too big" in error_str.lower():
                        logger.info("ℹ️ Fichier trop gros pour API Bot, passage direct aux clients avancés")
            
            # STRATÉGIE 2 : Fallback vers Pyrogram si API Bot a échoué
            if not downloaded_path:
                logger.info(f"📥 Tentative 2/3: Téléchargement via Pyrogram...")
                try:
                    client_info = await client_manager.get_best_client(0, "thumbnail")
                    pyro_client = client_info["client"]
                    
                    if not pyro_client:
                        raise Exception("Client Pyrogram non disponible")
                    
                    temp_path = os.path.join(settings.temp_folder, f"thumb_pyro_{os.urandom(4).hex()}.jpg")
                    downloaded_path = await pyro_client.download_media(thumb_id, temp_path)
                    
                    if downloaded_path and os.path.exists(downloaded_path) and os.path.getsize(downloaded_path) > 0:
                        logger.info(f"✅ Thumbnail téléchargé via Pyrogram: {downloaded_path}")
                    else:
                        raise Exception("Fichier téléchargé invalide via Pyrogram")
                        
                except Exception as pyro_error:
                    error_str = str(pyro_error)
                    logger.warning(f"⚠️ Échec Pyrogram: {error_str}")
                    downloaded_path = None
                    
                    # Gestion spécifique de FILE_REFERENCE_EXPIRED
                    if "FILE_REFERENCE_EXPIRED" in error_str:
                        logger.warning("🔄 FILE_REFERENCE_EXPIRED détecté, le thumbnail n'est plus accessible")
            
            # STRATÉGIE 3 : plus de Telethon — on arrête la chaîne ici
            
            # ✅ VÉRIFICATION FINALE ET OPTIMISATION
            if not downloaded_path:
                logger.error(f"❌ ÉCHEC TOTAL: Impossible de télécharger le thumbnail {thumb_id[:30]}...")
                return None
            
            # Validation finale du fichier téléchargé
            if not os.path.exists(downloaded_path) or os.path.getsize(downloaded_path) == 0:
                logger.error(f"❌ Fichier thumbnail téléchargé invalide: {downloaded_path}")
                try:
                    os.remove(downloaded_path)
                except:
                    pass
                return None
            
            # Optimiser la miniature
            logger.info(f"🔧 Optimisation du thumbnail...")
            optimized_path = optimize_thumbnail(downloaded_path)
            
            # Nettoyer le fichier temporaire de téléchargement (sauf si c'est le même que l'optimisé)
            if downloaded_path != optimized_path:
                try:
                    os.remove(downloaded_path)
                    logger.info(f"🧹 Fichier temporaire supprimé: {downloaded_path}")
                except Exception as cleanup_error:
                    logger.warning(f"⚠️ Erreur nettoyage: {cleanup_error}")
            
            if optimized_path and os.path.exists(optimized_path):
                logger.info(f"✅ Thumbnail finalisé: {optimized_path}")
                return optimized_path
            else:
                logger.error(f"❌ Échec de l'optimisation du thumbnail")
                return None
            
        elif operation == "get":
            # Obtenir les informations sur la miniature
            if os.path.exists(thumb_id):
                # C'est un fichier local
                return {"local_path": thumb_id, "size": os.path.getsize(thumb_id)}
            else:
                # C'est un file_id - essayer de récupérer les infos
                try:
                    client_info = await client_manager.get_best_client(0, "thumbnail")
                    pyro_client = client_info["client"]
                    if pyro_client:
                        # Note: get_file n'existe pas dans Pyrogram, utiliser download_media avec un path temporaire
                        return {"file_id": thumb_id, "accessible": True}
                    else:
                        return {"file_id": thumb_id, "accessible": False}
                except Exception:
                    return {"file_id": thumb_id, "accessible": False}
            
        elif operation == "delete":
            # Supprimer la miniature
            if os.path.exists(thumb_id):
                # C'est un fichier local
                try:
                    os.remove(thumb_id)
                    logger.info(f"✅ Fichier thumbnail local supprimé: {thumb_id}")
                    return "deleted"
                except Exception as e:
                    logger.error(f"❌ Erreur suppression fichier local: {e}")
                    return None
            else:
                # C'est un file_id - on ne peut pas supprimer un file_id Telegram
                logger.info(f"ℹ️ Impossible de supprimer un file_id Telegram: {thumb_id[:30]}...")
                return "file_id_cannot_be_deleted"
            
    except Exception as e:
        logger.error(f"❌ Erreur critique dans handle_thumbnail_pyrogram: {e}")
        return None

async def apply_thumbnail_to_message(message_id: int, thumb_path: str, chat_id: int) -> bool:
    """
    Applique une miniature à un message existant.
    
    Args:
        message_id: ID du message à modifier
        thumb_path: Chemin local vers la miniature
        chat_id: ID du chat
    
    Returns:
        bool: True si succès, False sinon
    """
    try:
        # ✅ VALIDATION DU FICHIER THUMBNAIL
        if not os.path.exists(thumb_path):
            logger.error(f"❌ Fichier thumbnail inexistant: {thumb_path}")
            return False
            
        if os.path.getsize(thumb_path) == 0:
            logger.error(f"❌ Fichier thumbnail vide: {thumb_path}")
            return False
        
        client_info = await client_manager.get_best_client(0, "thumbnail")
        pyro_client = client_info["client"]
        
        if not pyro_client:
            logger.error("❌ Aucun client Pyrogram disponible pour appliquer le thumbnail")
            return False
        
        # Modifier le message pour ajouter la miniature
        await pyro_client.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            thumb=thumb_path
        )
        
        logger.info(f"✅ Thumbnail appliqué au message {message_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'application du thumbnail: {e}")
        return False 
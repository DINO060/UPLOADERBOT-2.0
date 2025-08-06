"""
Handler pour l'envoi de fichiers avec gestion intelligente des clients
"""
import os
import logging
from typing import Optional, Dict, Any
from utils.clients import client_manager
from handlers.thumbnail import handle_thumbnail_pyrogram
from config import settings

logger = logging.getLogger(__name__)

async def send_file_smart(
    chat_id: str,
    file_path: str,
    caption: Optional[str] = None,
    thumb_id: Optional[str] = None,
    file_name: Optional[str] = None,
    force_document: bool = False,
    context = None
) -> Dict[str, Any]:
    """
    Envoie un fichier en utilisant le meilleur client disponible.
    
    Args:
        chat_id: ID du chat cible
        file_path: Chemin du fichier à envoyer
        caption: Légende du fichier
        thumb_id: ID de la miniature Telegram ou chemin local
        file_name: Nouveau nom pour le fichier
        force_document: Forcer l'envoi en tant que document
        context: Contexte Telegram optionnel pour gérer les thumb_id expirés
    
    Returns:
        Dict contenant le statut, message_id, file_id et les informations du message
    """
    try:
        # ✅ VALIDATION COMPLÈTE DU FICHIER
        if not file_path:
            raise Exception("Chemin de fichier manquant")
            
        if not os.path.exists(file_path):
            raise Exception(f"Fichier introuvable: {file_path}")
            
        if not os.path.isfile(file_path):
            raise Exception(f"Le chemin ne pointe pas vers un fichier: {file_path}")
            
        if not os.access(file_path, os.R_OK):
            raise Exception(f"Fichier non lisible: {file_path}")
            
        # Vérifier la taille du fichier
        try:
            file_size = os.path.getsize(file_path)
        except OSError as e:
            raise Exception(f"Impossible de lire la taille du fichier: {e}")
            
        if file_size == 0:
            raise Exception(f"Le fichier est vide (0 B): {file_path}")
            
        if file_size > 2000 * 1024 * 1024:  # 2GB limite Telegram
            raise Exception(f"Fichier trop volumineux ({file_size/1024/1024:.1f} MB > 2GB)")
            
        logger.info(f"📤 VALIDATION OK - Fichier: {file_path} ({file_size/1024/1024:.1f} MB)")

        # Déterminer le type de fichier
        file_extension = os.path.splitext(file_path)[1].lower()
        is_photo = file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.webp']
        is_video = file_extension in ['.mp4', '.avi', '.mov', '.mkv', '.webm']
        
        # ✅ PRÉPARATION SÉCURISÉE DU THUMBNAIL
        thumb_path = None
        if thumb_id:
            logger.info(f"🖼️ Préparation du thumbnail: {thumb_id[:30] if len(thumb_id) > 30 else thumb_id}...")
            try:
                thumb_path = await handle_thumbnail_pyrogram(thumb_id, context=context)
                if thumb_path and os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
                    logger.info(f"✅ Thumbnail préparé: {thumb_path}")
                else:
                    logger.warning("⚠️ Thumbnail préparé mais fichier invalide")
                    thumb_path = None
            except Exception as thumb_error:
                logger.warning(f"⚠️ Erreur thumbnail (continuant sans): {thumb_error}")
                thumb_path = None

        try:
            # ✅ OBTENIR LE MEILLEUR CLIENT AVEC VALIDATION
            try:
                client_info = await client_manager.get_best_client(file_size, "upload")
                client = client_info["client"]
                client_type = client_info["type"]
                
                if not client:
                    raise Exception("Aucun client disponible")
                    
                logger.info(f"📤 Client sélectionné: {client_type}")
            except Exception as client_error:
                raise Exception(f"Impossible d'obtenir un client: {client_error}")

            # ✅ ENVOI AVEC GESTION D'ERREURS ROBUSTE ET FALLBACK
            try:
                if client_type == "pyrogram":
                    message = await _send_with_pyrogram(
                        client, chat_id, file_path, caption, thumb_path, file_name, 
                        is_photo, is_video, force_document
                    )
                    
                    # Extraire le file_id selon le type de média
                    file_id = None
                    if message.photo:
                        file_id = message.photo.file_id
                    elif message.video:
                        file_id = message.video.file_id
                    elif message.document:
                        file_id = message.document.file_id
                    
                    return {
                        "success": True,
                        "message_id": message.id,
                        "file_id": file_id,
                        "client": "pyrogram"
                    }

                elif client_type == "telethon":
                    message = await _send_with_telethon(
                        client, chat_id, file_path, caption, thumb_path, file_name, 
                        is_photo, is_video, force_document
                    )
                    
                    # Pour Telethon, essayer de récupérer le file_id
                    file_id = None
                    try:
                        # Note: Récupération file_id simplifiée pour éviter les erreurs
                        file_id = f"telethon_msg_{message.id}"  # Fallback temporaire
                    except Exception as fwd_error:
                        logger.warning(f"⚠️ Impossible de récupérer le file_id: {fwd_error}")
                    
                    return {
                        "success": True,
                        "message_id": message.id,
                        "file_id": file_id,
                        "client": "telethon"
                    }
                    
                else:
                    raise Exception(f"Type de client non supporté: {client_type}")
                    
            except Exception as send_error:
                error_str = str(send_error)
                logger.warning(f"⚠️ Échec envoi avec {client_type}: {error_str}")
                
                # ✅ GESTION DES ERREURS SPÉCIFIQUES AVEC FALLBACK
                if "Peer id invalid" in error_str or "peer id invalid" in error_str.lower():
                    # Gérer l'erreur Peer ID et essayer l'autre client
                    await client_manager.handle_peer_error(client_type, send_error)
                    
                    # Essayer avec l'autre client
                    try:
                        fallback_client_type = "telethon" if client_type == "pyrogram" else "pyrogram"
                        logger.info(f"🔄 Fallback vers {fallback_client_type} après erreur Peer ID")
                        
                        fallback_client_info = await client_manager.get_best_client(file_size, "upload")
                        fallback_client = fallback_client_info["client"]
                        
                        if fallback_client and fallback_client_info["type"] == fallback_client_type:
                            if fallback_client_type == "pyrogram":
                                message = await _send_with_pyrogram(
                                    fallback_client, chat_id, file_path, caption, thumb_path, file_name, 
                                    is_photo, is_video, force_document
                                )
                                file_id = None
                                if message.photo:
                                    file_id = message.photo.file_id
                                elif message.video:
                                    file_id = message.video.file_id
                                elif message.document:
                                    file_id = message.document.file_id
                                
                                return {
                                    "success": True,
                                    "message_id": message.id,
                                    "file_id": file_id,
                                    "client": "pyrogram"
                                }
                            else:
                                message = await _send_with_telethon(
                                    fallback_client, chat_id, file_path, caption, thumb_path, file_name, 
                                    is_photo, is_video, force_document
                                )
                                file_id = f"telethon_msg_{message.id}"
                                
                                return {
                                    "success": True,
                                    "message_id": message.id,
                                    "file_id": file_id,
                                    "client": "telethon"
                                }
                        else:
                            raise Exception(f"Aucun client {fallback_client_type} disponible pour fallback")
                            
                    except Exception as fallback_error:
                        logger.error(f"❌ Échec du fallback: {fallback_error}")
                        raise Exception(f"Échec envoi {client_type} et fallback {fallback_client_type}: {send_error}")
                
                elif "FILE_REFERENCE_EXPIRED" in error_str or "file reference" in error_str.lower():
                    raise Exception(f"Référence de fichier expirée: {error_str}")
                    
                elif "File is too big" in error_str or "file is too big" in error_str.lower():
                    # Essayer avec l'autre client si possible
                    try:
                        fallback_client_type = "telethon" if client_type == "pyrogram" else "pyrogram"
                        logger.info(f"🔄 Fallback vers {fallback_client_type} pour fichier volumineux")
                        
                        fallback_client_info = await client_manager.get_best_client(file_size, "upload")
                        fallback_client = fallback_client_info["client"]
                        
                        if fallback_client and fallback_client_info["type"] == fallback_client_type:
                            if fallback_client_type == "telethon":
                                message = await _send_with_telethon(
                                    fallback_client, chat_id, file_path, caption, thumb_path, file_name, 
                                    is_photo, is_video, force_document
                                )
                                file_id = f"telethon_msg_{message.id}"
                                
                                return {
                                    "success": True,
                                    "message_id": message.id,
                                    "file_id": file_id,
                                    "client": "telethon"
                                }
                        
                        raise Exception("Aucun client alternatif disponible")
                        
                    except Exception as big_file_fallback_error:
                        logger.error(f"❌ Échec fallback fichier volumineux: {big_file_fallback_error}")
                        raise Exception(f"Fichier trop volumineux pour tous les clients: {error_str}")
                
                else:
                    # Autres erreurs - les relancer directement
                    raise send_error

        finally:
            # ✅ NETTOYAGE SÉCURISÉ DU THUMBNAIL TEMPORAIRE
            if thumb_path and os.path.exists(thumb_path):
                # Ne supprimer que si c'est un fichier temporaire (pas le fichier original)
                if 'temp' in thumb_path or thumb_path != thumb_id:
                    try:
                        os.remove(thumb_path)
                        logger.info("🧹 Thumbnail temporaire supprimé")
                    except Exception as e:
                        logger.warning(f"⚠️ Erreur suppression thumbnail: {e}")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ ERREUR send_file_smart: {error_msg}")
        
        # ✅ MESSAGES D'ERREUR DÉTAILLÉS
        if "File size equals to 0 B" in error_msg or "fichier est vide" in error_msg:
            error_msg = "Le fichier est vide ou corrompu. Veuillez renvoyer le fichier."
        elif "Fichier introuvable" in error_msg:
            error_msg = "Le fichier n'existe plus sur le serveur. Veuillez le renvoyer."
        elif "trop volumineux" in error_msg:
            error_msg = "Le fichier dépasse la limite de 2GB de Telegram."
        elif "non lisible" in error_msg:
            error_msg = "Impossible de lire le fichier. Vérifiez les permissions."
        
        return {
            "success": False,
            "error": error_msg,
            "file_id": None,
            "message_id": None
        }

async def _send_with_pyrogram(client, chat_id, file_path, caption, thumb_path, file_name, is_photo, is_video, force_document):
    """Envoi avec Pyrogram avec gestion d'erreurs et validation"""
    try:
        # ✅ VALIDATION SUPPLÉMENTAIRE AVANT ENVOI
        if not os.path.exists(file_path):
            raise Exception(f"Fichier inexistant pour Pyrogram: {file_path}")
            
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise Exception(f"Fichier vide pour Pyrogram: {file_path}")
            
        if not os.access(file_path, os.R_OK):
            raise Exception(f"Fichier non lisible pour Pyrogram: {file_path}")
            
        logger.info(f"📤 Pyrogram: Envoi {file_path} ({file_size/1024/1024:.1f} MB)")
        
        # ✅ GESTION SÉCURISÉE DU THUMBNAIL
        thumb_kwargs = {}
        if thumb_path and os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            thumb_kwargs["thumb"] = thumb_path
            logger.info(f"🖼️ Pyrogram: Thumbnail ajouté: {thumb_path}")
        
        # ✅ ENVOI SELON LE TYPE AVEC GESTION D'ERREURS
        if is_photo and not force_document:
            kwargs = {
                "chat_id": chat_id,
                "photo": file_path,
                "caption": caption,
                **thumb_kwargs
            }
            if file_name:
                kwargs["file_name"] = file_name
                
            message = await client.send_photo(**kwargs)
            logger.info("✅ Photo envoyée via Pyrogram")
            return message
            
        elif is_video and not force_document:
            kwargs = {
                "chat_id": chat_id,
                "video": file_path,
                "caption": caption,
                **thumb_kwargs
            }
            if file_name:
                kwargs["file_name"] = file_name
                
            message = await client.send_video(**kwargs)
            logger.info("✅ Vidéo envoyée via Pyrogram")
            return message
            
        else:
            kwargs = {
                "chat_id": chat_id,
                "document": file_path,
                "caption": caption,
                "force_document": True,
                **thumb_kwargs
            }
            if file_name:
                kwargs["file_name"] = file_name

            message = await client.send_document(**kwargs)
            logger.info("✅ Document envoyé via Pyrogram")
            return message
            
    except Exception as e:
        error_str = str(e)
        logger.error(f"❌ Erreur Pyrogram: {error_str}")
        
        # ✅ MESSAGES D'ERREUR SPÉCIFIQUES
        if "Fichier vide" in error_str:
            raise Exception("Le fichier à envoyer est vide (0 B). Vérifiez le fichier source.")
        elif "Fichier inexistant" in error_str:
            raise Exception("Le fichier à envoyer n'existe pas. Vérifiez le chemin.")
        elif "Fichier non lisible" in error_str:
            raise Exception("Impossible de lire le fichier. Vérifiez les permissions.")
        else:
            raise Exception(f"Erreur envoi Pyrogram: {error_str}")

async def _send_with_telethon(client, chat_id, file_path, caption, thumb_path, file_name, is_photo, is_video, force_document):
    """Envoi avec Telethon avec gestion d'erreurs et validation"""
    try:
        # ✅ VALIDATION SUPPLÉMENTAIRE AVANT ENVOI
        if not os.path.exists(file_path):
            raise Exception(f"Fichier inexistant pour Telethon: {file_path}")
            
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise Exception(f"Fichier vide pour Telethon: {file_path}")
            
        if not os.access(file_path, os.R_OK):
            raise Exception(f"Fichier non lisible pour Telethon: {file_path}")
            
        logger.info(f"📤 Telethon: Envoi {file_path} ({file_size/1024/1024:.1f} MB)")
        
        # ✅ GESTION SÉCURISÉE DU THUMBNAIL
        thumb_to_use = None
        if thumb_path and os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            thumb_to_use = thumb_path
            logger.info(f"🖼️ Telethon: Thumbnail ajouté: {thumb_path}")
        
        # ✅ ENVOI UNIFIÉ AVEC TELETHON
        try:
            if is_photo and not force_document:
                message = await client.send_file(
                    chat_id,
                    file_path,
                    caption=caption,
                    thumb=thumb_to_use,
                    filename=file_name if file_name else None,
                    force_document=False
                )
                logger.info("✅ Photo envoyée via Telethon")
                return message
                
            elif is_video and not force_document:
                message = await client.send_file(
                    chat_id,
                    file_path,
                    caption=caption,
                    thumb=thumb_to_use,
                    filename=file_name if file_name else None,
                    force_document=False
                )
                logger.info("✅ Vidéo envoyée via Telethon")
                return message
                
            else:
                message = await client.send_file(
                    chat_id,
                    file_path,
                    caption=caption,
                    thumb=thumb_to_use,
                    force_document=True,
                    filename=file_name if file_name else None
                )
                logger.info("✅ Document envoyé via Telethon")
                return message
                
        except Exception as send_error:
            send_error_str = str(send_error)
            
            # ✅ GESTION SPÉCIFIQUE DES ERREURS TELETHON
            if "File size equals to 0 B" in send_error_str:
                # Réessayer avec une approche différente
                logger.warning("⚠️ Telethon: Erreur taille 0B, tentative avec force_document=True")
                message = await client.send_file(
                    chat_id,
                    file_path,
                    caption=caption,
                    thumb=thumb_to_use,
                    force_document=True,
                    filename=file_name or os.path.basename(file_path)
                )
                logger.info("✅ Document envoyé via Telethon (force_document)")
                return message
            else:
                raise send_error
            
    except Exception as e:
        error_str = str(e)
        logger.error(f"❌ Erreur Telethon: {error_str}")
        
        # ✅ MESSAGES D'ERREUR SPÉCIFIQUES
        if "Fichier vide" in error_str:
            raise Exception("Le fichier à envoyer est vide (0 B). Vérifiez le fichier source.")
        elif "Fichier inexistant" in error_str:
            raise Exception("Le fichier à envoyer n'existe pas. Vérifiez le chemin.")
        elif "Fichier non lisible" in error_str:
            raise Exception("Impossible de lire le fichier. Vérifiez les permissions.")
        elif "File size equals to 0 B" in error_str:
            raise Exception("Erreur de taille de fichier détectée par Telethon. Le fichier pourrait être corrompu.")
        else:
            raise Exception(f"Erreur envoi Telethon: {error_str}")

async def edit_message_media(
    chat_id: int,
    message_id: int,
    file_path: str,
    thumb_id: Optional[str] = None
) -> bool:
    """
    Modifie un message média existant.
    
    Args:
        chat_id: ID du chat
        message_id: ID du message à modifier
        file_path: Nouveau fichier
        thumb_id: ID de la nouvelle miniature
    
    Returns:
        bool: True si succès, False sinon
    """
    try:
        # ✅ VALIDATION DU FICHIER
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            logger.error(f"Fichier invalide pour édition: {file_path}")
            return False
            
        # Utiliser Pyrogram pour la modification (meilleur support)
        client_info = await client_manager.get_best_client(0, "edit")
        client = client_info["client"]
        
        # Préparer la miniature si nécessaire
        thumb_path = None
        if thumb_id:
            thumb_path = await handle_thumbnail_pyrogram(thumb_id)
        
        try:
            await client.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=file_path,
                thumb=thumb_path
            )
            logger.info(f"✅ Message {message_id} modifié avec succès")
            return True
            
        finally:
            # Nettoyer la miniature temporaire
            if thumb_path and os.path.exists(thumb_path) and 'temp' in thumb_path:
                try:
                    os.remove(thumb_path)
                except:
                    pass
                    
    except Exception as e:
        logger.error(f"❌ Erreur lors de la modification du message: {e}")
        return False 
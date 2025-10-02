"""
Handler pour l'envoi de fichiers avec gestion intelligente des clients
"""
import os
import logging
from typing import Optional, Dict, Any
from utils.clients import client_manager
# from handlers.thumbnail import handle_thumbnail_pyrogram  # Removed if thumbnail.py is deprecated
from config import settings

logger = logging.getLogger(__name__)

async def send_file_smart(
    chat_id: str,
    file_path: str,
    caption: Optional[str] = None,
    thumb_id: Optional[str] = None,
    file_name: Optional[str] = None,
    force_document: bool = False,
    context = None,
    progress_chat_id: Optional[int] = None,
    progress_message_id: Optional[int] = None,
    progress_prefix: str = ""
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
            raise Exception(f"File not found: {file_path}")
            
        if not os.path.isfile(file_path):
            raise Exception(f"Path does not point to a file: {file_path}")
            
        if not os.access(file_path, os.R_OK):
            raise Exception(f"File not readable: {file_path}")
            
        # Vérifier la taille du fichier
        try:
            # Message de progression (optionnel)
            progress_chat = None
            progress_msg_id = None
            if progress_chat_id and progress_message_id:
                progress_chat = progress_chat_id
                progress_msg_id = progress_message_id
                try:
                    await context.bot.edit_message_text(chat_id=progress_chat, message_id=progress_msg_id, text=f"⏳ {progress_prefix}Preparing…")
                except Exception:
                    pass
            elif progress_chat_id:
                try:
                    msg = await context.bot.send_message(progress_chat_id, f"⏳ {progress_prefix}Preparing…")
                    progress_chat = msg.chat_id
                    progress_msg_id = msg.message_id
                except Exception:
                    progress_chat = None
                    progress_msg_id = None
            file_size = os.path.getsize(file_path)
        except OSError as e:
            raise Exception(f"Unable to read file size: {e}")
            
        if file_size == 0:
            raise Exception(f"File is empty (0 B): {file_path}")
            
        if file_size > 2000 * 1024 * 1024:  # 2GB limite Telegram
            raise Exception(f"File too large ({file_size/1024/1024:.1f} MB > 2GB)")
            
        logger.info(f"📤 VALIDATION OK - File: {file_path} ({file_size/1024/1024:.1f} MB)")

        # Déterminer le type de fichier
        file_extension = os.path.splitext(file_path)[1].lower()
        is_photo = file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.webp']
        is_video = file_extension in ['.mp4', '.avi', '.mov', '.mkv', '.webm']
        # Si l'extension du chemin n'est pas parlante, utiliser le nom fichier demandé
        if not is_photo and not is_video and file_name:
            name_ext = os.path.splitext(file_name)[1].lower()
            if name_ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                is_photo = True
            elif name_ext in ['.mp4', '.avi', '.mov', '.mkv', '.webm']:
                is_video = True
        
        # ✅ SAFE THUMBNAIL PREPARATION
        thumb_path = None
        if thumb_id:
            logger.info(f"🖼️ Preparing thumbnail: {thumb_id[:30] if len(thumb_id) > 30 else thumb_id}...")
            try:
                # If you keep thumbnail.py, re-enable the import and the call.
                # thumb_path = await handle_thumbnail_pyrogram(thumb_id, context=context)
                thumb_path = None
                if thumb_path and os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
                    logger.info(f"✅ Thumbnail prepared: {thumb_path}")
                else:
                    logger.warning("⚠️ Thumbnail prepared but invalid file")
                    thumb_path = None
            except Exception as thumb_error:
                logger.warning(f"⚠️ Thumbnail error (continuing without): {thumb_error}")
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
                # Pyrogram uniquement
                message = await _send_with_pyrogram(
                    client, chat_id, file_path, caption, thumb_path, file_name, 
                    is_photo, is_video, force_document
                )
                
                file_id = None
                if message.photo:
                    file_id = message.photo.file_id
                elif message.video:
                    file_id = message.video.file_id
                elif message.document:
                    file_id = message.document.file_id
                
                result = {
                    "success": True,
                    "message_id": message.id,
                    "file_id": file_id,
                    "client": "pyrogram"
                }
                if progress_chat and progress_msg_id:
                    try:
                        await context.bot.edit_message_text(chat_id=progress_chat, message_id=progress_msg_id, text=f"✅ {progress_prefix}Completed")
                    except Exception:
                        pass
                return result
                    
            except Exception as send_error:
                error_str = str(send_error)
                logger.warning(f"⚠️ Échec envoi avec {client_type}: {error_str}")
                
                # ✅ GESTION DES ERREURS SPÉCIFIQUES AVEC FALLBACK
                if progress_chat and progress_msg_id:
                    try:
                        await context.bot.edit_message_text(progress_chat, progress_msg_id, f"🔁 {progress_prefix}Nouvelle tentative…")
                    except Exception:
                        pass
                if "Peer id invalid" in error_str or "peer id invalid" in error_str.lower():
                    await client_manager.handle_peer_error(client_type, send_error)
                    # Réessayer une fois avec un nouveau client Pyrogram
                    fallback_client_info = await client_manager.get_best_client(file_size, "upload")
                    fallback_client = fallback_client_info["client"]
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
                    if progress_chat and progress_msg_id:
                        try:
                            await context.bot.edit_message_text(progress_chat, progress_msg_id, f"✅ {progress_prefix}Completed")
                        except Exception:
                            pass
                    return {"success": True, "message_id": message.id, "file_id": file_id, "client": "pyrogram"}
                
                elif "FILE_REFERENCE_EXPIRED" in error_str or "file reference" in error_str.lower():
                    raise Exception(f"File reference expired: {error_str}")
                    
                elif "File is too big" in error_str or "file is too big" in error_str.lower():
                    # Recreate/restart Pyrogram and retry
                    logger.info("🔄 Pyrogram retry for large file")
                    fallback_client_info = await client_manager.get_best_client(file_size, "upload")
                    fallback_client = fallback_client_info["client"]
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
                    if progress_chat and progress_msg_id:
                        try:
                            await context.bot.edit_message_text(progress_chat, progress_msg_id, f"✅ {progress_prefix}Completed")
                        except Exception:
                            pass
                    return {"success": True, "message_id": message.id, "file_id": file_id, "client": "pyrogram"}
                
                else:
                    # Other errors - raise them directly
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
            error_msg = "The file is empty or corrupted. Please resend the file."
        elif "Fichier introuvable" in error_msg or "File not found" in error_msg:
            error_msg = "The file no longer exists on the server. Please resend it."
        elif "trop volumineux" in error_msg or "too large" in error_msg:
            error_msg = "The file exceeds Telegram's 2GB limit."
        elif "non lisible" in error_msg or "not readable" in error_msg:
            error_msg = "Unable to read the file. Check permissions."
        
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
            raise Exception(f"Missing file for Pyrogram: {file_path}")
            
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise Exception(f"Empty file for Pyrogram: {file_path}")
            
        if not os.access(file_path, os.R_OK):
            raise Exception(f"Unreadable file for Pyrogram: {file_path}")
            
        logger.info(f"📤 Pyrogram: Envoi {file_path} ({file_size/1024/1024:.1f} MB)")
        
        # ✅ GESTION SÉCURISÉE DU THUMBNAIL
        thumb_kwargs = {}
        if thumb_path and os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            # Important: Pyrogram n'accepte pas 'thumb' sur send_photo; on n'ajoute la miniature
            # que pour les envois en document/vidéo.
            thumb_kwargs["thumb"] = thumb_path
            logger.info(f"🖼️ Pyrogram: Thumbnail prepared: {thumb_path}")
        
        # ✅ ENVOI SELON LE TYPE AVEC GESTION D'ERREURS
        if is_photo and not force_document:
            kwargs = {
                "chat_id": chat_id,
                "photo": file_path,
                "caption": caption,
                # Pas de thumbnail custom pour les photos
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
                "supports_streaming": True,
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
            raise Exception("The file to send is empty (0 B). Check the source file.")
        elif "Fichier inexistant" in error_str:
            raise Exception("The file to send does not exist. Check the path.")
        elif "Fichier non lisible" in error_str:
            raise Exception("Unable to read the file. Check permissions.")
        else:
            raise Exception(f"Erreur envoi Pyrogram: {error_str}")

# Telethon supprimé: envoi géré uniquement via Pyrogram

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
            logger.error(f"Invalid file for editing: {file_path}")
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
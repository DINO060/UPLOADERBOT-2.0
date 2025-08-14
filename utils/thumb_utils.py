"""
Utilitaires pour la gestion des miniatures (thumbnails)
"""
import os
from PIL import Image
from typing import Optional
import logging
from config import settings

logger = logging.getLogger(__name__)

def optimize_thumbnail(image_path: str, output_path: Optional[str] = None) -> Optional[str]:
    """
    Optimise une image pour l'utiliser comme miniature Telegram.
    - Redimensionne à 320x320 max
    - Convertit en JPEG
    - Compresse pour rester sous 200KB
    """
    try:
        if not output_path:
            output_path = os.path.join(settings.temp_folder, "thumb_temp.jpg")
            
        # Créer le dossier temp si nécessaire
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with Image.open(image_path) as img:
            # Convertir en RGB si nécessaire (pour les PNG avec transparence)
            if img.mode in ('RGBA', 'LA'):
                background = Image.new('RGB', img.size, 'white')
                background.paste(img, mask=img.split()[-1])
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Redimensionner
            img.thumbnail(settings.thumb_size)
            
            # Sauvegarder avec compression progressive
            img.save(output_path, 
                    'JPEG', 
                    quality=settings.thumb_quality, 
                    optimize=True, 
                    progressive=True)
            
            # Vérifier la taille
            if os.path.getsize(output_path) > settings.max_thumb_size:
                current_quality = settings.thumb_quality
                while os.path.getsize(output_path) > settings.max_thumb_size and current_quality > 5:
                    current_quality -= 5
                    img.save(output_path, 
                            'JPEG', 
                            quality=current_quality, 
                            optimize=True, 
                            progressive=True)
            
            logger.info(f"Thumbnail optimisé créé : {output_path} ({os.path.getsize(output_path)/1024:.1f}KB)")
            return output_path
            
    except Exception as e:
        logger.error(f"Erreur lors de l'optimisation du thumbnail: {e}")
        if output_path and os.path.exists(output_path):
            try:
                os.remove(output_path)
            except:
                pass
        return None

async def prepare_thumbnail(client, thumb_id: str) -> Optional[str]:
    """
    Prépare une miniature à partir d'un file_id Telegram.
    Télécharge et optimise pour l'utilisation avec userbot.
    """
    try:
        # Créer le dossier temp si nécessaire
        os.makedirs(settings.temp_folder, exist_ok=True)
        
        # Télécharger le thumbnail
        temp_path = os.path.join(settings.temp_folder, f"thumb_download_{os.urandom(4).hex()}.jpg")
        downloaded_path = await client.download_media(thumb_id, temp_path)
        
        if not downloaded_path:
            logger.error("Échec du téléchargement du thumbnail")
            return None
            
        # Optimiser le thumbnail
        optimized_path = optimize_thumbnail(downloaded_path)
        
        # Nettoyer le fichier temporaire de téléchargement
        try:
            os.remove(downloaded_path)
        except:
            pass
            
        return optimized_path
        
    except Exception as e:
        logger.error(f"Erreur lors de la préparation du thumbnail: {e}")
        return None

# Obsolète: fonctions liées à Telethon supprimées

def cleanup_thumbnail_file(file_path: str) -> None:
    """
    ✅ Supprime un fichier thumbnail temporaire.
    
    Args:
        file_path: Chemin du fichier à supprimer
    """
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"🧹 Thumbnail temporaire supprimé: {file_path}")
    except Exception as e:
        logger.warning(f"⚠️ Erreur suppression thumbnail {file_path}: {e}") 
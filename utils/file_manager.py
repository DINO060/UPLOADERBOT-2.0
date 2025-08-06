import os
import shutil
import logging
from pathlib import Path
from typing import Optional, Union
from datetime import datetime

from .validators import InputValidator

logger = logging.getLogger('TelegramBot')

class ValidationError(Exception):
    """Exception pour les erreurs de validation"""
    pass

class FileManager:
    """Gestionnaire de fichiers pour le bot"""
    
    def __init__(self, base_path: str = "downloads"):
        """
        Initialise le gestionnaire de fichiers
        
        Args:
            base_path: Chemin de base pour les téléchargements
        """
        self.base_path = Path(base_path)
        self._ensure_directories()
    
    def _ensure_directories(self) -> None:
        """Crée les répertoires nécessaires s'ils n'existent pas"""
        try:
            self.base_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Erreur lors de la création des répertoires: {e}")
            raise
    
    def get_file_path(self, file_id: str, file_type: str) -> Path:
        """
        Génère un chemin de fichier unique
        
        Args:
            file_id: ID du fichier
            file_type: Type de fichier (photo, video, document)
            
        Returns:
            Chemin du fichier
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.base_path / f"{file_type}_{file_id}_{timestamp}"
    
    async def save_file(
        self,
        file: Union[bytes, str],
        file_id: str,
        file_type: str,
        file_size: Optional[int] = None
    ) -> Path:
        """
        Sauvegarde un fichier
        
        Args:
            file: Contenu du fichier ou chemin source
            file_id: ID du fichier
            file_type: Type de fichier
            file_size: Taille du fichier en octets
            
        Returns:
            Chemin du fichier sauvegardé
            
        Raises:
            ValidationError: Si la taille du fichier est invalide
        """
        try:
            # Valide la taille du fichier si fournie
            if file_size is not None:
                max_size = 100 * 1024 * 1024  # 100MB par défaut
                if not InputValidator.validate_file_size(str(file_size), max_size):
                    raise ValidationError(f"Taille de fichier invalide: {file_size} octets")
            
            # Génère le chemin de destination
            dest_path = self.get_file_path(file_id, file_type)
            
            # Si file est un chemin, copie le fichier
            if isinstance(file, (str, Path)):
                shutil.copy2(file, dest_path)
            # Sinon, écrit les bytes
            else:
                with open(dest_path, 'wb') as f:
                    f.write(file)
            
            logger.info(f"Fichier sauvegardé: {dest_path}")
            return dest_path
            
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde du fichier: {e}")
            raise
    
    def delete_file(self, file_path: Union[str, Path]) -> bool:
        """
        Supprime un fichier
        
        Args:
            file_path: Chemin du fichier à supprimer
            
        Returns:
            True si le fichier a été supprimé, False sinon
        """
        try:
            file_path = Path(file_path)
            if file_path.exists():
                file_path.unlink()
                logger.info(f"Fichier supprimé: {file_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"Erreur lors de la suppression du fichier: {e}")
            return False
    
    def cleanup_old_files(self, max_age_days: int = 7) -> int:
        """
        Nettoie les fichiers plus vieux que max_age_days
        
        Args:
            max_age_days: Âge maximum en jours
            
        Returns:
            Nombre de fichiers supprimés
        """
        try:
            now = datetime.now()
            deleted_count = 0
            
            for file_path in self.base_path.glob("*"):
                if not file_path.is_file():
                    continue
                    
                file_age = datetime.fromtimestamp(file_path.stat().st_mtime)
                age_days = (now - file_age).days
                
                if age_days > max_age_days:
                    if self.delete_file(file_path):
                        deleted_count += 1
            
            logger.info(f"{deleted_count} fichiers supprimés")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage des fichiers: {e}")
            return 0
    
    def get_file_info(self, file_path: Union[str, Path]) -> dict:
        """
        Récupère les informations d'un fichier
        
        Args:
            file_path: Chemin du fichier
            
        Returns:
            Informations du fichier
        """
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                return {}
                
            stat = file_path.stat()
            return {
                "path": str(file_path),
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime),
                "modified": datetime.fromtimestamp(stat.st_mtime),
                "type": file_path.suffix[1:] if file_path.suffix else "unknown"
            }
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des informations du fichier: {e}")
            return {} 
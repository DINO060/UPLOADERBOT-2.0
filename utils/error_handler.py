import logging
from typing import Optional, Type, Callable, Awaitable, Any
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger('TelegramBot')

class BotError(Exception):
    """Classe de base pour les erreurs du bot"""
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        self.message = message
        self.original_error = original_error
        super().__init__(self.message)

class DatabaseError(BotError):
    """Erreur liée à la base de données"""
    pass

class ValidationError(BotError):
    """Erreur de validation"""
    pass

class ResourceError(BotError):
    """Erreur liée aux ressources"""
    pass

async def handle_error(error: Exception, context: Optional[Any] = None) -> None:
    """
    Gère les erreurs de manière centralisée
    
    Args:
        error: L'erreur à gérer
        context: Contexte supplémentaire (optionnel)
    """
    try:
        # Log de l'erreur
        error_message = str(error)
        if context:
            error_message += f"\nContexte: {context}"
        
        logger.error(error_message)
        
        # Si c'est une BotError, on a déjà un message utilisateur
        if isinstance(error, BotError):
            return error.message
        
        # Pour les autres erreurs, on retourne un message générique
        return "Une erreur est survenue. Veuillez réessayer plus tard."
        
    except Exception as e:
        logger.error(f"Erreur lors de la gestion d'erreur: {e}")
        return "Une erreur inattendue est survenue."

def error_handler(
    error_types: Optional[list[Type[Exception]]] = None
) -> Callable[[Callable], Callable]:
    """
    Décorateur pour la gestion des erreurs
    
    Args:
        error_types: Types d'erreurs à gérer
    """
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs) -> Awaitable:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if error_types and not any(isinstance(e, error_type) for error_type in error_types):
                    raise
                
                # Récupération du contexte
                update = None
                context = None
                
                for arg in args:
                    if isinstance(arg, Update):
                        update = arg
                    elif isinstance(arg, ContextTypes.DEFAULT_TYPE):
                        context = arg
                
                if update and context:
                    await handle_error(e, context)
                else:
                    logger.error(f"Erreur sans contexte: {e}", exc_info=True)
                
                return None
                
        return wrapper
    return decorator 
import asyncio
import logging
from typing import Type, Callable, Awaitable, Optional
from functools import wraps

logger = logging.getLogger('TelegramBot')

class RetryError(Exception):
    """Erreur après épuisement des tentatives"""
    pass

def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Optional[list[Type[Exception]]] = None
) -> Callable[[Callable], Callable]:
    """
    Décorateur pour les tentatives de réessai
    
    Args:
        max_attempts: Nombre maximum de tentatives
        delay: Délai initial entre les tentatives en secondes
        backoff: Facteur de multiplication du délai
        exceptions: Types d'exceptions à gérer
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Awaitable:
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if exceptions and not any(isinstance(e, exc) for exc in exceptions):
                        raise
                        
                    last_exception = e
                    logger.warning(
                        f"Tentative {attempt + 1}/{max_attempts} échouée pour {func.__name__}: {e}"
                    )
                    
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        raise RetryError(
                            f"Échec après {max_attempts} tentatives pour {func.__name__}"
                        ) from last_exception
                        
            raise RetryError(
                f"Échec après {max_attempts} tentatives pour {func.__name__}"
            ) from last_exception
            
        return wrapper
    return decorator

class RetryManager:
    """Gestionnaire de retry pour les opérations asynchrones"""
    
    def __init__(
        self,
        max_attempts: int = 3,
        delay: float = 1.0,
        backoff: float = 2.0,
        exceptions: Optional[list[Type[Exception]]] = None
    ):
        """
        Initialise le gestionnaire de retry
        
        Args:
            max_attempts: Nombre maximum de tentatives
            delay: Délai initial entre les tentatives en secondes
            backoff: Facteur de multiplication du délai
            exceptions: Types d'exceptions à gérer
        """
        self.max_attempts = max_attempts
        self.delay = delay
        self.backoff = backoff
        self.exceptions = exceptions or [Exception]
    
    async def execute(
        self,
        func: Callable,
        *args,
        **kwargs
    ) -> Awaitable:
        """
        Exécute une fonction avec retry
        
        Args:
            func: Fonction à exécuter
            *args: Arguments positionnels
            **kwargs: Arguments nommés
            
        Returns:
            Résultat de la fonction
            
        Raises:
            RetryError: Si toutes les tentatives échouent
        """
        current_delay = self.delay
        last_exception = None
        
        for attempt in range(self.max_attempts):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if not any(isinstance(e, exc) for exc in self.exceptions):
                    raise
                    
                last_exception = e
                logger.warning(
                    f"Tentative {attempt + 1}/{self.max_attempts} échouée pour {func.__name__}: {e}"
                )
                
                if attempt < self.max_attempts - 1:
                    await asyncio.sleep(current_delay)
                    current_delay *= self.backoff
                else:
                    raise RetryError(
                        f"Échec après {self.max_attempts} tentatives pour {func.__name__}"
                    ) from last_exception
                    
        raise RetryError(
            f"Échec après {self.max_attempts} tentatives pour {func.__name__}"
        ) from last_exception 
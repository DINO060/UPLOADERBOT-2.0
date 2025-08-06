import logging
from datetime import datetime
from typing import Optional, Callable, Awaitable, Any, Dict, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pytz import timezone
import asyncio

from .error_handler import BotError, handle_error

logger = logging.getLogger('TelegramBot')

class SchedulerError(BotError):
    """Erreur liée à la planification"""
    pass

class SchedulerManager:
    """Gestionnaire de tâches planifiées"""
    
    def __init__(self, timezone_str: str = "UTC"):
        """Initialise le gestionnaire de tâches"""
        try:
            # Configuration minimale sans options avancées
            self.timezone = timezone(timezone_str)
            self.scheduler = AsyncIOScheduler(timezone=self.timezone)
            
            self.logger = logging.getLogger('SchedulerManager')
            self.running = False
            
            logger.info(f"Scheduler initialisé avec le fuseau horaire: {timezone_str}")
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation du scheduler: {e}")
            raise SchedulerError(f"Initialisation du scheduler impossible: {e}")
            
    def start(self) -> None:
        """Démarre le scheduler"""
        try:
            if not self.running:
                self.scheduler.start()
                self.running = True
                logger.info("Scheduler démarré")
        except Exception as e:
            logger.error(f"Erreur lors du démarrage du scheduler: {e}")
            raise SchedulerError("Impossible de démarrer le scheduler")
    
    def stop(self) -> None:
        """Arrête le scheduler"""
        try:
            self.scheduler.shutdown()
            logger.info("Scheduler arrêté")
        except Exception as e:
            logger.error(f"Erreur lors de l'arrêt du scheduler: {e}")
            raise SchedulerError("Impossible d'arrêter le scheduler")
    
    async def schedule_task(
        self,
        task_id: str,
        run_date: datetime,
        func: Callable[..., Awaitable[Any]],
        *args,
        **kwargs
    ) -> bool:
        """
        Planifie une tâche unique
        
        Args:
            task_id: Identifiant unique de la tâche
            run_date: Date d'exécution
            func: Fonction à exécuter
            *args: Arguments positionnels
            **kwargs: Arguments nommés
            
        Returns:
            bool: True si la tâche a été planifiée
        """
        try:
            # Vérifie si la tâche existe déjà
            if self.scheduler.get_job(task_id):
                logger.warning(f"Tâche {task_id} déjà existante, remplacement...")
                self.scheduler.remove_job(task_id)
            
            # Planifie la tâche
            self.scheduler.add_job(
                func,
                trigger=DateTrigger(run_date=run_date),
                id=task_id,
                args=args,
                kwargs=kwargs,
                replace_existing=True
            )
            
            logger.info(f"Tâche {task_id} planifiée pour {run_date}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors de la planification de la tâche {task_id}: {e}")
            raise SchedulerError(f"Impossible de planifier la tâche {task_id}")
    
    async def schedule_recurring_task(
        self,
        task_id: str,
        interval_seconds: int,
        func: Callable[..., Awaitable[Any]],
        *args,
        **kwargs
    ) -> bool:
        """
        Planifie une tâche récurrente
        
        Args:
            task_id: Identifiant unique de la tâche
            interval_seconds: Intervalle en secondes
            func: Fonction à exécuter
            *args: Arguments positionnels
            **kwargs: Arguments nommés
            
        Returns:
            bool: True si la tâche a été planifiée
        """
        try:
            # Vérifie si la tâche existe déjà
            if self.scheduler.get_job(task_id):
                logger.warning(f"Tâche {task_id} déjà existante, remplacement...")
                self.scheduler.remove_job(task_id)
            
            # Planifie la tâche
            self.scheduler.add_job(
                func,
                trigger=IntervalTrigger(seconds=interval_seconds),
                id=task_id,
                args=args,
                kwargs=kwargs,
                replace_existing=True
            )
            
            logger.info(f"Tâche récurrente {task_id} planifiée toutes les {interval_seconds} secondes")
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors de la planification de la tâche récurrente {task_id}: {e}")
            raise SchedulerError(f"Impossible de planifier la tâche récurrente {task_id}")
    
    async def reschedule_task(
        self,
        task_id: str,
        new_run_date: datetime
    ) -> bool:
        """
        Replanifie une tâche existante
        
        Args:
            task_id: Identifiant de la tâche
            new_run_date: Nouvelle date d'exécution
            
        Returns:
            bool: True si la tâche a été replanifiée
        """
        try:
            job = self.scheduler.get_job(task_id)
            if not job:
                raise JobLookupError(f"Tâche {task_id} non trouvée")
            
            # Replanifie la tâche
            job.reschedule(trigger=DateTrigger(run_date=new_run_date))
            
            logger.info(f"Tâche {task_id} replanifiée pour {new_run_date}")
            return True
            
        except JobLookupError as e:
            logger.warning(f"Tâche {task_id} non trouvée pour replanification")
            raise SchedulerError(f"Tâche {task_id} non trouvée")
        except Exception as e:
            logger.error(f"Erreur lors de la replanification de la tâche {task_id}: {e}")
            raise SchedulerError(f"Impossible de replanifier la tâche {task_id}")
    
    async def cancel_task(self, task_id: str) -> bool:
        """
        Annule une tâche
        
        Args:
            task_id: Identifiant de la tâche
            
        Returns:
            bool: True si la tâche a été annulée
        """
        try:
            self.scheduler.remove_job(task_id)
            logger.info(f"Tâche {task_id} annulée")
            return True
        except JobLookupError:
            logger.warning(f"Tâche {task_id} non trouvée pour annulation")
            return False
        except Exception as e:
            logger.error(f"Erreur lors de l'annulation de la tâche {task_id}: {e}")
            raise SchedulerError(f"Impossible d'annuler la tâche {task_id}")
    
    async def execute_task_now(
        self,
        task_id: str,
        func: Optional[Callable[..., Awaitable[Any]]] = None,
        *args,
        **kwargs
    ) -> bool:
        """
        Exécute une tâche immédiatement
        
        Args:
            task_id: Identifiant de la tâche
            func: Fonction à exécuter (optionnel si la tâche existe)
            *args: Arguments positionnels
            **kwargs: Arguments nommés
            
        Returns:
            bool: True si la tâche a été exécutée
        """
        try:
            if func:
                # Exécute la fonction directement
                await func(*args, **kwargs)
            else:
                # Récupère et exécute la tâche existante
                job = self.scheduler.get_job(task_id)
                if not job:
                    raise JobLookupError(f"Tâche {task_id} non trouvée")
                
                await job.func(*job.args, **job.kwargs)
            
            logger.info(f"Tâche {task_id} exécutée immédiatement")
            return True
            
        except JobLookupError:
            logger.warning(f"Tâche {task_id} non trouvée pour exécution immédiate")
            raise SchedulerError(f"Tâche {task_id} non trouvée")
        except Exception as e:
            logger.error(f"Erreur lors de l'exécution immédiate de la tâche {task_id}: {e}")
            raise SchedulerError(f"Impossible d'exécuter la tâche {task_id}")
    
    def list_tasks(self) -> List[Dict]:
        """
        Liste toutes les tâches planifiées
        
        Returns:
            Liste des informations sur les tâches
        """
        tasks = []
        for job in self.scheduler.get_jobs():
            tasks.append({
                'id': job.id,
                'next_run_time': job.next_run_time,
                'trigger': str(job.trigger),
                'func': job.func.__name__ if callable(job.func) else str(job.func)
            })
        return tasks

# Ne pas créer d'instance globale ici pour éviter les conflits
# L'instance principale est créée dans bot.py 
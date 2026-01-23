"""
WORKER SYSTEM
=============
Système de workers pour le traitement parallèle des tâches.
Permet de gérer plusieurs utilisateurs simultanément sans blocage.
"""

import asyncio
import logging
import time
from typing import Callable, Any, Optional, Dict, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import traceback

logger = logging.getLogger("workers")


class TaskStatus(Enum):
    """Statut d'une tâche."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TaskPriority(Enum):
    """Priorité des tâches."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


@dataclass
class Task:
    """Représente une tâche à exécuter."""
    id: str
    func: Callable
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    priority: TaskPriority = TaskPriority.NORMAL
    user_id: Optional[int] = None
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retries: int = 0
    max_retries: int = 3
    timeout: int = 300  # 5 minutes par défaut

    def __lt__(self, other):
        """Pour le tri par priorité dans la queue."""
        return self.priority.value > other.priority.value


class WorkerPool:
    """
    Pool de workers pour le traitement parallèle.

    Usage:
        pool = WorkerPool(num_workers=4)
        await pool.start()

        # Ajouter une tâche
        task_id = await pool.submit(my_async_func, arg1, arg2, user_id=123)

        # Attendre le résultat
        result = await pool.wait_for(task_id)

        # Arrêter
        await pool.stop()
    """

    def __init__(
        self,
        num_workers: int = 4,
        queue_size: int = 100,
        task_timeout: int = 300,
        max_retries: int = 3,
        retry_delay: int = 5
    ):
        self.num_workers = num_workers
        self.queue_size = queue_size
        self.task_timeout = task_timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Queue prioritaire
        self._queue: asyncio.PriorityQueue = None
        self._workers: List[asyncio.Task] = []
        self._tasks: Dict[str, Task] = {}
        self._running = False
        self._task_counter = 0
        self._lock = asyncio.Lock()

        # Statistiques
        self.stats = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "active_workers": 0,
            "queue_size": 0,
        }

    async def start(self):
        """Démarre le pool de workers."""
        if self._running:
            logger.warning("Worker pool already running")
            return

        self._queue = asyncio.PriorityQueue(maxsize=self.queue_size)
        self._running = True

        # Créer les workers
        for i in range(self.num_workers):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)

        logger.info(f"Worker pool started with {self.num_workers} workers")

    async def stop(self, wait: bool = True):
        """Arrête le pool de workers."""
        if not self._running:
            return

        self._running = False

        # Envoyer des signaux d'arrêt aux workers
        for _ in range(self.num_workers):
            try:
                await self._queue.put((TaskPriority.URGENT.value, None))
            except Exception:
                pass

        if wait:
            # Attendre que les workers se terminent
            await asyncio.gather(*self._workers, return_exceptions=True)

        self._workers.clear()
        logger.info("Worker pool stopped")

    async def submit(
        self,
        func: Callable,
        *args,
        user_id: int = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: int = None,
        **kwargs
    ) -> str:
        """
        Soumet une tâche au pool.

        Args:
            func: Fonction async à exécuter
            *args: Arguments positionnels
            user_id: ID de l'utilisateur (pour le tracking)
            priority: Priorité de la tâche
            timeout: Timeout spécifique (optionnel)
            **kwargs: Arguments nommés

        Returns:
            str: ID de la tâche
        """
        if not self._running:
            raise RuntimeError("Worker pool is not running")

        async with self._lock:
            self._task_counter += 1
            task_id = f"task_{self._task_counter}_{int(time.time())}"

        task = Task(
            id=task_id,
            func=func,
            args=args,
            kwargs=kwargs,
            priority=priority,
            user_id=user_id,
            max_retries=self.max_retries,
            timeout=timeout or self.task_timeout
        )

        self._tasks[task_id] = task
        self.stats["total_tasks"] += 1
        self.stats["queue_size"] = self._queue.qsize()

        # Ajouter à la queue (priorité négative car PriorityQueue est min-first)
        await self._queue.put((-priority.value, task))

        logger.debug(f"Task {task_id} submitted (priority: {priority.name}, user: {user_id})")
        return task_id

    async def wait_for(self, task_id: str, timeout: float = None) -> Any:
        """
        Attend le résultat d'une tâche.

        Args:
            task_id: ID de la tâche
            timeout: Timeout d'attente (secondes)

        Returns:
            Résultat de la tâche

        Raises:
            TimeoutError: Si timeout dépassé
            Exception: Si la tâche a échoué
        """
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        start = time.time()
        while task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            if timeout and (time.time() - start) > timeout:
                raise TimeoutError(f"Task {task_id} timed out waiting for result")
            await asyncio.sleep(0.1)

        if task.status == TaskStatus.FAILED:
            raise Exception(f"Task failed: {task.error}")

        if task.status == TaskStatus.TIMEOUT:
            raise TimeoutError(f"Task {task_id} execution timed out")

        return task.result

    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """Retourne le statut d'une tâche."""
        task = self._tasks.get(task_id)
        return task.status if task else None

    def get_task(self, task_id: str) -> Optional[Task]:
        """Retourne une tâche par son ID."""
        return self._tasks.get(task_id)

    def get_user_tasks(self, user_id: int) -> List[Task]:
        """Retourne toutes les tâches d'un utilisateur."""
        return [t for t in self._tasks.values() if t.user_id == user_id]

    def cancel_task(self, task_id: str) -> bool:
        """Annule une tâche en attente."""
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.PENDING:
            task.status = TaskStatus.CANCELLED
            return True
        return False

    def cancel_user_tasks(self, user_id: int) -> int:
        """Annule toutes les tâches d'un utilisateur."""
        count = 0
        for task in self._tasks.values():
            if task.user_id == user_id and task.status == TaskStatus.PENDING:
                task.status = TaskStatus.CANCELLED
                count += 1
        return count

    def get_stats(self) -> dict:
        """Retourne les statistiques du pool."""
        self.stats["queue_size"] = self._queue.qsize() if self._queue else 0
        self.stats["active_workers"] = sum(
            1 for t in self._tasks.values() if t.status == TaskStatus.RUNNING
        )
        return self.stats.copy()

    async def _worker(self, worker_id: int):
        """Worker qui traite les tâches de la queue."""
        logger.debug(f"Worker {worker_id} started")

        while self._running:
            try:
                # Récupérer une tâche de la queue
                try:
                    priority, task = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                # Signal d'arrêt
                if task is None:
                    break

                # Tâche annulée
                if task.status == TaskStatus.CANCELLED:
                    self._queue.task_done()
                    continue

                # Exécuter la tâche
                await self._execute_task(task, worker_id)
                self._queue.task_done()

            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                await asyncio.sleep(1)

        logger.debug(f"Worker {worker_id} stopped")

    async def _execute_task(self, task: Task, worker_id: int):
        """Exécute une tâche avec gestion des erreurs et retries."""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()

        logger.info(f"Worker {worker_id} executing task {task.id} (user: {task.user_id})")

        while task.retries <= task.max_retries:
            try:
                # Exécuter avec timeout
                task.result = await asyncio.wait_for(
                    task.func(*task.args, **task.kwargs),
                    timeout=task.timeout
                )
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now()
                self.stats["completed_tasks"] += 1

                duration = (task.completed_at - task.started_at).total_seconds()
                logger.info(f"Task {task.id} completed in {duration:.2f}s")
                return

            except asyncio.TimeoutError:
                task.retries += 1
                if task.retries > task.max_retries:
                    task.status = TaskStatus.TIMEOUT
                    task.error = f"Task timed out after {task.timeout}s"
                    self.stats["failed_tasks"] += 1
                    logger.error(f"Task {task.id} timed out")
                    return
                logger.warning(f"Task {task.id} timeout, retry {task.retries}/{task.max_retries}")

            except Exception as e:
                task.retries += 1
                error_msg = f"{type(e).__name__}: {str(e)}"

                if task.retries > task.max_retries:
                    task.status = TaskStatus.FAILED
                    task.error = error_msg
                    task.completed_at = datetime.now()
                    self.stats["failed_tasks"] += 1
                    logger.error(f"Task {task.id} failed: {error_msg}")
                    logger.debug(traceback.format_exc())
                    return

                logger.warning(f"Task {task.id} error, retry {task.retries}/{task.max_retries}: {error_msg}")
                await asyncio.sleep(self.retry_delay)

    def cleanup_old_tasks(self, max_age_seconds: int = 3600):
        """Nettoie les tâches terminées plus anciennes que max_age."""
        now = datetime.now()
        to_remove = []

        for task_id, task in self._tasks.items():
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                if task.completed_at:
                    age = (now - task.completed_at).total_seconds()
                    if age > max_age_seconds:
                        to_remove.append(task_id)

        for task_id in to_remove:
            del self._tasks[task_id]

        if to_remove:
            logger.debug(f"Cleaned up {len(to_remove)} old tasks")


# ============================================================
# INSTANCE GLOBALE
# ============================================================

_worker_pool: Optional[WorkerPool] = None


async def get_worker_pool() -> WorkerPool:
    """Retourne l'instance globale du worker pool."""
    global _worker_pool
    if _worker_pool is None:
        from bot_config import worker_config
        _worker_pool = WorkerPool(
            num_workers=worker_config.MAX_WORKERS,
            queue_size=worker_config.QUEUE_SIZE,
            task_timeout=worker_config.TASK_TIMEOUT,
            max_retries=worker_config.MAX_RETRIES,
            retry_delay=worker_config.RETRY_DELAY
        )
        await _worker_pool.start()
    return _worker_pool


async def stop_worker_pool():
    """Arrête le worker pool global."""
    global _worker_pool
    if _worker_pool:
        await _worker_pool.stop()
        _worker_pool = None


# ============================================================
# DÉCORATEURS UTILITAIRES
# ============================================================

def run_in_worker(priority: TaskPriority = TaskPriority.NORMAL, timeout: int = None):
    """
    Décorateur pour exécuter une fonction dans le worker pool.

    Usage:
        @run_in_worker(priority=TaskPriority.HIGH)
        async def my_heavy_task(arg1, arg2):
            ...
    """
    def decorator(func: Callable):
        async def wrapper(*args, user_id: int = None, **kwargs):
            pool = await get_worker_pool()
            task_id = await pool.submit(
                func, *args,
                user_id=user_id,
                priority=priority,
                timeout=timeout,
                **kwargs
            )
            return await pool.wait_for(task_id)
        return wrapper
    return decorator


# ============================================================
# FONCTIONS UTILITAIRES
# ============================================================

async def submit_task(
    func: Callable,
    *args,
    user_id: int = None,
    priority: TaskPriority = TaskPriority.NORMAL,
    wait: bool = False,
    **kwargs
) -> Any:
    """
    Soumet une tâche au worker pool.

    Args:
        func: Fonction à exécuter
        user_id: ID utilisateur
        priority: Priorité
        wait: Attendre le résultat

    Returns:
        task_id si wait=False, sinon le résultat
    """
    pool = await get_worker_pool()
    task_id = await pool.submit(func, *args, user_id=user_id, priority=priority, **kwargs)

    if wait:
        return await pool.wait_for(task_id)
    return task_id


async def get_worker_stats() -> dict:
    """Retourne les statistiques des workers."""
    pool = await get_worker_pool()
    return pool.get_stats()

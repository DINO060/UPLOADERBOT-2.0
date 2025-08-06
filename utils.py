from datetime import datetime
import pytz
import asyncio
import logging
from typing import List, Dict, Any, Callable, Awaitable, Tuple, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


class TimeUtils:
    @staticmethod
    def parse_and_validate_time(time_text: str) -> tuple[int, int]:
        """Parse et valide une entrée de temps.

        Args:
            time_text: Texte contenant l'heure (format: HH:MM, HHMM, HH MM, ou HH)

        Returns:
            Tuple (heure, minute)

        Raises:
            ValueError: Si le format est invalide ou les valeurs sont hors limites
        """
        try:
            if ':' in time_text:
                hour, minute = map(int, time_text.split(':'))
            elif len(time_text) == 4:
                hour, minute = int(time_text[:2]), int(time_text[2:])
            elif len(time_text.split()) == 2:
                hour, minute = map(int, time_text.split())
            elif len(time_text) in {1, 2}:
                hour, minute = int(time_text), 0
            else:
                raise ValueError("Format d'heure invalide")

            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Heure hors limites")

            return hour, minute
        except ValueError as e:
            raise ValueError(f"Erreur de parsing de l'heure: {e}")

    @staticmethod
    def validate_scheduled_time(scheduled_time: datetime) -> bool:
        """Vérifie si une heure programmée est valide (pas dans le passé).

        Args:
            scheduled_time: L'heure programmée à vérifier

        Returns:
            bool: True si l'heure est valide, False sinon
        """
        return scheduled_time > datetime.now(pytz.UTC)


class KeyboardUtils:
    @staticmethod
    def build_inline_keyboard(options: List[Dict[str, str]]) -> InlineKeyboardMarkup:
        """Construit un InlineKeyboardMarkup à partir d'une liste d'options.

        Args:
            options: Liste de dictionnaires contenant 'text' et 'callback_data'

        Returns:
            InlineKeyboardMarkup
        """
        keyboard = [
            [InlineKeyboardButton(option['text'], callback_data=option['callback_data'])]
            for option in options
        ]
        return InlineKeyboardMarkup(keyboard)


class RetryUtils:
    @staticmethod
    async def retry_operation(
            operation: Callable[[], Awaitable[Any]],
            max_retries: int = 3,
            delay: float = 1.0
    ) -> Any:
        """Exécute une opération avec logique de réessai.

        Args:
            operation: Fonction asynchrone à exécuter
            max_retries: Nombre maximum de tentatives
            delay: Délai initial entre les tentatives (en secondes)

        Returns:
            Résultat de l'opération

        Raises:
            Exception: Si toutes les tentatives échouent
        """
        for attempt in range(max_retries):
            try:
                return await operation()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"Tentative {attempt + 1} échouée: {e}")
                await asyncio.sleep(delay * (attempt + 1))


class ErrorMessages:
    @staticmethod
    def get_time_format_error() -> str:
        """Retourne un message d'erreur détaillé pour un format d'heure invalide."""
        return (
            "❌ Format d'heure invalide. Veuillez utiliser l'un des formats suivants:\n"
            "• '15:30' ou '1530'\n"
            "• '6' (06:00)\n"
            "• '5 3' (05:03)"
        )


class TimezoneManager:
    @staticmethod
    def format_time_for_user(dt: datetime, timezone: str) -> str:
        """Formate une date pour l'affichage utilisateur."""
        local_tz = pytz.timezone(timezone)
        local_dt = dt.astimezone(local_tz)
        return local_dt.strftime("%d/%m/%Y à %H:%M")

    @staticmethod
    def validate_future_time(dt: datetime, timezone: str) -> Tuple[bool, str]:
        """Vérifie si une date est dans le futur."""
        local_tz = pytz.timezone(timezone)
        now = datetime.now(local_tz)
        if dt <= now:
            return False, "Cette heure est déjà passée"
        return True, ""


class MessageTemplates:
    @staticmethod
    def get_time_selection_message() -> str:
        return (
            "📅 Choisissez la nouvelle date pour votre publication :\n\n"
            "1️⃣ Sélectionnez le jour (Aujourd'hui ou Demain)\n"
            "2️⃣ Ensuite, envoyez-moi l'heure au format :\n"
            "   • '15:30' ou '1530' (24h)\n"
            "   • '6' (06:00)\n"
            "   • '5 3' (05:03)\n\n"
        )

    @staticmethod
    def get_invalid_time_message() -> str:
        return (
            "❌ Format d'heure invalide. Utilisez un format comme :\n"
            "• '15:30' ou '1530' (24h)\n"
            "• '6' (06:00)\n"
            "• '5 3' (05:03)"
        )


class KeyboardManager:
    @staticmethod
    def get_time_selection_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Aujourd'hui", callback_data="schedule_today"),
                InlineKeyboardButton("Demain", callback_data="schedule_tomorrow"),
            ],
            [InlineKeyboardButton("↩️ Retour", callback_data="retour")]
        ])

    @staticmethod
    def get_error_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
        ]])


class PostEditingState:
    def __init__(self, context):
        self.context = context
        self.post_id = context.user_data.get('editing_post_id')
        self.schedule_day = context.user_data.get('schedule_day')
        self.timezone = context.user_data.get('timezone', "UTC")

    def is_valid(self) -> Tuple[bool, str]:
        if not self.post_id:
            return False, "Publication introuvable"
        if not self.schedule_day:
            return False, "Jour non sélectionné"
        return True, ""
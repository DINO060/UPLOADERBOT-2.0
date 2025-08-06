"""
Gestionnaire de claviers pour le bot Telegram.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

class KeyboardManager:
    @staticmethod
    def get_time_selection_keyboard():
        """Retourne le clavier pour la sélection de l'heure."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Aujourd'hui", callback_data="schedule_today"),
                InlineKeyboardButton("Demain", callback_data="schedule_tomorrow"),
            ],
            [InlineKeyboardButton("↩️ Retour", callback_data="retour")]
        ])

    @staticmethod
    def get_error_keyboard():
        """Retourne le clavier pour les messages d'erreur."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
        ]) 
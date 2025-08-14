"""
Gestionnaire de claviers pour le bot Telegram.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

class KeyboardManager:
    @staticmethod
    def get_time_selection_keyboard():
        """Returns the keyboard for time selection."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Today", callback_data="schedule_today"),
                InlineKeyboardButton("Tomorrow", callback_data="schedule_tomorrow"),
            ],
            [InlineKeyboardButton("↩️ Retour", callback_data="retour")]
        ])

    @staticmethod
    def get_error_keyboard():
        """Returns the keyboard for error messages."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
        ]) 
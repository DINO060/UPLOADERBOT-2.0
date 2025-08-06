# Constantes de configuration
DEFAULT_TIMEZONE = "UTC"
DEFAULT_CHANNEL = "https://t.me/sheweeb"
DEFAULT_SESSION_NAME = "uploader_session"
DEFAULT_DB_NAME = "bot.db"
DEFAULT_DOWNLOAD_FOLDER = "downloads/"

# Limites
BOT_MAX_MEDIA_SIZE = 100 * 1024 * 1024  # 10 Mo
USERBOT_MAX_MEDIA_SIZE = 2 * 1024 * 1024 * 1024  # 2 Go
MAX_STORAGE_MB = 1000

# Messages d'erreur
ERROR_MESSAGES = {
    "invalid_time": "❌ Format d'heure invalide. Utilisez :\n• '15:30' ou '1530' (24h)\n• '6' (06:00)\n• '5 3' (05:03)",
    "past_time": "❌ Cette heure est déjà passée. Veuillez choisir une heure future.",
    "no_content": "❌ Aucun contenu à planifier. Veuillez d'abord envoyer du contenu.",
    "no_day_selected": "❌ Veuillez d'abord sélectionner un jour (Aujourd'hui ou Demain).",
    "invalid_url": "❌ Format d'URL invalide",
    "permission_denied": "❌ Vous n'avez pas les permissions nécessaires.",
    "generic_error": "❌ Une erreur est survenue. Veuillez réessayer."
}

# Messages de succès
SUCCESS_MESSAGES = {
    "scheduled": "✅ {count} fichier(s) planifié(s) pour {day} à {time} ({timezone})",
    "sent": "✅ Publication envoyée avec succès",
    "deleted": "✅ Publication supprimée avec succès",
    "edited": "✅ Publication modifiée avec succès"
}

# Types de fichiers autorisés
ALLOWED_FILE_TYPES = {
    'photo': ['.jpg', '.jpeg', '.png', '.gif'],
    'video': ['.mp4', '.mov', '.avi'],
    'document': ['.pdf', '.doc', '.docx', '.txt']
}

# États de la conversation
CONVERSATION_STATES = {
    'MAIN_MENU': 0,
    'WAITING_CHANNEL_SELECTION': 1,
    'WAITING_PUBLICATION_CONTENT': 2,
    'POST_ACTIONS': 3,
    'SEND_OPTIONS': 4,
    'AUTO_DESTRUCTION': 5,
    'SCHEDULE_SEND': 6,
    'EDIT_POST': 7,
    'SCHEDULE_SELECT_CHANNEL': 8,
    'STATS_SELECT_CHANNEL': 9,
    'WAITING_CHANNEL_INFO': 10,
    'SETTINGS': 11,
    'WAITING_TIMEZONE': 12,
    'BACKUP_MENU': 13,
    'WAITING_SCHEDULE_TEXT': 14,
    'WAITING_SCHEDULE_MEDIA': 15,
    'WAITING_SCHEDULE_TIME': 16,
    'WAITING_CONFIRMATION': 17,
    'WAITING_NEW_TIME': 18,
    'SCHEDULED_POSTS_MENU': 19,
    'STATS_MENU': 20,
    'WAITING_REACTION_INPUT': 21,
    'WAITING_URL_INPUT': 22
}

# Patterns de validation
VALIDATION_PATTERNS = {
    'time': r'^(\d{1,2}(?::\d{2})?|\d{1,2}\s\d{2})$',
    'url': r'^https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)$'
}
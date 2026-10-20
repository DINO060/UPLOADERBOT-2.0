"""Module contenant les templates de messages pour le bot Telegram."""

class MessageTemplates:
    """Classe contenant les templates de messages pour le bot."""
    
    @staticmethod
    def get_invalid_time_message() -> str:
        """Retourne le message pour une heure invalide."""
        return (
            "❌ Format d'heure invalide. Veuillez utiliser l'un des formats suivants :\n"
            "• '15:30' ou '1530' (24h)\n"
            "• '6' (06:00)\n"
            "• '5 3' (05:03)"
        )
    
    @staticmethod
    def get_invalid_date_message() -> str:
        """Retourne le message pour une date invalide."""
        return (
            "❌ Format de date invalide. Veuillez utiliser le format :\n"
            "• YYYY-MM-DD (ex: 2024-03-15)"
        )
    
    @staticmethod
    def get_invalid_datetime_message() -> str:
        """Retourne le message pour une date et heure invalides."""
        return (
            "❌ Format de date et heure invalide. Veuillez utiliser le format :\n"
            "• YYYY-MM-DD HH:MM (ex: 2024-03-15 14:30)"
        )
    
    @staticmethod
    def get_timezone_setup_message() -> str:
        """Retourne le message pour la configuration du fuseau horaire."""
        return (
            "🌍 Configuration du fuseau horaire\n\n"
            "Veuillez m'envoyer votre fuseau horaire au format :\n"
            "• Europe/Paris\n"
            "• America/New_York\n"
            "• Asia/Tokyo\n"
            "• Africa/Cairo\n\n"
            "Vous pouvez trouver votre fuseau horaire ici :\n"
            "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
        )
    
    @staticmethod
    def get_schedule_options_message() -> str:
        """Retourne le message pour les options de planification."""
        return (
            "📅 Choisissez quand envoyer votre publication :\n\n"
            "1️⃣ Sélectionnez le jour (Aujourd'hui ou Demain)\n"
            "2️⃣ Envoyez-moi l'heure au format :\n"
            "   • '15:30' ou '1530' (24h)\n"
            "   • '6' (06:00)\n"
            "   • '5 3' (05:03)"
        )
    
    @staticmethod
    def get_auto_destruction_message() -> str:
        """Retourne le message pour les options d'auto-destruction."""
        return (
            "⏰ **Auto-destruction**\n\n"
            "After how long should the posts be deleted from your channel?\n\n"
            "Choose a duration:"
        ) 
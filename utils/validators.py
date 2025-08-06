import re
import json
import os
from datetime import datetime
from typing import Optional, Union, Dict, Any
import pytz

class InputValidator:
    """Classe de base pour la validation des entrées utilisateur"""
    
    @staticmethod
    def validate_channel_username(username: str) -> bool:
        """
        Valide le format d'un nom d'utilisateur de canal Telegram
        """
        if not username:
            return False
        username = username.strip()
        return bool(re.match(r'^@?[a-zA-Z0-9_]{5,32}$', username))

    @staticmethod
    def validate_url(url: str) -> bool:
        """
        Valide le format d'une URL
        """
        if not url:
            return False
        url = url.strip()
        url_pattern = re.compile(
            r'^(https?://)?'  # http:// ou https:// (optionnel)
            r'([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+'  # domaine
            r'[a-zA-Z]{2,}'  # TLD
            r'(/[a-zA-Z0-9-._~:/?#[\]@!$&\'()*+,;=]*)?$'  # chemin (optionnel)
        )
        return bool(url_pattern.match(url))

    @staticmethod
    def validate_reaction(reaction: str) -> bool:
        """
        Valide le format d'une réaction (emoji)
        """
        if not reaction:
            return False
        # Vérifie si la chaîne contient au moins un emoji
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F700-\U0001F77F"  # alchemical symbols
            "\U0001F780-\U0001F7FF"  # Geometric Shapes
            "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
            "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
            "\U0001FA00-\U0001FA6F"  # Chess Symbols
            "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
            "\U00002702-\U000027B0"  # Dingbats
            "\U000024C2-\U0001F251" 
            "]+"
        )
        return bool(emoji_pattern.search(reaction))
    
    @staticmethod
    def validate_time(time_str: str) -> Optional[datetime]:
        """Valide et convertit une chaîne d'heure en objet datetime"""
        try:
            time_pattern = r'^(\d{1,2}(?::\d{2})?|\d{1,2}\s\d{2})$'
            if not re.match(time_pattern, time_str):
                return None

            if ':' in time_str:
                hour, minute = map(int, time_str.split(':'))
            elif ' ' in time_str:
                hour, minute = map(int, time_str.split())
            else:
                hour = int(time_str)
                minute = 0

            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None

            return datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def validate_file_type(file_path: str, expected_type: str) -> bool:
        """Valide le type d'un fichier"""
        allowed_file_types = {
            'photo': ['.jpg', '.jpeg', '.png', '.gif'],
            'video': ['.mp4', '.mov', '.avi'],
            'document': ['.pdf', '.doc', '.docx', '.txt']
        }
        
        if expected_type not in allowed_file_types:
            return False

        file_ext = file_path.lower().split('.')[-1]
        return f'.{file_ext}' in allowed_file_types[expected_type]

    @staticmethod
    def validate_file_size(file_path: str, max_size_bytes: int) -> bool:
        """Valide la taille d'un fichier"""
        try:
            return os.path.getsize(file_path) <= max_size_bytes
        except (OSError, TypeError):
            return False

    @staticmethod
    def validate_post_data(post_data: Dict[str, Any]) -> bool:
        """Valide les données d'un post"""
        required_fields = ['type', 'content']
        return all(field in post_data for field in required_fields)

    @staticmethod
    def validate_timezone(timezone: str) -> bool:
        """Valide un fuseau horaire"""
        try:
            pytz.timezone(timezone)
            return True
        except pytz.exceptions.UnknownTimeZoneError:
            return False

    @staticmethod
    def sanitize_text(text: str) -> str:
        """Nettoie un texte pour éviter les injections"""
        if not text:
            return ""
        # Supprimer les caractères potentiellement dangereux
        return re.sub(r'[<>]', '', text)

    @staticmethod
    def validate_buttons(buttons_data: str) -> Optional[Dict]:
        """Valide et parse les données des boutons"""
        try:
            buttons = json.loads(buttons_data)
            if not isinstance(buttons, list):
                return None

            for button in buttons:
                if not isinstance(button, dict):
                    return None
                if 'text' not in button or 'url' not in button:
                    return None
                if not InputValidator.validate_url(button['url']):
                    return None

            return buttons
        except (json.JSONDecodeError, TypeError):
            return None
    
    @staticmethod
    def validate_channel_name(channel_name: str) -> bool:
        """Valide un nom de canal"""
        if not channel_name:
            return False
        # Supprimer @ si présent et vérifier la longueur
        clean_name = channel_name.lstrip('@')
        return len(clean_name) >= 5 and clean_name.replace('_', '').replace('.', '').isalnum()

class TimeInputValidator:
    """Classe pour la validation des entrées de temps"""
    
    @staticmethod
    def validate_time_format(time_str: str) -> bool:
        """
        Valide le format d'une heure (HH:MM)
        """
        if not time_str:
            return False
        time_pattern = re.compile(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$')
        return bool(time_pattern.match(time_str))

    @staticmethod
    def validate_date_format(date_str: str) -> bool:
        """
        Valide le format d'une date (YYYY-MM-DD)
        """
        if not date_str:
            return False
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
            return True
        except ValueError:
            return False

    @staticmethod
    def validate_datetime_format(datetime_str: str) -> bool:
        """
        Valide le format d'une date et heure (YYYY-MM-DD HH:MM)
        """
        if not datetime_str:
            return False
        try:
            datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
            return True
        except ValueError:
            return False

    @staticmethod
    def is_future_datetime(datetime_str: str) -> bool:
        """
        Vérifie si la date/heure est dans le futur
        """
        try:
            dt = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
            return dt > datetime.now()
        except ValueError:
            return False
    
    @staticmethod
    def parse_time(time_text: str) -> tuple[bool, tuple[int, int], str]:
        """Parse et valide une entrée d'heure."""
        try:
            if ':' in time_text:
                hour, minute = map(int, time_text.split(':'))
            elif ' ' in time_text:
                hour, minute = map(int, time_text.split())
            else:
                hour = int(time_text)
                minute = 0

            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return False, (0, 0), "Heure invalide"
            return True, (hour, minute), ""
        except ValueError:
            return False, (0, 0), "Format d'heure invalide" 
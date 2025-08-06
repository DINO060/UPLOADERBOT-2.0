"""
Gestionnaire de fuseaux horaires pour le bot Telegram.
"""
import pytz
from datetime import datetime
from typing import Optional

class TimezoneManager:
    @staticmethod
    def format_time_for_user(date: datetime, timezone: str) -> str:
        """
        Formate une date pour l'affichage utilisateur dans son fuseau horaire.
        
        Args:
            date: La date à formater
            timezone: Le fuseau horaire de l'utilisateur
            
        Returns:
            str: La date formatée
        """
        try:
            user_tz = pytz.timezone(timezone)
            local_date = date.astimezone(user_tz)
            return local_date.strftime('%d/%m/%Y %H:%M')
        except Exception as e:
            # En cas d'erreur, retourner la date en UTC
            return date.strftime('%d/%m/%Y %H:%M UTC')

    @staticmethod
    def get_valid_timezones() -> list:
        """
        Retourne la liste des fuseaux horaires valides.
        
        Returns:
            list: Liste des fuseaux horaires
        """
        return pytz.all_timezones

    @staticmethod
    def is_valid_timezone(timezone: str) -> bool:
        """
        Vérifie si un fuseau horaire est valide.
        
        Args:
            timezone: Le fuseau horaire à vérifier
            
        Returns:
            bool: True si le fuseau horaire est valide
        """
        try:
            pytz.timezone(timezone)
            return True
        except pytz.exceptions.UnknownTimeZoneError:
            return False

    @staticmethod
    def convert_to_utc(date: datetime, timezone: str) -> Optional[datetime]:
        """
        Convertit une date locale en UTC.
        
        Args:
            date: La date à convertir
            timezone: Le fuseau horaire source
            
        Returns:
            Optional[datetime]: La date en UTC ou None en cas d'erreur
        """
        try:
            source_tz = pytz.timezone(timezone)
            local_date = source_tz.localize(date)
            return local_date.astimezone(pytz.UTC)
        except Exception as e:
            return None 
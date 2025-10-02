"""
Utilitaires pour vérifier les permissions Telegram des canaux
"""

import logging
from typing import Optional
from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

async def check_user_admin_status(bot: Bot, chat_id: int, user_id: int) -> Optional[str]:
    """
    Vérifie si un utilisateur est administrateur d'un canal/groupe
    
    Args:
        bot: Instance du bot Telegram
        chat_id: ID du chat/canal
        user_id: ID de l'utilisateur à vérifier
    
    Returns:
        str: 'creator', 'administrator', 'member', 'left', 'kicked' ou None si erreur
    """
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status
    except TelegramError as e:
        logger.error(f"Erreur vérification admin status: {e}")
        return None

async def check_bot_admin_status(bot: Bot, chat_id: int) -> Optional[str]:
    """
    Vérifie si le bot est administrateur d'un canal/groupe
    
    Args:
        bot: Instance du bot Telegram
        chat_id: ID du chat/canal
    
    Returns:
        str: 'administrator' si admin, autre statut sinon, None si erreur
    """
    try:
        bot_user = await bot.get_me()
        return await check_user_admin_status(bot, chat_id, bot_user.id)
    except Exception as e:
        logger.error(f"Erreur vérification bot admin status: {e}")
        return None

async def can_user_add_channel(bot: Bot, chat_id: int, user_id: int) -> tuple[bool, str]:
    """
    Vérifie si un utilisateur peut ajouter un canal au bot
    
    Args:
        bot: Instance du bot Telegram
        chat_id: ID du canal à ajouter
        user_id: ID de l'utilisateur qui veut ajouter
    
    Returns:
        tuple: (can_add: bool, reason: str)
    """
    # 1. Vérifier que le bot est admin du canal
    bot_status = await check_bot_admin_status(bot, chat_id)
    if bot_status not in ('creator', 'administrator'):
        return False, "⚠️ Le bot doit être administrateur du canal. Ajoutez d'abord le bot comme admin."
    
    # 2. Vérifier que l'utilisateur est admin du canal
    user_status = await check_user_admin_status(bot, chat_id, user_id)
    if user_status not in ('creator', 'administrator'):
        return False, "vous etes pas adm , vous devez etre adm pour add ce canal et rien d'autre"
    
    return True, "✅ Permissions validées"

def format_permission_error(can_add: bool, reason: str) -> str:
    """
    Formate un message d'erreur de permission pour l'utilisateur
    
    Args:
        can_add: Si l'utilisateur peut ajouter le canal
        reason: Raison du refus/succès
    
    Returns:
        str: Message formaté pour l'utilisateur
    """
    if can_add:
        return reason
    else:
        return f"{reason}\n\n💡 **Pour ajouter un canal au bot :**\n1️⃣ Ajoute le bot comme admin du canal\n2️⃣ Assure-toi d'être admin du canal\n3️⃣ Réessaie l'ajout"
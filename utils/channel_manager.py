"""
Nouvelle logique d'ajout de canaux avec vérification des permissions Telegram
"""

import logging
from typing import Optional, Dict, Any
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.channel_permissions import can_user_add_channel, format_permission_error
from database.channel_repo import db

logger = logging.getLogger(__name__)

async def resolve_channel_info(bot: Bot, channel_input: str) -> Optional[Dict[str, Any]]:
    """
    Résout les informations d'un canal à partir d'un username ou ID
    
    Args:
        bot: Instance du bot Telegram
        channel_input: @username ou -100123456789
    
    Returns:
        dict: Infos du canal (id, title, username) ou None si erreur
    """
    try:
        # Nettoyer l'input
        if channel_input.startswith('@'):
            chat_identifier = channel_input
        elif channel_input.startswith('-100'):
            chat_identifier = int(channel_input)
        else:
            # Essayer d'ajouter le @
            chat_identifier = f"@{channel_input}"
        
        # Récupérer les infos du chat
        chat = await bot.get_chat(chat_id=chat_identifier)
        
        return {
            'id': chat.id,
            'title': chat.title,
            'username': getattr(chat, 'username', None)
        }
        
    except Exception as e:
        logger.error(f"Erreur résolution canal {channel_input}: {e}")
        return None

async def add_channel_with_permissions(bot: Bot, channel_input: str, user_id: int) -> tuple[bool, str, Optional[Dict]]:
    """
    Ajoute un canal avec vérification complète des permissions
    
    Args:
        bot: Instance du bot Telegram
        channel_input: @username ou -100123456789 du canal
        user_id: ID de l'utilisateur qui ajoute
    
    Returns:
        tuple: (success: bool, message: str, channel_info: dict)
    """
    # 1. Résoudre les infos du canal
    channel_info = await resolve_channel_info(bot, channel_input)
    if not channel_info:
        return False, "❌ Canal introuvable. Vérifiez le nom d'utilisateur ou l'ID.", None
    
    chat_id = channel_info['id']
    title = channel_info['title']
    username = channel_info['username']
    
    # 2. Vérifier les permissions
    can_add, reason = await can_user_add_channel(bot, chat_id, user_id)
    if not can_add:
        return False, format_permission_error(can_add, reason), channel_info
    
    # 3. Ajouter à la base de données
    try:
        with db() as conn:
            cursor = conn.cursor()
            
            # Vérifier si le canal existe déjà
            cursor.execute("SELECT id FROM channels WHERE tg_chat_id = ?", (chat_id,))
            existing = cursor.fetchone()
            
            if existing:
                channel_id = existing[0]
                # Canal existe, ajouter l'utilisateur comme membre s'il ne l'est pas
                cursor.execute("""
                    INSERT OR IGNORE INTO channel_members (channel_id, user_id)
                    VALUES (?, ?)
                """, (channel_id, user_id))
                
                # Vérifier si c'était déjà membre
                cursor.execute("""
                    SELECT COUNT(*) FROM channel_members 
                    WHERE channel_id = ? AND user_id = ?
                """, (channel_id, user_id))
                
                if cursor.fetchone()[0] > 0:
                    conn.commit()
                    return True, f"✅ Accès accordé au canal **{title}**\n🔗 @{username or 'canal privé'}", channel_info
                else:
                    return False, "❌ Impossible d'ajouter l'accès au canal", channel_info
            else:
                # Nouveau canal, l'ajouter
                cursor.execute("""
                    INSERT INTO channels (tg_chat_id, title, username, bot_is_admin)
                    VALUES (?, ?, ?, 1)
                """, (chat_id, title, username))
                
                channel_id = cursor.lastrowid
                
                # Ajouter l'utilisateur comme membre
                cursor.execute("""
                    INSERT INTO channel_members (channel_id, user_id)
                    VALUES (?, ?)
                """, (channel_id, user_id))
                
                conn.commit()
                
                return True, f"✅ Canal ajouté avec succès !\n\n📺 **{title}**\n🔗 @{username or 'canal privé'}", channel_info
                
    except Exception as e:
        logger.error(f"Erreur base de données lors de l'ajout du canal: {e}")
        return False, f"❌ Erreur base de données: {str(e)}", channel_info

async def handle_add_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_input: str):
    """
    Gère l'ajout d'un canal depuis un message utilisateur
    
    Args:
        update: Update Telegram
        context: Context du bot
        channel_input: Texte saisi par l'utilisateur
    """
    user_id = update.effective_user.id
    bot = context.bot
    
    try:
        # Nettoyer l'input
        channel_input = channel_input.strip()
        if not channel_input:
            await update.message.reply_text(
                "❌ Veuillez fournir un nom d'utilisateur (@canal) ou un ID de canal.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Retry", callback_data="add_channel")
                ]])
            )
            return
        
        # Message de progression
        progress_msg = await update.message.reply_text("⏳ Checking permissions...")
        
        # Ajouter le canal
        success, message, channel_info = await add_channel_with_permissions(bot, channel_input, user_id)
        
        # Supprimer le message de progression
        try:
            await progress_msg.delete()
        except:
            pass
        
        # Afficher le résultat
        if success:
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Manage Channels", callback_data="manage_channels")],
                    [InlineKeyboardButton("↩️ Main Menu", callback_data="main_menu")]
                ]),
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Retry", callback_data="add_channel")],
                    [InlineKeyboardButton("↩️ Main Menu", callback_data="main_menu")]
                ]),
                parse_mode='Markdown'
            )
            
    except Exception as e:
        logger.error(f"Erreur handle_add_channel_message: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors de l'ajout du canal.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main Menu", callback_data="main_menu")
            ]])
        )
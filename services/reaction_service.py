"""
Reaction service for handling emoji reactions on messages
"""

from typing import Dict, List, Tuple, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database.reaction_models import ReactionManager

# Default emojis available for reactions
DEFAULT_EMOJIS = ["👍", "👎", "❤️", "🔥", "😂", "😮", "😢", "👏"]

class ReactionService:
    """Service for managing message reactions"""
    
    def __init__(self):
        self.reaction_manager = ReactionManager()
    
    async def toggle_reaction(self, chat_id: int, message_id: int, user_id: int, emoji: str) -> Tuple[bool, int]:
        """
        Toggle a reaction for a user on a message
        
        Args:
            chat_id: Chat ID where the message is
            message_id: Message ID to react to
            user_id: User ID who is reacting
            emoji: Emoji to toggle
            
        Returns:
            Tuple of (is_added: bool, new_count: int)
        """
        return await self.reaction_manager.toggle_reaction(chat_id, message_id, user_id, emoji)
    
    async def get_reaction_counts(self, chat_id: int, message_id: int) -> Dict[str, int]:
        """Get reaction counts for a message"""
        return await self.reaction_manager.get_reaction_counts(chat_id, message_id)
    
    async def reset_reactions(self, chat_id: int, message_id: int):
        """Reset all reactions for a message"""
        await self.reaction_manager.reset_reactions(chat_id, message_id)
    
    def build_markup(self, chat_id: int, message_id: int) -> InlineKeyboardMarkup:
        """
        Build inline keyboard markup for reactions
        
        Args:
            chat_id: Chat ID
            message_id: Message ID
            
        Returns:
            InlineKeyboardMarkup with reaction buttons
        """
        buttons = []
        row = []
        
        for i, emoji in enumerate(DEFAULT_EMOJIS):
            # Create callback data for the reaction
            callback_data = f"react_{chat_id}_{message_id}_{emoji}"
            
            # Truncate callback data if too long (Telegram limit is 64 bytes)
            if len(callback_data) > 64:
                callback_data = f"react_{i}_{chat_id}_{message_id}"
            
            button = InlineKeyboardButton(
                text=emoji,
                callback_data=callback_data
            )
            row.append(button)
            
            # Create rows of 4 buttons each
            if len(row) == 4:
                buttons.append(row)
                row = []
        
        # Add remaining buttons
        if row:
            buttons.append(row)
        
        # Add reset button
        reset_button = InlineKeyboardButton(
            text="🗑️ Reset",
            callback_data=f"reset_reactions_{chat_id}_{message_id}"
        )
        buttons.append([reset_button])
        
        return InlineKeyboardMarkup(buttons)

# Global instance
reaction_service = ReactionService()
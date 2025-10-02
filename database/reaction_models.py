from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from .manager import Base

class ReactionCount(Base):
    """Stores the count of each reaction emoji per message"""
    __tablename__ = 'reaction_counts'
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, nullable=False)
    message_id = Column(Integer, nullable=False)
    emoji = Column(String(10), nullable=False)  # Store the emoji character
    count = Column(Integer, default=0)
    
    # Composite unique constraint
    __table_args__ = (
        UniqueConstraint('chat_id', 'message_id', 'emoji', name='_message_emoji_uc'),
    )

class UserReaction(Base):
    """Tracks which users have reacted with which emojis to which messages"""
    __tablename__ = 'user_reactions'
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, nullable=False)
    message_id = Column(Integer, nullable=False)
    user_id = Column(Integer, nullable=False)
    emoji = Column(String(10), nullable=False)  # Store the emoji character
    
    # Composite unique constraint
    __table_args__ = (
        UniqueConstraint('chat_id', 'message_id', 'user_id', 'emoji', 
                        name='_user_message_emoji_uc'),
    )


class ReactionManager:
    """Manager class for handling reaction operations"""
    
    def __init__(self):
        from .manager import DatabaseManager
        self.db_manager = DatabaseManager()
    
    async def toggle_reaction(self, chat_id: int, message_id: int, user_id: int, emoji: str):
        """
        Toggle a reaction for a user on a message
        
        Returns:
            Tuple of (is_added: bool, new_count: int)
        """
        async with self.db_manager.get_session() as session:
            # Check if user already reacted with this emoji
            existing_reaction = await session.execute(
                "SELECT * FROM user_reactions WHERE chat_id = ? AND message_id = ? AND user_id = ? AND emoji = ?",
                (chat_id, message_id, user_id, emoji)
            )
            existing = existing_reaction.fetchone()
            
            if existing:
                # Remove the reaction
                await session.execute(
                    "DELETE FROM user_reactions WHERE chat_id = ? AND message_id = ? AND user_id = ? AND emoji = ?",
                    (chat_id, message_id, user_id, emoji)
                )
                
                # Decrease count
                await session.execute(
                    "UPDATE reaction_counts SET count = count - 1 WHERE chat_id = ? AND message_id = ? AND emoji = ?",
                    (chat_id, message_id, emoji)
                )
                
                # Get new count
                result = await session.execute(
                    "SELECT count FROM reaction_counts WHERE chat_id = ? AND message_id = ? AND emoji = ?",
                    (chat_id, message_id, emoji)
                )
                new_count = result.fetchone()
                count = new_count[0] if new_count else 0
                
                # Remove count record if count is 0
                if count <= 0:
                    await session.execute(
                        "DELETE FROM reaction_counts WHERE chat_id = ? AND message_id = ? AND emoji = ?",
                        (chat_id, message_id, emoji)
                    )
                    count = 0
                
                await session.commit()
                return False, count
            else:
                # Add the reaction
                await session.execute(
                    "INSERT OR IGNORE INTO user_reactions (chat_id, message_id, user_id, emoji) VALUES (?, ?, ?, ?)",
                    (chat_id, message_id, user_id, emoji)
                )
                
                # Increase count
                await session.execute(
                    "INSERT OR IGNORE INTO reaction_counts (chat_id, message_id, emoji, count) VALUES (?, ?, ?, 0)",
                    (chat_id, message_id, emoji)
                )
                
                await session.execute(
                    "UPDATE reaction_counts SET count = count + 1 WHERE chat_id = ? AND message_id = ? AND emoji = ?",
                    (chat_id, message_id, emoji)
                )
                
                # Get new count
                result = await session.execute(
                    "SELECT count FROM reaction_counts WHERE chat_id = ? AND message_id = ? AND emoji = ?",
                    (chat_id, message_id, emoji)
                )
                new_count = result.fetchone()
                count = new_count[0] if new_count else 1
                
                await session.commit()
                return True, count
    
    async def get_reaction_counts(self, chat_id: int, message_id: int):
        """Get reaction counts for a message"""
        async with self.db_manager.get_session() as session:
            result = await session.execute(
                "SELECT emoji, count FROM reaction_counts WHERE chat_id = ? AND message_id = ?",
                (chat_id, message_id)
            )
            rows = result.fetchall()
            return {row[0]: row[1] for row in rows}
    
    async def reset_reactions(self, chat_id: int, message_id: int):
        """Reset all reactions for a message"""
        async with self.db_manager.get_session() as session:
            await session.execute(
                "DELETE FROM user_reactions WHERE chat_id = ? AND message_id = ?",
                (chat_id, message_id)
            )
            await session.execute(
                "DELETE FROM reaction_counts WHERE chat_id = ? AND message_id = ?",
                (chat_id, message_id)
            )
            await session.commit()

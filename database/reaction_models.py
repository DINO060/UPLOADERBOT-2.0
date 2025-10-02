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

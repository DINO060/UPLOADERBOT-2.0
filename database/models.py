"""
Modèles SQLAlchemy pour la base de données du bot
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

Base = declarative_base()

class User(Base):
    """Modèle pour les utilisateurs du bot"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String(255))
    first_name = Column(String(255))
    last_name = Column(String(255))
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relations
    channels = relationship("Channel", back_populates="user", cascade="all, delete-orphan")
    settings = relationship("UserSettings", uselist=False, back_populates="user", cascade="all, delete-orphan")
    scheduled_posts = relationship("ScheduledPost", back_populates="user", cascade="all, delete-orphan")

class Channel(Base):
    """Modèle pour les canaux Telegram"""
    __tablename__ = 'channels'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    username = Column(String(255), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    user = relationship("User", back_populates="channels")
    thumbnails = relationship("ChannelThumbnail", back_populates="channel", cascade="all, delete-orphan")
    tags = relationship("ChannelTag", back_populates="channel", cascade="all, delete-orphan")
    scheduled_posts = relationship("ScheduledPost", back_populates="channel", cascade="all, delete-orphan")
    
    # Index unique pour éviter les doublons
    __table_args__ = (
        {'mysql_engine': 'InnoDB'}
    )

class ChannelThumbnail(Base):
    """Modèle pour les miniatures des canaux"""
    __tablename__ = 'channel_thumbnails'
    
    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey('channels.id'), nullable=False)
    file_id = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    channel = relationship("Channel", back_populates="thumbnails")
    
    # Index unique pour un thumbnail par canal
    __table_args__ = (
        {'mysql_engine': 'InnoDB'}
    )

class ChannelTag(Base):
    """Modèle pour les tags personnalisés des canaux"""
    __tablename__ = 'channel_tags'
    
    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey('channels.id'), nullable=False)
    tag_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    channel = relationship("Channel", back_populates="tags")

class ScheduledPost(Base):
    """Modèle pour les posts planifiés"""
    __tablename__ = 'scheduled_posts'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    channel_id = Column(Integer, ForeignKey('channels.id'), nullable=False)
    content_type = Column(String(50), nullable=False)  # photo, video, document, text
    content = Column(Text, nullable=False)  # file_id ou texte
    caption = Column(Text)
    buttons = Column(JSON)  # Stockage JSON des boutons
    reactions = Column(JSON)  # Stockage JSON des réactions
    scheduled_time = Column(DateTime, nullable=False)
    is_sent = Column(Boolean, default=False)
    sent_at = Column(DateTime)
    error_message = Column(Text)
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    user = relationship("User", back_populates="scheduled_posts")
    channel = relationship("Channel", back_populates="scheduled_posts")

class UserSettings(Base):
    """Modèle pour les paramètres utilisateur"""
    __tablename__ = 'user_settings'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    timezone = Column(String(50), default='UTC')
    language = Column(String(10), default='fr')
    notifications_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relations
    user = relationship("User", back_populates="settings") 
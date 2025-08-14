"""
Utilitaires pour la gestion des posts et la compatibilité entre systèmes
"""

import logging

logger = logging.getLogger('UploaderBot')


def normalize_post_data(post_data):
    """
    Standardise les noms de champs des posts pour la compatibilité entre tous les systèmes
    
    Champs standardisés:
    - content: file_id ou texte
    - type: photo, video, document, text
    - caption: légende du fichier
    - filename: nom du fichier (si applicable)
    - thumbnail: file_id du thumbnail
    - channel: nom d'utilisateur du canal (@username ou username)
    - channel_name: nom d'affichage du canal
    - file_size: taille du fichier en octets
    """
    if not isinstance(post_data, dict):
        return post_data
    
    # Copier les données pour éviter les modifications directes
    normalized = post_data.copy()
    
    # Normaliser les champs de contenu (anciens noms -> nouveaux noms)
    if 'file_id' in normalized and 'content' not in normalized:
        normalized['content'] = normalized.pop('file_id')
    
    if 'file_name' in normalized and 'filename' not in normalized:
        normalized['filename'] = normalized.pop('file_name')
    
    # Normaliser les champs de canal
    if 'channel' in normalized and isinstance(normalized['channel'], str):
        # S'assurer que le nom de canal commence par @
        channel = normalized['channel']
        if channel and not channel.startswith('@'):
            normalized['channel'] = f"@{channel}"
    
    # S'assurer que tous les champs obligatoires existent
    defaults = {
        'content': '',
        'type': 'text',
        'caption': '',
        'filename': '',
        'thumbnail': None,
        'channel': '',
        'channel_name': '',
        'file_size': 0,
        'reactions': [],
        'buttons': []
    }
    
    for key, default_value in defaults.items():
        if key not in normalized:
            normalized[key] = default_value
    
    return normalized


def get_channel_info_from_post_and_context(post, context):
    """
    Récupère les informations du canal depuis un post et le contexte
    Essaie plusieurs sources pour maximiser la compatibilité
    
    Args:
        post: Dictionnaire du post
        context: Contexte Telegram
        
    Returns:
        dict: {'username': str, 'name': str, 'clean_username': str}
    """
    # Essayer plusieurs sources pour le nom d'utilisateur
    username = (
        post.get('channel') or 
        post.get('channel_name') or
        context.user_data.get('selected_channel', {}).get('username') or
        context.user_data.get('selected_channel', {}).get('name') or
        ''
    )
    
    # Essayer plusieurs sources pour le nom d'affichage
    display_name = (
        post.get('channel_name') or
        context.user_data.get('selected_channel', {}).get('name') or
        post.get('channel') or
        context.user_data.get('selected_channel', {}).get('username') or
        'Canal par défaut'
    )
    
    # Nettoyer le nom d'utilisateur (pour les requêtes DB)
    clean_username = normalize_channel_username(username)
    
    return {
        'username': username,
        'name': display_name,
        'clean_username': clean_username
    }


def normalize_channel_username(channel_username):
    """
    Normalise un nom d'utilisateur de canal
    Enlève @ au début et valide le format
    
    Args:
        channel_username: str - nom du canal avec ou sans @
        
    Returns:
        str or None: nom nettoyé ou None si invalide
    """
    if not channel_username:
        return None
    
    # Convertir en string si nécessaire
    if not isinstance(channel_username, str):
        return None
    
    # Enlever @ au début
    clean = channel_username.lstrip('@')
    
    # Valider que ce n'est pas vide après nettoyage
    if not clean or clean.isspace():
        return None
    
    return clean


def get_post_summary(post):
    """
    Génère un résumé lisible d'un post pour les logs et aperçus
    
    Args:
        post: dict - données du post
        
    Returns:
        str: résumé du post
    """
    try:
        post_type = post.get('type', 'unknown')
        filename = post.get('filename', '')
        file_size = post.get('file_size', 0)
        has_thumbnail = bool(post.get('thumbnail'))
        has_caption = bool(post.get('caption', ''))
        reactions_count = len(post.get('reactions', []))
        buttons_count = len(post.get('buttons', []))
        
        summary_parts = []
        
        # Type et nom
        if post_type == 'text':
            content_preview = post.get('content', '')[:50]
            if len(post.get('content', '')) > 50:
                content_preview += '...'
            summary_parts.append(f"📝 Texte: {content_preview}")
        else:
            type_emoji = {
                'photo': '📸',
                'video': '🎥',
                'document': '📄'
            }
            emoji = type_emoji.get(post_type, '📄')
            
            if filename:
                summary_parts.append(f"{emoji} {filename}")
            else:
                summary_parts.append(f"{emoji} {post_type.capitalize()}")
        
        # Taille
        if file_size > 0:
            size_mb = file_size / 1024 / 1024
            if size_mb < 1:
                summary_parts.append(f"({file_size / 1024:.1f}KB)")
            else:
                summary_parts.append(f"({size_mb:.1f}MB)")
        
        # Extras
        extras = []
        if has_thumbnail:
            extras.append("🖼️ Thumbnail")
        if has_caption:
            extras.append("📝 Légende")
        if reactions_count > 0:
            extras.append(f"✨ {reactions_count} reaction(s)")
        if buttons_count > 0:
            extras.append(f"🔗 {buttons_count} button(s)")
        
        result = " ".join(summary_parts)
        if extras:
            result += f" + {', '.join(extras)}"
        
        return result
        
    except Exception as e:
        logger.error(f"Error in get_post_summary: {e}")
        return f"Post {post.get('type', 'unknown')}"


def validate_post_data(post):
    """
    Valide les données d'un post et retourne les erreurs trouvées
    
    Args:
        post: dict - données du post
        
    Returns:
        list: liste des erreurs trouvées (vide si pas d'erreur)
    """
    errors = []
    
    if not isinstance(post, dict):
        errors.append("Post data must be a dictionary")
        return errors
    
    # Vérifier les champs obligatoires
    required_fields = ['content', 'type']
    for field in required_fields:
        if field not in post or not post[field]:
            errors.append(f"Missing required field: {field}")
    
    # Valider le type
    valid_types = ['text', 'photo', 'video', 'document']
    if post.get('type') not in valid_types:
        errors.append(f"Invalid type: {post.get('type')}. Must be one of: {', '.join(valid_types)}")
    
    # Valider la taille de fichier
    file_size = post.get('file_size', 0)
    if file_size > 2 * 1024 * 1024 * 1024:  # 2 GB
        errors.append(f"File too large: {file_size / 1024 / 1024 / 1024:.1f}GB (max 2GB)")
    
    # Valider le thumbnail (doit être un file_id si présent)
    thumbnail = post.get('thumbnail')
    if thumbnail and not isinstance(thumbnail, str):
        errors.append("Thumbnail must be a string (file_id)")
    
    return errors


def migrate_old_post_format(old_post):
    """
    Migre un ancien format de post vers le nouveau format standardisé
    Utile pour la compatibilité avec les anciens posts stockés
    
    Args:
        old_post: dict - post dans l'ancien format
        
    Returns:
        dict: post dans le nouveau format
    """
    if not isinstance(old_post, dict):
        return old_post
    
    # Mapping des anciens champs vers les nouveaux
    field_mapping = {
        'file_id': 'content',
        'file_name': 'filename',
        'file_size': 'file_size',
        'media_type': 'type',
        'text': 'content',
        'message': 'content'
    }
    
    migrated = {}
    
    # Migrer les champs connus
    for old_field, new_field in field_mapping.items():
        if old_field in old_post:
            migrated[new_field] = old_post[old_field]
    
    # Copier les champs déjà corrects
    for field in ['type', 'content', 'caption', 'thumbnail', 'channel', 'channel_name', 'reactions', 'buttons']:
        if field in old_post:
            migrated[field] = old_post[field]
    
    # Normaliser le résultat
    return normalize_post_data(migrated) 
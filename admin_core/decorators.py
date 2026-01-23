"""
ADMIN CORE - Decorators
=======================
D\u00e9corateurs r\u00e9utilisables pour les commandes admin.
"""

import logging
from functools import wraps
from typing import Callable, List, Optional
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger("admin_core.decorators")


def admin_only(func: Callable = None, *, custom_message: str = None):
    """
    D\u00e9corateur pour restreindre une commande aux admins uniquement.

    Usage:
        @admin_only
        async def my_command(update, context):
            ...

        @admin_only(custom_message="Acc\u00e8s refus\u00e9!")
        async def my_command(update, context):
            ...
    """
    def decorator(f: Callable):
        @wraps(f)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id

            # R\u00e9cup\u00e9rer la config depuis bot_data
            config = context.bot_data.get("admin_config")

            if not config:
                logger.error("AdminConfig not found in bot_data!")
                await update.message.reply_text("Configuration error.")
                return

            if not config.is_admin(user_id):
                message = custom_message or "You don't have permission to use this command."
                await update.message.reply_text(message)
                logger.warning(f"Unauthorized access attempt by user {user_id}")
                return

            return await f(update, context, *args, **kwargs)
        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def owner_only(func: Callable = None, *, custom_message: str = None):
    """
    D\u00e9corateur pour restreindre une commande au propri\u00e9taire uniquement.

    Usage:
        @owner_only
        async def dangerous_command(update, context):
            ...
    """
    def decorator(f: Callable):
        @wraps(f)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id

            config = context.bot_data.get("admin_config")

            if not config:
                logger.error("AdminConfig not found in bot_data!")
                await update.message.reply_text("Configuration error.")
                return

            if not config.is_owner(user_id):
                message = custom_message or "Only the owner can use this command."
                await update.message.reply_text(message)
                logger.warning(f"Owner-only access attempt by user {user_id}")
                return

            return await f(update, context, *args, **kwargs)
        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def ban_check(func: Callable):
    """
    D\u00e9corateur pour v\u00e9rifier si un utilisateur est banni.
    \u00c0 utiliser sur les commandes accessibles \u00e0 tous.

    Usage:
        @ban_check
        async def start_command(update, context):
            ...
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id

        db = context.bot_data.get("admin_db")

        if db:
            is_banned, reason = db.is_banned(user_id)
            if is_banned:
                message = "You are banned from using this bot."
                if reason:
                    message += f"\n\nReason: {reason}"
                await update.message.reply_text(message)
                logger.info(f"Banned user {user_id} tried to access bot")
                return

        return await func(update, context, *args, **kwargs)
    return wrapper


def rate_limit(func: Callable = None, *, max_calls: int = None, window: int = None):
    """
    D\u00e9corateur pour appliquer un rate limit sur une commande.

    Usage:
        @rate_limit
        async def command(update, context):
            ...

        @rate_limit(max_calls=5, window=60)  # 5 appels par minute
        async def command(update, context):
            ...
    """
    def decorator(f: Callable):
        @wraps(f)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id

            config = context.bot_data.get("admin_config")
            db = context.bot_data.get("admin_db")

            if not config or not db:
                return await f(update, context, *args, **kwargs)

            # Bypass pour les admins
            if config.is_admin(user_id):
                return await f(update, context, *args, **kwargs)

            if not config.rate_limit_enabled:
                return await f(update, context, *args, **kwargs)

            # Utiliser les param\u00e8tres custom ou ceux de la config
            _max = max_calls or config.rate_limit_messages
            _window = window or config.rate_limit_window

            is_limited, remaining = db.check_rate_limit(user_id, _max, _window)

            if is_limited:
                await update.message.reply_text(
                    f"Slow down! You're sending too many messages.\n"
                    f"Please wait a moment before trying again."
                )
                logger.warning(f"Rate limit exceeded by user {user_id}")
                return

            return await f(update, context, *args, **kwargs)
        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def track_user(func: Callable):
    """
    D\u00e9corateur pour enregistrer/mettre \u00e0 jour l'utilisateur dans la DB.

    Usage:
        @track_user
        async def any_handler(update, context):
            ...
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user

        if user:
            db = context.bot_data.get("admin_db")

            if db:
                db.add_user(
                    user_id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    language_code=user.language_code or "en"
                )

        return await func(update, context, *args, **kwargs)
    return wrapper


def log_command(func: Callable):
    """
    D\u00e9corateur pour logger les commandes ex\u00e9cut\u00e9es.

    Usage:
        @log_command
        async def my_command(update, context):
            ...
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        command = update.message.text if update.message else "callback"

        logger.info(
            f"Command executed: {command} | "
            f"User: {user.id} (@{user.username}) | "
            f"Name: {user.first_name}"
        )

        return await func(update, context, *args, **kwargs)
    return wrapper


def force_join_check(func: Callable = None, *, channels: List[str] = None):
    """
    D\u00e9corateur pour v\u00e9rifier le Force Join avant d'ex\u00e9cuter une commande.

    Usage:
        @force_join_check
        async def command(update, context):
            ...

        @force_join_check(channels=["@mychannel"])
        async def command(update, context):
            ...
    """
    def decorator(f: Callable):
        @wraps(f)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id

            config = context.bot_data.get("admin_config")

            if not config or not config.force_join_enabled:
                return await f(update, context, *args, **kwargs)

            # Bypass pour les admins
            if config.force_join_bypass_admins and config.is_admin(user_id):
                return await f(update, context, *args, **kwargs)

            # Canaux \u00e0 v\u00e9rifier
            channels_to_check = channels or config.force_join_channels

            if not channels_to_check:
                return await f(update, context, *args, **kwargs)

            # V\u00e9rifier les abonnements
            from .force_join import ForceJoinManager
            force_join = context.bot_data.get("admin_managers", {}).get("force_join")

            if force_join:
                is_member, missing = await force_join.check_membership(
                    context.bot, user_id, channels_to_check
                )

                if not is_member:
                    await force_join.send_join_message(update, context, missing)
                    return

            return await f(update, context, *args, **kwargs)
        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def private_chat_only(func: Callable):
    """
    D\u00e9corateur pour restreindre une commande aux chats priv\u00e9s.

    Usage:
        @private_chat_only
        async def command(update, context):
            ...
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_chat.type != "private":
            await update.message.reply_text(
                "This command only works in private chat."
            )
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


def group_only(func: Callable):
    """
    D\u00e9corateur pour restreindre une commande aux groupes.

    Usage:
        @group_only
        async def command(update, context):
            ...
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_chat.type == "private":
            await update.message.reply_text(
                "This command only works in groups."
            )
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


# Combinaison de d\u00e9corateurs courants
def protected_command(func: Callable):
    """
    Combinaison: track_user + ban_check + rate_limit + force_join_check

    Usage:
        @protected_command
        async def command(update, context):
            ...
    """
    @wraps(func)
    @track_user
    @ban_check
    @rate_limit
    @force_join_check
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        return await func(update, context, *args, **kwargs)
    return wrapper

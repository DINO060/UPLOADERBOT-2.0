from utils.telegram_checks import is_user_admin


async def require_user_admin_or_die(context, chat_id: int, user_id: int):
    if not await is_user_admin(context, chat_id, user_id):
        raise PermissionError("You are not an admin of this channel.")



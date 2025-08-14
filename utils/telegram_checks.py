from telegram.constants import ChatMemberStatus


async def is_bot_admin(context, chat_id: int) -> bool:
    me = await context.bot.get_me()
    cm = await context.bot.get_chat_member(chat_id, me.id)
    return cm.status == ChatMemberStatus.ADMINISTRATOR


async def is_user_admin(context, chat_id: int, user_id: int) -> bool:
    admins = await context.bot.get_chat_administrators(chat_id)
    return any(a.user.id == user_id for a in admins)


async def resolve_chat_id(context, ident: str) -> int | None:
    ident = (ident or "").strip()
    if ident.startswith("https://t.me/") or ident.startswith("http://t.me/"):
        ident = ident.split("/")[-1]
    if ident.startswith("@"):  # username -> bare
        ident = ident[1:]
    if ident.startswith("-100") and ident[4:].isdigit():
        try:
            return int(ident)
        except Exception:
            pass
    try:
        chat = await context.bot.get_chat(ident)
        return chat.id
    except Exception:
        return None



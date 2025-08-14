from telegram import Update
from telegram.ext import ContextTypes, ChatMemberHandler
from database.channel_repo import upsert_channel

KNOWN_CHANNELS = {}  # tg_chat_id -> {"title":..., "username":...}


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mcm = update.my_chat_member
    if not mcm or mcm.chat.type != "channel":
        return
    chat = mcm.chat
    status = mcm.new_chat_member.status  # administrator | member | left | kicked ...
    bot_is_admin = (status == "administrator")

    upsert_channel(chat.id, chat.title, getattr(chat, "username", None), bot_is_admin)

    if status in ("administrator", "member"):
        KNOWN_CHANNELS[chat.id] = {"title": chat.title or "", "username": getattr(chat, "username", None)}
    else:
        KNOWN_CHANNELS.pop(chat.id, None)


def register_my_chat_member(app):
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))



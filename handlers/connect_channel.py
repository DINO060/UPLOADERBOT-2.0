from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from utils.telegram_checks import is_bot_admin, is_user_admin, resolve_chat_id
from handlers.my_chat_member import KNOWN_CHANNELS
from database.channel_repo import upsert_channel, get_channel_by_tg_id, add_member_if_missing


async def connect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if args:
        ident = " ".join(args)
        chat_id = await resolve_chat_id(context, ident)
        if not chat_id:
            return await update.effective_message.reply_text(
                "❌ I cannot access this channel. Add the bot as an admin first.")
        if not await is_bot_admin(context, chat_id):
            return await update.effective_message.reply_text("❌ Please add the bot as channel administrator first.")
        if not await is_user_admin(context, chat_id, user.id):
            return await update.effective_message.reply_text("❌ You are not an admin of this channel.")

        info = KNOWN_CHANNELS.get(chat_id, {"title": "", "username": None})
        ch = get_channel_by_tg_id(chat_id) or upsert_channel(chat_id, info["title"], info["username"], True)
        add_member_if_missing(ch["id"], user.id)
        return await update.effective_message.reply_text("✅ Channel connected to your account.")

    # No argument: auto-list channels where bot & user are admins
    eligible = []
    for cid, meta in KNOWN_CHANNELS.items():
        try:
            if await is_bot_admin(context, cid) and await is_user_admin(context, cid, user.id):
                eligible.append((cid, meta))
        except Exception:
            pass

    if not eligible:
        return await update.effective_message.reply_text(
            "No channels found where both the bot and you are admins.\n"
            "➡️ Add the bot as a channel admin, then run /connect again.")

    buttons = [[InlineKeyboardButton(f"{m['title'] or m['username'] or cid}", callback_data=f"connect:{cid}")]
               for cid, m in eligible[:25]]
    await update.effective_message.reply_text("Select the channel to connect:", reply_markup=InlineKeyboardMarkup(buttons))


async def connect_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = update.effective_user
    _, cid_str = q.data.split(":")
    chat_id = int(cid_str)

    if not await is_bot_admin(context, chat_id):
        return await q.edit_message_text("❌ The bot is no longer an admin of this channel.")
    if not await is_user_admin(context, chat_id, user.id):
        return await q.edit_message_text("❌ You are not an admin of this channel.")

    info = KNOWN_CHANNELS.get(chat_id, {"title": "", "username": None})
    ch = get_channel_by_tg_id(chat_id) or upsert_channel(chat_id, info["title"], info["username"], True)
    add_member_if_missing(ch["id"], user.id)
    await q.edit_message_text("✅ Channel connected to your account.")


def register_connect(app):
    app.add_handler(CommandHandler("connect", connect_cmd))
    app.add_handler(CallbackQueryHandler(connect_cb, pattern=r"^connect:-?\d+$"))



"""🖼️ A thumbnail per channel (utils/channel_thumbs): ⚙️ Settings → 🌐 Manage channels → a channel → 🖼️ Thumbnail
to set, see or delete it; ✏️ Edit File → 🖼️ Thumbnail to put it on a video or document of the post (the file is
sent again with it, in the background, like a rename).

Callbacks: cthumb_<channel> (the screen), cthumb_add_ / cthumb_view_ / cthumb_del_<channel>, apply_thumb_<index>;
routed before handle_callback answers every button (their alerts need the answer).
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from conversation_states import MAIN_MENU, SETTINGS, WAITING_PUBLICATION_CONTENT
from utils import channel_thumbs

logger = logging.getLogger("UploaderBot")

WAITING_KEY = "awaiting_channel_thumb"


def _screen(user_id: int, channel: str, note: str = ""):
    ch = channel_thumbs.clean(channel)
    has = channel_thumbs.path_for(user_id, ch) is not None
    text = (f"🖼️ Thumbnail of @{ch}\n\n"
            + ("✅ Set. Put it on a video or a document: ✏️ Edit File → 🖼️ Thumbnail." if has
               else "No thumbnail yet. Add one: it can then be put on the videos and documents you post here.")
            + (f"\n\n{note}" if note else ""))
    rows = []
    if has:
        rows.append([InlineKeyboardButton("👁️ See it", callback_data=f"cthumb_view_{ch}")])
        rows.append([InlineKeyboardButton("🔄 Change", callback_data=f"cthumb_add_{ch}", api_kwargs={"style": "primary"}),
                     InlineKeyboardButton("🗑️ Delete", callback_data=f"cthumb_del_{ch}", api_kwargs={"style": "danger"})])
    else:
        rows.append([InlineKeyboardButton("➕ Add a thumbnail", callback_data=f"cthumb_add_{ch}",
                                          api_kwargs={"style": "success"})])
    rows.append([InlineKeyboardButton("↩️ Back", callback_data=f"channel_{ch}")])
    return text, InlineKeyboardMarkup(rows)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> int:
    """cthumb_… buttons."""
    from utils.message_utils import safe_edit_message_text
    query = update.callback_query
    user_id = update.effective_user.id
    if data.startswith("cthumb_view_"):
        ch = data[len("cthumb_view_"):]
        path = channel_thumbs.path_for(user_id, ch)
        if not path:
            await query.answer("No thumbnail for this channel.", show_alert=True)
            return SETTINGS
        await query.answer()
        with open(path, "rb") as fh:
            await context.bot.send_photo(chat_id=query.message.chat_id, photo=fh, caption=f"🖼️ Thumbnail of @{ch}")
        return SETTINGS
    await query.answer()
    if data.startswith("cthumb_add_"):
        ch = data[len("cthumb_add_"):]
        context.user_data[WAITING_KEY] = ch
        await safe_edit_message_text(
            query,
            f"🖼️ Send me the picture for @{ch}, as a photo or as an image file.\n"
            "It is resized for Telegram (320 px).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cthumb_{ch}")]]))
        return SETTINGS
    if data.startswith("cthumb_del_"):
        ch = data[len("cthumb_del_"):]
        channel_thumbs.delete(user_id, ch)
        text, markup = _screen(user_id, ch, "🗑️ Thumbnail deleted.")
        await safe_edit_message_text(query, text, reply_markup=markup)
        return SETTINGS
    ch = data[len("cthumb_"):]
    context.user_data.pop(WAITING_KEY, None)          # « ❌ Cancel » of the picture request lands here
    text, markup = _screen(user_id, ch)
    await safe_edit_message_text(query, text, reply_markup=markup)
    return SETTINGS


async def on_picture(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """The picture asked by « ➕ Add a thumbnail » (any other picture in Settings is left alone)."""
    ch = context.user_data.get(WAITING_KEY)
    message = update.message
    if not ch or message is None:
        return SETTINGS
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        file_id = message.document.file_id
    else:
        await message.reply_text("🖼️ That's not a picture: send a photo or an image file (or ❌ Cancel).")
        return SETTINGS
    try:
        await channel_thumbs.save(context.bot, update.effective_user.id, ch, file_id)
    except Exception as e:
        logger.exception(f"thumbnail of @{ch} not saved: {e}")
        await message.reply_text(f"❌ This picture couldn't be used ({str(e)[:120]}). Try another one.")
        return SETTINGS
    context.user_data.pop(WAITING_KEY, None)
    text, markup = _screen(update.effective_user.id, ch, "✅ Thumbnail saved.")
    await message.reply_text(text, reply_markup=markup)
    return SETTINGS


async def apply_to_post(update: Update, context: ContextTypes.DEFAULT_TYPE, post_index: int) -> int:
    """✏️ Edit File → 🖼️ Thumbnail: the file sent again with its channel's thumbnail."""
    query = update.callback_query
    user_id = update.effective_user.id
    posts = context.user_data.get("posts") or []
    if post_index >= len(posts):
        await query.answer("❌ This file is no longer in the post.", show_alert=True)
        return MAIN_MENU
    post = posts[post_index]
    if post.get("type") not in ("video", "document"):
        await query.answer("🖼️ A thumbnail goes on a video or a document.", show_alert=True)
        return WAITING_PUBLICATION_CONTENT
    if post.get("renaming"):
        await query.answer("⏳ This file is still being sent again: wait a moment.", show_alert=True)
        return WAITING_PUBLICATION_CONTENT
    channel = channel_thumbs.clean(post.get("channel") or (context.user_data.get("selected_channel") or {}).get("username"))
    path = channel_thumbs.path_for(user_id, channel)
    if not path:
        await query.answer()
        from utils.message_utils import safe_edit_message_text
        await safe_edit_message_text(
            query,
            f"🖼️ @{channel} has no thumbnail yet.\n\n"
            f"Add one once: ⚙️ Settings → 🌐 Manage channels → @{channel} → 🖼️ Thumbnail.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Rename instead", callback_data=f"rename_post_{post_index}")]]))
        return WAITING_PUBLICATION_CONTENT
    await query.answer("🖼️ Adding the thumbnail…")
    try:                                              # the Edit File menu: its place is taken by the new preview
        await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
    except Exception:
        pass
    from i18n import get_user_lang
    from handlers.rename_handlers import start_rename
    post["thumb_before"], post["thumb_path"] = post.get("thumb_path"), path
    name = post.get("filename") or ("video.mp4" if post.get("type") == "video" else "file")
    start_rename(context.bot, query.message.chat_id, context.user_data, post_index, post, name,
                 get_user_lang(user_id, getattr(update.effective_user, "language_code", None)), kind="thumb")
    return WAITING_PUBLICATION_CONTENT

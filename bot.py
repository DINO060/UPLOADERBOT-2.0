"""
Telegram Bot for managing publications with reactions and URL buttons
"""

import os
# Configuration de l'encodage pour gérer correctement les emojis
os.environ['PYTHONIOENCODING'] = 'utf-8'

import re
import logging
import asyncio
import sqlite3
import io
import tempfile
import uuid
import shutil
from datetime import datetime, timedelta
from datetime import timezone
from pathlib import Path
import json
from time import perf_counter
from functools import wraps
from typing import Optional, List, Dict, Any, Callable, Awaitable
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
    ApplicationHandlerStop,
)
from dotenv import load_dotenv
# Ensure environment variables from .env are available before reading them below
load_dotenv()
from telegram.error import BadRequest, Forbidden
import pytz
import time
import sys
import platform
# Telethon supprimé: Pyrogram suffit pour le fallback MTProto
import math
from PIL import Image
from database import init_models
from handlers.reaction_handlers import setup_reaction_handlers
from conversation_states import (
    MAIN_MENU, POST_CONTENT, POST_ACTIONS, SEND_OPTIONS, AUTO_DESTRUCTION,
    SCHEDULE_SEND, EDIT_POST, SCHEDULE_SELECT_CHANNEL, STATS_SELECT_CHANNEL,
    WAITING_CHANNEL_INFO, SETTINGS, BACKUP_MENU, WAITING_CHANNEL_SELECTION,
    WAITING_PUBLICATION_CONTENT, WAITING_TIMEZONE, WAITING_THUMBNAIL_RENAME_INPUT,
    WAITING_REACTION_INPUT, WAITING_URL_INPUT, WAITING_RENAME_INPUT,
    WAITING_SCHEDULE_TIME, WAITING_EDIT_TIME,
    WAITING_CUSTOM_USERNAME, WAITING_TAG_INPUT
)
from config import settings
from database.manager import DatabaseManager
from handlers.reaction_functions import (
    handle_reaction_input,
    handle_url_input,
    remove_reactions,
    remove_url_buttons,
    add_reactions_to_post,
    add_url_button_to_post,
)
from utils.scheduler import SchedulerManager
from database.channel_repo import init_db
from handlers.my_chat_member import register_my_chat_member
from handlers.connect_channel import register_connect
# Imports schedule_handler supprimés - utilisation de callback_handlers.py
# Thumbnail handlers removed
from utils.pyro_client import ensure_pyro_started, get_pyro
from handlers.callback_handlers import handle_callback, send_post_now
from handlers.message_handlers import handle_text, handle_media, handle_channel_info, handle_post_content, handle_tag_input
from handlers.reaction_system import handle_reaction_toggle
from handlers.media_handler import send_file_smart
from i18n import SUPPORTED, set_user_lang, get_user_lang, t
from telegram.request import HTTPXRequest
from telegram.ext import ApplicationBuilder

# Import admin_core module
from admin_core import setup_admin, AdminConfig, get_manager

load_dotenv()

# Option pour réduire les httpx.ReadError
request = HTTPXRequest(
    connection_pool_size=100,
    read_timeout=60.0,
)
# --- fin patch ---

# --- config & état (Force-Join & Admin) ---
START_TIME = datetime.now(timezone.utc)

# ADMIN_IDS via env ou config.py (string: "123,456")
try:
    from config import ADMIN_IDS as ADMIN_IDS_STR  # optionnel
except Exception:
    ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")


def _parse_admin_ids(s: str) -> set[int]:
    ids = set()
    for x in (s or "").replace(" ", "").split(","):
        if not x:
            continue
        try:
            ids.add(int(x))
        except ValueError:
            pass
    return ids


ADMIN_IDS: set[int] = _parse_admin_ids(ADMIN_IDS_STR)
try:
    # Fusionner avec la config existante si disponible
    from config import settings as _cfg_settings  # type: ignore
    if hasattr(_cfg_settings, 'admin_ids') and _cfg_settings.admin_ids:
        ADMIN_IDS |= set(int(x) for x in _cfg_settings.admin_ids)
except Exception:
    pass

# Fichier des canaux force-join (dans le même dossier que le bot)
BASE_DIR = Path(__file__).resolve().parent
FJ_PATH = BASE_DIR / "force_join_channels.json"
USERS_DB = BASE_DIR / "users.json"  # optionnel
RENAME_STATS_PATH = BASE_DIR / "rename_stats.json"

# Protection concurrente pour le fichier JSON
fj_lock = asyncio.Lock()
rename_stats_lock = asyncio.Lock()


def _ensure_fj_file():
    if not FJ_PATH.exists():
        FJ_PATH.write_text(json.dumps({"channels": []}, ensure_ascii=False, indent=2))


def _ensure_rename_stats_file():
    if not RENAME_STATS_PATH.exists():
        data = {"total_files_renamed": 0, "total_storage_bytes": 0}
        RENAME_STATS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def load_rename_stats() -> dict:
    _ensure_rename_stats_file()
    try:
        return json.loads(RENAME_STATS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"total_files_renamed": 0, "total_storage_bytes": 0}


async def add_rename_stat(file_size_bytes: int) -> None:
    _ensure_rename_stats_file()
    async with rename_stats_lock:
        try:
            data = json.loads(RENAME_STATS_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {"total_files_renamed": 0, "total_storage_bytes": 0}
        data["total_files_renamed"] = int(data.get("total_files_renamed", 0)) + 1
        inc = int(file_size_bytes or 0)
        data["total_storage_bytes"] = int(data.get("total_storage_bytes", 0)) + max(0, inc)
        RENAME_STATS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_channel(ref: str) -> str:
    """@name -> @name |  -100123 -> -100123 (str)"""
    ref = ref.strip()
    if not ref:
        return ref
    if ref.startswith("@"):    # garder @username
        return ref
    # autoriser ids type -100xxxxxxxxxx (chat id)
    try:
        int(ref)
        return ref
    except ValueError:
        # si l’utilisateur tape "t.me/xxx", extraire @xxx
        if "t.me/" in ref:
            tail = ref.split("t.me/", 1)[1].strip().strip("/")
            if tail and not tail.startswith("@"):
                tail = "@" + tail
            return tail
        return "@" + ref if not ref.startswith("@") else ref


async def load_fj_channels() -> list[str]:
    _ensure_fj_file()
    try:
        data = json.loads(FJ_PATH.read_text(encoding="utf-8"))
        ch = data.get("channels", [])
        # dédoublonner et normaliser
        uniq = []
        seen = set()
        for c in ch:
            nc = _normalize_channel(str(c))
            if nc and nc not in seen:
                seen.add(nc)
                uniq.append(nc)
        return uniq
    except Exception:
        return []


async def save_fj_channels(channels: list[str]) -> None:
    _ensure_fj_file()
    data = {"channels": channels}
    FJ_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# --- utilitaires admin ---
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def require_owner_or_admin(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else 0
    if not is_admin(uid):
        await update.effective_message.reply_text("🚫 Admins only.")
        return False
    return True


# --- commandes admin: /addfsub /delfsub /channels ---
async def add_fsub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner_or_admin(update):
        return
    if not context.args:
        return await update.message.reply_text(
            "Usage: /addfsub <@username|chat_id> [others…]\n"
            "Examples: /addfsub @myChannel  -100123456789  t.me/mychannel"
        )
    refs = [_normalize_channel(a) for a in context.args if a.strip()]
    async with fj_lock:
        cur = await load_fj_channels()
        added = []
        for r in refs:
            if r and r not in cur:
                cur.append(r)
                added.append(r)
        await save_fj_channels(cur)
    if added:
        await update.message.reply_text("✅ Added:\n" + "\n".join(f"• {x}" for x in added))
    else:
        await update.message.reply_text("ℹ️ Nothing to add (already present or invalid).")


async def del_fsub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner_or_admin(update):
        return
    if not context.args:
        return await update.message.reply_text("Usage: /delfsub <@username|chat_id> [autres…]")
    refs = [_normalize_channel(a) for a in context.args if a.strip()]
    async with fj_lock:
        cur = await load_fj_channels()
        removed = []
        keep = []
        to_remove = set(refs)
        for c in cur:
            if c in to_remove:
                removed.append(c)
            else:
                keep.append(c)
        await save_fj_channels(keep)
    if removed:
        await update.message.reply_text("🗑️ Removed:\n" + "\n".join(f"• {x}" for x in removed))
    else:
        await update.message.reply_text("ℹ️ No match.")


async def list_fsubs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner_or_admin(update):
        return
    ch = await load_fj_channels()
    if not ch:
        return await update.message.reply_text("No force-join channels configured.")
    await update.message.reply_text("📋 Force-join:\n" + "\n".join(f"• {x}" for x in ch))


# --- Ban System ---
BANNED_USERS_PATH = BASE_DIR / "data" / "banned_users.json"
ban_lock = asyncio.Lock()

def _ensure_banned_file():
    BANNED_USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not BANNED_USERS_PATH.exists():
        BANNED_USERS_PATH.write_text('{"banned": []}', encoding="utf-8")

async def load_banned_users() -> list[dict]:
    """Load banned users list"""
    _ensure_banned_file()
    try:
        data = json.loads(BANNED_USERS_PATH.read_text(encoding="utf-8"))
        return data.get("banned", [])
    except Exception:
        return []

async def save_banned_users(banned: list[dict]) -> None:
    """Save banned users list"""
    _ensure_banned_file()
    data = {"banned": banned}
    BANNED_USERS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

async def is_user_banned(user_id: int) -> bool:
    """Check if user is banned"""
    banned = await load_banned_users()
    for b in banned:
        if b.get("user_id") == user_id:
            return True
    return False

async def ban_user(user_id: int, reason: str = "No reason", banned_by: int = 0) -> bool:
    """Ban a user"""
    async with ban_lock:
        banned = await load_banned_users()
        # Check if already banned
        for b in banned:
            if b.get("user_id") == user_id:
                return False  # Already banned

        banned.append({
            "user_id": user_id,
            "reason": reason,
            "banned_by": banned_by,
            "banned_at": datetime.now(timezone.utc).isoformat()
        })
        await save_banned_users(banned)
        return True

async def unban_user(user_id: int) -> bool:
    """Unban a user"""
    async with ban_lock:
        banned = await load_banned_users()
        new_banned = [b for b in banned if b.get("user_id") != user_id]
        if len(new_banned) == len(banned):
            return False  # User was not banned
        await save_banned_users(new_banned)
        return True

async def get_banned_user_info(user_id: int) -> dict | None:
    """Get info about a banned user"""
    banned = await load_banned_users()
    for b in banned:
        if b.get("user_id") == user_id:
            return b
    return None


# --- Redirect Buttons System ---
REDIRECT_BUTTONS_PATH = BASE_DIR / "data" / "redirect_buttons.json"
redirect_lock = asyncio.Lock()

def _ensure_redirect_buttons_file():
    REDIRECT_BUTTONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not REDIRECT_BUTTONS_PATH.exists():
        REDIRECT_BUTTONS_PATH.write_text('{"buttons": []}', encoding="utf-8")

async def load_redirect_buttons() -> list[dict]:
    """Load redirect buttons list"""
    _ensure_redirect_buttons_file()
    try:
        data = json.loads(REDIRECT_BUTTONS_PATH.read_text(encoding="utf-8"))
        return data.get("buttons", [])
    except Exception:
        return []

async def save_redirect_buttons(buttons: list[dict]) -> None:
    """Save redirect buttons list"""
    _ensure_redirect_buttons_file()
    data = {"buttons": buttons}
    REDIRECT_BUTTONS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

async def add_redirect_button(text: str, url: str) -> bool:
    """Add a redirect button"""
    async with redirect_lock:
        buttons = await load_redirect_buttons()
        # Check if already exists
        for b in buttons:
            if b.get("text") == text and b.get("url") == url:
                return False
        buttons.append({
            "text": text,
            "url": url,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        await save_redirect_buttons(buttons)
        return True

async def remove_redirect_button(index: int) -> bool:
    """Remove a redirect button by index"""
    async with redirect_lock:
        buttons = await load_redirect_buttons()
        if 0 <= index < len(buttons):
            buttons.pop(index)
            await save_redirect_buttons(buttons)
            return True
        return False

async def get_redirect_buttons_keyboard() -> list[list]:
    """Get redirect buttons as InlineKeyboardButton list for use in messages"""
    buttons = await load_redirect_buttons()
    keyboard = []
    for b in buttons:
        text = b.get("text", "Button")
        url = b.get("url", "")
        if text and url:
            keyboard.append([InlineKeyboardButton(text, url=url)])
    return keyboard


# --- /status (publique) ---
def _uptime_str() -> str:
    delta = datetime.now(timezone.utc) - START_TIME
    d = delta.days
    h, rem = divmod(delta.seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def _safe_read_json_count(p: Path, key: str | None = None) -> int:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if key and isinstance(data, dict) and key in data and isinstance(data[key], list):
            return len(data[key])
        if isinstance(data, (list, dict)):
            return len(data)
    except Exception:
        pass
    return 0


def _format_bytes(num_bytes: float) -> str:
    try:
        num = float(num_bytes or 0)
    except Exception:
        num = 0.0
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while num >= 1024 and idx < len(units) - 1:
        num /= 1024.0
        idx += 1
    return f"{num:.2f} {units[idx]}"


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Measure a simple API call latency as ping
    start = perf_counter()
    try:
        await context.bot.get_me()
    except Exception:
        pass
    ping_ms = (perf_counter() - start) * 1000

    # Users (approx) and channels
    try:
        dbm = DatabaseManager()
        users_count = dbm.get_total_users()
    except Exception:
        users_count = _safe_read_json_count(USERS_DB) if USERS_DB.exists() else 0
    ch_count = len(await load_fj_channels())

    # System stats (optional psutil)
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        ram_line = f"N/A" if not vm else f"{vm.percent:.1f}% ({vm.used/1024/1024/1024:.2f} GB / {vm.total/1024/1024/1024:.2f} GB)"
        cpu_line = f"{psutil.cpu_percent(interval=0.1):.1f}%"
    except Exception:
        ram_line = "N/A"
        cpu_line = "N/A"

    # Disk usage (current drive)
    try:
        current_root = Path.cwd().anchor or str(Path.cwd())
        total_b, used_b, free_b = shutil.disk_usage(current_root)
        used_pct = used_b / total_b * 100 if total_b else 0.0

        # Progress bar of 12 slots
        slots = 12
        filled = int((used_pct / 100) * slots)
        filled = max(0, min(slots, filled))
        bar = "[" + ("■" * filled) + ("□" * (slots - filled)) + "]"

        used_gb = used_b / 1024 / 1024 / 1024
        free_gb = free_b / 1024 / 1024 / 1024
        total_gb = total_b / 1024 / 1024 / 1024
        disk_block = (
            f"┎ DISK :\n"
            f"┃ {bar} {used_pct:.1f}%\n"
            f"┃ Used : {used_gb:.2f} GB\n"
            f"┃ Free : {free_gb:.2f} GB\n"
            f"┖ Total : {total_gb:.2f} GB\n"
        )
    except Exception:
        disk_block = (
            "┎ DISK :\n"
            "┖ N/A\n"
        )

    # Rename statistics (JSON local)
    try:
        stats = await load_rename_stats()
        total_renamed = int(stats.get("total_files_renamed", 0))
        total_storage_used = float(stats.get("total_storage_bytes", 0.0))
    except Exception:
        total_renamed = 0
        total_storage_used = 0.0
    total_storage_used_h = _format_bytes(total_storage_used)

    text = (
        "⌬ BOT STATISTICS :\n\n"
        f"┎ Bᴏᴛ Uᴘᴛɪᴍᴇ : {_uptime_str()}\n"
        f"┃ Cᴜʀʀᴇɴᴛ Pɪɴɢ : {ping_ms:.3f}ms\n"
        f"┖ Tᴏᴛᴀʟ Uꜱᴇʀꜱ: {users_count}\n\n"
        f"┎ RAM ( MEMORY ):\n"
        f"┖ {ram_line}\n\n"
        f"┎ CPU ( USAGE ) :\n"
        f"┖ {cpu_line}\n\n"
        f"{disk_block}"
        f"┎ RENAME STATISTICS :\n"
        f"┃ Files renamed : {total_renamed}\n"
        f"┖ Storage used : {total_storage_used_h}\n"
    )
    await update.message.reply_text(text)


async def forced_channels(context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    """Every channel to join: force_join_channels.json (the admin panel, @djd208) AND admin_core's list (/addfsub,
    which only wrote there: a channel added that way was never checked)."""
    found, seen = [], set()
    sources = list(await load_fj_channels())
    admin_db = context.bot_data.get("admin_db") if context and getattr(context, "bot_data", None) is not None else None
    if admin_db:
        try:
            sources += list(admin_db.get_force_join_channels())
        except Exception as e:
            logger.warning(f"force join: admin_core channels unreadable: {e}")
    for ch in sources:
        ch = _normalize_channel(str(ch))
        key = ch.lower().lstrip("@")
        if ch and key not in seen:
            seen.add(key)
            found.append(ch)
    return found


FJ_ALERT_EVERY = 6 * 3600          # a channel the bot can't check is reported to the admins this often
_fj_alerted: dict[str, float] = {}


async def _fj_alert(context: ContextTypes.DEFAULT_TYPE, ch: str, why: str) -> None:
    if time.time() - _fj_alerted.get(ch, 0) < FJ_ALERT_EVERY:
        return
    _fj_alerted[ch] = time.time()
    text = (f"⚠️ Force join: I can't check who is in {ch} ({why}).\n\n"
            "Until this is fixed, users are NOT checked for this channel.\n"
            "Fix: make this bot an administrator of the channel, then /channels to verify.")
    for admin in ADMIN_IDS:
        try:
            await context.bot.send_message(admin, text)
        except Exception as e:
            logger.warning(f"force join alert to {admin}: {e}")


async def channel_problem(context: ContextTypes.DEFAULT_TYPE, ch: str):
    """None when the bot can check this channel's members (it must be an admin there), else why not."""
    try:
        me = await context.bot.get_chat_member(ch, context.bot.id)
        return None if me.status in ("administrator", "creator") else "I'm not an administrator there"
    except Exception as e:
        return str(e) or type(e).__name__


# --- vérification d'abonnement (utilitaire réutilisable) ---
async def is_user_in_required_channels(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> tuple[bool, list[str]]:
    """
    Returns (ok, missing[]). ok=True if user is a member of ALL required channels.
    A channel the bot can't check (not an admin there, wrong name) used to refuse EVERY user, silently: users now
    pass and the admins are alerted. A network error lets them through too.
    """
    channels = await forced_channels(context)
    if not channels:
        return True, []
    missing = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(ch, user_id)
            status = getattr(member, "status", "")
            # considered member if 'member', 'administrator', 'creator', or 'restricted' but is_member True
            is_member = status in ("member", "administrator", "creator") or getattr(
                member, "is_member", False
            )
            if not is_member:
                missing.append(ch)
        except BadRequest as e:
            if any(k in str(e).lower() for k in ("user not found", "participant_id_invalid", "user_not_participant")):
                missing.append(ch)
            else:
                await _fj_alert(context, ch, str(e))
        except Forbidden as e:
            await _fj_alert(context, ch, str(e))
        except Exception as e:
            logger.warning(f"force join check {ch}: {e}")
    return (len(missing) == 0), missing


async def join_buttons(context: ContextTypes.DEFAULT_TYPE, channels: list[str]) -> InlineKeyboardMarkup:
    """A « Join » button per channel (t.me/name, or the invite link of a private one) and « I have joined »."""
    rows = []
    for ch in channels:
        url = f"https://t.me/{ch.lstrip('@')}" if ch.startswith("@") else None
        if not url:
            try:
                url = (await context.bot.get_chat(ch)).invite_link
            except Exception:
                url = None
        if url:
            rows.append([InlineKeyboardButton(f"📢 Join {ch}", url=url, api_kwargs={"style": "primary"})])
    rows.append([InlineKeyboardButton("✅ I have joined", callback_data="fsub_check", api_kwargs={"style": "success"})])
    return InlineKeyboardMarkup(rows)


async def fsub_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """« ✅ I have joined » (the join message had no button at all)."""
    q = update.callback_query
    ok, missing = await is_user_in_required_channels(context, q.from_user.id)
    if ok:
        await q.answer("✅ Thank you!")
        await q.edit_message_text(
            "✅ You're in! Tap below to start.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Start", callback_data="main_menu",
                                                                      api_kwargs={"style": "success"})]]))
    else:
        await q.answer("❌ You haven't joined all the channels yet.", show_alert=True)
    raise ApplicationHandlerStop


async def channels_overview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/channels and /fsub (admins): every channel really required, and whether the bot can check it."""
    if not is_admin(update.effective_user.id if update.effective_user else 0):
        raise ApplicationHandlerStop
    channels = await forced_channels(context)
    if not channels:
        await update.message.reply_text("No force-join channels configured.")
    else:
        lines = []
        for ch in channels:
            problem = await channel_problem(context, ch)
            lines.append(f"• {ch} — " + ("✅ checked (I'm an admin)" if not problem else f"❌ NOT checked: {problem}"))
        await update.message.reply_text("📋 Force-join channels:\n" + "\n".join(lines)
                                        + "\n\nAdd with /addfsub @channel, remove with /delfsub @channel.")
    raise ApplicationHandlerStop


async def delfsub_everywhere(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/delfsub (admins): removed from both lists (each command used to know only one of them)."""
    if not is_admin(update.effective_user.id if update.effective_user else 0):
        raise ApplicationHandlerStop
    if not context.args:
        await update.message.reply_text("Usage: /delfsub <@username|chat_id> [others…]")
        raise ApplicationHandlerStop
    drop = {_normalize_channel(a).lower().lstrip("@") for a in context.args if a.strip()}
    async with fj_lock:
        cur = await load_fj_channels()
        await save_fj_channels([c for c in cur if c.lower().lstrip("@") not in drop])
    admin_db, admin_config = context.bot_data.get("admin_db"), context.bot_data.get("admin_config")
    for ch in context.args:
        for store in (admin_db, admin_config):
            try:
                if store:
                    store.remove_force_join_channel(_normalize_channel(ch))
            except Exception as e:
                logger.warning(f"/delfsub {ch}: {e}")
    left = await forced_channels(context)
    await update.message.reply_text("🗑️ Done. Channels still required:\n" + ("\n".join(f"• {c}" for c in left) or "none"))
    raise ApplicationHandlerStop


async def require_fsub_or_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Call at the start of sensitive/public commands to enforce f-sub and ban check."""
    user = update.effective_user
    if not user:
        return False

    # Check if user is banned FIRST (using admin_core if available, fallback to local)
    user_is_banned = False
    ban_reason = "No reason provided"

    # Try admin_core database first
    admin_db = context.bot_data.get("admin_db")
    if admin_db:
        try:
            is_banned_result, reason = admin_db.is_banned(user.id)
            if is_banned_result:
                user_is_banned = True
                ban_reason = reason or "No reason provided"
        except Exception:
            pass

    # Fallback to local JSON storage
    if not user_is_banned:
        if await is_user_banned(user.id):
            user_is_banned = True
            ban_info = await get_banned_user_info(user.id)
            ban_reason = ban_info.get('reason', 'No reason provided') if ban_info else 'No reason provided'

    if user_is_banned:
        await update.effective_message.reply_text(
            f"🚫 **You are banned from using this bot.**\n\n"
            f"📝 Reason: {ban_reason}\n\n"
            f"If you believe this is a mistake, contact the administrator.",
            parse_mode="Markdown"
        )
        return False

    # admins bypass f-sub (check both sources)
    admin_config = context.bot_data.get("admin_config")
    if admin_config and admin_config.is_admin(user.id):
        return True
    if is_admin(user.id):
        return True

    ok, missing = await is_user_in_required_channels(context, user.id)
    if ok:
        return True
    links = "\n".join(f"• {x}" for x in missing)
    await update.effective_message.reply_text(
        "🔒 To use the bot, please join these channels, then tap « I have joined »:\n" + links,
        reply_markup=await join_buttons(context, missing)
    )
    return False

# Wrapper pour handle_schedule_time
async def handle_schedule_time_wrapper(update, context):
    """Wrapper pour handle_schedule_time"""
    try:
        from handlers.callback_handlers import handle_schedule_time
        return await handle_schedule_time(update, context)
    except Exception as e:
        logger.error(f"❌ Erreur dans handle_schedule_time_wrapper: {e}")
        return MAIN_MENU

# Configuration des boutons ReplyKeyboard (labels en anglais, compatibilité FR au parsing)
REPLY_KEYBOARD_BUTTONS = ["📋 Preview", "🚀 Send", "🗑️ Delete all", "❌ Cancel"]

# Filtre intelligent pour les boutons ReplyKeyboard
class ReplyKeyboardButtonFilter(filters.MessageFilter):
    def filter(self, message):
        if not message.text:
            return False
        text = message.text.strip().lower()
        # Vérifier si c'est un de nos boutons (FR ou EN, sans tenir compte des emojis)
        keywords = [
            "aperçu", "envoyer", "tout supprimer", "annuler",
            "preview", "send", "delete all", "cancel"
        ]
        return any(keyword in text for keyword in keywords)

reply_keyboard_filter = filters.TEXT & ReplyKeyboardButtonFilter()

# Fonction pour créer le ReplyKeyboard standard
def create_reply_keyboard():
    """Crée le clavier de réponse standard (labels anglais)"""
    reply_keyboard = [
        [KeyboardButton("📋 Preview"), KeyboardButton("🚀 Send")],
        [KeyboardButton("🗑️ Delete all"), KeyboardButton("❌ Cancel")]
    ]
    return ReplyKeyboardMarkup(
        reply_keyboard,
        resize_keyboard=True,
        one_time_keyboard=False
    )

# Handler principal pour TOUS les boutons ReplyKeyboard
async def handle_reply_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère TOUS les boutons ReplyKeyboard de manière intelligente"""
    try:
        user_text = update.message.text.strip()
        
        # Récupérer le contexte
        posts = context.user_data.get("posts", [])
        selected_channel = context.user_data.get('selected_channel', {})
        
        if any(k in user_text.lower() for k in ["aperçu", "preview"]):
            if not posts:
                await update.message.reply_text(
                    "🔍 **Preview unavailable**\n\nNo draft posts are currently being created.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                    ]]),
                    parse_mode='Markdown'
                )
                return MAIN_MENU
            else:
                # Afficher l'aperçu détaillé des posts
                for i, post in enumerate(posts):
                    try:
                        # Message simple comme demandé
                        preview_text = "The post preview sent above.\n\n"
                        preview_text += "You have 1 message in this post:\n"
                        
                        # Déterminer le type d'icône selon le type de fichier
                        if post.get('type') == 'photo':
                            preview_text += "1. 📸 Photo"
                        elif post.get('type') == 'video':
                            preview_text += "1. 📹 Video"
                        elif post.get('type') == 'document':
                            preview_text += "1. 📄 Document"
                        else:
                            preview_text += "1. 📝 Text"
                        
                        # Ajouter l'heure actuelle
                        from datetime import datetime
                        current_time = datetime.now().strftime("%I:%M %p")
                        preview_text += f" {current_time}"
                        
                        if post.get('type') == 'text':
                            await update.message.reply_text(preview_text)
                        else:
                            # Envoyer d'abord le fichier sans caption
                            if post.get('type') == 'photo':
                                await context.bot.send_photo(
                                    chat_id=update.effective_chat.id,
                                    photo=post.get('content')
                                )
                            elif post.get('type') == 'video':
                                await context.bot.send_video(
                                    chat_id=update.effective_chat.id,
                                    video=post.get('content')
                                )
                            elif post.get('type') == 'document':
                                await context.bot.send_document(
                                    chat_id=update.effective_chat.id,
                                    document=post.get('content')
                                )
                            
                            # Puis envoyer le message texte séparément
                            await context.bot.send_message(
                                chat_id=update.effective_chat.id,
                                text=preview_text
                            )
                    except Exception as e:
                        logger.error(f"Preview error for post {i}: {e}")
                        await update.message.reply_text(f"❌ Preview error post {i + 1}")
                
                # Retour au menu principal sans message de synthèse
                return WAITING_PUBLICATION_CONTENT
        
        elif any(k in user_text.lower() for k in ["envoyer", "send"]):
            return await handle_send_button(update, context)
        
        elif any(k in user_text.lower() for k in ["tout supprimer", "delete all"]):
            if not posts:
                await update.message.reply_text(
                    "🗑️ **Trash is empty**\n\nNo posts to delete.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                    ]]),
                    parse_mode='Markdown'
                )
                return MAIN_MENU
            else:
                # Supprimer tous les posts mais garder le canal sélectionné
                context.user_data['posts'] = []
                # Ne pas supprimer le canal : context.user_data.pop('selected_channel', None)
                
                await update.message.reply_text(
                    f"🗑️ **Posts deleted**\n\n{len(posts)} post(s) removed successfully.\n\n📤 Now send your new files:",
                    reply_markup=create_reply_keyboard()
                )
                return WAITING_PUBLICATION_CONTENT
        
        elif any(k in user_text.lower() for k in ["annuler", "cancel"]):
            # Nettoyer toutes les données
            context.user_data.clear()
            
            await update.message.reply_text(
                "❌ **Operation cancelled**\n\nAll temporary data has been cleared.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]]),
                parse_mode='Markdown'
            )
            return MAIN_MENU
        
        # Fallback pour les autres cas
        await update.message.reply_text(
            "❓ **Unknown button**\n\nUse the available buttons below.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU
        
    except Exception as e:
        logger.error(f"Error in handle_reply_keyboard: {e}")
        await update.message.reply_text(
            "❌ An error occurred.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

# -----------------------------------------------------------------------------
# CONFIGURATION DU LOGGING
# -----------------------------------------------------------------------------
def setup_logging():
    """Configure the logging system"""
    # Créer le dossier logs s'il n'existe pas
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # Configuration du logger principal
    logger = logging.getLogger('UploaderBot')
    logger.setLevel(logging.INFO)

    # Handler pour la console avec encodage UTF-8
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    console_handler.stream.reconfigure(encoding='utf-8')  # Configuration de l'encodage UTF-8
    logger.addHandler(console_handler)

    # Handler pour le fichier avec encodage UTF-8
    file_handler = logging.FileHandler('logs/bot.log', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

# Configuration globale
logger = setup_logging()

# --- DB migration: ensure posts table uses 'post_type' instead of legacy 'type'
def run_db_migrations():
    """Ensure posts table uses 'post_type' only, migrating from legacy 'type'."""
    try:
        db_path = None
        try:
            # Prefer structured config
            if hasattr(settings, 'db_config') and isinstance(settings.db_config, dict):
                db_path = settings.db_config.get('path')
            # Fallback legacy path
            if not db_path and hasattr(settings, 'db_path'):
                db_path = settings.db_path
        except Exception:
            pass
        if not db_path:
            db_path = 'bot.db'

        import sqlite3
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(posts)")
            cols_info = cur.fetchall()
            cols = [c[1] for c in cols_info]

            # Case 1: only legacy 'type' exists -> simple rename
            if 'type' in cols and 'post_type' not in cols:
                logger.info("⚙️ Migration DB: renaming column 'type' → 'post_type'")
                cur.execute("ALTER TABLE posts RENAME COLUMN type TO post_type")
                conn.commit()
                logger.info("✅ Migration DB applied: posts.type → posts.post_type")
            # Case 2: both columns exist and legacy 'type' may be NOT NULL -> rebuild table
            elif 'type' in cols and 'post_type' in cols:
                logger.info("⚙️ Migration DB: columns 'type' and 'post_type' coexist, rebuilding 'posts' table")
                cur.execute("BEGIN")
                try:
                    cur.execute("ALTER TABLE posts RENAME TO posts_old")
                    # Recreate target schema without legacy 'type'
                    cur.execute(
                        """
                        CREATE TABLE posts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            channel_id INTEGER NOT NULL,
                            post_type TEXT NOT NULL,
                            content TEXT NOT NULL,
                            caption TEXT,
                            buttons TEXT,
                            reactions TEXT,
                            scheduled_time TIMESTAMP,
                            status TEXT DEFAULT 'pending',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (channel_id) REFERENCES channels (id)
                        )
                        """
                    )
                    # Copy data, preferring non-null post_type, else fallback to legacy type
                    cur.execute(
                        """
                        INSERT INTO posts (id, channel_id, post_type, content, caption, buttons, reactions, scheduled_time, status, created_at)
                        SELECT id, channel_id,
                               COALESCE(NULLIF(post_type, ''), type),
                               content, caption, buttons, reactions, scheduled_time, status, created_at
                        FROM posts_old
                        """
                    )
                    cur.execute("DROP TABLE posts_old")
                    conn.commit()
                    logger.info("✅ Table 'posts' reconstruite sans la colonne legacy 'type'")
                except Exception as rebuild_err:
                    conn.rollback()
                    logger.warning(f"⚠️ Reconstruction de la table 'posts' échouée: {rebuild_err}")
            else:
                logger.info("ℹ️ Schéma DB OK (seulement 'post_type' présent)")

            # Ensure optional columns exist: buttons, reactions, status
            cur.execute("PRAGMA table_info(posts)")
            cols = [c[1] for c in cur.fetchall()]
            try:
                if 'buttons' not in cols:
                    logger.info("⚙️ Migration DB: ajout colonne 'buttons' TEXT")
                    cur.execute("ALTER TABLE posts ADD COLUMN buttons TEXT")
                if 'reactions' not in cols:
                    logger.info("⚙️ Migration DB: ajout colonne 'reactions' TEXT")
                    cur.execute("ALTER TABLE posts ADD COLUMN reactions TEXT")
                if 'status' not in cols:
                    logger.info("⚙️ Migration DB: ajout colonne 'status' TEXT DEFAULT 'pending'")
                    cur.execute("ALTER TABLE posts ADD COLUMN status TEXT DEFAULT 'pending'")
                conn.commit()
            except Exception as add_err:
                logger.warning(f"⚠️ Ajout de colonnes optionnelles échoué/ignoré: {add_err}")
    except Exception as e:
        logger.warning(f"⚠️ Migration DB ignorée/échouée: {e}")

run_db_migrations()
# --- end DB migration

# -----------------------------------------------------------------------------
# RATE LIMITER
# -----------------------------------------------------------------------------
class RateLimiter:
    def __init__(self):
        self.user_timestamps = {}

    async def can_send_message(self, chat_id, user_id, limit=1, per_seconds=1):
        now = time.time()
        key = (chat_id, user_id)
        timestamps = self.user_timestamps.get(key, [])
        # On ne garde que les timestamps récents
        timestamps = [t for t in timestamps if now - t < per_seconds]
        if len(timestamps) < limit:
            timestamps.append(now)
            self.user_timestamps[key] = timestamps
            return True
        return False

rate_limiter = RateLimiter()

# -----------------------------------------------------------------------------
# DEBUG: global callback query logger
# -----------------------------------------------------------------------------
async def _debug_cbq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lightweight logger for all CallbackQuery updates.
    Placed in group=0 to observe flow without blocking other handlers.
    """
    try:
        q = update.callback_query
        if not q:
            return
        data = getattr(q, "data", None)
        user_id = getattr(getattr(q, "from_user", None), "id", None)
        chat_id = getattr(getattr(q, "message", None), "chat", None)
        chat_id = getattr(chat_id, "id", None)
        msg_id = getattr(getattr(q, "message", None), "message_id", None)
        logger.debug(f"CBQ data='{data}' from={user_id} chat={chat_id} msg={msg_id}")
        # Do not answer() here to avoid interfering with real handlers that may answer
    except Exception as e:
        logger.warning(f"_debug_cbq error: {e}")

# -----------------------------------------------------------------------------
# FONCTIONS UTILITAIRES
# -----------------------------------------------------------------------------
def normalize_channel_username(channel_username):
    """
    Normalise le nom d'utilisateur d'un canal en enlevant le @ s'il est présent
    Retourne None si l'entrée est vide ou None
    """
    if not channel_username:
        return None
    return channel_username.lstrip('@') if isinstance(channel_username, str) else None

# Thumbnail table functions removed

# Initialisation de la base de données
db_manager = DatabaseManager()
db_manager.setup_database()

# Initialize SQLAlchemy models
init_models()

# Vérifier et créer la table channel_thumbnails si nécessaire
def ensure_channel_thumbnails_table():
    """S'assure que la table channel_thumbnails existe dans la base de données"""
    try:
        cursor = db_manager.connection.cursor()
        
        # Vérifier si la table existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channel_thumbnails'")
        table_exists = cursor.fetchone() is not None
        
        if not table_exists:
            logger.info("⚠️ Table channel_thumbnails manquante - création en cours...")
            cursor.execute('''
                CREATE TABLE channel_thumbnails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_username TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    thumbnail_file_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel_username, user_id)
                )
            ''')
            db_manager.connection.commit()
            logger.info("✅ Table channel_thumbnails créée avec succès!")
        else:
            logger.info("✅ Table channel_thumbnails existe déjà")
        
        return True
    except Exception as e:
        logger.error(f"❌ Erreur lors de la vérification de la table channel_thumbnails: {e}")
        return False

# Exécuter la vérification
ensure_channel_thumbnails_table()

logger.info(f"Base de données initialisée avec succès")

# -----------------------------------------------------------------------------
# DECORATEURS ET UTILITAIRES
# -----------------------------------------------------------------------------
def admin_only(func):
    @wraps(func)
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in settings.ADMIN_IDS:
            await update.message.reply_text("❌ You don't have the necessary permissions.")
            return
        return await func(update, context, *args, **kwargs)


async def retry_operation(operation, max_retries=3, delay=1):
    for attempt in range(max_retries):
        try:
            return await operation()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Tentative {attempt + 1} échouée: {e}")
            await asyncio.sleep(delay * (attempt + 1))


# -----------------------------------------------------------------------------
# DÉFINITION DES ÉTATS DE LA CONVERSATION
# -----------------------------------------------------------------------------
# Stockage des réactions
reaction_counts = {}

# Variable globale pour le userbot
userbot = None

# Ensemble pour stocker les callbacks déjà traités
processed_callbacks = set()

# Filtres personnalisés
class WaitingForUrlFilter(filters.MessageFilter):
    def filter(self, message):
        if not message.text:
            return False
        context = message.get_bot().application.user_data.get(message.from_user.id, {})
        return context.get('waiting_for_url', False)

class WaitingForReactionsFilter(filters.MessageFilter):
    def filter(self, message):
        if not message.text:
            return False
        context = message.get_bot().application.user_data.get(message.from_user.id, {})
        return context.get('waiting_for_reactions', False)

# Instances des filtres (ancienne classe ReplyKeyboardFilter supprimée - conflit avec la nouvelle)
waiting_for_url_filter = WaitingForUrlFilter()
waiting_for_reactions_filter = WaitingForReactionsFilter()
# reply_keyboard_filter est maintenant défini plus haut avec ReplyKeyboardButtonFilter






# SchedulerManager maintenant importé de schedule_handler


# Téléthon retiré: pas de userbot initialisé


def log_conversation_state(update, context, function_name, state_return):
    """Enregistre les informations d'état de conversation pour débogage"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Reduced verbose state logging

    # Détecter les incohérences potentielles
    if 'conversation_state' in context.user_data and state_return != context.user_data['conversation_state']:
        logger.warning(
            f"[ÉTAT] Incohérence détectée! Retour: {state_return}, Stocké: {context.user_data['conversation_state']}")

    # Mettre à jour l'état stocké
    context.user_data['conversation_state'] = state_return

    return state_return


# Fonction start supprimée - utilise maintenant command_handlers.start dans CommandHandlers

# Fonction create_publication supprimée - utilise maintenant handle_create_publication dans callback_handlers.py


# planifier_post maintenant importé de schedule_handler


# Fonction send_post_now déplacée vers callback_handlers.py pour éviter l'import circulaire
# Elle est maintenant importée depuis callback_handlers


async def handle_set_thumbnail_and_rename(update, context):
    """Applique le thumbnail ET permet de renommer le fichier"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Extraire l'index du post
        post_index = int(query.data.split("_")[-1])
        
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        post = context.user_data['posts'][post_index]
        channel_username = post.get('channel', context.user_data.get('selected_channel', {}).get('username'))
        user_id = update.effective_user.id
        
        # Utiliser la fonction de normalisation
        clean_username = normalize_channel_username(channel_username)
        
        if not clean_username:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Impossible de déterminer le canal cible.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Récupérer et appliquer le thumbnail
        thumbnail_file_id = db_manager.get_thumbnail(clean_username, user_id)
        
        if thumbnail_file_id:
            post['thumbnail'] = thumbnail_file_id
            thumbnail_status = "✅ Thumbnail appliqué"
        else:
            thumbnail_status = "⚠️ Aucun thumbnail enregistré pour ce canal"
        
        # Stocker l'index pour le renommage
        context.user_data['waiting_for_rename'] = True
        context.user_data['current_post_index'] = post_index
        
        # Demander le nouveau nom
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"🖼️✏️ Thumbnail + Renommage\n\n"
                 f"{thumbnail_status}\n\n"
                 f"Maintenant, envoyez-moi le nouveau nom pour votre fichier (avec l'extension).\n"
                 f"Par exemple: mon_document.pdf",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_rename_{post_index}")
            ]])
        )
        
        return WAITING_RENAME_INPUT
        
    except Exception as e:
        logger.error(f"Erreur dans handle_set_thumbnail_and_rename: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

async def handle_view_thumbnail(update, context):
    """Affiche le thumbnail enregistré pour un canal"""
    query = update.callback_query
    await query.answer()
    
    channel_username = context.user_data.get('custom_channel')
    if not channel_username:
        selected_channel = context.user_data.get('selected_channel', {})
        channel_username = selected_channel.get('username')
    
    if not channel_username:
        await query.edit_message_text(
            "❌ Aucun canal sélectionné.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Back", callback_data="custom_settings")
            ]])
        )
        return SETTINGS
    
    user_id = update.effective_user.id
    clean_username = normalize_channel_username(channel_username)
    
    thumbnail_file_id = db_manager.get_thumbnail(clean_username, user_id)
    
    if thumbnail_file_id:
        try:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=thumbnail_file_id,
                caption=f"🖼️ Thumbnail actuel pour @{clean_username}"
            )
            
            keyboard = [
                [InlineKeyboardButton("🔄 Change", callback_data="add_thumbnail")],
                [InlineKeyboardButton("🗑️ Delete", callback_data="delete_thumbnail")],
                [InlineKeyboardButton("↩️ Back", callback_data="thumbnail_menu")]
            ]
            
            await query.message.reply_text(
                "What would you like to do with this thumbnail?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Error displaying thumbnail: {e}")
            await query.edit_message_text(
                "❌ Unable to display thumbnail.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Back", callback_data="thumbnail_menu")
                ]])
            )
    else:
        await query.edit_message_text(
            "❌ No thumbnail saved for this channel.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Back", callback_data="thumbnail_menu")
            ]])
        )
    
    return SETTINGS

async def handle_delete_thumbnail(update, context):
    """Supprime le thumbnail enregistré pour un canal"""
    query = update.callback_query
    await query.answer()
    
    channel_username = context.user_data.get('custom_channel')
    if not channel_username:
        selected_channel = context.user_data.get('selected_channel', {})
        channel_username = selected_channel.get('username')
    
    if not channel_username:
        await query.edit_message_text(
            "❌ Aucun canal sélectionné.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Back", callback_data="custom_settings")
            ]])
        )
        return SETTINGS
    
    user_id = update.effective_user.id
    clean_username = normalize_channel_username(channel_username)
    
    if db_manager.delete_thumbnail(clean_username, user_id):
        await query.edit_message_text(
            f"✅ Thumbnail supprimé pour @{clean_username}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Back", callback_data="thumbnail_menu")
            ]])
        )
    else:
        await query.edit_message_text(
            "❌ Error deleting thumbnail.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Back", callback_data="thumbnail_menu")
            ]])
        )
    
    return SETTINGS

async def handle_rename_input(update, context):
    """New name of a file: handlers/rename_handlers sends the file again under that name (it used to change
    only the preview: the channel got the old file, old name, old caption)."""
    from handlers.rename_handlers import handle_rename_input as rename_input
    return await rename_input(update, context)


async def handle_thumbnail_rename_input(update, context):
    """Gère la saisie du nouveau nom - fonction simplifiée sans thumbnails"""
    try:
        # Cette fonction est conservée pour la compatibilité, redirige vers handle_rename_input
        return await handle_rename_input(update, context)
    
    except Exception as e:
        logger.error(f"Erreur dans handle_thumbnail_rename_input: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[ 
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

async def handle_add_thumbnail_and_rename(update, context):
    """Gère le bouton 'Add Thumbnail + Rename' - reproduit la fonctionnalité du renambot"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Extraire l'index du post
        post_index = int(query.data.split("_")[-1])
        
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        post = context.user_data['posts'][post_index]
        channel_username = post.get('channel', context.user_data.get('selected_channel', {}).get('username'))
        user_id = update.effective_user.id
        
        # Utiliser la fonction de normalisation
        clean_username = normalize_channel_username(channel_username)
        
        if not clean_username:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Impossible de déterminer le canal cible.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Récupérer le thumbnail
        db_manager = DatabaseManager()
        thumbnail_file_id = db_manager.get_thumbnail(clean_username, user_id)
        
        if not thumbnail_file_id:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ **Aucun thumbnail enregistré**\n\n"
                     f"Aucun thumbnail trouvé pour @{clean_username}.\n"
                     f"Veuillez d'abord configurer un thumbnail dans les paramètres.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⚙️ Settings", callback_data="settings", api_kwargs={"style": "primary"}),
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Créer la carte MEDIA INFO exactement comme dans le renambot
        file_type = post.get('type', 'unknown')
        file_content = post.get('content', '')
        file_caption = post.get('caption', '')
        filename = post.get('filename', 'unnamed_file')
        file_size = post.get('file_size', 'Unknown')
        extension = os.path.splitext(filename)[1] or "Unknown"
        mime_type = post.get('mime_type', 'Unknown')
        dc_id = post.get('dc_id', 'N/A')
        
        info_card = f"""📁 <b>MEDIA INFO</b>

📁 <b>FILE NAME:</b> <code>{filename}</code>
🧩 <b>EXTENSION:</b> <code>{extension}</code>
📦 <b>FILE SIZE:</b> {file_size}
🪄 <b>MIME TYPE:</b> {mime_type}
🧭 <b>DC ID:</b> {dc_id}

<b>PLEASE ENTER THE NEW FILENAME WITH EXTENSION AND REPLY THIS MESSAGE.</b>"""
        
        # Stocker l'index pour le traitement thumbnail+rename
        context.user_data['awaiting_thumb_rename'] = True
        context.user_data['current_post_index'] = post_index
        
        # Envoyer le message et stocker l'ID
        ask_msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=info_card,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_thumbnail_rename_{post_index}")
            ]])
        )
        
        # Stocker l'ID du message pour la validation des réponses
        context.user_data['thumbnail_rename_prompt_message_id'] = ask_msg.message_id
        context.user_data['rename_prompt_message_id'] = ask_msg.message_id
        context.user_data['rename_prompt_chat_id'] = query.message.chat_id
        
        return WAITING_THUMBNAIL_RENAME_INPUT
        
    except Exception as e:
        logger.error(f"Erreur dans handle_add_thumbnail_and_rename: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

def is_valid_channel_username(username):
    """
    Vérifie que le username commence par @ ou t.me/ et ne contient pas d'espaces
    """
    if not username:
        return False
    username = username.strip()
    return (username.startswith('@') or username.startswith('t.me/')) and ' ' not in username


def clean_channel_username(username):
    """
    Nettoie le username du canal en enlevant les préfixes @ et t.me/
    """
    if not username:
        return None
    username = username.strip()
    if username.startswith('@'):
        return username[1:]
    elif username.startswith('t.me/'):
        return username[5:]
    return username

async def download_and_upload_with_thumbnail(context, file_id, new_filename, thumbnail_path, chat_id, post_type):
    """
    Télécharge un fichier et le re-upload avec thumbnail et nouveau nom
    """
    import tempfile
    import shutil
    import uuid
    
    temp_file = None
    progress_msg = None
    
    try:
        # Créer un nom de fichier temporaire unique
        temp_filename = f"temp_{uuid.uuid4().hex[:8]}"
        temp_file = os.path.join(tempfile.gettempdir(), temp_filename)
        
        # Message de progression
        progress_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="🖼️ **Traitement avec thumbnail...**"
        )
        
        # Étape 1: Télécharger le fichier
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=progress_msg.message_id,
            text="📥 **Téléchargement du fichier...**"
        )
        
        # Télécharger le fichier
        file_info = await context.bot.get_file(file_id)
        downloaded_path = await file_info.download_to_drive(temp_file)
        
        if not downloaded_path or not os.path.exists(downloaded_path):
            raise Exception("Échec du téléchargement du fichier")
        
        # Étape 2: Upload avec thumbnail
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=progress_msg.message_id,
            text="📤 **Upload avec thumbnail...**"
        )
        
        # Envoyer selon le type
        if post_type == 'photo':
            sent_message = await context.bot.send_photo(
                chat_id=chat_id,
                photo=open(downloaded_path, 'rb'),
                caption=f"<code>{new_filename}</code>",
                parse_mode="HTML",
                filename=new_filename
            )
        elif post_type == 'video':
            sent_message = await context.bot.send_video(
                chat_id=chat_id,
                video=open(downloaded_path, 'rb'),
                caption=f"<code>{new_filename}</code>",
                parse_mode="HTML",
                filename=new_filename,
                thumbnail=open(thumbnail_path, 'rb') if os.path.exists(thumbnail_path) else None
            )
        elif post_type == 'document':
            sent_message = await context.bot.send_document(
                chat_id=chat_id,
                document=open(downloaded_path, 'rb'),
                caption=f"<code>{new_filename}</code>",
                parse_mode="HTML",
                filename=new_filename,
                thumbnail=open(thumbnail_path, 'rb') if os.path.exists(thumbnail_path) else None
            )
        else:
            # Type par défaut: document
            sent_message = await context.bot.send_document(
                chat_id=chat_id,
                document=open(downloaded_path, 'rb'),
                caption=f"<code>{new_filename}</code>",
                parse_mode="HTML",
                filename=new_filename,
                thumbnail=open(thumbnail_path, 'rb') if os.path.exists(thumbnail_path) else None
            )
        
        # Supprimer le message de progression
        await context.bot.delete_message(chat_id=chat_id, message_id=progress_msg.message_id)
        
        return sent_message
        
    except Exception as e:
        logger.error(f"Erreur dans download_and_upload_with_thumbnail: {e}")
        if progress_msg:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_msg.message_id,
                    text=f"❌ **Erreur lors du traitement**\n\n{str(e)}"
                )
            except:
                pass
        raise e
    finally:
        # Nettoyer le fichier temporaire
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass


async def remove_reactions(update, context):
    """Supprime les réactions d'un message"""
    try:
        if not update.callback_query:
            return
        message = update.callback_query.message
        if not message:
            await update.callback_query.answer("Message non trouvé")
            return
        message_id = message.message_id
        chat_id = message.chat_id
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None
            )
            await update.callback_query.answer("✅ Réactions supprimées")
        except Exception as e:
            logger.error(f"Erreur lors de la suppression des réactions: {e}")
            await update.callback_query.answer("❌ Erreur lors de la suppression des réactions")
    except Exception as e:
        logger.error(f"Erreur dans remove_reactions: {e}")
        if update.callback_query:
            await update.callback_query.answer("❌ Une erreur est survenue")


async def remove_url_buttons(update, context):
    """Supprime les boutons URL d'un message"""
    try:
        if not update.callback_query:
            return
        message = update.callback_query.message
        if not message:
            await update.callback_query.answer("Message non trouvé")
            return
        message_id = message.message_id
        chat_id = message.chat_id
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None
            )
            await update.callback_query.answer("✅ Boutons URL supprimés")
        except Exception as e:
            logger.error(f"Erreur lors de la suppression des boutons URL: {e}")
            await update.callback_query.answer("❌ Erreur lors de la suppression des boutons URL")
    except Exception as e:
        logger.error(f"Erreur dans remove_url_buttons: {e}")
        if update.callback_query:
            await update.callback_query.answer("❌ Une erreur est survenue")


async def send_preview_file(update, context, post_index):
    """Envoie une prévisualisation du fichier à l'utilisateur"""
    try:
        posts = context.user_data.get("posts", [])
        if not posts or post_index >= len(posts):
            await update.callback_query.answer("❌ Aucun fichier trouvé")
            return
        post = posts[post_index]
        file_id = post.get("file_id")
        file_name = post.get("file_name", "fichier")
        file_size = post.get("file_size", 0)
        caption = post.get("caption", "")
        if not file_id:
            await update.callback_query.answer("❌ Fichier non trouvé")
            return
        preview_text = (
            f"📁 Prévisualisation du fichier {post_index + 1}/{len(posts)}\n\n"
            f"📝 Nom: {file_name}\n"
            f"📊 Taille: {file_size / 1024 / 1024:.2f} MB\n"
        )
        if caption:
            preview_text += f"\n📝 Légende: {caption}"
        try:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file_id,
                caption=preview_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_file_{post_index}")],
                    [InlineKeyboardButton("📝 Edit Caption", callback_data=f"edit_caption_{post_index}")]
                ])
            )
            await update.callback_query.answer("✅ Prévisualisation envoyée")
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi de la prévisualisation: {e}")
            await update.callback_query.answer("❌ Erreur lors de l'envoi de la prévisualisation")
    except Exception as e:
        logger.error(f"Erreur dans send_preview_file: {e}")
        if update.callback_query:
            await update.callback_query.answer("❌ Une erreur est survenue")

async def cleanup(application):
    """Nettoie les ressources avant l'arrêt du bot"""
    try:
        # Arrêter proprement les clients Pyrogram utilisés pour gros fichiers
        try:
            from utils.clients import client_manager
            await client_manager.stop_clients()
        except Exception as e:
            logger.warning(f"⚠️ Erreur lors de l'arrêt des clients avancés: {e}")
        
        # Fermer la connexion à la base de données
        try:
            if db_manager:
                db_manager.close()
        except:
            pass
        
        # Aucun client Telethon à arrêter
        
        # Arrêter le scheduler depuis l'application
        try:
            if application.bot_data.get('scheduler_manager'):
                application.bot_data['scheduler_manager'].stop()
        except:
            pass
        
        logger.info("✅ Nettoyage effectué avec succès")
    except Exception as e:
        logger.error(f"❌ Erreur lors du nettoyage: {e}")

# -----------------------------------------------------------------------------
# COMMANDE D'URGENCE POUR RE-LIER UN POST
# -----------------------------------------------------------------------------

async def cmd_bindchannel(update, context):
    """Commande d'urgence pour re-lier un post à un canal"""
    try:
        args = context.args if hasattr(context, "args") else update.text.split()[1:]
        if len(args) < 2:
            await update.message.reply_text("Usage: /bindchannel <post_id> <@username|id>")
            return
        
        post_id = int(args[0])
        channel_ref = args[1]
        
        # Résoudre l'ID + valider l'accès
        try:
            chat = await context.bot.get_chat(channel_ref)  # accepte @username ou -100id
        except Exception as e:
            await update.message.reply_text(f"❌ Unable to access {channel_ref}: {e}")
            return

        channel_id = chat.id
        channel_username = getattr(chat, "username", None)

        # (Optionnel) vérifier que le bot est admin
        try:
            member = await context.bot.get_chat_member(chat.id, (await context.bot.get_me()).id)
            if not (member.can_post_messages or member.status in ("administrator", "creator")):
                await update.message.reply_text("❌ Le bot n'a pas les droits pour publier dans ce canal.")
                return
        except Exception:
            pass

        # MAJ DB
        import sqlite3
        with sqlite3.connect('bot.db') as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE posts SET channel_id = ? WHERE id = ?", (channel_id, post_id))
            conn.commit()
            
            # Vérifier que la mise à jour a fonctionné
            cursor.execute("SELECT channel_id FROM posts WHERE id = ?", (post_id,))
            result = cursor.fetchone()
            if result and result[0] == channel_id:
                await update.message.reply_text(f"✅ Post {post_id} linked to {channel_username or channel_id}.\nYou can reopen the send menu.")
            else:
                await update.message.reply_text(f"❌ Error updating post {post_id}.")
                
    except ValueError:
        await update.message.reply_text("❌ Post ID invalide. Utilisez un nombre.")
    except Exception as e:
        logger.error(f"❌ Erreur dans cmd_bindchannel: {e}")
        await update.message.reply_text(f"❌ Erreur: {e}")

# -----------------------------------------------------------------------------
# GESTION SIMPLE DU BOUTON "ENVOYER" - UTILISE LES FONCTIONS EXISTANTES
# -----------------------------------------------------------------------------

async def handle_send_button(update, context):
    """Gère le bouton 'Envoyer' du ReplyKeyboard en utilisant les fonctions existantes"""
    try:
        # ReplyKeyboard 'Send' pressed
        
        # Vérifier si un post planifié est sélectionné
        if 'current_scheduled_post' in context.user_data:
            # scheduled post detected
            scheduled_post = context.user_data['current_scheduled_post']
            return await send_post_now(update, context, scheduled_post=scheduled_post)
        
        # Vérifier s'il y a des posts en attente
        posts = context.user_data.get("posts", [])
        if not posts:
            await update.message.reply_text(
                "❌ There are no files to send yet.\n"
                "Please add content first (text, photo, video, document).",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📝 New post", callback_data="create_publication", api_kwargs={"style": "success"})
                ], [
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return WAITING_PUBLICATION_CONTENT
        
        # ✅ VALIDATION - Vérifier que les posts existent en base de données et ont un canal
        try:
            from handlers.callback_handlers import ensure_post_has_channel
            import sqlite3
            
            valid_posts = []
            for post in posts:
                if 'id' in post:
                    # Vérifier que le post existe et a un canal
                    ok, reason, channel = await ensure_post_has_channel('bot.db', post['id'], update.effective_user.id)
                    if ok:
                        valid_posts.append(post)
                        logger.info(f"✅ Post {post['id']} validated with channel: {channel}")
                    else:
                        logger.warning(f"⚠️ Post {post['id']} validation failed: {reason}")
                else:
                    # Post sans ID (nouveau), on le garde
                    valid_posts.append(post)
            
            posts = valid_posts
            context.user_data['posts'] = posts
            
        except Exception as e:
            logger.error(f"❌ Error validating posts in database: {e}")
        
        # Vérifier à nouveau après nettoyage
        if not posts:
            await update.message.reply_text(
                "❌ No valid posts found.\n"
                "Please create new content.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📝 New post", callback_data="create_publication", api_kwargs={"style": "success"})
                ], [
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return WAITING_PUBLICATION_CONTENT
        
        # Obtenir les informations du canal
        selected_channel = context.user_data.get('selected_channel', {})
        channel = posts[0].get("channel") or selected_channel.get('username', '@default_channel')
        
        # ✅ VALIDATION DU CANAL - Vérifier que le canal est valide
        if not channel or channel == '@default_channel' or not selected_channel:
            logger.warning(f"⚠️ No valid channel found for posts. Channel: {channel}, Selected: {selected_channel}")
            await update.message.reply_text(
                "⚠️ **Aucun canal n'est sélectionné pour ce post.**\n\n"
                "👉 Veuillez d'abord sélectionner un canal, puis réessayez.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📺 Choose channel", callback_data="choose_channel")],
                    [InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")]
                ])
            )
            return WAITING_PUBLICATION_CONTENT
        
        # Utiliser les MÊMES boutons que dans schedule_handler.py
        keyboard = [
            [InlineKeyboardButton("Set auto-destruction time", callback_data="auto_destruction")],
            [InlineKeyboardButton("Send now", callback_data="send_now")],
            [InlineKeyboardButton("Schedule", callback_data="schedule_send")],
            [InlineKeyboardButton("↩️ Back", callback_data="main_menu")]
        ]
        
        # Message identique à celui de schedule_handler.py
        message = f"Your {len(posts)} files are ready to be sent to {channel}.\nWhen would you like to send them?"
        
        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        logger.info(f"Send menu displayed for {len(posts)} files to {channel}")
        return WAITING_PUBLICATION_CONTENT
        
    except Exception as e:
        logger.error(f"Error in handle_send_button: {e}")
        await update.message.reply_text(
            "❌ An error occurred while preparing to send.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


def analyze_posts_content(posts):
    """Analyse et résume le contenu des posts"""
    try:
        type_counts = {
            "photo": 0,
            "video": 0,
            "document": 0,
            "text": 0
        }
        
        total_reactions = 0
        total_buttons = 0
        
        for post in posts:
            post_type = post.get("type", "unknown")
            if post_type in type_counts:
                type_counts[post_type] += 1
            
            # Compter les réactions et boutons
            reactions = post.get("reactions", [])
            buttons = post.get("buttons", [])
            total_reactions += len(reactions)
            total_buttons += len(buttons)
        
        # Construire le résumé
        summary_parts = []
        total_files = sum(type_counts.values())
        
        if total_files == 1:
            # Un seul fichier
            for file_type, count in type_counts.items():
                if count > 0:
                    type_names = {
                        "photo": "📸 Photo",
                        "video": "🎥 Vidéo", 
                        "document": "📄 Document",
                        "text": "📝 Texte"
                    }
                    summary_parts.append(type_names.get(file_type, f"{file_type}"))
                    break
        else:
            # Plusieurs fichiers
            summary_parts.append(f"{total_files} fichiers")
            if type_counts["photo"] > 0:
                summary_parts.append(f"{type_counts['photo']} photo(s)")
            if type_counts["video"] > 0:
                summary_parts.append(f"{type_counts['video']} vidéo(s)")
            if type_counts["document"] > 0:
                summary_parts.append(f"{type_counts['document']} document(s)")
            if type_counts["text"] > 0:
                summary_parts.append(f"{type_counts['text']} texte(s)")
        
        # Ajouter les extras
        extras = []
        if total_reactions > 0:
            extras.append(f"{total_reactions} réaction(s)")
        if total_buttons > 0:
            extras.append(f"{total_buttons} bouton(s) URL")
        
        result = ", ".join(summary_parts)
        if extras:
            result += f" + {', '.join(extras)}"
            
        return result
        
    except Exception as e:
        logger.error(f"Erreur dans analyze_posts_content: {e}")
        return f"{len(posts)} fichier(s)"

def main():
    """Fonction principale du bot"""
    try:
        # Configuration de l'application avec Pyrogram global
        # Vérifier que le token est bien défini
        if not hasattr(settings, 'BOT_TOKEN') or not settings.BOT_TOKEN:
            raise ValueError("Le token du bot n'est pas défini dans les paramètres")
            
        application = (
            ApplicationBuilder()
            .token(settings.BOT_TOKEN)
            .request(request)
            .build()
        )
        # Init DB (channel repository)
        try:
            init_db()
        except Exception as _:
            pass

        # Ajout de logs pour le démarrage
        logger.info("🚀 Démarrage du bot...")
        logger.info(f"📱 Version Python: {platform.python_version()}")
        logger.info(f"💻 Système: {platform.system()} {platform.release()}")

        # Initialisation des compteurs de réactions globaux
        application.bot_data['reaction_counts'] = {}

        # ============================================================
        # INTÉGRATION ADMIN_CORE
        # ============================================================
        # Créer la configuration admin depuis les variables d'environnement
        admin_config = AdminConfig.from_env()

        # Fusionner avec les ADMIN_IDS déjà parsés
        for admin_id in ADMIN_IDS:
            if admin_id not in admin_config.admin_ids:
                admin_config.admin_ids.append(admin_id)

        # Initialiser admin_core et obtenir les managers
        admin_managers = setup_admin(application, admin_config)
        logger.info(f"✅ Admin Core initialisé avec {len(admin_config.admin_ids)} admin(s)")
        logger.info(f"   Managers actifs: {', '.join(admin_managers.keys())}")
        # ============================================================

        # Initialisation du scheduler (créer seulement, ne pas démarrer encore)
        application.bot_data['scheduler_manager'] = SchedulerManager()
        logger.info("✅ Scheduler manager créé avec succès")
        
        # Définir le scheduler manager global pour les callbacks
        from handlers.callback_handlers import set_global_scheduler_manager
        set_global_scheduler_manager(application.bot_data['scheduler_manager'])
        
        # Définir l'application globale pour les tâches planifiées
        from utils.scheduler_utils import set_global_application
        set_global_application(application)
        
        # ✅ CORRECTION : Définir aussi le scheduler manager dans scheduler_utils
        from utils.scheduler_utils import set_global_scheduler_manager as set_scheduler_utils_manager
        set_scheduler_utils_manager(application.bot_data['scheduler_manager'])

        # Fonction d'initialisation post-startup pour démarrer le scheduler
        async def post_init(app: Application) -> None:
            """Initialisation après le démarrage de l'application"""
            try:
                # Démarrer Pyrogram en tâche de fond (singleton)
                asyncio.create_task(ensure_pyro_started())
                
                # Attendre Pyrogram et enregistrer les handlers de réactions côté Pyrogram
                try:
                    pyro_client = await get_pyro()
                    if pyro_client:
                        await setup_reaction_handlers(pyro_client)
                    else:
                        logger.warning("⚠️ Pyrogram indisponible: handlers de réactions non enregistrés")
                except Exception as rh_err:
                    logger.warning(f"⚠️ Enregistrement des handlers de réactions échoué: {rh_err}")
                # Démarrer le scheduler maintenant que l'event loop est actif
                app.bot_data['scheduler_manager'].start()
                logger.info("✅ Scheduler démarré avec succès")
                
                # Vérifier que le scheduler fonctionne
                logger.info(f"🔍 Scheduler running: {app.bot_data['scheduler_manager'].scheduler.running}")
                logger.info(f"🔍 Scheduler state: {app.bot_data['scheduler_manager'].scheduler.state}")
                
                # Nettoyer TOUS les jobs orphelins avant de restaurer (aggressif)
                try:
                    scheduler = app.bot_data['scheduler_manager'].scheduler
                    
                    # Obtenir tous les IDs de posts valides
                    with sqlite3.connect(settings.db_config["path"]) as conn:
                        cursor = conn.cursor()
                        cursor.execute('SELECT id FROM posts')
                        valid_post_ids = {str(row[0]) for row in cursor.fetchall()}
                    
                    # Supprimer tous les jobs qui ne correspondent pas à des posts valides
                    jobs_to_remove = []
                    for job in scheduler.get_jobs():
                        job_id = job.id
                        should_remove = False
                        
                        if job_id.startswith('post_'):
                            post_id = job_id.replace('post_', '')
                            if post_id not in valid_post_ids:
                                should_remove = True
                        elif job_id.isdigit():
                            if job_id not in valid_post_ids:
                                should_remove = True
                        
                        if should_remove:
                            jobs_to_remove.append(job_id)
                    
                    # Supprimer les jobs orphelins
                    removed_count = 0
                    for job_id in jobs_to_remove:
                        try:
                            scheduler.remove_job(job_id)
                            removed_count += 1
                            logger.info(f"🧹 Removed orphaned job: {job_id}")
                        except Exception as job_err:
                            logger.warning(f"⚠️ Failed to remove job {job_id}: {job_err}")
                    
                    if removed_count > 0:
                        logger.info(f"🧹 {removed_count} job(s) orphelin(s) supprimé(s)")
                    else:
                        logger.info("✅ No orphaned jobs found")
                        
                except Exception as e:
                    logger.warning(f"⚠️ Erreur lors du nettoyage des jobs orphelins: {e}")
                
                # Restaurer les posts planifiés (in order; the ones missed while the bot was off go out now)
                try:
                    from utils.scheduler_utils import restore_scheduled_posts
                    await restore_scheduled_posts(app)
                except Exception as restore_err:
                    logger.exception(f"❌ Erreur lors de la restauration des posts planifiés: {restore_err}")
                
                # Planifier les tâches de maintenance
                await schedule_maintenance_tasks(app)

                # Pyrogram est maintenant démarré automatiquement via ensure_pyro_started()
                logger.info("✅ Client Pyrogram géré automatiquement (singleton)")
                
                # A real update is announced once (whatsnew.txt) and deleted after 6 h; a plain restart tells only
                # the admins. It replaces « 🟢 Bot started! » sent to every user at EVERY start.
                from utils.whats_new import announce_update, update_cleanup_loop
                asyncio.create_task(announce_update(app, settings.db_config["path"], ADMIN_IDS,
                                                    forced_channels, channel_problem))
                asyncio.create_task(update_cleanup_loop(app.bot))
                
            except Exception as e:
                logger.error(f"Erreur lors de l'initialisation post-startup: {e}")
                raise
        
        # Ajouter le callback post_init
        application.post_init = post_init

        # Fonction pour planifier les tâches de maintenance 
        async def schedule_maintenance_tasks(app: Application):
            """Planifie les tâches de maintenance automatique"""
            try:
                from utils.file_manager import FileManager
                file_manager = FileManager()
                
                # Fonction de nettoyage
                def cleanup_old_files_job():
                    try:
                        logger.info("🧹 Début du nettoyage automatique des vieux fichiers...")
                        deleted_count = file_manager.cleanup_old_files(max_age_days=7)
                        logger.info(f"✅ {deleted_count} fichiers supprimés")
                    except Exception as e:
                        logger.error(f"❌ Erreur lors du nettoyage des fichiers: {e}")
                
                # Planifier le nettoyage tous les jours à 3h du matin
                app.bot_data['scheduler_manager'].scheduler.add_job(
                    func=cleanup_old_files_job,
                    trigger="cron",
                    hour=3,
                    minute=0,
                    id="cleanup_old_files",
                    replace_existing=True
                )
                logger.info("✅ Tâche de nettoyage automatique planifiée (tous les jours à 3h)")
                
                # Exécuter un nettoyage immédiat au démarrage
                cleanup_old_files_job()
                
            except Exception as e:
                logger.warning(f"⚠️ Impossible de planifier le nettoyage automatique: {e}")

        # Pyrogram est maintenant géré globalement via _post_init et _post_shutdown

        # Log des états de conversation pour débogage
        logger.info(f"Définition des états de conversation:")
        logger.info(f"MAIN_MENU = {MAIN_MENU}")
        logger.info(f"POST_CONTENT = {POST_CONTENT}")
        logger.info(f"POST_ACTIONS = {POST_ACTIONS}")
        logger.info(f"WAITING_PUBLICATION_CONTENT = {WAITING_PUBLICATION_CONTENT}")
        logger.info(f"WAITING_REACTION_INPUT = {WAITING_REACTION_INPUT}")
        logger.info(f"WAITING_URL_INPUT = {WAITING_URL_INPUT}")

        # Aucun userbot Telethon

        # Initialiser les command handlers
        from handlers.command_handlers import CommandHandlers
        
        # ✅ CORRECTION : ScheduledTasks supprimé - utiliser None
        command_handlers = CommandHandlers(db_manager, None)

        # --- Enregistrement des handlers admin/public supplémentaires ---
        application.add_handler(CommandHandler("addfsub", add_fsub, filters=filters.User(ADMIN_IDS)))
        application.add_handler(CommandHandler("delfsub", del_fsub, filters=filters.User(ADMIN_IDS)))
        application.add_handler(CommandHandler("channels", list_fsubs, filters=filters.User(ADMIN_IDS)))
        application.add_handler(CommandHandler("status", status_cmd))
        application.add_handler(CommandHandler("bindchannel", cmd_bindchannel, filters=filters.User(ADMIN_IDS)))
        
        # Language handlers
        LANG_CB_PREFIX = "lang:"  # ex: "lang:fr"

        async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle /language command to change bot language"""
            user = update.effective_user
            current_lang = get_user_lang(user.id, user.language_code)
            
            buttons = [
                [InlineKeyboardButton(f"{meta['flag']} {meta['name']}", callback_data=LANG_CB_PREFIX + code)]
                for code, meta in SUPPORTED.items()
            ]
            
            await update.effective_message.reply_text(
                t(current_lang, "buttons.choose_language"),
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        async def cb_set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle language selection callback"""
            query = update.callback_query
            await query.answer()
            user = update.effective_user
            
            data = query.data or ""
            if not data.startswith(LANG_CB_PREFIX):
                return
            
            lang = data.split(":", 1)[1]
            try:
                set_user_lang(user.id, lang)
                await query.edit_message_text(
                    t(lang, "lang.saved", lang_flag=SUPPORTED[lang]["flag"], lang_name=SUPPORTED[lang]["name"])
                )
            except ValueError:
                # langue non supportée
                await query.edit_message_text("❌ Unsupported language.")

        # --- Enregistrement des handlers de langue ---
        application.add_handler(CommandHandler("language", command_handlers.language_cmd))

        # --- Enregistrement du handler admin ---
        application.add_handler(CommandHandler("adm", command_handlers.adm))

        # Wrapper /start avec vérification f-sub
        async def start_guarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await require_fsub_or_prompt(update, context):
                return ConversationHandler.END
            return await command_handlers.start(update, context)

        # Wrapper /create avec vérification f-sub
        async def create_guarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await require_fsub_or_prompt(update, context):
                return ConversationHandler.END
            return await command_handlers.create_publication(update, context)

        # Wrapper /settings avec vérification f-sub
        async def settings_guarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await require_fsub_or_prompt(update, context):
                return ConversationHandler.END
            return await command_handlers.settings(update, context)

        # Handler PRIORITAIRE pour les réactions (group=-1 = priorité maximale)
        async def global_reaction_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handler global pour les réactions avec priorité maximale"""
            query = update.callback_query
            if query and query.data and query.data.startswith('r:'):
                await handle_reaction_toggle(update, context)
                raise ApplicationHandlerStop      # not again by the conversation (it rewrote the channel post)

        application.add_handler(CallbackQueryHandler(global_reaction_handler, pattern=r'^r:.*'), group=-1)
        # Force join, one list for everyone (admin_core's /addfsub and the JSON file used to be two lists)
        application.add_handler(CallbackQueryHandler(fsub_check_callback, pattern=r"^fsub_check$"), group=-1)
        application.add_handler(CommandHandler(["channels", "fsub"], channels_overview), group=-1)
        application.add_handler(CommandHandler("delfsub", delfsub_everywhere), group=-1)

        # Every button logged — in its own group: in group 0 its « .* » took every button of that group (/connect, the
        # channel reactions react_…, the buttons pressed outside the conversation), which then never answered
        application.add_handler(CallbackQueryHandler(_debug_cbq, pattern=".*"), group=-2)

        async def main_menu_guarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """« ↩️ Main menu » on any old message brings the user back in (after a restart the conversation,
            kept in memory only, is gone and every button did nothing)."""
            if not await require_fsub_or_prompt(update, context):
                return ConversationHandler.END
            return await handle_callback(update, context)

        # Définition du ConversationHandler avec les différents états
        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(main_menu_guarded, pattern=r"^main_menu$"),
                CommandHandler("start", start_guarded),
                CommandHandler("create", create_guarded),
                CommandHandler("settings", settings_guarded),
                CommandHandler("help", command_handlers.help),
                CommandHandler("addchannel", command_handlers.addchannel_cmd),
                CommandHandler("language", command_handlers.language_cmd),
            ],
            states={
                MAIN_MENU: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    CallbackQueryHandler(handle_callback),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
                ],
                POST_CONTENT: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    MessageHandler(filters.Document.ALL, handle_media),
                    MessageHandler(filters.PHOTO, handle_media),
                    MessageHandler(filters.VIDEO, handle_media),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_REACTION_INPUT: [
                    MessageHandler(filters.TEXT, handle_reaction_input),
                    CallbackQueryHandler(handle_callback)
                ],
                WAITING_URL_INPUT: [
                    MessageHandler(filters.TEXT, handle_url_input),
                    CallbackQueryHandler(handle_callback)
                ],
                WAITING_CHANNEL_SELECTION: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_CUSTOM_USERNAME: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
                ],
                WAITING_CHANNEL_INFO: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    MessageHandler(filters.TEXT, handle_channel_info),
                ],
                SETTINGS: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    CallbackQueryHandler(handle_callback),
                ],
                POST_ACTIONS: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    CallbackQueryHandler(handle_callback),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
                ],
                WAITING_PUBLICATION_CONTENT: [
                    # Handler prioritaire pour les boutons ReplyKeyboard
                    MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                    MessageHandler(filters.PHOTO, handle_post_content),
                    MessageHandler(filters.VIDEO, handle_post_content),
                    MessageHandler(filters.Document.ALL, handle_post_content),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_post_content),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_RENAME_INPUT: [
                    MessageHandler(filters.TEXT, handle_rename_input),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_THUMBNAIL_RENAME_INPUT: [
                    MessageHandler(filters.TEXT, handle_thumbnail_rename_input),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_TAG_INPUT: [
                    MessageHandler(filters.TEXT, handle_tag_input),
                    CallbackQueryHandler(handle_callback),
                ],
                SCHEDULE_SEND: [
                    # Handler pour la planification
                    MessageHandler(filters.TEXT, handle_schedule_time_wrapper),
                    CallbackQueryHandler(handle_callback),
                ],
                SCHEDULE_SELECT_CHANNEL: [
                    # Handler pour la sélection de canal planifié
                    CallbackQueryHandler(handle_callback),
                ],


            },
            fallbacks=[
                CommandHandler("cancel", lambda update, context: ConversationHandler.END),
                CommandHandler("start", start_guarded),
                # Handler de fallback pour les boutons ReplyKeyboard
                MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
                CallbackQueryHandler(handle_callback),
            ],
            per_message=False,
            name="main_conversation",
            persistent=False,
            allow_reentry=True,
        )

        logger.info("ConversationHandler configuré avec états: %s",
                    ", ".join(str(state) for state in conv_handler.states.keys()))

        # Le ConversationHandler est mis en group=1 pour laisser passer le handler global (group=0)
        application.add_handler(conv_handler, group=1)

        async def outside_conversation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """A button pressed outside the conversation (in it, group 1 handles it): a channel reaction (react_…,
            from any channel member), or a button of an old message after a restart. Both did nothing."""
            q = update.callback_query
            data = (q.data or "") if q else ""
            if data.startswith("react_"):
                await handle_callback(update, context)
                raise ApplicationHandlerStop          # not a second time by the conversation
            if conv_handler._conversations.get(conv_handler._get_key(update)) is not None:
                return
            if any(isinstance(e, CallbackQueryHandler) and e.check_update(update) for e in conv_handler.entry_points):
                return                                # « ↩️ Main menu »: it starts the conversation again
            try:
                await q.answer("⌛ This button has expired (the bot was restarted). Tap ↩️ Main menu or send /start.",
                               show_alert=True)
            except Exception:
                pass

        application.add_handler(CallbackQueryHandler(outside_conversation_callback), group=0)

        # Register chat member updates and /connect
        register_my_chat_member(application)
        register_connect(application)
        logger.info("Ajout du handler de callback global")
        
        # Importer et utiliser le gestionnaire d'erreurs
        from handlers.command_handlers import error_handler
        application.add_error_handler(error_handler)

        # Démarrage du bot
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Erreur lors du démarrage du bot: {e}")
        raise
    finally:
        # Nettoyage à la fin - seulement si l'application a été créée
        try:
            # Vérifier que l'application existe et que asyncio est accessible
            if 'application' in locals() and application is not None:
                import asyncio as asyncio_module
                try:
                    loop = asyncio_module.get_event_loop()
                    if not loop.is_closed():
                        loop.run_until_complete(cleanup(application))
                except RuntimeError:
                    # Si la boucle est fermée, créer une nouvelle boucle
                    loop = asyncio_module.new_event_loop()
                    asyncio_module.set_event_loop(loop)
                    loop.run_until_complete(cleanup(application))
                    loop.close()
        except Exception as cleanup_error:
            logger.error(f"Erreur lors du nettoyage: {cleanup_error}")

if __name__ == '__main__':
    main()

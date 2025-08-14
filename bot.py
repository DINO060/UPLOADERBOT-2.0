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
    ContextTypes
)
from telegram.error import BadRequest, Forbidden
from dotenv import load_dotenv
import pytz
import time
import sys
import platform
# Telethon supprimé: Pyrogram suffit pour le fallback MTProto
import math
from PIL import Image
from conversation_states import (
    MAIN_MENU, POST_CONTENT, POST_ACTIONS, SEND_OPTIONS, AUTO_DESTRUCTION,
    SCHEDULE_SEND, EDIT_POST, SCHEDULE_SELECT_CHANNEL, STATS_SELECT_CHANNEL,
    WAITING_CHANNEL_INFO, SETTINGS, BACKUP_MENU, WAITING_CHANNEL_SELECTION,
    WAITING_PUBLICATION_CONTENT, WAITING_TIMEZONE, WAITING_THUMBNAIL,
    WAITING_REACTION_INPUT, WAITING_URL_INPUT, WAITING_RENAME_INPUT,
    WAITING_THUMBNAIL_RENAME_INPUT, WAITING_SCHEDULE_TIME, WAITING_EDIT_TIME,
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
from handlers.thumbnail_handler import (
    handle_thumbnail_functions,
    handle_add_thumbnail_to_post,
    handle_set_thumbnail_and_rename,
    handle_view_thumbnail,
    handle_delete_thumbnail,
    handle_thumbnail_input,
    handle_add_thumbnail
)
from pyrogram import Client
from handlers.callback_handlers import handle_callback, send_post_now
from handlers.message_handlers import handle_text, handle_media, handle_channel_info, handle_post_content, handle_tag_input
from handlers.media_handler import send_file_smart

load_dotenv()

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


# --- vérification d’abonnement (utilitaire réutilisable) ---
async def is_user_in_required_channels(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> tuple[bool, list[str]]:
    """
    Returns (ok, missing[]). ok=True if user is a member of ALL required channels.
    """
    channels = await load_fj_channels()
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
        except (BadRequest, Forbidden):
            # if the bot has no access, consider as missing
            missing.append(ch)
        except Exception:
            missing.append(ch)
    return (len(missing) == 0), missing


async def require_fsub_or_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Call at the start of sensitive/public commands to enforce f-sub."""
    user = update.effective_user
    if not user:
        return False
    # admins bypass f-sub
    if is_admin(user.id):
        return True
    ok, missing = await is_user_in_required_channels(context, user.id)
    if ok:
        return True
    links = "\n".join(f"• {x}" for x in missing)
    await update.effective_message.reply_text(
        "🔒 To use the bot, please join these channels and try again:\n" + links
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

def debug_thumbnail_search(user_id, channel_username, db_manager):
    """Fonction de debug pour diagnostiquer les problèmes de recherche de thumbnails"""
    logger.info(f"=== DEBUG THUMBNAIL SEARCH ===")
    logger.info(f"User ID: {user_id}")
    logger.info(f"Channel Username Original: '{channel_username}'")
    
    # Normalisation
    clean_username = normalize_channel_username(channel_username)
    logger.info(f"Channel Username Normalisé: '{clean_username}'")
    
    # Tester différentes variantes
    test_variants = [
        channel_username,
        clean_username,
        f"@{clean_username}" if clean_username and not clean_username.startswith('@') else clean_username,
        clean_username.lstrip('@') if clean_username else None
    ]
    
    logger.info(f"Variants à tester: {test_variants}")
    
    # Tester chaque variant
    for variant in test_variants:
        if variant:
            result = db_manager.get_thumbnail(variant, user_id)
            logger.info(f"Test variant '{variant}': {result}")
    
    # Vérifier directement dans la base de données
    try:
        conn = sqlite3.connect(settings.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT channel_username, thumbnail_file_id FROM channel_thumbnails WHERE user_id = ?", (user_id,))
        all_thumbnails = cursor.fetchall()
        logger.info(f"TOUS les thumbnails pour user {user_id}: {all_thumbnails}")
        conn.close()
    except Exception as e:
        logger.error(f"Erreur lors de la vérification DB: {e}")
    
    logger.info(f"=== FIN DEBUG ===")

def ensure_thumbnail_table_exists():
    """S'assure que la table channel_thumbnails existe"""
    try:
        conn = sqlite3.connect(settings.db_path)
        cursor = conn.cursor()
        
        # Vérifier si la table existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channel_thumbnails'")
        table_exists = cursor.fetchone() is not None
        
        if not table_exists:
            logger.info("Création de la table channel_thumbnails manquante...")
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
            conn.commit()
            logger.info("✅ Table channel_thumbnails créée avec succès!")
        else:
            logger.info("✅ Table channel_thumbnails existe déjà")
        
        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ Erreur lors de la création de la table channel_thumbnails: {e}")
        return False

# Initialisation de la base de données
db_manager = DatabaseManager()
db_manager.setup_database()

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
            await update.message.reply_text("❌ Vous n'avez pas les permissions nécessaires.")
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
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
                InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_rename_{post_index}")
            ]])
        )
        
        return WAITING_RENAME_INPUT
        
    except Exception as e:
        logger.error(f"Erreur dans handle_set_thumbnail_and_rename: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
                InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")
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
                [InlineKeyboardButton("🔄 Changer", callback_data="add_thumbnail")],
                [InlineKeyboardButton("🗑️ Supprimer", callback_data="delete_thumbnail")],
                [InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")]
            ]
            
            await query.message.reply_text(
                "Que voulez-vous faire avec ce thumbnail?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Erreur lors de l'affichage du thumbnail: {e}")
            await query.edit_message_text(
                "❌ Impossible d'afficher le thumbnail.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
                ]])
            )
    else:
        await query.edit_message_text(
            "❌ Aucun thumbnail enregistré pour ce canal.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
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
                InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")
            ]])
        )
        return SETTINGS
    
    user_id = update.effective_user.id
    clean_username = normalize_channel_username(channel_username)
    
    if db_manager.delete_thumbnail(clean_username, user_id):
        await query.edit_message_text(
            f"✅ Thumbnail supprimé pour @{clean_username}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
            ]])
        )
    else:
        await query.edit_message_text(
            "❌ Erreur lors de la suppression du thumbnail.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
            ]])
        )
    
    return SETTINGS

async def handle_rename_input(update, context):
    """Gère la saisie du nouveau nom de fichier (comme dans renambot)"""
    try:
        if not context.user_data.get('waiting_for_rename') or 'current_post_index' not in context.user_data:
            await update.message.reply_text(
                "❌ Aucun renommage en cours.",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        post_index = context.user_data['current_post_index']
        new_filename = update.message.text.strip()
        user_message_id = update.message.message_id
        user_chat_id = update.effective_chat.id
        
        # Validation du nom de fichier
        if not new_filename:
            await update.message.reply_text(
                "❌ Please provide a valid filename.",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_rename_{post_index}")
                ]])
            )
            return WAITING_RENAME_INPUT
        
        # Appliquer le nouveau "nom" en légende, sans re-téléverser
        if 'posts' in context.user_data and post_index < len(context.user_data['posts']):
            post = context.user_data['posts'][post_index]
            post['filename'] = new_filename

            # Construire les boutons dynamiques selon l'état courant
            keyboard = []
            reactions = post.get('reactions') or []
            if reactions:
                # Afficher les réactions existantes
                current_row = []
                for reaction in reactions:
                    current_row.append(InlineKeyboardButton(reaction, callback_data=f"react_{post_index}_{reaction}"))
                    if len(current_row) == 4:
                        keyboard.append(current_row)
                        current_row = []
                if current_row:
                    keyboard.append(current_row)
                keyboard.append([InlineKeyboardButton("🗑️ Supprimer les réactions", callback_data=f"remove_reactions_{post_index}")])
            else:
                keyboard.append([InlineKeyboardButton("✨ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")])

            # Boutons URL existants
            for btn in post.get('buttons', []) or []:
                if isinstance(btn, dict) and 'text' in btn and 'url' in btn:
                    keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
            # Boutons d'action
            keyboard.extend([
                [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
                [InlineKeyboardButton("✏️ Edit File", callback_data=f"edit_file_{post_index}")],
                [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")]
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)

            # Supprimer l'ancien aperçu si présent
            preview_info = context.user_data.get('preview_messages', {}).get(post_index)
            if preview_info:
                try:
                    await context.bot.delete_message(chat_id=preview_info['chat_id'], message_id=preview_info['message_id'])
                except Exception:
                    pass

            # Envoyer à nouveau le média avec une légende = nouveau nom + tag éventuel sur la même ligne
            caption_text = f"{new_filename}"
            try:
                from database.manager import DatabaseManager
                dbm = DatabaseManager()
                channel_username = post.get('channel') or context.user_data.get('selected_channel', {}).get('username')
                clean_channel = channel_username.lstrip('@') if isinstance(channel_username, str) else None
                tag = dbm.get_channel_tag(clean_channel, update.effective_user.id) if clean_channel else None
                if tag and str(tag).strip():
                    caption_text = f"{new_filename} {str(tag).strip()}"
            except Exception:
                pass
            sent_message = None
            if post['type'] == 'photo':
                sent_message = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=post['content'],
                    caption=caption_text,
                    reply_markup=reply_markup
                )
            elif post['type'] == 'video':
                sent_message = await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=post['content'],
                    caption=caption_text,
                    reply_markup=reply_markup
                )
            elif post['type'] == 'document':
                # Measure file size for stats
                file_size_bytes = 0
                try:
                    # Try to get size from context (if available) or default to 0
                    file_size_bytes = int(post.get('file_size') or 0)
                except Exception:
                    file_size_bytes = 0

                sent_message = await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=post['content'],
                    caption=caption_text,
                    reply_markup=reply_markup
                )
                # Update rename stats (files renamed and storage used)
                try:
                    await add_rename_stat(file_size_bytes)
                except Exception:
                    pass
            elif post['type'] == 'text':
                sent_message = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=caption_text,
                    reply_markup=reply_markup
                )

            # Enregistrer le nouvel aperçu pour ce post
            if sent_message:
                if 'preview_messages' not in context.user_data:
                    context.user_data['preview_messages'] = {}
                context.user_data['preview_messages'][post_index] = {
                    'message_id': sent_message.message_id,
                    'chat_id': update.effective_chat.id
                }

            # Envoyer un message de confirmation après le média
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"✅ Fichier renommé : <code>{new_filename}</code>",
                    parse_mode="HTML"
                )
            except Exception:
                pass

            # Supprimer le prompt et le message utilisateur
            try:
                prompt_msg_id = context.user_data.pop('rename_prompt_message_id', None)
                prompt_chat_id = context.user_data.pop('rename_prompt_chat_id', None)
                if prompt_msg_id and prompt_chat_id:
                    await context.bot.delete_message(chat_id=prompt_chat_id, message_id=prompt_msg_id)
                await context.bot.delete_message(chat_id=user_chat_id, message_id=user_message_id)
            except Exception:
                pass

            # Nettoyer les variables temporaires
            context.user_data.pop('waiting_for_rename', None)
            context.user_data.pop('current_post_index', None)

            return WAITING_PUBLICATION_CONTENT
        else:
            await update.message.reply_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
    
    except Exception as e:
        logger.error(f"Erreur dans handle_rename_input: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[ 
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

async def handle_thumbnail_rename_input(update, context):
    """Gère la saisie du nouveau nom après l'ajout du thumbnail"""
    try:
        if not context.user_data.get('awaiting_thumb_rename') or 'current_post_index' not in context.user_data:
            await update.message.reply_text(
                "❌ Aucun traitement thumbnail+rename en cours.",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        post_index = context.user_data['current_post_index']
        new_filename = update.message.text.strip()
        user_message_id = update.message.message_id
        user_chat_id = update.effective_chat.id
        
        # Validation du nom de fichier
        if not new_filename:
            await update.message.reply_text(
                "❌ Veuillez fournir un nom de fichier valide.",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("❌ Annuler", callback_data="main_menu")
                ]])
            )
            return WAITING_THUMBNAIL_RENAME_INPUT
        
        # Stocker le nouveau nom temporairement
        context.user_data['pending_rename_filename'] = new_filename
        # Spécifique: pour 'Add Thumbnail + Rename', on veut renvoyer la vidéo en DOCUMENT
        try:
            post = context.user_data['posts'][post_index]
            if post.get('type') == 'video':
                context.user_data['force_document_for_video'] = True
        except Exception:
            pass

        # Message de progression visible pour l'utilisateur
        try:
            progress_msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⏳ Traitement du fichier…"
            )
            context.user_data['progress_message_id'] = progress_msg.message_id
        except Exception:
            context.user_data.pop('progress_message_id', None)
        
        # Appeler la fonction de traitement
        from handlers.callback_handlers import process_thumbnail_and_upload
        success = await process_thumbnail_and_upload(update, context, post_index)
        
        # Supprimer le prompt et le message de l'utilisateur
        try:
            prompt_id = context.user_data.pop('thumbnail_rename_prompt_message_id', None)
            if prompt_id:
                await context.bot.delete_message(chat_id=user_chat_id, message_id=prompt_id)
            await context.bot.delete_message(chat_id=user_chat_id, message_id=user_message_id)
        except Exception:
            pass
        
        if success:
            # Nettoyer le contexte et revenir à l'état principal
            context.user_data.pop('awaiting_thumb_rename', None)
            context.user_data.pop('current_post_index', None)
            context.user_data.pop('pending_rename_filename', None)
            context.user_data.pop('force_document_for_video', None)
            return WAITING_PUBLICATION_CONTENT
        else:
            await update.message.reply_text(
                "❌ Erreur lors du traitement. Veuillez réessayer.",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
    
    except Exception as e:
        logger.error(f"Erreur dans handle_thumbnail_rename_input: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[ 
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
                    InlineKeyboardButton("⚙️ Paramètres", callback_data="settings"),
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
                InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_thumbnail_rename_{post_index}")
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
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
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
                    [InlineKeyboardButton("📝 Modifier la légende", callback_data=f"edit_caption_{post_index}")]
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
                    InlineKeyboardButton("📝 New post", callback_data="create_publication")
                ], [
                    InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")
                ]])
            )
            return WAITING_PUBLICATION_CONTENT
        
        # Obtenir les informations du canal
        selected_channel = context.user_data.get('selected_channel', {})
        channel = posts[0].get("channel") or selected_channel.get('username', '@default_channel')
        
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
        # Configuration de l'application
        application = Application.builder().token(settings.bot_token).build()
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
                # Démarrer le scheduler maintenant que l'event loop est actif
                app.bot_data['scheduler_manager'].start()
                logger.info("✅ Scheduler démarré avec succès")
                
                # Vérifier que le scheduler fonctionne
                logger.info(f"🔍 Scheduler running: {app.bot_data['scheduler_manager'].scheduler.running}")
                logger.info(f"🔍 Scheduler state: {app.bot_data['scheduler_manager'].scheduler.state}")
                
                # Restaurer les posts planifiés
                await restore_scheduled_posts(app)
                
                # Planifier les tâches de maintenance
                await schedule_maintenance_tasks(app)

                # Démarrer le client Pyrogram dans la boucle existante
                try:
                    await init_clients()
                    logger.info("✅ Client Pyrogram démarré (post_init)")
                except Exception as e:
                    logger.warning(f"⚠️ Impossible de démarrer les clients avancés (post_init): {e}")
                
            except Exception as e:
                logger.error(f"Erreur lors de l'initialisation post-startup: {e}")
                raise
        
        # Ajouter le callback post_init
        application.post_init = post_init

        # ✅ NOUVEAU : Restaurer les posts planifiés depuis la base de données
        async def restore_scheduled_posts(app: Application):
            """Restaure tous les posts planifiés depuis la base de données au démarrage"""
            try:
                logger.info("🔄 Restauration des posts planifiés...")
                
                # Récupérer tous les posts planifiés non envoyés
                with sqlite3.connect(settings.db_config["path"]) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT id, scheduled_time, post_type, content, caption, channel_id
                        FROM posts 
                        WHERE scheduled_time > datetime('now') 
                        AND (status = 'pending' OR status IS NULL)
                    """)
                    scheduled_posts = cursor.fetchall()
                    
                if not scheduled_posts:
                    logger.info("✅ Aucun post planifié à restaurer")
                    return
                    
                restored_count = 0
                for post_data in scheduled_posts:
                    try:
                        post_id, scheduled_time_str, post_type, content, caption, channel_id = post_data
                        
                        # Parser la date avec le bon fuseau horaire
                        from datetime import datetime
                        import pytz
                        
                        # Récupérer le fuseau horaire depuis la base de données
                        # On cherche l'utilisateur propriétaire du post
                        cursor.execute("SELECT c.user_id FROM channels c WHERE c.id = ?", (channel_id,))
                        user_result = cursor.fetchone()
                        
                        if user_result:
                            user_id = user_result[0]
                            cursor.execute("SELECT timezone FROM user_timezones WHERE user_id = ?", (user_id,))
                            tz_result = cursor.fetchone()
                            user_timezone = tz_result[0] if tz_result else 'Europe/Paris'
                        else:
                            user_timezone = 'Europe/Paris'  # Fallback
                        
                        scheduled_time = datetime.strptime(scheduled_time_str, '%Y-%m-%d %H:%M:%S')
                        # Localiser avec le bon fuseau horaire
                        scheduled_time = pytz.timezone(user_timezone).localize(scheduled_time)
                        
                        # Créer le job
                        job_id = f"post_{post_id}"
                        
                        # ✅ CORRECTION : Créer une fonction wrapper synchrone simple
                        def send_restored_post_job(post_id=post_id):
                            """Fonction wrapper pour envoyer un post restauré"""
                            import asyncio
                            try:
                                # Créer une nouvelle boucle pour le job
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                
                                # Fonction asynchrone pour envoyer le post
                                async def send_post_async():
                                    from utils.scheduler_utils import send_scheduled_file
                                    post_dict = {"id": post_id}
                                    await send_scheduled_file(post_dict, app)
                                
                                # Exécuter la fonction asynchrone
                                loop.run_until_complete(send_post_async())
                                loop.close()
                                
                                logger.info(f"✅ Post {post_id} envoyé avec succès")
                                
                            except Exception as job_error:
                                logger.error(f"❌ Erreur dans le job {post_id}: {job_error}")
                                logger.exception("Traceback:")
                        
                        # Ajouter le job au scheduler avec la fonction wrapper corrigée
                        app.bot_data['scheduler_manager'].scheduler.add_job(
                            func=send_restored_post_job,
                            trigger="date",
                            run_date=scheduled_time,
                            id=job_id,
                            replace_existing=True
                        )
                        
                        restored_count += 1
                        logger.info(f"✅ Post {post_id} restauré pour {scheduled_time}")
                        
                    except Exception as e:
                        logger.error(f"❌ Erreur lors de la restauration du post {post_id}: {e}")
                        continue
                
                logger.info(f"✅ {restored_count} posts planifiés restaurés avec succès")
                
            except Exception as e:
                logger.error(f"❌ Erreur lors de la restauration des posts planifiés: {e}")
                logger.exception("Traceback:")
        
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

        # Initialisation du client Pyrogram pour les gros fichiers
        async def init_clients():
            try:
                from utils.clients import client_manager
                await client_manager.start_clients()
                logger.info("✅ Client Pyrogram démarré pour la gestion des gros fichiers")
            except Exception as e:
                logger.warning(f"⚠️ Impossible de démarrer les clients avancés: {e}")
                logger.warning("Les fichiers > 50MB ne pourront pas être traités avec thumbnail personnalisé")
        
        # Les clients sont démarrés dans post_init via la boucle existante (plus de boucle manuelle ici)

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

        # Définition du ConversationHandler avec les différents états
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("start", start_guarded),
                CommandHandler("create", create_guarded),
                CommandHandler("settings", settings_guarded),
                CommandHandler("help", command_handlers.help),
                CommandHandler("addchannel", command_handlers.addchannel_cmd),
                CommandHandler("setthumbnail", command_handlers.setthumbnail_cmd),
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
                WAITING_THUMBNAIL: [
                    MessageHandler(filters.PHOTO, handle_thumbnail_input),
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

        application.add_handler(conv_handler, group=0)  # Priorité normale après handler global
        
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
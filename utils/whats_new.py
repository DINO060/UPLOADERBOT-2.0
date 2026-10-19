"""
What's new: whatsnew.txt, newest version on top. At start-up a version not announced yet is sent once to every user,
and deleted after UPDATE_MESSAGE_TTL; a plain restart (crash, deploy without a new entry) tells users nothing. The
admins hear of every restart, with the state of force join and of the scheduled posts. It replaces the « 🟢 Bot
started! » sent to every user at EVERY start.
"""
import asyncio
import html
import json
import logging
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

from telegram.error import Forbidden, RetryAfter

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
WHATS_NEW_FILE = ROOT / "whatsnew.txt"
ANNOUNCED_FILE = ROOT / "data" / "announced_version.txt"
UPDATE_MESSAGE_TTL = 6 * 3600          # the notice deletes itself after this (the owner's wish), even across a restart
UPDATE_MESSAGES_FILE = ROOT / "data" / "update_messages.json"
NAME = "Uploader Bot"
GUIDE_EN = "https://telegra.ph/Uploader-Bot--How-to-use-it-10-19"
GUIDE_FR = "https://telegra.ph/Uploader-Bot--Mode-demploi-10-19"


def whats_new():
    """(version, [changes]) of the newest entry of whatsnew.txt, or (None, [])."""
    try:
        lines = WHATS_NEW_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, []
    version, changes = None, []
    for line in lines:
        s = line.strip()
        if s.startswith("==") and s.endswith("=="):
            if version:
                break
            version = s.strip("= ").strip()
        elif version and s.startswith("- "):
            changes.append(s[2:].strip())
    return version, changes


def update_message(changes) -> str:
    return (f"🆕 <b>{NAME} has been updated!</b>\n\n<b>What's new:</b>\n"
            + "\n".join(f"• {html.escape(c)}" for c in changes)
            + f"\n\n📖 <a href=\"{GUIDE_EN}\">How to use the bot</a> · <a href=\"{GUIDE_FR}\">Mode d'emploi</a>"
            + f"\n\n<i>🕒 This message disappears in {UPDATE_MESSAGE_TTL // 3600} h.</i>")


def all_user_ids(db_path: str) -> list:
    """Everyone who used the bot: channels, timezones, usage, thumbnails — only the tables that exist (one missing
    table made the old start message reach nobody)."""
    ids = set()
    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("channel_members", "user_timezones", "user_usage", "channel_thumbnails", "channels", "posts"):
            if table not in tables:
                continue
            cols = {c[1] for c in conn.execute(f"PRAGMA table_info({table})")}
            col = "user_id" if "user_id" in cols else "owner_id" if "owner_id" in cols else None
            if col:
                ids.update(r[0] for r in conn.execute(f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL"))
    return sorted(i for i in ids if isinstance(i, int) and i > 0)


async def send_to_all(bot, user_ids, text: str, sent: list = None) -> dict:
    """One message to each user, paced; a flood wait is waited for. sent: gets (user, message id) of each."""
    counts = {"sent": 0, "blocked": 0, "failed": 0}
    for uid in user_ids:
        for attempt in range(2):
            try:
                msg = await bot.send_message(uid, text, parse_mode="HTML", disable_web_page_preview=True)
                counts["sent"] += 1
                if sent is not None and msg is not None:
                    sent.append((uid, msg.message_id))
                break
            except RetryAfter as e:
                wait = e.retry_after.total_seconds() if hasattr(e.retry_after, "total_seconds") else float(e.retry_after)
                if attempt or wait > 300:
                    counts["failed"] += 1
                    break
                await asyncio.sleep(wait + 1)
            except Forbidden:
                counts["blocked"] += 1
                break
            except Exception as e:  # noqa: BLE001
                counts["blocked" if "deactivated" in str(e).lower() else "failed"] += 1
                break
        await asyncio.sleep(0.05)
    return counts


def _pending_updates() -> list:
    try:
        return json.loads(UPDATE_MESSAGES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_pending_updates(rows: list) -> None:
    UPDATE_MESSAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    UPDATE_MESSAGES_FILE.write_text(json.dumps(rows), encoding="utf-8")


async def delete_due_updates(bot) -> int:
    """Deletes the update notices whose time is up; returns how many."""
    now = time.time()
    due = [r for r in _pending_updates() if r[2] <= now]
    for chat_id, msg_id, _ in due:
        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"update notice {chat_id}/{msg_id} not deleted: {e}")
        await asyncio.sleep(0.05)
    if due:          # read again: notices sent meanwhile are kept
        _save_pending_updates([r for r in _pending_updates() if r[2] > now])
    return len(due)


async def update_cleanup_loop(bot) -> None:
    while True:
        try:
            await delete_due_updates(bot)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"update notice cleanup: {e}")
        await asyncio.sleep(60)


async def announce_update(app, db_path: str, admin_ids, forced_channels=None, channel_problem=None) -> None:
    """At start-up: a new version is announced to every user once; the admins hear of every restart.
    forced_channels / channel_problem: bot.py's (passed in: importing bot.py from here would run it twice)."""
    await asyncio.sleep(5)
    version, changes = whats_new()
    try:
        announced = ANNOUNCED_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        announced = None
    counts = None
    if version and changes and version != announced:
        ANNOUNCED_FILE.parent.mkdir(parents=True, exist_ok=True)
        ANNOUNCED_FILE.write_text(version, encoding="utf-8")       # first: a crash midway never sends it twice
        sent = []
        counts = await send_to_all(app.bot, all_user_ids(db_path), update_message(changes), sent)
        delete_at = time.time() + UPDATE_MESSAGE_TTL
        _save_pending_updates(_pending_updates() + [[uid, mid, delete_at] for uid, mid in sent])
        logger.info(f"Update {version} announced: {counts}")

    note = [f"🔄 <b>{NAME} restarted</b> (version {html.escape(version or '?')})."]
    note.append(f"🆕 Update announced: {counts['sent']} sent, {counts['blocked']} blocked, {counts['failed']} failed."
                if counts else "No new version: users were not told.")
    if forced_channels and channel_problem:
        ctx = SimpleNamespace(bot=app.bot, bot_data=app.bot_data)
        try:
            channels = await forced_channels(ctx)
            note.append("📢 Force join: " + ("OFF" if not channels else ""))
            for ch in channels:
                problem = await channel_problem(ctx, ch)
                note.append(f"   • {html.escape(ch)}: " + ("✅ checked" if not problem else f"❌ NOT checked ({html.escape(problem)})"))
        except Exception as e:  # noqa: BLE001
            note.append(f"📢 Force join: state unknown ({html.escape(str(e))})")
    try:
        with sqlite3.connect(db_path) as conn:
            waiting = conn.execute("SELECT COUNT(*) FROM posts WHERE status = 'pending' OR status IS NULL").fetchone()[0]
        note.append(f"📅 Scheduled posts waiting: {waiting}")
    except Exception:  # noqa: BLE001
        pass
    for admin in admin_ids:
        try:
            await app.bot.send_message(int(admin), "\n".join(note), parse_mode="HTML")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"restart note to {admin}: {e}")

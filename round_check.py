"""Offline check of the 2026-10-19 round (python round_check.py): the real bot.py, its real Application built (not
started), a fake Telegram, a throw-away database.

- buttons: the « .* » logger no longer swallows group 0; /connect and channel reactions answer; a button outside the
  conversation (after a restart) says so; buttons that had no branch (Back from scheduling, Cancel, Choose channel)
  have one; the conversation leaves alone the buttons of other handlers;
- force join: one list (the JSON file + admin_core's /addfsub), a channel the bot can't check no longer locks
  everyone out, Join / « I have joined » buttons, /channels says what is really checked, /delfsub removes everywhere;
- the update notice: once per version, deleted after 6 h (kept on disk), the admin's note; coloured buttons.
"""
import asyncio
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
WORK = Path(tempfile.mkdtemp())
os.chdir(WORK)
sys.stdout.reconfigure(errors="replace")
os.environ.update(BOT_TOKEN="1:x", API_ID="1", API_HASH="x", ADMIN_IDS="42")
dotenv = types.ModuleType("dotenv")              # never load the real .env
dotenv.load_dotenv = lambda *a, **k: False
dotenv.find_dotenv = lambda *a, **k: ""
sys.modules["dotenv"] = dotenv
shutil.copy(ROOT / "i18n.py", WORK)              # i18n keeps its own bot.db next to itself: the copy's
shutil.copytree(ROOT / "locales", WORK / "locales")
sys.path[:0] = [str(WORK), str(ROOT)]

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

from config import settings  # noqa: E402
import database.manager as dbm  # noqa: E402
DB = str(WORK / "bot.db")
settings.db_config["path"] = DB
dbm.DB_CONFIG["path"] = DB
import database.channel_repo as channel_repo  # noqa: E402
channel_repo.DB_PATH = DB
channel_repo.init_db()
dbm.DatabaseManager()

from telegram.error import BadRequest  # noqa: E402
from telegram.ext import Application, ApplicationBuilder, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler  # noqa: E402

built = {}
_build = ApplicationBuilder.build


def _capture(self):
    app = _build(self)
    built["app"] = app
    return app
ApplicationBuilder.build = _capture
Application.run_polling = lambda self, *a, **k: None
from telegram.ext import JobQueue  # noqa: E402
_set_app = JobQueue.set_application


def _strong_ref(self, application):              # PTB 20.3's weakref to Application fails on Python 3.13 (not the VPS)
    try:
        _set_app(self, application)
    except TypeError:
        self._application = lambda: application
JobQueue.set_application = _strong_ref

import bot  # noqa: E402
bot.FJ_PATH = WORK / "force_join_channels.json"
bot.FJ_PATH.write_text('{"channels": ["@djd208"]}')
import handlers.callback_handlers as cb  # noqa: E402
import utils.whats_new as wn  # noqa: E402
wn.ANNOUNCED_FILE = WORK / "data" / "announced_version.txt"
wn.UPDATE_MESSAGES_FILE = WORK / "data" / "update_messages.json"
bot.main()                                       # registers every handler, does not start
app = built["app"]
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))


class FakeBot:
    id = 999

    def __init__(self):
        self.log, self.members, self.not_admin = [], set(), set()

    async def get_chat_member(self, chat, user_id):
        if chat in self.not_admin:
            raise BadRequest("Chat not found")
        if user_id == self.id:
            return SimpleNamespace(status="administrator")
        return SimpleNamespace(status="member" if (chat, user_id) in self.members else "left")

    async def get_chat(self, chat):
        return SimpleNamespace(invite_link="https://t.me/+private")

    async def send_message(self, chat_id, text, **kw):
        self.log.append(("msg", chat_id, text, kw.get("reply_markup")))
        return SimpleNamespace(message_id=len(self.log), chat_id=chat_id)

    async def delete_message(self, chat_id, message_id):
        self.log.append(("deleted", chat_id, str(message_id), None))


fake = FakeBot()


class Query(SimpleNamespace):
    async def answer(self, text=None, show_alert=False, **kw):
        self.answers.append(text)

    async def edit_message_text(self, text, **kw):
        self.edits.append((text, kw.get("reply_markup")))

    async def edit_message_reply_markup(self, *a, **kw):
        pass


def cq_update(uid, data):
    q = Query(data=data, from_user=SimpleNamespace(id=uid), answers=[], edits=[],
              message=SimpleNamespace(chat_id=uid, message_id=5, chat=SimpleNamespace(id=uid)))
    msg = SimpleNamespace(reply_text=lambda *a, **k: _reply(uid, *a, **k), chat_id=uid)
    return SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=uid), effective_message=msg,
                           effective_chat=SimpleNamespace(id=uid), message=None), q


async def _reply(uid, text, **kw):
    fake.log.append(("reply", uid, text, kw.get("reply_markup")))
    return SimpleNamespace(message_id=1)


def ctx_for():
    return SimpleNamespace(bot=fake, bot_data=app.bot_data, user_data={}, args=[], application=app)


def handlers_of(group):
    return app.handlers.get(group, [])


def buttons(markup):
    return [b for row in (markup.inline_keyboard if markup else []) for b in row]


async def main():
    # 1. the button routing
    debug = [h for h in handlers_of(-2) if isinstance(h, CallbackQueryHandler)]
    g0 = [h for h in handlers_of(0) if isinstance(h, CallbackQueryHandler)]
    catch_all_first = next((h for h in g0 if h.pattern is None or h.pattern.pattern == ".*"), None)
    check("the « .* » button logger is alone in its own group (in group 0 it swallowed the buttons after it)",
          len(debug) == 1 and getattr(catch_all_first, "callback", None).__name__ == "outside_conversation_callback",
          str([getattr(h.callback, "__name__", h) for h in g0]))
    connect = [h for h in handlers_of(-1) if isinstance(h, CallbackQueryHandler) and h.pattern and "connect" in h.pattern.pattern]
    check("/connect's button in group -1 (it never answered)", connect)

    conv = next(h for h in handlers_of(1))
    outside = next(h.callback for h in g0 if h.callback.__name__ == "outside_conversation_callback")
    upd, q = cq_update(77, "main_menu_old")
    await outside(upd, ctx_for())
    check("a button pressed outside the conversation (after a restart): told to go back, not silent",
          q.answers and "expired" in q.answers[-1], str(q.answers))
    conv._conversations[conv._get_key(upd)] = 1           # now in the conversation: group 1 handles it
    upd2, q2 = cq_update(77, "settings")
    await outside(upd2, ctx_for())
    check("… in the conversation: left to it", not q2.answers)
    from datetime import datetime
    from telegram import CallbackQuery, Chat, Message, Update, User
    alerts_real = []

    async def _answer(self, text=None, show_alert=False, **kw):
        alerts_real.append(text)
    CallbackQuery.answer = _answer
    real = Update(1, callback_query=CallbackQuery(
        "1", User(78, "u", False), "ci", data="main_menu",
        message=Message(5, datetime.now(), Chat(78, "private"))))
    await outside(real, ctx_for())
    check("… « ↩️ Main menu » outside it: no « expired » alert, the conversation starts again",
          not alerts_real and conv.entry_points[0].check_update(real), str(alerts_real))
    called = []
    real_hc = bot.handle_callback

    async def fake_hc(update, context):
        called.append(update.callback_query.data)
    bot.handle_callback = fake_hc
    stopped = False
    try:
        await outside(cq_update(88, "react_5_👍")[0], ctx_for())
    except ApplicationHandlerStop:
        stopped = True
    bot.handle_callback = real_hc
    check("a channel reaction (react_…) from a channel member: handled, once", called == ["react_5_👍"] and stopped)

    upd, q = cq_update(77, "r:👍:5")
    check("the conversation leaves alone the buttons of other handlers (it rewrote the channel post)",
          await cb.handle_callback(upd, ctx_for()) is None and not q.edits)
    upd, q = cq_update(77, "send_post")
    context = ctx_for()
    context.user_data.update(posts=[{}, {}], selected_channel={"username": "mychan"})
    state = await cb.handle_callback(upd, context)
    labels = [b.text for b in buttons(q.edits[-1][1])] if q.edits else []
    check("« ↩️ Back » from scheduling: the send options (it said « not implemented »)",
          "📤 Send now" in labels and "2 files are ready" in q.edits[-1][0], str(q.edits))
    upd, q = cq_update(77, "cancel")
    await cb.handle_callback(upd, ctx_for())
    check("« Cancel » of the channel choice: back to the main menu", q.edits and "Main menu" in q.edits[-1][0], str(q.edits))
    upd, q = cq_update(77, "choose_channel")
    context = ctx_for()
    context.user_data["posts"] = [{"type": "document"}]
    await cb.handle_callback(upd, context)
    check("« 📺 Choose channel »: the channel choice, the files kept", q.edits and context.user_data["posts"] == [{"type": "document"}]
          and "not implemented" not in q.edits[-1][0], str(q.edits))
    upd, q = cq_update(77, "auto_destruction")
    await cb.handle_callback(upd, ctx_for())
    upd2, q2 = cq_update(77, "auto_dest_3600")
    context = ctx_for()
    await cb.handle_callback(upd2, context)
    check("auto-destruction: in English, « Back » to the send options (it went to the main menu)",
          q.edits and "Choose a duration" in q.edits[-1][0] and buttons(q.edits[-1][1])[-1].callback_data == "send_post"
          and context.user_data.get("auto_destruction_time") == 3600 and "1 hour(s)" in q2.edits[-1][0]
          and buttons(q2.edits[-1][1])[-1].callback_data == "send_post", f"{q.edits[-1:]} {q2.edits[-1:]}")

    # 2. force join
    admin_db = app.bot_data.get("admin_db")
    admin_db.add_force_join_channel(channel_id="@added_by_addfsub", channel_name="Added")
    context = ctx_for()
    chans = await bot.forced_channels(context)
    check("one list: the JSON file AND admin_core's /addfsub (that one was never checked)",
          chans == ["@djd208", "@added_by_addfsub"], str(chans))
    fake.members.add(("@djd208", 50))
    ok_, missing = await bot.is_user_in_required_channels(context, 50)
    check("not in the /addfsub channel: refused", not ok_ and missing == ["@added_by_addfsub"], str(missing))
    fake.not_admin.add("@added_by_addfsub")
    mark = len(fake.log)
    ok_, missing = await bot.is_user_in_required_channels(context, 50)
    ok2, _ = await bot.is_user_in_required_channels(context, 50)
    alerts = [e for e in fake.log[mark:] if e[1] == 42 and "can't check" in e[2]]
    check("a channel the bot can't check: users not locked out (they ALL were), the admin alerted once",
          ok_ and ok2 and len(alerts) == 1, f"{ok_} {len(alerts)}")
    fake.not_admin.clear()
    upd, q = cq_update(51, "x")
    sent_before = len(fake.log)
    allowed = await bot.require_fsub_or_prompt(upd, context)
    prompt = [e for e in fake.log[sent_before:] if e[0] == "reply"]
    urls = [b.url for b in buttons(prompt[-1][3])] if prompt else []
    datas = [b.callback_data for b in buttons(prompt[-1][3])] if prompt else []
    check("the join message: a Join button per channel and « I have joined » (it had none)",
          not allowed and "https://t.me/djd208" in urls and "https://t.me/added_by_addfsub" in urls and "fsub_check" in datas,
          f"{urls} {datas}")
    upd, q = cq_update(51, "fsub_check")
    try:
        await bot.fsub_check_callback(upd, context)
    except ApplicationHandlerStop:
        pass
    check("« I have joined » before joining: told so", q.answers and "haven't joined" in q.answers[-1])
    fake.members |= {("@djd208", 51), ("@added_by_addfsub", 51)}
    upd, q = cq_update(51, "fsub_check")
    try:
        await bot.fsub_check_callback(upd, context)
    except ApplicationHandlerStop:
        pass
    check("… after joining: in, with a Start button into the conversation",
          q.edits and "You're in" in q.edits[-1][0] and buttons(q.edits[-1][1])[0].callback_data == "main_menu")
    entry = [h for h in conv.entry_points if isinstance(h, CallbackQueryHandler)]
    check("« ↩️ Main menu » / Start re-enters the conversation (after a restart buttons did nothing)",
          entry and entry[0].pattern.pattern == "^main_menu$")

    replies = []
    admin_msg = SimpleNamespace(reply_text=lambda t, **k: _rec(replies, t))
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=admin_msg, effective_message=admin_msg)
    fake.not_admin.add("@added_by_addfsub")
    try:
        await bot.channels_overview(upd, context)
    except ApplicationHandlerStop:
        pass
    check("/channels: both lists, with what is really checked", replies and "@djd208 — ✅" in replies[-1]
          and "@added_by_addfsub — ❌ NOT checked" in replies[-1], replies and replies[-1])
    context.args = ["@added_by_addfsub", "@djd208"]
    try:
        await bot.delfsub_everywhere(upd, context)
    except ApplicationHandlerStop:
        pass
    check("/delfsub: removed from both lists (each command knew only one)", await bot.forced_channels(context) == [],
          str(await bot.forced_channels(context)))
    cmds = [h for h in handlers_of(-1) if isinstance(h, CommandHandler)]
    check("… /channels, /fsub and /delfsub answer before admin_core's own (group -1)",
          {c for h in cmds for c in h.commands} >= {"channels", "fsub", "delfsub"})

    # 3. the update notice
    with sqlite3.connect(DB) as conn:
        conn.execute("INSERT OR IGNORE INTO user_timezones (user_id, timezone) VALUES (61, 'UTC'), (62, 'UTC')")
    real_sleep = asyncio.sleep
    wn.asyncio.sleep = lambda s: real_sleep(0)
    fake_app = SimpleNamespace(bot=fake, bot_data=app.bot_data)
    mark = len(fake.log)
    await wn.announce_update(fake_app, DB, [42], bot.forced_channels, bot.channel_problem)
    news = [e for e in fake.log[mark:] if e[0] == "msg" and "has been updated" in e[2]]
    note = [e for e in fake.log[mark:] if e[1] == 42 and "restarted" in e[2]]
    check("a new version: every user told once (no more « Bot started » at every start), the admin's note",
          sorted(e[1] for e in news) == [61, 62] and note and "Scheduled posts waiting" in note[-1][2]
          and "disappears in 6 h" in news[0][2], f"{[e[1] for e in news]} {note and note[-1][2]}")
    pending = wn._pending_updates()
    check("… each notice due for deletion in 6 h (kept on disk)", sorted(r[0] for r in pending) == [61, 62]
          and all(5.9 * 3600 < r[2] - time.time() <= 6 * 3600 for r in pending))
    wn._save_pending_updates([[c, m, time.time() - 1] for c, m, _ in pending])
    mark = len(fake.log)
    n = await wn.delete_due_updates(fake)
    check("… after 6 h: deleted for every user", n == 2 and sorted(e[1] for e in fake.log[mark:] if e[0] == "deleted") == [61, 62])
    mark = len(fake.log)
    await wn.announce_update(fake_app, DB, [42], bot.forced_channels, bot.channel_problem)
    check("… restarted again: users told nothing, the admin still told",
          not [e for e in fake.log[mark:] if "has been updated" in e[2]] and any("No new version" in e[2] for e in fake.log[mark:]))
    wn.asyncio.sleep = real_sleep

    # 4. colours
    upd, q = cq_update(77, "main_menu")
    await cb.handle_callback(upd, ctx_for())
    styles = {b.text: b.to_dict().get("style") for b in buttons(q.edits[-1][1])} if q.edits else {}
    check("coloured buttons: New post green, Scheduled posts and Settings blue",
          styles.get("📝 New post") == "success" and styles.get("⚙️ Settings") == "primary", str(styles))


async def _rec(store, text):
    store.append(text)


asyncio.run(main())
print("\nALL OK" if ok else "\nFAILED")

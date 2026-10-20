"""Offline check of the sending order and of the posts that used to get lost (python send_order_check.py).
No network: a fake Telegram, a throw-away database, the bot's real code and a real APScheduler.

- episode numbers read from file names; a shuffled batch of one series put back in order, anything else untouched;
- « send now »: 12 shuffled episodes go out in episode order, a flood wait is really waited for, a post that
  fails is reported by name and kept to be sent again;
- scheduled: 12 posts planned for the same minute go out in order (they used to race in 12 threads), Telegram
  unreachable → tried again later in the same order, a broken post → given up and its owner told;
- start-up: a future post gets its job back at the right UTC time, a post missed while the bot was off goes out now
  (owner told), a very old one is marked 'missed';
- scheduling: ids in episode order, owner and UTC time stored; « Scheduled posts » shows only the caller's posts.
"""
import asyncio
import os
import random
import shutil
import sqlite3
import sys
import tempfile
import types
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
WORK = Path(tempfile.mkdtemp())
os.chdir(WORK)
sys.stdout.reconfigure(errors="replace")
os.environ.update(BOT_TOKEN="1:x", API_ID="1", API_HASH="x", ADMIN_IDS="42")
dotenv = types.ModuleType("dotenv")              # never load the real .env
dotenv.load_dotenv = lambda *a, **k: False
sys.modules["dotenv"] = dotenv
shutil.copy(ROOT / "i18n.py", WORK)              # i18n keeps its own bot.db next to itself: the copy's, not the bot's
shutil.copytree(ROOT / "locales", WORK / "locales")
sys.path[:0] = [str(WORK), str(ROOT)]

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import pytz  # noqa: E402
from telegram.error import BadRequest, NetworkError, RetryAfter  # noqa: E402

from config import settings  # noqa: E402
import database.manager as dbm  # noqa: E402
DB = str(WORK / "bot.db")
settings.db_config["path"] = DB
dbm.DB_CONFIG["path"] = DB
import database.channel_repo as channel_repo  # noqa: E402
channel_repo.DB_PATH = DB
channel_repo.init_db()                           # the tables in the order the bot creates them (as on the VPS)
dbm.DatabaseManager()
with sqlite3.connect(DB) as _c:
    _c.execute("INSERT INTO channels (tg_chat_id, title, username, bot_is_admin) VALUES (-100777, 'My channel', 'mychan', 1)")
    _c.execute("INSERT INTO channel_members (channel_id, user_id) VALUES (1, 5)")

from utils import scheduler_utils as su, telegram_retry  # noqa: E402
from utils.episode_order import episode_of, in_episode_order  # noqa: E402
from utils.scheduler import SchedulerManager  # noqa: E402
import handlers.callback_handlers as cb  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))


# ---------------------------------------------------------------- fake Telegram
class FakeBot:
    def __init__(self):
        self.sent, self.dm, self.down = [], [], False
        self.flood_once, self.broken = set(), set()
        self.n = 0

    async def _post(self, chat_id, item):
        await asyncio.sleep(0)
        if self.down:
            raise NetworkError("Connection reset")
        if item in self.flood_once:
            self.flood_once.discard(item)
            raise RetryAfter(7)
        if item in self.broken:
            raise BadRequest("Wrong file identifier/http url specified")
        self.n += 1
        self.sent.append(item)
        return SimpleNamespace(message_id=self.n, chat_id=chat_id)

    async def send_document(self, chat_id, document, **kw):
        return await self._post(chat_id, document)

    async def send_video(self, chat_id, video, **kw):
        return await self._post(chat_id, video)

    async def send_photo(self, chat_id, photo, **kw):
        return await self._post(chat_id, photo)

    async def send_message(self, chat_id, text, **kw):
        if str(chat_id).startswith("-100"):
            return await self._post(chat_id, text)
        self.dm.append((chat_id, text))
        return SimpleNamespace(message_id=0, chat_id=chat_id)

    async def get_chat(self, chat_id):
        if self.down:
            raise NetworkError("Connection reset")
        return SimpleNamespace(id=-100777, username="mychan", title="My channel")


real_sleep = asyncio.sleep
waits = []


async def fast_sleep(delay, *a, **k):           # « send now » pauses 1 s per post, flood waits: recorded, not slept
    waits.append(delay)
    await real_sleep(0)


def fake_update(user_id=5, text=None):
    replies = []

    async def reply_text(t, reply_markup=None, **kw):
        replies.append(f"{t} | {reply_markup}")

    async def edit_message_text(t, reply_markup=None, **kw):
        replies.append(f"{t} | {reply_markup}")

    async def answer(*a, **k):
        pass
    message = SimpleNamespace(text=text, reply_text=reply_text)
    query = SimpleNamespace(message=message, edit_message_text=edit_message_text, answer=answer, data="planifier_post")
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id), message=message, callback_query=query), replies


def episodes(n, shuffle=True, name="[Erai-raws] Kaiju No. 8 - {:02d} [1080p].mkv"):
    posts = [{"type": "document", "content": f"ep{k:02d}", "filename": name.format(k), "caption": "",
              "channel": "mychan"} for k in range(1, n + 1)]
    if shuffle:
        random.Random(3).shuffle(posts)
    return posts


async def main():
    # ------------------------------------------------------------ 1. episode numbers
    cases = {"[Erai-raws] Kaiju No. 8 - 03 [1080p].mkv": 3, "Show S01E05 1080p x264.mkv": 5, "Show.EP12.VOSTFR.mp4": 12,
             "One Piece Episode 1071 VF.mp4": 1071, "Show 2023 - 04.mkv": 4, "Mob Psycho 100 - 07.mkv": 7,
             "Re Zero 3rd Season - 09v2 [720p].mkv": 9, "Movie 1080p x265.mkv": None, "cover": None}
    got = {k: (episode_of(k) or (0, 0, None))[2] for k in cases}
    check("episode number read from typical file names", got == cases, str(got))
    shuffled = episodes(12)
    fixed, moved = in_episode_order(shuffled)
    check("a shuffled batch of one series: put back in episode order",
          moved and [p["content"] for p in fixed] == [f"ep{k:02d}" for k in range(1, 13)])
    check("… already in order: untouched", in_episode_order(fixed) == (fixed, False))
    with_cover = [{"type": "photo", "content": "cover", "caption": "Kaiju No. 8"}] + shuffled
    check("… with a cover photo: order kept as sent", in_episode_order(with_cover) == (with_cover, False))
    two = episodes(2, False) + episodes(2, False, "Other Show - {:02d}.mkv")
    two.reverse()
    check("… two different series: order kept as sent", in_episode_order(two) == (two, False))
    vf = [{"type": "video", "content": c, "filename": f, "caption": ""} for c, f in
          (("b-vf", "Show - 02 VF.mp4"), ("a-vf", "Show - 01 VF.mp4"), ("a-vo", "Show - 01 VOSTFR.mp4"))]
    check("… two versions of one episode keep their own order", [p["content"] for p in in_episode_order(vf)[0]]
          == ["a-vf", "a-vo", "b-vf"])

    # ------------------------------------------------------------ 2. « send now »
    asyncio.sleep = fast_sleep
    bot = FakeBot()
    bot.flood_once.add("ep04")
    bot.broken.add("ep09")
    posts = episodes(12)
    update, replies = fake_update(5)
    context = SimpleNamespace(bot=bot, user_data={"posts": posts, "selected_channel": {"username": "mychan", "name": "My"}},
                              application=None)
    await cb.send_post_now(update, context)
    expected = [f"ep{k:02d}" for k in range(1, 13) if k != 9]
    check("send now: 12 shuffled episodes published in episode order", bot.sent == expected, str(bot.sent))
    check("… Telegram's « wait 7 s » really waited for (it was capped at 2 s, then the post dropped)", 8 in waits, str(waits))
    summary = replies[-1] if replies else ""
    check("… the summary says 11/12, that they were reordered, and which one failed and why",
          "11/12" in summary and "🔢" in summary and "#9" in summary and "Wrong file identifier" in summary, summary)
    kept = context.user_data["posts"]
    check("… the failed one is kept (with its channel) for « 🚀 Send »",
          [p["content"] for p in kept] == ["ep09"] and context.user_data.get("selected_channel"), str(kept))
    asyncio.sleep = real_sleep

    # ------------------------------------------------------------ 3. scheduled posts
    su.GATHER_SECONDS, su.GAP_SECONDS = 0.3, 0.01
    su.RETRY_LATER = timedelta(seconds=1)
    su.STARTUP_DELAY = timedelta(seconds=0.5)
    telegram_retry.NETWORK_WAITS = (0.01, 0.01)
    manager = SchedulerManager("UTC")
    manager.start()
    bot = FakeBot()
    app = SimpleNamespace(bot=bot, bot_data={"scheduler_manager": manager})
    su.set_global_scheduler_manager(manager)
    su.set_global_application(app)
    cb.set_global_scheduler_manager(manager)

    def add_posts(contents, when_local="2030-01-01 20:00:00", owner=5, run_at=None, status="pending"):
        ids = []
        with sqlite3.connect(DB) as conn:
            su.ensure_schedule_columns(conn.cursor())
            for c in contents:
                cur = conn.execute("INSERT INTO posts (channel_id, post_type, content, caption, scheduled_time, status,"
                                   " owner_id, run_at) VALUES (?, 'document', ?, '', ?, ?, ?, ?)",
                                   (-100777, c, when_local, status, owner, run_at))
                ids.append(cur.lastrowid)
        return ids

    def pending(ids):
        with sqlite3.connect(DB) as conn:
            return {r[0]: r[1] for r in conn.execute(
                f"SELECT id, status FROM posts WHERE id IN ({','.join('?' * len(ids))})", ids)}

    async def until(cond, seconds=8.0):
        for _ in range(int(seconds / 0.05)):
            if cond():
                return True
            await real_sleep(0.05)
        return cond()

    ids = add_posts([f"s{k:02d}" for k in range(1, 13)])
    when = datetime.now(pytz.UTC) + timedelta(seconds=1)
    for post_id in random.Random(7).sample(ids, len(ids)):      # jobs created in any order, all at the same second
        su.add_post_job(manager.scheduler, post_id, when)
    await until(lambda: len(bot.sent) == 12)
    check("scheduled: 12 posts of the same minute published in order (they raced in 12 threads)",
          bot.sent == [f"s{k:02d}" for k in range(1, 13)], str(bot.sent))
    check("… and removed from the database once sent", pending(ids) == {})

    bot.sent.clear()
    bot.down = True
    ids = add_posts([f"n{k}" for k in range(1, 6)])
    when = datetime.now(pytz.UTC) + timedelta(seconds=0.5)
    for post_id in reversed(ids):
        su.add_post_job(manager.scheduler, post_id, when)
    await until(lambda: all(manager.scheduler.get_job(f"post_{i}") for i in ids)
                and manager.scheduler.get_job(f"post_{ids[0]}").next_run_time > when, 5)
    check("Telegram unreachable: nothing lost, every post planned again (not marked missing / failed)",
          pending(ids) == {i: "pending" for i in ids} and bot.sent == [], str(pending(ids)))
    bot.down = False
    await until(lambda: len(bot.sent) == 5)
    check("… back online: all sent, still in order", bot.sent == [f"n{k}" for k in range(1, 6)], str(bot.sent))

    bot.sent.clear()
    bot.broken.add("b2")
    ids = add_posts(["b1", "b2", "b3"], owner=77)
    when = datetime.now(pytz.UTC) + timedelta(seconds=0.5)
    for post_id in ids:
        su.add_post_job(manager.scheduler, post_id, when)
    await until(lambda: len(bot.sent) == 2 and bot.dm)
    check("a broken post: the others go out in order", bot.sent == ["b1", "b3"], str(bot.sent))
    check("… it is marked failed and its owner told why", pending(ids) == {ids[1]: "failed"}
          and bot.dm and bot.dm[-1][0] == 77 and "Wrong file identifier" in bot.dm[-1][1], f"{pending(ids)} {bot.dm}")

    # ------------------------------------------------------------ 4. start-up
    for job in manager.scheduler.get_jobs():
        job.remove()
    bot.sent.clear()
    bot.dm.clear()
    now = datetime.now(pytz.UTC)
    future = add_posts(["future"], run_at=su.utc_text(now + timedelta(hours=3)))[0]
    late = add_posts(["late1", "late2"], owner=88, run_at=su.utc_text(now - timedelta(hours=2)))
    old = add_posts(["old"], run_at=su.utc_text(now - timedelta(days=3)))[0]
    failed = add_posts(["failed"], run_at=su.utc_text(now - timedelta(hours=1)), status="failed")[0]
    with sqlite3.connect(DB) as conn:
        conn.execute("INSERT OR REPLACE INTO user_timezones (user_id, timezone) VALUES (99, 'America/New_York')")
    ny = pytz.timezone("America/New_York")
    legacy_local = (now + timedelta(days=1)).astimezone(ny).replace(minute=0, second=0, microsecond=0)
    legacy = add_posts(["legacy"], when_local=legacy_local.strftime("%Y-%m-%d %H:%M:%S"), owner=99)[0]
    await su.restore_scheduled_posts(app)
    job = manager.scheduler.get_job
    check("start-up: a future post gets its job back at its UTC time",
          job(f"post_{future}") and abs((job(f"post_{future}").next_run_time - (now + timedelta(hours=3))).total_seconds()) < 2)
    check("… one scheduled before this update (no UTC time): read in its owner's timezone",
          job(f"post_{legacy}") and job(f"post_{legacy}").next_run_time == legacy_local.astimezone(pytz.UTC),
          str(job(f"post_{legacy}") and job(f"post_{legacy}").next_run_time))
    await until(lambda: len(bot.sent) == 2)
    check("… posts missed while the bot was off go out now, in order", bot.sent == ["late1", "late2"], str(bot.sent))
    check("… and their owner is told", any(c == 88 and "2" in t for c, t in bot.dm), str(bot.dm))
    check("… a 3-day-old one is marked missed, a failed one left alone",
          pending([old, failed]) == {old: "missed", failed: "failed"} and not job(f"post_{failed}"))

    # ------------------------------------------------------------ 5. scheduling, and the list of scheduled posts
    for j in manager.scheduler.get_jobs():
        j.remove()
    bot = FakeBot()
    update, replies = fake_update(5, "12:00")
    context = SimpleNamespace(bot=bot, application=app, user_data={
        "posts": episodes(4), "selected_channel": {"username": "mychan", "name": "My"}, "schedule_day": "tomorrow"})
    await cb.handle_schedule_time(update, context)
    with sqlite3.connect(DB) as conn:
        rows = conn.execute("SELECT id, content, owner_id, run_at FROM posts WHERE content LIKE 'ep%' ORDER BY id").fetchall()
    check("scheduling a shuffled batch: stored in episode order (ids), with owner and UTC time",
          [r[1] for r in rows] == ["ep01", "ep02", "ep03", "ep04"] and all(r[2] == 5 and r[3] for r in rows), str(rows))
    check("… one job each, run on the bot's loop", all(job(f"post_{r[0]}") and job(f"post_{r[0]}").func is su.run_post_job
                                                     for r in rows))
    check("… the confirmation says they were reordered", replies and "🔢" in replies[-1], str(replies))
    update, replies = fake_update(5, "12:00")
    context.user_data.update(posts=[{"type": "document", "content": "overmorrow", "filename": "x.pdf", "caption": "",
                                     "channel": "mychan"}], schedule_day="overmorrow",
                             selected_channel={"username": "mychan", "name": "My"})
    await cb.handle_schedule_time(update, context)
    with sqlite3.connect(DB) as conn:
        run_at = conn.execute("SELECT run_at FROM posts WHERE content = 'overmorrow'").fetchone()
    hours = run_at and (pytz.UTC.localize(datetime.strptime(run_at[0][:19], "%Y-%m-%d %H:%M:%S"))
                        - datetime.now(pytz.UTC)).total_seconds() / 3600
    check("« Overmorrow » at 12:00: in 2 days (it was today: sent 2 days early, or refused as past)",
          run_at and 36 < hours <= 60 and replies and "scheduled for" in replies[-1] and "tomorrow" not in replies[-1],
          f"{hours} {replies[-1:]}")
    soonest =(datetime.now(pytz.UTC) + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")   # the next post of all
    add_posts(["someone else's"], when_local=soonest, owner=6)
    with sqlite3.connect(DB) as conn:                    # someone else's channel, first in the table
        cols = [r[1] for r in conn.execute("PRAGMA table_info(channels)")]
        if "tg_chat_id" in cols:
            conn.execute("INSERT INTO channels (tg_chat_id, title, username) VALUES (-100555, 'Someone else''s channel', 'someone')")
        else:
            conn.execute("INSERT INTO channels (name, username, user_id) VALUES ('Someone else''s channel', 'someone', 6)")
    update, replies = fake_update(5)
    await cb.planifier_post(update, context)
    shown = "\n".join(replies)
    other_id = sqlite3.connect(DB).execute("SELECT id FROM posts WHERE content = ?", ("someone else's",)).fetchone()[0]
    check("« Scheduled posts »: only the caller's own posts (anyone's next post was shown, editable)",
          f"show_post_{other_id}'" not in shown and f"show_post_{rows[0][0]}'" in shown, shown[:400])
    check("… all 4 of them, not just the next one, in send order",
          [shown.find(f"show_post_{r[0]}'") for r in rows] == sorted(shown.find(f"show_post_{r[0]}'") for r in rows)
          and all(f"show_post_{r[0]}'" in shown for r in rows), shown[:400])
    check("… with their own channel's name (it showed the first channel of the table, someone else's)",
          "My channel" in shown and "Someone else" not in shown, shown[:300])
    add_posts([f"x{k}" for k in range(9)], when_local="2031-01-01 20:00:00")
    update, replies = fake_update(5)
    await cb.planifier_post(update, context)
    with sqlite3.connect(DB) as conn:
        mine = conn.execute("SELECT COUNT(*) FROM posts WHERE owner_id = 5 AND status = 'pending'"
                            " AND scheduled_time > '2026'").fetchone()[0]
    check(f"… {mine} scheduled: the next 10 shown, « and {mine - 10} more »", replies and mine > 10
          and f"… and {mine - 10} more" in replies[-1] and replies[-1].count("show_post_") == 10,
          replies and replies[-1][:900])
    manager.scheduler.shutdown(wait=False)


asyncio.run(main())
print("\nALL OK" if ok else "\nFAILED")

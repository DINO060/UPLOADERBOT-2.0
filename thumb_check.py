"""Offline check of the channel thumbnail and the auto-destruction (python thumb_check.py). No network: a fake
Telegram and a fake Pyrogram, the bot's real handlers, a throw-away database and data folder.

- 🖼️ a channel's thumbnail: set from a photo or an image file (made a Telegram thumbnail: JPEG ≤ 320 px, ≤ 200 KB),
  seen, changed, deleted; reached from Settings → Manage channels → the channel;
- ✏️ Edit File → 🖼️ Thumbnail: the video / document sent again with it (same name), kept by a later rename; no
  thumbnail yet → where to set it; not offered for a photo; one answer per button (Telegram refuses two);
- ⏱️ auto-destruction: a minute or more kept on disk and deleted when due, also after a restart; shorter ones a timer.
"""
import asyncio
import io
import os
import shutil
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
sys.modules["dotenv"] = dotenv
shutil.copy(ROOT / "i18n.py", WORK)
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
settings.TEMP_DIR = WORK / "temp"


class FakePyro:
    def __init__(self):
        self.calls = []

    async def download_media(self, file_id, file_name=None, progress=None, progress_args=()):
        path = Path(file_name) / f"document_{file_id}"
        path.write_bytes(b"x" * 1000)
        return str(path)

    async def _send(self, kind, chat_id, path, **kw):
        thumb = kw.get("thumb")
        self.calls.append((kind, Path(path).name, thumb and Path(thumb).read_bytes()))

        async def delete():
            pass
        media = SimpleNamespace(file_id=f"new_{kind}_{len(self.calls)}")
        return SimpleNamespace(document=media if kind == "document" else None,
                               video=media if kind == "video" else None, delete=delete)

    async def send_document(self, chat_id, document, **kw):
        return await self._send("document", chat_id, document, **kw)

    async def send_video(self, chat_id, video, **kw):
        return await self._send("video", chat_id, video, **kw)


pyro = FakePyro()
fake_pyro_client = types.ModuleType("utils.pyro_client")


async def get_pyro():
    return pyro
fake_pyro_client.get_pyro = get_pyro
sys.modules["utils.pyro_client"] = fake_pyro_client

from PIL import Image  # noqa: E402
import utils.channel_thumbs as ct  # noqa: E402
import utils.auto_destruction as ad  # noqa: E402
import handlers.rename_handlers as rh  # noqa: E402
import handlers.callback_handlers as cb  # noqa: E402
import handlers.channel_thumb_ui as ui  # noqa: E402
from conversation_states import SETTINGS  # noqa: E402
ct.THUMB_DIR = WORK / "data" / "thumbnails"
ad.PENDING = WORK / "data" / "auto_destruction.json"

ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))


def big_picture(fmt="PNG") -> bytes:
    img = Image.effect_noise((1600, 1000), 90).convert("RGB")       # noise: it doesn't compress
    out = io.BytesIO()
    img.save(out, fmt)
    return out.getvalue()


PICTURE = big_picture()


class FakeBot:
    def __init__(self):
        self.texts, self.photos, self.deleted = [], [], []

    async def get_file(self, file_id):
        async def download_as_bytearray():
            return bytearray(PICTURE)

        async def download_to_drive(path):
            Path(path).write_bytes(b"OWN-" + file_id.encode())
            return Path(path)
        return SimpleNamespace(download_as_bytearray=download_as_bytearray, download_to_drive=download_to_drive)

    async def send_message(self, chat_id, text, **kw):
        self.texts.append(text)

        async def edit_text(t, **k):
            pass

        async def delete():
            pass
        return SimpleNamespace(message_id=len(self.texts), chat_id=chat_id, edit_text=edit_text, delete=delete)

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        self.photos.append((chat_id, photo, caption))
        return SimpleNamespace(message_id=500 + len(self.photos), chat_id=chat_id)

    async def send_video(self, chat_id, video, caption=None, **kw):
        return SimpleNamespace(message_id=600, chat_id=chat_id)

    async def send_document(self, chat_id, document, caption=None, **kw):
        return SimpleNamespace(message_id=700, chat_id=chat_id)

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class Query:
    def __init__(self, data, uid=5):
        self.data, self.answers, self.edits = data, [], []
        self.from_user = SimpleNamespace(id=uid)
        self.message = SimpleNamespace(chat_id=uid, message_id=31, chat=SimpleNamespace(id=uid))

    async def answer(self, text=None, show_alert=False, **kw):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None, **kw):
        self.edits.append((text, reply_markup))

    async def edit_message_caption(self, caption=None, reply_markup=None, **kw):
        self.edits.append((caption, reply_markup))


def press(data, context, uid=5):
    q = Query(data, uid)
    update = SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=uid, language_code="en"),
                             effective_chat=SimpleNamespace(id=uid), message=None)
    return update, q


def datas(markup):
    return [b.callback_data for row in (markup.inline_keyboard if markup else []) for b in row]


def picture_message(uid=5, photo=True, mime="image/jpeg"):
    replies = []

    async def reply_text(t, reply_markup=None, **kw):
        replies.append((t, reply_markup))
    msg = SimpleNamespace(photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="big")] if photo else [],
                          document=None if photo else SimpleNamespace(file_id="doc_pic", mime_type=mime),
                          reply_text=reply_text)
    return SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=uid)), replies


async def main():
    jpeg = ct.to_thumbnail(PICTURE)
    img = Image.open(io.BytesIO(jpeg))
    check("a 1600×1000 picture → a Telegram thumbnail: JPEG, ≤ 320 px, ≤ 200 KB",
          img.format == "JPEG" and max(img.size) <= 320 and len(jpeg) <= 200 * 1024 and len(PICTURE) > 1_000_000,
          f"{img.format} {img.size} {len(jpeg)}")

    bot = FakeBot()
    channel_repo.add_channel("My Channel", "mychan", 5)
    context = SimpleNamespace(bot=bot, application=None, user_data={})

    # 1. Settings → Manage channels → the channel → 🖼️ Thumbnail
    update, q = press("channel_mychan", context)
    await cb.handle_callback(update, context)
    check("the channel's screen: a « 🖼️ Thumbnail » button", "cthumb_mychan" in datas(q.edits[-1][1]) if q.edits else False,
          str(q.edits))
    update, q = press("cthumb_mychan", context)
    state = await cb.handle_callback(update, context)
    check("🖼️ Thumbnail: « no thumbnail yet », ➕ Add, ↩️ Back; one answer (Telegram refuses two)",
          state == SETTINGS and "No thumbnail yet" in q.edits[-1][0] and datas(q.edits[-1][1]) == ["cthumb_add_mychan", "channel_mychan"]
          and len(q.answers) == 1, f"{q.edits} {q.answers}")
    update, q = press("cthumb_add_mychan", context)
    await cb.handle_callback(update, context)
    check("➕ Add: asks for the picture, ❌ Cancel", context.user_data.get(ui.WAITING_KEY) == "mychan"
          and "Send me the picture" in q.edits[-1][0] and datas(q.edits[-1][1]) == ["cthumb_mychan"])

    upd, replies = picture_message(photo=False, mime="application/pdf")
    await ui.on_picture(upd, context)
    check("… a PDF instead: « not a picture », still waiting", replies and "not a picture" in replies[0][0]
          and context.user_data.get(ui.WAITING_KEY) == "mychan")
    upd, replies = picture_message()
    state = await ui.on_picture(upd, context)
    saved = ct.path_for(5, "mychan")
    check("… the photo (its biggest size): saved as the channel's thumbnail, the screen with 👁️ / 🔄 / 🗑️",
          state == SETTINGS and saved and Path(saved).read_bytes() == jpeg and replies and "Thumbnail saved" in replies[0][0]
          and datas(replies[0][1]) == ["cthumb_view_mychan", "cthumb_add_mychan", "cthumb_del_mychan", "channel_mychan"]
          and ui.WAITING_KEY not in context.user_data, f"{saved} {replies}")
    rec = dbm.DatabaseManager().get_thumbnail("mychan", 5)
    check("… recorded in channel_thumbnails (file id + file on disk)", rec and rec.get("local_path") == saved
          and rec.get("file_id") == "big", str(rec))
    upd, replies = picture_message()
    await ui.on_picture(upd, context)
    check("a picture sent later, not asked for: left alone", replies == [])
    update, q = press("cthumb_view_mychan", context)
    await cb.handle_callback(update, context)
    check("👁️ See it: the thumbnail sent as a photo", bot.photos and "mychan" in bot.photos[-1][2] and len(q.answers) == 1)

    # 2. Edit File → 🖼️ Thumbnail
    video = {"type": "video", "content": "vid0", "filename": "Show - 05.mkv", "caption": "Show - 05",
             "thumb_id": "own", "channel": "mychan", "duration": 1400, "width": 1920, "height": 1080}
    photo = {"type": "photo", "content": "ph0", "caption": "x", "channel": "mychan"}
    context.user_data.update(posts=[video, photo], selected_channel={"username": "mychan", "name": "My"},
                             preview_messages={0: {"chat_id": 5, "message_id": 31}})
    update, q = press("edit_file_0", context)
    await cb.handle_callback(update, context)
    menu_video = datas(q.edits[-1][1]) if q.edits else []
    update, q = press("edit_file_1", context)
    await cb.handle_callback(update, context)
    menu_photo = datas(q.edits[-1][1]) if q.edits else []
    check("✏️ Edit File: « 🖼️ Thumbnail » for a video or document, not for a photo",
          "apply_thumb_0" in menu_video and not any(d.startswith("apply_thumb") for d in menu_photo),
          f"{menu_video} {menu_photo}")

    update, q = press("apply_thumb_0", context)
    await cb.handle_callback(update, context)
    await asyncio.gather(*rh._running)
    kind, name, thumb = pyro.calls[-1]
    check("🖼️ Thumbnail: the video sent again with the channel's thumbnail, same name, as a video",
          kind == "video" and name == "Show - 05.mkv" and thumb == jpeg, f"{kind} {name} {thumb and thumb[:10]}")
    check("… the post uses the new file, « thumbnail added » said (not « renamed »), one answer",
          video["content"] == "new_video_1" and not video["renaming"] and "Thumbnail added" in bot.texts[-1]
          and len(q.answers) == 1, f"{video} {bot.texts[-1:]}")
    context.user_data.update(waiting_for_rename=True, current_post_index=0)
    replies = []

    async def reply_text(t, **kw):
        replies.append(t)
    rename_update = SimpleNamespace(effective_user=SimpleNamespace(id=5), effective_chat=SimpleNamespace(id=5),
                                    message=SimpleNamespace(text="Show - 05 VF", message_id=9, reply_text=reply_text),
                                    callback_query=None)
    await rh.handle_rename_input(rename_update, context)
    await asyncio.gather(*rh._running)
    kind, name, thumb = pyro.calls[-1]
    check("… a rename afterwards keeps the channel's thumbnail", name == "Show - 05 VF.mkv" and thumb == jpeg,
          f"{name} {thumb and thumb[:10]}")
    video["renaming"] = True
    update, q = press("apply_thumb_0", context)
    await cb.handle_callback(update, context)
    check("… pressed while the file is being sent again: an alert, nothing started",
          q.answers and q.answers[0][1] and "wait" in q.answers[0][0], str(q.answers))
    video["renaming"] = False

    update, q = press("cthumb_del_mychan", context)
    await cb.handle_callback(update, context)
    check("🗑️ Delete: gone (file and record), « no thumbnail yet » again",
          ct.path_for(5, "mychan") is None and "No thumbnail yet" in q.edits[-1][0]
          and not dbm.DatabaseManager().get_thumbnail("mychan", 5))
    calls = len(pyro.calls)
    update, q = press("apply_thumb_0", context)
    await cb.handle_callback(update, context)
    check("Edit File → 🖼️ Thumbnail with none set: where to set it, nothing sent again",
          len(pyro.calls) == calls and q.edits and "Manage channels" in q.edits[-1][0], str(q.edits[-1:]))

    # 3. auto-destruction
    ad.schedule(bot, -100777, 41, 3600)
    ad.schedule(bot, -100777, 42, 86400)
    check("⏱️ 1 h and 24 h: kept on disk (they were timers in memory, forgotten at a restart)",
          [r[1] for r in ad._load()] == [41, 42])
    check("… not due yet: nothing deleted", await ad.delete_due(bot) == 0 and len(ad._load()) == 2)
    rows = ad._load()
    rows[0][2] = time.time() - 5                       # the bot was off when it came due
    ad._save(rows)
    n = await ad.delete_due(bot)
    check("… due (also while the bot was off): deleted at the next look, the other kept",
          n == 1 and (-100777, 41) in bot.deleted and [r[1] for r in ad._load()] == [42])
    cb.schedule_auto_destruction(SimpleNamespace(bot=bot), 5, 43, 1)
    check("a 1 s one (the bot's own notes): a timer, not on disk", [r[1] for r in ad._load()] == [42])
    await asyncio.sleep(1.3)
    check("… deleted after 1 s", (5, 43) in bot.deleted)
    cb.schedule_auto_destruction(SimpleNamespace(bot=bot), -100777, 44, 300)
    check("« Send now » with 5 min: through the same list", [r[1] for r in ad._load()] == [42, 44])


asyncio.run(main())
print("\nALL OK" if ok else "\nFAILED")

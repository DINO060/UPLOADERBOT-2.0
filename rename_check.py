"""Offline check of the rename (python rename_check.py). No network: a fake Telegram and a fake Pyrogram, the bot's
real handlers and a throw-away database.

- a renamed document / video is really sent again under its new name (its own thumbnail, duration and size kept),
  in the background, and the post then uses the new file; the caption is what the preview shows;
- « 🚀 Send » (and scheduling) waits while a file is being renamed, then publishes the renamed file;
- a rename that fails leaves the post as it was and says so; a photo only gets its caption changed;
- a title typed without extension keeps the file's extension.
"""
import asyncio
import os
import shutil
import sys
import tempfile
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
shutil.copy(ROOT / "i18n.py", WORK)              # i18n keeps its own bot.db next to itself: the copy's, not the bot's
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
    """Pyrogram logged in as the bot: downloads write a file, sends record what they got."""
    def __init__(self):
        self.calls, self.fail, self.deleted = [], None, 0

    async def download_media(self, file_id, file_name=None, progress=None, progress_args=()):
        if self.fail:
            raise RuntimeError(self.fail)
        path = Path(file_name) / f"document_{file_id}"
        path.write_bytes(b"x" * 1000)
        await progress(500, 1000, *progress_args)
        return str(path)

    async def _send(self, kind, chat_id, path, **kw):
        assert Path(path).exists(), "the file sent must exist on disk"
        thumb = kw.get("thumb")
        self.calls.append((kind, chat_id, Path(path).name, kw, thumb and Path(thumb).read_bytes()))
        await kw["progress"](1000, 1000, *kw["progress_args"])

        async def delete():
            self.deleted += 1
        media = SimpleNamespace(file_id=f"new_{kind}_id")
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

import utils.file_rename as fr  # noqa: E402
import handlers.rename_handlers as rh  # noqa: E402
import handlers.callback_handlers as cb  # noqa: E402
from conversation_states import WAITING_PUBLICATION_CONTENT  # noqa: E402
fr.PROGRESS_EVERY = 0

ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))


class FakeBot:
    def __init__(self):
        self.sent, self.texts, self.edits, self.deleted = [], [], [], []

    async def send_message(self, chat_id, text, **kw):
        self.texts.append(text)
        if str(chat_id).startswith("-100"):
            self.sent.append(("text", text, None))

        async def edit_text(t, **k):
            self.edits.append(t)

        async def delete():
            pass
        return SimpleNamespace(message_id=len(self.texts), chat_id=chat_id, edit_text=edit_text, delete=delete)

    async def _media(self, kind, chat_id, item, caption):
        self.sent.append((kind, item, caption, chat_id))
        return SimpleNamespace(message_id=100 + len(self.sent), chat_id=chat_id)

    async def send_document(self, chat_id, document, caption=None, **kw):
        return await self._media("document", chat_id, document, caption)

    async def send_video(self, chat_id, video, caption=None, **kw):
        return await self._media("video", chat_id, video, caption)

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        return await self._media("photo", chat_id, photo, caption)

    async def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)

    async def get_file(self, file_id):
        async def download_to_drive(path):
            Path(path).write_bytes(b"JPEG-" + file_id.encode())
            return Path(path)
        return SimpleNamespace(download_to_drive=download_to_drive)

    async def get_chat(self, chat_id):
        return SimpleNamespace(id=-100777, username="mychan")


def rename_update(text, user_id=5):
    replies = []

    async def reply_text(t, **kw):
        replies.append(t)
    message = SimpleNamespace(text=text, message_id=9, reply_text=reply_text)
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id), effective_chat=SimpleNamespace(id=user_id),
                           message=message, callback_query=None), replies


async def rename(context, index, text):
    context.user_data.update(waiting_for_rename=True, current_post_index=index)
    update, replies = rename_update(text)
    state = await rh.handle_rename_input(update, context)
    return state, replies


async def main():
    check("a title typed without extension keeps the file's",
          fr.with_extension("Kaiju No. 8 - 05", "x.mkv") == "Kaiju No. 8 - 05.mkv"
          and fr.with_extension("Mr. Robot", "a.mp4") == "Mr. Robot.mp4"
          and fr.with_extension("new.mp4", "a.mkv") == "new.mp4" and fr.with_extension("name", None) == "name")
    check("… and a name can't escape the temporary folder", fr.safe_name("../a/b:c") == "_a_b_c")

    bot = FakeBot()
    doc = {"type": "document", "content": "old_doc", "filename": "x.mkv", "caption": "old caption",
           "thumb_id": "thumb1", "file_size": 1_500_000_000, "channel": "mychan"}
    context = SimpleNamespace(bot=bot, application=None, user_data={
        "posts": [doc], "selected_channel": {"username": "mychan", "name": "My"},
        "preview_messages": {0: {"chat_id": 5, "message_id": 77}}})
    state, _ = await rename(context, 0, "Kaiju No. 8 - 05")
    check("rename of a document: the handler answers at once, the file is renamed in the background",
          state == WAITING_PUBLICATION_CONTENT and doc["renaming"] and len(rh._running) == 1)

    update, replies = rename_update(None)
    await cb.send_post_now(update, context)
    check("« 🚀 Send » meanwhile: refused (it would publish the old file), the user told",
          not [s for s in bot.sent if s[3] == -100777] and replies and "1" in replies[-1], str(replies))

    await asyncio.gather(*rh._running)
    kind, chat_id, name, kw, thumb = pyro.calls[-1]
    check("… the file sent again under its new name, with the extension, in the user's chat",
          kind == "document" and chat_id == 5 and name == "Kaiju No. 8 - 05.mkv" and kw["file_name"] == name
          and kw["force_document"], str(pyro.calls[-1]))
    check("… with its own thumbnail", thumb == b"JPEG-thumb1", str(thumb))
    check("… that upload message deleted, the temporary folder emptied",
          pyro.deleted == 1 and not any((WORK / "temp").iterdir()))
    check("… the post now uses the renamed file, its caption is the new name",
          doc["content"] == "new_document_id" and doc["caption"] == "Kaiju No. 8 - 05" and not doc["renaming"]
          and doc["filename"] == "Kaiju No. 8 - 05.mkv", str(doc))
    check("… the old preview replaced by the renamed file, progress shown, « renamed » said",
          77 in bot.deleted and ("document", "new_document_id", "Kaiju No. 8 - 05", 5) in bot.sent
          and any("%" in e for e in bot.edits) and "Kaiju No. 8 - 05.mkv" in bot.texts[-1], f"{bot.edits} {bot.texts}")

    update, replies = rename_update(None)
    await cb.send_post_now(update, context)
    published = [s for s in bot.sent if s[3] == -100777]
    check("… then « 🚀 Send » publishes the renamed file with its new caption",
          published == [("document", "new_document_id", "Kaiju No. 8 - 05", -100777)], str(published))

    video = {"type": "video", "content": "old_vid", "filename": "clip.mp4", "caption": "", "duration": 1440,
             "width": 1920, "height": 1080, "thumb_id": "thumb2", "channel": "mychan"}
    context.user_data["posts"] = [video]
    await rename(context, 0, "Episode 6")
    await asyncio.gather(*rh._running)
    kind, _, name, kw, thumb = pyro.calls[-1]
    check("rename of a video: sent again as a video, duration and size kept, its thumbnail too",
          kind == "video" and name == "Episode 6.mp4" and (kw["duration"], kw["width"], kw["height"]) == (1440, 1920, 1080)
          and kw["supports_streaming"] and thumb == b"JPEG-thumb2" and video["content"] == "new_video_id", str(kw))

    pyro.fail = "FILE_REFERENCE_EXPIRED"
    broken = {"type": "document", "content": "old_doc2", "filename": "y.pdf", "caption": "c", "channel": "mychan"}
    context.user_data["posts"] = [broken]
    await rename(context, 0, "Chapter 2")
    await asyncio.gather(*rh._running)
    check("a rename that fails: the post keeps its file and name, the user told why",
          broken["content"] == "old_doc2" and broken["filename"] == "y.pdf" and not broken["renaming"]
          and "FILE_REFERENCE_EXPIRED" in bot.texts[-1], f"{broken} {bot.texts[-1]}")
    pyro.fail = None

    gone = {"type": "document", "content": "old_doc3", "filename": "z.zip", "caption": "", "channel": "mychan"}
    context.user_data["posts"] = [gone]
    await rename(context, 0, "Pack")
    context.user_data["posts"].clear()                    # « Delete » pressed while it is being renamed
    shown = len(bot.sent)
    await asyncio.gather(*rh._running)
    check("a file deleted while being renamed: no preview of it comes back", len(bot.sent) == shown, str(bot.sent[shown:]))

    calls = len(pyro.calls)
    photo = {"type": "photo", "content": "ph", "caption": "", "channel": "mychan"}
    context.user_data["posts"] = [photo]
    await rename(context, 0, "Cover")
    check("a photo: only its caption changes (nothing sent again)",
          len(pyro.calls) == calls and photo["caption"] == "Cover" and not rh._running
          and ("photo", "ph", "Cover", 5) in bot.sent)


asyncio.run(main())
print("\nALL OK" if ok else "\nFAILED")

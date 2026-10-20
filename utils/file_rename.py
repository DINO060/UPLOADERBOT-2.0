"""
Renaming a file for real: it is downloaded and sent again under its new name, so the channel gets the renamed
file. Done with Pyrogram logged in as this bot (utils/pyro_client): any size up to 2 GB, where the Bot API can only
download 20 MB. The file keeps its own thumbnail (or its channel's, once 🖼️ Thumbnail was applied) and, for a
video, its duration and size.
"""
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

PROGRESS_EVERY = 5.0          # seconds between two progress updates


def safe_name(name: str) -> str:
    """A file name without path separators or characters a disk refuses."""
    clean = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    return clean[:200] or "file"


def with_extension(new_name: str, old_name: Optional[str]) -> str:
    """« Show - 05 » for « x.mkv » → « Show - 05.mkv »: a title typed without its extension keeps the file's."""
    old_ext = os.path.splitext(old_name or "")[1]
    new_ext = os.path.splitext(new_name)[1]
    has_ext = 1 < len(new_ext) <= 6 and new_ext[1:].isalnum()
    return new_name if has_ext or not old_ext else new_name + old_ext


def _temp_root() -> str:
    try:
        from config.settings import TEMP_DIR
        Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)
        return str(TEMP_DIR)
    except Exception:
        return tempfile.gettempdir()


async def reupload(bot, chat_id: int, post: dict, new_name: str,
                   on_progress: Optional[Callable[[str, int], Awaitable[None]]] = None) -> str:
    """Downloads the post's file and sends it again as `new_name` in `chat_id` (that message is then deleted);
    returns the new file_id, usable by the Bot API. on_progress(« download » | « upload », percent)."""
    from utils.pyro_client import get_pyro
    pyro = await get_pyro()
    if pyro is None:
        raise RuntimeError("Pyrogram is not available on this bot")

    last = {"at": 0.0}

    async def progress(current, total, phase):
        if on_progress and total and time.monotonic() - last["at"] >= PROGRESS_EVERY:
            last["at"] = time.monotonic()
            await on_progress(phase, int(current * 100 / total))

    work = Path(tempfile.mkdtemp(prefix="rename_", dir=_temp_root()))
    try:
        source = await pyro.download_media(post["content"], file_name=str(work) + os.sep,
                                           progress=progress, progress_args=("download",))
        if not source or not os.path.exists(source):
            raise RuntimeError("download failed")
        target = work / safe_name(new_name)
        os.replace(source, target)

        thumb = None
        if post.get("thumb_path") and os.path.exists(post["thumb_path"]):
            thumb = post["thumb_path"]       # the channel's thumbnail (🖼️ Thumbnail), kept by later renames
        elif post.get("thumb_id"):          # the file's own thumbnail (small: the Bot API is enough)
            try:
                thumb_file = await bot.get_file(post["thumb_id"])
                thumb = str(await thumb_file.download_to_drive(str(work / "thumb.jpg")))
            except Exception:
                thumb = None

        last["at"] = 0.0
        if post.get("type") == "video":
            message = await pyro.send_video(
                chat_id, str(target), file_name=target.name, thumb=thumb, supports_streaming=True,
                duration=int(post.get("duration") or 0), width=int(post.get("width") or 0),
                height=int(post.get("height") or 0), progress=progress, progress_args=("upload",))
            media = message.video or message.document
        else:
            message = await pyro.send_document(
                chat_id, str(target), file_name=target.name, thumb=thumb, force_document=True,
                progress=progress, progress_args=("upload",))
            media = message.document
        try:
            await message.delete()
        except Exception:
            pass
        if not media:
            raise RuntimeError("Telegram returned no file")
        return media.file_id
    finally:
        shutil.rmtree(work, ignore_errors=True)

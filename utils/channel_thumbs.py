"""A thumbnail per channel: ⚙️ Settings → 🌐 Manage channels → a channel → 🖼️ Thumbnail. The picture is kept on
disk as Telegram wants a thumbnail (JPEG, at most 320 px a side, under 200 KB) and recorded in channel_thumbnails;
✏️ Edit File → 🖼️ Thumbnail then sends the file again with it (utils/file_rename.reupload, like a rename)."""
import io
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("UploaderBot")

BASE_DIR = Path(__file__).resolve().parent.parent
THUMB_DIR = BASE_DIR / "data" / "thumbnails"
MAX_SIDE = 320
MAX_BYTES = 200 * 1024


def clean(channel: str) -> str:
    return (channel or "").strip().lstrip("@")


def _file(user_id: int, channel: str) -> Path:
    return THUMB_DIR / f"{int(user_id)}_{clean(channel).lower()}.jpg"


def to_thumbnail(data: bytes) -> bytes:
    """Any picture → a JPEG Telegram accepts as a thumbnail."""
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    for quality in (90, 80, 70, 60, 50, 40):
        out = io.BytesIO()
        img.save(out, "JPEG", quality=quality, optimize=True)
        if out.tell() <= MAX_BYTES:
            break
    return out.getvalue()


async def save(bot, user_id: int, channel: str, file_id: str) -> Path:
    """Downloads the picture the user sent, makes it a thumbnail, keeps it for this channel."""
    tg_file = await bot.get_file(file_id)
    raw = bytes(await tg_file.download_as_bytearray())
    path = _file(user_id, channel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(to_thumbnail(raw))
    from database.manager import DatabaseManager
    DatabaseManager().save_thumbnail(clean(channel), user_id, file_id, str(path))
    return path


def path_for(user_id: int, channel: str) -> Optional[str]:
    """This channel's thumbnail on disk, or None."""
    if not clean(channel):
        return None
    path = _file(user_id, channel)
    if path.exists():
        return str(path)
    try:                                       # recorded before (another file name): its local copy
        from database.manager import DatabaseManager
        rec = DatabaseManager().get_thumbnail(clean(channel), user_id) or {}
        local = rec.get("local_path") if isinstance(rec, dict) else None
        return local if local and os.path.exists(local) else None
    except Exception:
        return None


def delete(user_id: int, channel: str) -> None:
    try:
        _file(user_id, channel).unlink(missing_ok=True)
    except OSError:
        pass
    try:
        from database.manager import DatabaseManager
        DatabaseManager().delete_thumbnail(clean(channel), user_id)
    except Exception:
        logger.warning("thumbnail of @%s not removed from the database", clean(channel), exc_info=True)

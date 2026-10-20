"""⏱️ Auto-destruction: a post published in a channel is deleted after the time chosen (5 min … 24 h).

Every deletion of a minute or more is written to data/auto_destruction.json and a loop deletes it when due, so a
restart of the bot loses none (it used to be a timer in memory: after a restart, a « 24 h » post stayed forever).
Shorter ones (the bot's own « ✅ … » notes, 2 s) stay a plain timer.
"""
import asyncio
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("UploaderBot")

BASE_DIR = Path(__file__).resolve().parent.parent
PENDING = BASE_DIR / "data" / "auto_destruction.json"
SHORT = 60                 # below this: a timer in memory
EVERY = 30                 # seconds between two looks at the list
_tasks: set = set()


def _load() -> list:
    try:
        return json.loads(PENDING.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(rows: list) -> None:
    try:
        PENDING.parent.mkdir(parents=True, exist_ok=True)
        PENDING.write_text(json.dumps(rows), encoding="utf-8")
    except OSError:
        logger.warning("auto-destruction list not saved", exc_info=True)


def schedule(bot, chat_id, message_id: int, delay: float) -> None:
    """Delete this message in `delay` seconds."""
    delay = max(0, int(delay or 0))
    if delay >= SHORT:
        rows = _load()
        rows.append([chat_id, int(message_id), time.time() + delay])
        _save(rows)
        return

    async def later():
        await asyncio.sleep(delay)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            logger.info(f"auto-deletion of {chat_id}/{message_id}: {e}")

    task = asyncio.create_task(later())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def delete_due(bot) -> int:
    """Deletes what is due; the rest stays listed. Returns how many were deleted."""
    rows, keep, done = _load(), [], 0
    now = time.time()
    for chat_id, message_id, due in rows:
        if due > now:
            keep.append([chat_id, message_id, due])
            continue
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            done += 1
        except Exception as e:                  # already deleted by hand, bot no longer admin… : not retried
            logger.info(f"auto-deletion of {chat_id}/{message_id} failed: {e}")
    if len(keep) != len(rows):
        _save(keep)
    return done


async def loop(bot) -> None:
    """For the bot's lifetime (started in post_init): also catches up on what came due while it was off."""
    while True:
        try:
            await delete_due(bot)
        except Exception:
            logger.warning("auto-destruction loop", exc_info=True)
        await asyncio.sleep(EVERY)

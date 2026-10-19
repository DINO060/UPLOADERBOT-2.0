"""
Sending to a channel without losing a post to Telegram's flood control or to a passing network error.
"""
import asyncio
import logging

from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut

logger = logging.getLogger(__name__)

MAX_FLOOD_WAIT = 300          # Telegram asks to wait longer than this: the post fails (and is reported)
MAX_FLOOD_TRIES = 5
NETWORK_WAITS = (3, 10, 30)   # a timeout / network error: tried again after these waits


def _seconds(value) -> float:
    return value.total_seconds() if hasattr(value, "total_seconds") else float(value or 0)


async def send_with_retry(coro_factory, description: str = "post"):
    """Telegram's « retry in N s » is really waited for (it used to be capped at 2 s, and the post was dropped
    after 3 tries); a timeout or a network error is tried again after NETWORK_WAITS; anything else (wrong
    file, bot not admin…) is raised at once."""
    flood_tries = network_tries = 0
    while True:
        try:
            return await coro_factory()
        except RetryAfter as e:
            wait = _seconds(e.retry_after) + 1
            flood_tries += 1
            if wait > MAX_FLOOD_WAIT or flood_tries > MAX_FLOOD_TRIES:
                raise
            logger.warning(f"⏳ Flood control: {description} sent again in {wait:.0f}s")
            await asyncio.sleep(wait)
        except BadRequest:
            raise
        except (TimedOut, NetworkError) as e:
            if network_tries >= len(NETWORK_WAITS):
                raise
            wait = NETWORK_WAITS[network_tries]
            network_tries += 1
            logger.warning(f"⏳ {type(e).__name__} ({e}): {description} sent again in {wait}s")
            await asyncio.sleep(wait)

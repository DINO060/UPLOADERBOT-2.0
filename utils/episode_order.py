"""
Episode numbers in file names, to publish a batch in the right order.

Files picked together on a phone often reach the bot shuffled. When every file of a batch is an episode of the
same series ("Show - 03 [1080p].mkv", "Show S01E03", "Show Ep 3"…), the batch is put back in episode order.
Anything else (a cover photo, a text, two different series, a file without a number) keeps the order it came in.
"""
import re
from typing import List, Optional, Tuple

_SXE = re.compile(r"\bS(\d{1,2})\s*[._ -]?\s*E(\d{1,4})(?!\d)", re.I)
_EP = re.compile(r"(?:\bEP|\bEPS|\bE|\bEpisode|\bÉpisode|\bEpisodio|\bFolge)\s*[._#-]?\s*(\d{1,4})(?!\d)", re.I)
_DASH = re.compile(r"\s[-–]\s*(\d{1,4})(?:v\d)?(?=$|[\s\[\(._-])")
_NUM = re.compile(r"(?<![\dA-Za-z])(\d{1,4})(?![\dA-Za-z])")
_EXT = re.compile(r"\.[A-Za-z0-9]{2,4}$")


def _series(prefix: str) -> str:
    return re.sub(r"[^0-9a-zà-ÿ]+", "", prefix.lower())


def episode_of(text: Optional[str]) -> Optional[Tuple[str, int, int]]:
    """(series, season, episode) read from a file name or a caption, or None when there is no episode number."""
    if not text or not text.strip():
        return None
    stem = _EXT.sub("", text.strip().splitlines()[0])
    m = _SXE.search(stem)
    if m:
        return _series(stem[:m.start()]), int(m.group(1)), int(m.group(2))
    m = _EP.search(stem)
    if m:
        return _series(stem[:m.start()]), 0, int(m.group(1))
    found = list(_DASH.finditer(stem))
    if not found:            # a bare number, but not a resolution (1080p), a codec (x264) or a year
        found = [n for n in _NUM.finditer(stem) if not 1900 <= int(n.group(1)) <= 2099]
    if not found:
        return None
    m = found[-1]
    return _series(stem[:m.start()]), 0, int(m.group(1))


def in_episode_order(posts: List[dict]) -> Tuple[List[dict], bool]:
    """The posts in episode order when they are all episodes of one series and came shuffled (True), otherwise
    exactly as they are (False). Two files of the same episode (VF and VOSTFR…) keep their own order."""
    if len(posts) < 2:
        return posts, False
    keys = []
    for post in posts:
        if post.get("type") not in ("video", "document"):
            return posts, False
        ep = episode_of(post.get("filename")) or episode_of(post.get("caption"))
        if not ep:
            return posts, False
        keys.append(ep)
    if len({k[0] for k in keys}) != 1:
        return posts, False
    order = sorted(range(len(posts)), key=lambda i: (keys[i][1], keys[i][2], i))
    if order == list(range(len(posts))):
        return posts, False
    return [posts[i] for i in order], True

import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, Optional

BASE = Path(__file__).parent
LOCALES_DIR = BASE / "locales"
DB_PATH = BASE / "bot.db"  # Utilise la DB existante

DEFAULT_LANG = "en"
SUPPORTED = {
    "en": {"name": "English", "flag": "🇬🇧"},
    "fr": {"name": "Français", "flag": "🇫🇷"},
}

_translations: Dict[str, Dict[str, str]] = {}


def init_db():
    """Initialize the database with user preferences table"""
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id INTEGER PRIMARY KEY,
                lang TEXT NOT NULL DEFAULT 'en'
            )
        """)
        con.commit()


def load_translations():
    """Load all translation files"""
    global _translations
    _translations = {}
    
    for lang in SUPPORTED.keys():
        p = LOCALES_DIR / f"{lang}.json"
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                _translations[lang] = json.load(f)
        else:
            print(f"Warning: Translation file {p} not found")


def set_user_lang(user_id: int, lang: str):
    """Set user language preference"""
    if lang not in SUPPORTED:
        raise ValueError(f"Unsupported language: {lang}")
    
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO user_prefs(user_id, lang) VALUES(?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET lang=excluded.lang",
            (user_id, lang),
        )
        con.commit()


def get_user_lang(user_id: Optional[int] = None, fallback_lang_code: Optional[str] = None) -> str:
    """Get user language preference with fallback chain"""
    # 1) Database preference
    if user_id is not None:
        with sqlite3.connect(DB_PATH) as con:
            cur = con.execute("SELECT lang FROM user_prefs WHERE user_id=?", (user_id,))
            row = cur.fetchone()
            if row and row[0] in SUPPORTED:
                return row[0]

    # 2) DISABLED: Telegram language detection - Force English by default
    # if fallback_lang_code:
    #     code = fallback_lang_code.split("-")[0].lower()
    #     if code in SUPPORTED:
    #         return code

    # 3) Default - Always English unless explicitly set by user
    return DEFAULT_LANG


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Get translated text with variable substitution"""
    # Fallback chain: user lang -> default -> raw key
    msg = _translations.get(lang, {}).get(key)
    if msg is None:
        msg = _translations.get(DEFAULT_LANG, {}).get(key, key)
    
    try:
        return msg.format(**kwargs)
    except Exception:
        # If formatting variables missing, return unformatted
        return msg


def tn(lang: str, key_base: str, count: int, **kwargs: Any) -> str:
    """Get translated text with pluralization"""
    # Simple plural selection: .one / .other
    suffix = "one" if count == 1 else "other"
    key = f"{key_base}.{suffix}"
    return t(lang, key, count=count, **kwargs)


def lang_human(lang: str) -> str:
    """Get human-readable language name with flag"""
    meta = SUPPORTED.get(lang, {"name": lang, "flag": ""})
    return f"{meta['flag']} {meta['name']}".strip()


# Initialize on import
init_db()
load_translations()

import os
import json
from aiohttp import web
import jwt
from datetime import datetime, timedelta

from database.channel_repo import init_db, db

API_KEY = os.getenv("BOT_KNOWN_API_KEY", "")
WEBAPP_SSO_SECRET = os.getenv("WEBAPP_SSO_SECRET", "")
HTTP_HOST = os.getenv("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("HTTP_PORT", "5000"))
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "http://localhost:8888")  # Used for SSO links if needed


async def require_api_key(request: web.Request):
    key = request.headers.get("X-Api-Key")
    if not key or key != API_KEY:
        raise web.HTTPForbidden(text="Forbidden")


def rows_to_dicts(rows):
    cols = ["id", "tg_chat_id", "title", "username", "bot_is_admin"]
    return [dict(zip(cols, r)) for r in rows]


async def known_channels(request: web.Request):
    await require_api_key(request)
    # Return channels where bot_is_admin = 1
    with db() as cx:
        rows = cx.execute(
            "SELECT id,tg_chat_id,title,username,bot_is_admin FROM channels WHERE bot_is_admin=1 ORDER BY created_at DESC"
        ).fetchall()
        items = rows_to_dicts(rows)
    return web.json_response({
        "success": True,
        "channels": [
            {
                "tg_chat_id": it["tg_chat_id"],
                "title": it["title"],
                "username": it["username"],
                "bot_is_admin": bool(it["bot_is_admin"]),
            }
            for it in items
        ],
        "total": len(items),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })


async def generate_sso(request: web.Request):
    await require_api_key(request)
    if not WEBAPP_SSO_SECRET:
        raise web.HTTPInternalServerError(text="Missing WEBAPP_SSO_SECRET")

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    uid = payload.get("uid")
    redirect = payload.get("redirect", "/channels")
    if not uid:
        raise web.HTTPBadRequest(text="Missing uid")

    token = jwt.encode({
        "uid": int(uid),
        "redirect": redirect,
        "iat": int(datetime.utcnow().timestamp()),
        "exp": int((datetime.utcnow() + timedelta(minutes=10)).timestamp()),
    }, WEBAPP_SSO_SECRET, algorithm="HS256")

    sso_link = f"{SITE_BASE_URL}/sso/telegram?token={token}"
    return web.json_response({
        "success": True,
        "token": token,
        "sso_link": sso_link,
        "expires_in": 600,
    })


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/internal/known-channels", known_channels)
    app.router.add_post("/internal/generate-sso", generate_sso)
    return app


def main():
    # Ensure DB initialized
    try:
        init_db()
    except Exception:
        pass

    app = create_app()
    web.run_app(app, host=HTTP_HOST, port=HTTP_PORT)


if __name__ == "__main__":
    main()

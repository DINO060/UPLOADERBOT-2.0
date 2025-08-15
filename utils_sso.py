import os
import time
import secrets
import jwt  # PyJWT

WEBAPP_SSO_SECRET = os.environ.get("WEBAPP_SSO_SECRET", "supersecretkey123456789")
WEBAPP_BASE_URL = os.environ.get("WEBAPP_BASE_URL", "http://localhost:5173")

def make_sso_link(user_id: int, redirect="/channels"):
    """
    Crée un lien SSO de 60 secondes vers ton site.
    """
    iat = int(time.time())
    payload = {
        "uid": user_id,
        "iat": iat,
        "exp": iat + 60,  # valide 60s
        "nonce": secrets.token_hex(8),
        "redirect": redirect
    }
    token = jwt.encode(payload, WEBAPP_SSO_SECRET, algorithm="HS256")
    return f"{WEBAPP_BASE_URL}/sso/telegram?token={token}"

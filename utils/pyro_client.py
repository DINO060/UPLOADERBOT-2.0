"""
Client Pyrogram global pour le bot Telegram
Ce module expose le client Pyrogram global qui est démarré/arrêté par PTB
"""

# Le client global sera défini dans bot.py et importé ici
PYRO = None

def set_global_pyro_client(client):
    """Définit le client Pyrogram global"""
    global PYRO
    PYRO = client

def get_global_pyro_client():
    """Récupère le client Pyrogram global"""
    return PYRO

def is_pyro_available():
    """Vérifie si le client Pyrogram est disponible"""
    return PYRO is not None and PYRO.is_connected

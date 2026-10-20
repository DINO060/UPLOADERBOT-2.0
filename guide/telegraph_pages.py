"""Publishes, or updates, the bot's Telegraph guide in English and French: python guide/telegraph_pages.py <commit>.
The pictures are served by jsDelivr from this public repo at that commit (guide/img, made by build_guide.py).
The Telegraph token stays out of every repo (~/.telegraph_accounts.json): it can edit the pages."""
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ACCOUNTS = Path.home() / ".telegraph_accounts.json"     # never in a repo: the token edits the pages
KEY = "uploaderbot"
NAME = "Uploader Bot"
BOT_URL = ""                                            # t.me/<username> once known: adds « Open the bot »
COMMIT = sys.argv[1] if len(sys.argv) > 1 else "main"
IMG = f"https://cdn.jsdelivr.net/gh/DINO060/UPLOADERBOT-2.0@{COMMIT}/guide/img/"


def api(method, **params):
    data = urllib.parse.urlencode({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                                   for k, v in params.items()}).encode()
    with urllib.request.urlopen(urllib.request.Request(f"https://api.telegra.ph/{method}", data=data), timeout=30) as r:
        res = json.load(r)
    if not res.get("ok"):
        raise RuntimeError(f"{method}: {res.get('error')}")
    return res["result"]


def node(tag, *children, **attrs):
    n = {"tag": tag, "children": [c for c in children if c not in (None, "")]}
    if attrs:
        n["attrs"] = attrs
    return n


def p(*c): return node("p", *c)
def h3(t): return node("h3", t)
def b(t): return node("b", t)
def code(t): return node("code", t)
def a(t, href): return node("a", t, href=href)
def ul(*items): return node("ul", *[node("li", *(i if isinstance(i, tuple) else (i,))) for i in items])
def fig(name, caption): return node("figure", node("img", src=IMG + name), node("figcaption", caption))
def video(name, caption): return node("figure", node("video", src=IMG + name), node("figcaption", caption))


def english(other_url):
    return [
        p(NAME, " publishes your files to ", b("your Telegram channels"), ": up to 30 per post, ", b("episodes in order"),
          ", reactions your members tap, link buttons, files really renamed — ", b("now or scheduled"), "."),
        video("explainer_en.mp4", "The bot in 30 seconds"),
        p(a("🇫🇷 Version française", other_url)) if other_url else None,
        h3("1. Add your channel (once)"),
        p("Make the bot an ", b("administrator"), " of your channel (it posts there, and deletes for auto-destruction). Then send ",
          code("/addchannel @yourchannel"), " — or the t.me link — or use ⚙️ Settings → 🌐 Manage channels → ➕ Add channel."),
        h3("2. Create a post"),
        p("📝 ", b("New post"), " → choose the channel → send your files: videos, documents, photos or text, ", b("up to 30"), "."),
        p("Each file comes back with its buttons. At the bottom: 📋 Preview, 🚀 Send, 🗑️ Delete all, ❌ Cancel."),
        fig("flow_post.gif", "Channel, files, Send now: in your channel, in order"),
        h3("3. Dress up each file"),
        ul((b("✨ Add Reactions"), " — ", code("👍/❤️/🔥"), " (up to 8): your members tap them, each tap is counted."),
           (b("🔗 Add URL Button"), " — ", code("Watch in HD | https://…"), ": a link under the file."),
           (b("✏️ Edit File → Rename"), " — the file itself gets its new name (up to 2 GB), its caption too."),
           (b("❌ Delete"), " — removes this file from the post.")),
        fig("flow_dressup.gif", "Reactions, a link button, a new name"),
        h3("4. Send now"),
        ul(("🚀 Send → ", b("📤 Send now"), "."),
           ("Episodes sent together go out ", b("in episode order"), " (01, 02, 03…), even if they arrived mixed up."),
           "If one can't be sent, the summary names it and keeps it: 🚀 Send tries it again.",
           (b("⏱️ Set auto-destruction time"), " — the posts are deleted from the channel after 5 min … 24 h.")),
        fig("channel_post.png", "In your channel: in order, reactions counted, your link"),
        h3("5. Schedule"),
        ul(("🚀 Send → ", b("📅 Schedule"), " → Today, Tomorrow or Overmorrow → send the time: ", code("20:30"), ", ",
            code("2030"), ", ", code("6"), " (06:00), ", code("5 3"), " (05:03)."),
           ("In your timezone: ⚙️ Settings → 🕐 Timezone (Paris by default)."),
           "If the bot was offline at that time, the late posts go out as soon as it's back, in order — and you're told.",
           ("📅 ", b("Scheduled posts"), " (main menu) lists your next 10 with their channel; open one to edit or cancel it.")),
        fig("flow_schedule.gif", "Tomorrow at 20:30, then the list of your scheduled posts"),
        h3("6. Settings"),
        ul((b("🌐 Manage channels"), " — add or remove a channel."), (b("🕐 Timezone"), " — for your scheduled posts."),
           (b("🌐 Language"), " — the bot's language.")),
        fig("settings.png", "Settings, and the auto-destruction durations"),
        fig("features.png", "What one post can do"),
        h3("Commands"),
        ul((code("/start"), " — main menu"), (code("/addchannel"), " — add a channel"), (code("/settings"), " — settings"),
           (code("/help"), " — help and this guide")),
        h3("Good to know"),
        ul("If the bot asks you to join a channel first, join it, then tap ✅ I have joined.",
           "After the bot restarts, an old button may say it has expired: tap ↩️ Main menu or send /start.",
           "When the bot gets new features, it tells you what's new — once (the message disappears after 6 h)."),
        p(a("👉 Open the bot", BOT_URL)) if BOT_URL else None,
    ]


def french(other_url):
    return [
        p(NAME, " publie tes fichiers sur ", b("tes chaînes Telegram"), " : jusqu'à 30 par post, ", b("les épisodes dans l'ordre"),
          ", des réactions que tes membres touchent, des boutons lien, des fichiers vraiment renommés — ",
          b("tout de suite ou planifié"), "."),
        video("explainer_fr.mp4", "Le bot en 30 secondes"),
        p(a("🇬🇧 English version", other_url)) if other_url else None,
        h3("1. Ajoute ta chaîne (une fois)"),
        p("Mets le bot ", b("administrateur"), " de ta chaîne (il y publie, et supprime pour l'auto-destruction). Puis envoie ",
          code("/addchannel @tachaine"), " — ou le lien t.me — ou passe par ⚙️ Settings → 🌐 Manage channels → ➕ Add channel."),
        h3("2. Crée un post"),
        p("📝 ", b("New post"), " → choisis la chaîne → envoie tes fichiers : vidéos, documents, photos ou texte, ", b("jusqu'à 30"), "."),
        p("Chaque fichier revient avec ses boutons. En bas : 📋 Preview, 🚀 Send, 🗑️ Delete all, ❌ Cancel."),
        fig("flow_post.gif", "La chaîne, les fichiers, Send now : sur ta chaîne, dans l'ordre"),
        h3("3. Habille chaque fichier"),
        ul((b("✨ Add Reactions"), " — ", code("👍/❤️/🔥"), " (8 maximum) : tes membres les touchent, chaque clic est compté."),
           (b("🔗 Add URL Button"), " — ", code("Watch in HD | https://…"), " : un lien sous le fichier."),
           (b("✏️ Edit File → Rename"), " — le fichier lui-même prend son nouveau nom (jusqu'à 2 Go), sa légende aussi."),
           (b("❌ Delete"), " — retire ce fichier du post.")),
        fig("flow_dressup.gif", "Des réactions, un bouton lien, un nouveau nom"),
        h3("4. Envoie tout de suite"),
        ul(("🚀 Send → ", b("📤 Send now"), "."),
           ("Les épisodes envoyés ensemble partent ", b("dans l'ordre des épisodes"), " (01, 02, 03…), même s'ils sont arrivés mélangés."),
           "Si l'un d'eux ne peut pas partir, le résumé le nomme et le garde : 🚀 Send le réessaie.",
           (b("⏱️ Set auto-destruction time"), " — les posts sont supprimés de la chaîne après 5 min … 24 h.")),
        fig("channel_post.png", "Sur ta chaîne : dans l'ordre, réactions comptées, ton lien"),
        h3("5. Planifie"),
        ul(("🚀 Send → ", b("📅 Schedule"), " → Today, Tomorrow ou Overmorrow (après-demain) → envoie l'heure : ", code("20:30"), ", ",
            code("2030"), ", ", code("6"), " (06:00), ", code("5 3"), " (05:03)."),
           ("À ton fuseau horaire : ⚙️ Settings → 🕐 Timezone (Paris par défaut)."),
           "Si le bot était hors ligne à cette heure-là, les posts en retard partent dès son retour, dans l'ordre — et tu es prévenu.",
           ("📅 ", b("Scheduled posts"), " (menu principal) liste tes 10 prochains avec leur chaîne ; ouvre-en un pour le modifier ou l'annuler.")),
        fig("flow_schedule.gif", "Demain à 20:30, puis la liste de tes posts planifiés"),
        h3("6. Réglages"),
        ul((b("🌐 Manage channels"), " — ajouter ou retirer une chaîne."), (b("🕐 Timezone"), " — pour tes posts planifiés."),
           (b("🌐 Language"), " — la langue du bot.")),
        fig("settings.png", "Les réglages, et les durées d'auto-destruction"),
        fig("features.png", "Ce qu'un post peut faire"),
        h3("Commandes"),
        ul((code("/start"), " — menu principal"), (code("/addchannel"), " — ajouter une chaîne"), (code("/settings"), " — réglages"),
           (code("/help"), " — l'aide et ce guide")),
        h3("Bon à savoir"),
        ul("Si le bot te demande de rejoindre une chaîne d'abord, rejoins-la puis appuie sur ✅ I have joined.",
           "Après un redémarrage du bot, un ancien bouton peut dire qu'il a expiré : appuie sur ↩️ Main menu ou envoie /start.",
           "Quand le bot reçoit de nouvelles fonctions, il te dit ce qui change — une seule fois (le message disparaît après 6 h)."),
        p(a("👉 Ouvrir le bot", BOT_URL)) if BOT_URL else None,
    ]


def clean(nodes):
    return [n for n in nodes if n]


def main():
    accounts = json.loads(ACCOUNTS.read_text(encoding="utf-8")) if ACCOUNTS.exists() else {}
    acc = accounts.get(KEY) or {}
    author = {"author_name": NAME, **({"author_url": BOT_URL} if BOT_URL else {})}
    if not acc.get("token"):
        acc["token"] = api("createAccount", short_name=NAME[:32], **author)["access_token"]
        accounts[KEY] = acc
        ACCOUNTS.write_text(json.dumps(accounts, indent=2), encoding="utf-8")
    common = {"access_token": acc["token"], **author}
    titles = {"en": f"{NAME} — How to use it", "fr": f"{NAME} — Mode d'emploi"}

    def publish(lang, content):
        if acc.get(lang):
            return api(f"editPage/{acc[lang]}", title=titles[lang], content=clean(content), **common)
        return api("createPage", title=titles[lang], content=clean(content), **common)

    en = publish("en", english(f"https://telegra.ph/{acc['fr']}" if acc.get("fr") else None))
    acc["en"] = en["path"]
    fr = publish("fr", french(en["url"]))
    acc["fr"] = fr["path"]
    en = publish("en", english(fr["url"]))
    accounts[KEY] = acc
    ACCOUNTS.write_text(json.dumps(accounts, indent=2), encoding="utf-8")
    print("EN", en["url"])
    print("FR", fr["url"])


if __name__ == "__main__":
    main()

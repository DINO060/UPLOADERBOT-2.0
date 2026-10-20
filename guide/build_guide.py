"""Builds the pictures of the Telegraph guide (python guide/build_guide.py): Telegram-like screens with the bot's
real messages and buttons, animated GIFs of each flow, and a short explainer video in English and French.
Needs Playwright (Chromium), Pillow and ffmpeg. Everything lands in guide/img/."""
import html
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "img"
WORK = Path(tempfile.mkdtemp())
BOT = "Uploader Bot"
LETTER = "U"
FONT_BOLD = "C:/Windows/Fonts/segoeuib.ttf"

# ---------------------------------------------------------------------------------------------- demo pictures
def poster(path, size, title, sub):
    """A made-up episode cover (no real artwork): gradient, title, episode."""
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(20 + 60 * t), int(60 + 40 * (1 - t)), int(140 + 80 * (1 - t))))
    for i in range(6):                                  # soft circles
        r = int(w * (0.12 + 0.05 * i))
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse([w * 0.62 - r, h * 0.35 - r, w * 0.62 + r, h * 0.35 + r],
                                      outline=(255, 255, 255, 40 - 5 * i), width=max(2, w // 160))
        img.paste(layer, (0, 0), layer)
    big = ImageFont.truetype(FONT_BOLD, int(h * 0.34))
    small = ImageFont.truetype(FONT_BOLD, int(h * 0.1))
    for text, font, y, colour in ((title, small, 0.2, (255, 255, 255)), (sub, big, 0.36, (255, 214, 102))):
        width = d.textlength(text, font=font)       # centred: Telegram shows a square crop of the middle
        d.text(((w - width) / 2, int(h * y)), text, font=font, fill=colour)
    img.filter(ImageFilter.SMOOTH).save(path, quality=92)
    return path


# ---------------------------------------------------------------------------------------------- chat screens
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Color+Emoji&display=block');
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: transparent; font-family: 'Segoe UI', 'Segoe UI Emoji', 'Noto Color Emoji', sans-serif; }
.phone { width: 420px; background: #0e1621; border-radius: 22px; overflow: hidden; border: 1px solid #22303f; }
.top { display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: #17212b; }
.ava { width: 40px; height: 40px; border-radius: 50%; background: linear-gradient(135deg, #5fb3ff, #7d5fff);
       color: #fff; font: 700 19px 'Segoe UI'; display: flex; align-items: center; justify-content: center; }
.ava.ch { background: linear-gradient(135deg, #ffb35f, #ff5f7d); }
.name { color: #f5f5f5; font: 600 16px 'Segoe UI'; } .sub { color: #708499; font-size: 13px; }
.chat { padding: 14px 10px 10px; display: flex; flex-direction: column; gap: 6px; min-height: 120px; }
.row { display: flex; flex-direction: column; } .row.out { align-items: flex-end; } .row.in { align-items: flex-start; }
.b { max-width: 330px; padding: 8px 11px 6px; border-radius: 14px; color: #f5f5f5; font-size: 14.5px; line-height: 1.38;
     white-space: pre-wrap; word-wrap: break-word; }
.in .b { background: #182533; border-bottom-left-radius: 5px; } .out .b { background: #2b5278; border-bottom-right-radius: 5px; }
.t { float: right; font-size: 11px; color: #6d7f8f; margin: 6px 0 0 10px; } .out .t { color: #7da8d3; }
b, strong { font-weight: 700; } code { font-family: Consolas, monospace; color: #9cd3ff; font-size: 13.5px; }
a { color: #6ab3f3; text-decoration: none; }
.kb { width: 330px; display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
.kr { display: flex; gap: 4px; }
.k { flex: 1; text-align: center; padding: 9px 6px; border-radius: 9px; color: #fff; font: 600 13.5px 'Segoe UI';
     background: rgba(48, 70, 92, .85); }
.k.success { background: #2e9c4f; } .k.primary { background: #2f6fd8; } .k.danger { background: #d0453f; }
.k.url::after { content: ' ↗'; font-size: 11px; opacity: .8; }
.file { display: flex; gap: 11px; align-items: center; min-width: 250px; }
.ico { width: 46px; height: 46px; border-radius: 50%; background: #4a90d9; display: flex; align-items: center;
       justify-content: center; font-size: 22px; flex: none; }
.thumb { width: 54px; height: 54px; border-radius: 8px; object-fit: cover; flex: none; }
.fn { color: #f5f5f5; font-weight: 600; font-size: 14px; word-break: break-all; } .fs { color: #7f95a8; font-size: 12.5px; }
.out .fs { color: #9cc1e6; }
.ph { width: 300px; border-radius: 12px; display: block; }
.input { margin: 6px 10px 12px; padding: 10px 14px; background: #17212b; border-radius: 18px; color: #6d7f8f;
         font-size: 14px; }
.rk { background: #17212b; padding: 6px; display: flex; flex-direction: column; gap: 5px; }
.rk .kr .k { background: #2b3a4a; padding: 11px 6px; }
.chbar { background: #17212b; color: #6ab3f3; text-align: center; padding: 12px; font: 600 14px 'Segoe UI'; }
"""


def esc(s):
    return html.escape(s, quote=False)


def uri(path):
    """An image inside the page itself (a page made with set_content can't load local files)."""
    import base64
    data = Path(path).read_bytes()
    kind = "png" if str(path).endswith(".png") else "jpeg"
    return f"data:image/{kind};base64," + base64.b64encode(data).decode()


def keys(rows, cls="kb"):
    return (f'<div class="{cls}">' + "".join(
        '<div class="kr">' + "".join(f'<div class="k {style or ""}">{esc(text)}</div>' for text, style in row) + "</div>"
        for row in rows) + "</div>")


def bubble(m):
    side = m.get("side", "in")
    inner = ""
    if m.get("photo"):
        inner += f'<img class="ph" src="{uri(m["photo"])}">'
    if m.get("file"):
        f = m["file"]
        icon = (f'<img class="thumb" src="{uri(f["thumb"])}">' if f.get("thumb")
                else f'<div class="ico">{"🎬" if f.get("video") else "📄"}</div>')
        inner += f'<div class="file">{icon}<div><div class="fn">{esc(f["name"])}</div><div class="fs">{esc(f["size"])}</div></div></div>'
    if m.get("html"):
        inner += ("<div style='margin-top:6px'>" if m.get("file") or m.get("photo") else "<div>") + m["html"] + "</div>"
    inner += f'<span class="t">{m.get("time", "14:02")}</span>'
    out = f'<div class="row {side}"><div class="b">{inner}</div>'
    if m.get("buttons"):
        out += keys(m["buttons"])
    return out + "</div>"


def chat(screen):
    """A chat with the bot (with its bottom keyboard when it shows one), or the user's channel."""
    messages = screen["messages"]
    if screen.get("channel"):
        top = ("<div class='top'><div class='ava ch'>M</div><div><div class='name'>My Channel</div>"
               "<div class='sub'>2 481 subscribers</div></div></div>")
        bottom = "<div class='chbar'>🔇 Mute</div>"
    else:
        top = (f"<div class='top'><div class='ava'>{LETTER}</div><div><div class='name'>{BOT}</div>"
               f"<div class='sub'>bot</div></div></div>")
        bottom = (keys(screen["reply_kb"], "rk") if screen.get("reply_kb") else "<div class='input'>Message</div>")
    return (f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body><div class='phone'>{top}"
            f"<div class='chat'>{''.join(bubble(m) for m in messages)}</div>{bottom}</div></body></html>")


SLIDE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Color+Emoji&display=block');
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 1280px; height: 720px; font-family: 'Segoe UI', 'Segoe UI Emoji', 'Noto Color Emoji', sans-serif; overflow: hidden;
       background: radial-gradient(circle at 20% 20%, #1e3a5f 0%, #0b1320 60%); color: #fff; display: flex;
       align-items: center; padding: 0 70px; gap: 60px; }
.txt { flex: 1; } .step { color: #6ab3f3; font: 700 22px 'Segoe UI'; letter-spacing: 1px; margin-bottom: 14px; }
h1 { font: 800 50px 'Segoe UI'; line-height: 1.1; margin-bottom: 20px; } p { font-size: 25px; color: #c6d4e1; line-height: 1.45; }
.shot { height: 640px; display: flex; align-items: center; } .shot img { max-height: 640px; max-width: 520px; border-radius: 22px;
       box-shadow: 0 20px 60px rgba(0,0,0,.5); }
.center { flex-direction: column; justify-content: center; text-align: center; padding: 0 140px; gap: 0; }
.center h1 { font-size: 64px; } .center p { font-size: 28px; }
.logo { width: 120px; height: 120px; border-radius: 50%; margin: 0 auto 30px; background: linear-gradient(135deg, #5fb3ff, #7d5fff);
        display: flex; align-items: center; justify-content: center; font: 800 58px 'Segoe UI'; }
"""


def slide(step, title, text, shot=None):
    body = (f"<div class='txt'><div class='step'>{esc(step)}</div><h1>{esc(title)}</h1><p>{esc(text)}</p></div>"
            + (f"<div class='shot'><img src='{uri(shot)}'></div>" if shot else ""))
    return f"<html><head><meta charset='utf-8'><style>{SLIDE_CSS}</style></head><body>{body}</body></html>"


def title_slide(title, text, cta=""):
    return (f"<html><head><meta charset='utf-8'><style>{SLIDE_CSS}</style></head><body class='center'>"
            f"<div class='logo'>{LETTER}</div><h1>{esc(title)}</h1><p>{esc(text)}</p>"
            + (f"<p style='margin-top:26px;color:#6ab3f3;font-weight:700'>{esc(cta)}</p>" if cta else "") + "</body></html>")


# ---------------------------------------------------------------------------------------------- the content
EDIT_KB = [[("✨ Add Reactions", "success")], [("🔗 Add URL Button", "primary")], [("✏️ Edit File", "primary")],
           [("❌ Delete", "danger")]]
REPLY_KB = [[("📋 Preview", None), ("🚀 Send", None)], [("🗑️ Delete all", None), ("❌ Cancel", None)]]


def ep(n, tag=""):
    return f"Blue Horizon - {n:02d} [1080p]{tag}.mkv"


def screens(thumbs, cover):
    T = "14:02"
    home = ("👋 Welcome to Rename & Scheduler Bot!\n\nI help you rename captions/filenames and schedule your posts to "
            "your channels.\n\n📋 Features:\n• Rename caption/filename\n• Schedule post sending\n\n🎯 Commands:\n"
            "/start - Show this message\n/help - Show help and usage\n/addchannel - Add a new channel\n/settings - Open settings")
    menu = [[("📝 New post", "success")], [("📅 Scheduled posts", "primary")], [("⚙️ Settings", "primary")]]
    return {
        "start": {"messages": [
            {"side": "out", "html": "/start", "time": T},
            {"html": home, "buttons": menu, "time": T},
        ]},
        "addchannel": {"messages": [
            {"side": "out", "html": "/addchannel @mychannel", "time": "14:03"},
            {"html": "✅ Channel added!\n\n📺 My Channel (@mychannel)", "time": "14:03"},
            {"side": "out", "html": "📝 New post", "time": "14:04"},
            {"html": "📝 Select a channel for your post:\n\n• Choose an existing channel, or\n• Add a new channel", "time": "14:04",
             "buttons": [[("My Channel", None), ("Anime VF", None)], [("➕ Add channel", None)], [("↩️ Main menu", None)]]},
        ]},
        "channel": {"messages": [
            {"html": "📺 Selected channel: <b>My Channel</b>\n\nNow send your content:\n• 📝 Text\n• 🖼️ Photo\n• 🎥 Video\n"
                     "• 📄 Document", "buttons": [[("❌ Cancel", None)]], "time": "14:04"},
            *[{"side": "out", "file": {"name": ep(n), "size": "348 MB", "video": True}, "time": "14:05"} for n in (3, 1, 2)],
        ]},
        "files": {"reply_kb": REPLY_KB, "messages": [
            {"file": {"name": ep(2), "size": "348 MB", "thumb": thumbs[2]}, "html": "Blue Horizon - 02 [1080p]",
             "buttons": EDIT_KB, "time": "14:05"},
            {"html": "✅ 3/30 • Channel: My Channel", "time": "14:05"},
        ]},
        "reactions": {"reply_kb": REPLY_KB, "messages": [
            {"html": "📝 Send me the reactions, separated by '/'.\nExample: 👍/❤️/🔥/😂\n\nUp to 8 reactions.",
             "buttons": [[("❌ Cancel", None)]], "time": "14:06"},
            {"side": "out", "html": "👍/❤️/🔥", "time": "14:06"},
            {"html": "📝 Send me the URL button as:\nButton text | URL\n\nExample: Visit the site | https://example.com",
             "time": "14:06"},
            {"side": "out", "html": "▶️ Watch in HD | https://example.com/blue-horizon", "time": "14:07"},
        ]},
        "dressed": {"reply_kb": REPLY_KB, "messages": [
            {"file": {"name": ep(2), "size": "348 MB", "thumb": thumbs[2]}, "html": "Blue Horizon - 02 [1080p]", "time": "14:07",
             "buttons": [[("👍", None), ("❤️", None), ("🔥", None)], [("▶️ Watch in HD", "url")],
                         [("🗑️ Remove Reactions", None)], [("Remove URL Buttons", None)], [("✏️ Edit File", "primary")],
                         [("❌ Delete", "danger")]]},
        ]},
        "rename": {"reply_kb": REPLY_KB, "messages": [
            {"html": "✏️ <b>Edit file 2</b>\n\nType: video\nChoose an action:", "buttons": [[("✏️ Rename", "success")]],
             "time": "14:08"},
            {"html": "✏️ <b>Rename file 2</b>\n\nSend the new name/title for this file:", "time": "14:08"},
            {"side": "out", "html": "Blue Horizon - 02 VF @MyChannel", "time": "14:08"},
            {"file": {"name": "Blue Horizon - 02 VF @MyChannel.mkv", "size": "348 MB", "thumb": thumbs[2]},
             "html": "Blue Horizon - 02 VF @MyChannel", "time": "14:09"},
            {"html": "✅ File renamed: <code>Blue Horizon - 02 VF @MyChannel.mkv</code>", "time": "14:09"},
        ]},
        "send": {"messages": [
            {"side": "out", "html": "🚀 Send", "time": "14:10"},
            {"html": "Your 3 files are ready to be sent to @mychannel.\nWhen would you like to send them?", "time": "14:10",
             "buttons": [[("⏱️ Set auto-destruction time", None)], [("📤 Send now", "success")], [("📅 Schedule", "primary")],
                         [("↩️ Back", None)]]},
            {"side": "out", "html": "📤 Send now", "time": "14:10"},
            {"html": "✅ Sent!\n\n3 post(s) sent to @mychannel\n\n🔢 Put back in episode order (the files arrived shuffled).",
             "buttons": [[("↩️ Main menu", None)]], "time": "14:11"},
        ]},
        "channel_post": {"channel": True, "messages": [
            *[{"file": {"name": ep(n), "size": "348 MB", "thumb": thumbs[n]}, "html": f"Blue Horizon - {n:02d} [1080p]",
               "time": "14:11"} for n in (1,)],
            {"file": {"name": "Blue Horizon - 02 VF @MyChannel.mkv", "size": "348 MB", "thumb": thumbs[2]},
             "html": "Blue Horizon - 02 VF @MyChannel", "time": "14:11",
             "buttons": [[("👍 128", None), ("❤️ 54", None), ("🔥 31", None)], [("▶️ Watch in HD", "url")]]},
            {"file": {"name": ep(3), "size": "348 MB", "thumb": thumbs[3]}, "html": "Blue Horizon - 03 [1080p]", "time": "14:11"},
        ]},
        "schedule": {"messages": [
            {"html": "📅 Choose when to send your post:\n\n1️⃣ Select the day (Today, Tomorrow, or Overmorrow)\n"
                     "2️⃣ Send the time in one of these formats:\n   • '15:30' or '1530' (24h)\n   • '6' (06:00)\n"
                     "   • '5 3' (05:03)\n\n✅ Selected day: Tomorrow", "time": "15:00",
             "buttons": [[("Today", None), ("Tomorrow ✅", None), ("Overmorrow", None)], [("↩️ Back", None)]]},
            {"side": "out", "html": "20:30", "time": "15:00"},
            {"html": "✅ 3 file(s) scheduled for tomorrow at 20:30\n🌍 Timezone: Paris (Europe/Paris)\n\n"
                     "🔢 Put back in episode order (the files arrived shuffled).", "buttons": [[("↩️ Main menu", None)]],
             "time": "15:00"},
        ]},
        "scheduled": {"messages": [
            {"side": "out", "html": "📅 Scheduled posts", "time": "16:00"},
            {"html": "📅 Scheduled posts:\n\n• 2026-10-20 20:30 - My Channel\n• 2026-10-20 20:30 - My Channel\n"
                     "• 2026-10-20 20:30 - My Channel\n• 2026-10-21 18:00 - Anime VF", "time": "16:00",
             "buttons": [[("2026-10-20 20:30 - My Channel", None)], [("2026-10-20 20:30 - My Channel", None)],
                         [("2026-10-20 20:30 - My Channel", None)], [("2026-10-21 18:00 - Anime VF", None)],
                         [("↩️ Main menu", None)]]},
        ]},
        "settings": {"messages": [
            {"side": "out", "html": "⚙️ Settings", "time": "17:00"},
            {"html": "⚙️ <b>Custom settings</b>\n\nChoose an option:", "time": "17:00",
             "buttons": [[("🌐 Manage channels", None)], [("🕐 Timezone", None)], [("🌐 Language", None)], [("↩️ Main menu", None)]]},
            {"html": "⏰ <b>Auto-destruction</b>\n\nAfter how long should the posts be deleted from your channel?\n\n"
                     "Choose a duration:", "time": "17:01",
             "buttons": [[("5 minutes", None), ("30 minutes", None), ("1 hour", None)], [("6 hours", None), ("24 hours", None)],
                         [("❌ Disable", None)], [("↩️ Back", None)]]},
        ]},
    }


NAMES_CARD = """<html><head><meta charset='utf-8'><style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Color+Emoji&display=block');
body { margin: 0; font-family: 'Segoe UI', 'Segoe UI Emoji', 'Noto Color Emoji'; background: transparent; }
.c { width: 640px; background: #0e1621; border: 1px solid #22303f; border-radius: 20px; padding: 26px 28px; color: #f5f5f5; }
h3 { font-size: 19px; margin-bottom: 14px; } .r { display: flex; gap: 12px; padding: 9px 0; border-top: 1px solid #1d2a37; }
.r:first-of-type { border-top: 0; } .k { font: 600 15px 'Segoe UI'; color: #9cd3ff; width: 170px; flex: none; }
.d { color: #c6d4e1; font-size: 14.5px; line-height: 1.4; }
</style></head><body><div class='c'><h3>📦 What one post can do</h3>
<div class='r'><div class='k'>📁 30 files</div><div class='d'>Videos, documents, photos or text — up to 30 in one post</div></div>
<div class='r'><div class='k'>🔢 Episode order</div><div class='d'>Episodes sent together go out 01, 02, 03… even if they arrived mixed up</div></div>
<div class='r'><div class='k'>✨ Reactions</div><div class='d'>Up to 8 buttons your members tap — each one counted</div></div>
<div class='r'><div class='k'>🔗 URL button</div><div class='d'><code>Text | https://…</code> under the file</div></div>
<div class='r'><div class='k'>✏️ Rename</div><div class='d'>The file itself gets its new name — up to 2 GB</div></div>
<div class='r'><div class='k'>📅 Schedule</div><div class='d'>Today, tomorrow or overmorrow, at your time, in your timezone</div></div>
<div class='r'><div class='k'>⏱️ Auto-destruction</div><div class='d'>Deleted from the channel after 5 min … 24 h</div></div>
<div class='r'><div class='k'>🔁 Restart-proof</div><div class='d'>Scheduled posts still go out after the bot restarts — late ones are sent, in order</div></div>
</div></body></html>"""

FLOWS = {"post": ["addchannel", "channel", "files", "send", "channel_post"],
         "dressup": ["reactions", "dressed", "rename"],
         "schedule": ["schedule", "scheduled"]}

VIDEO = {
    "en": [("title", BOT, "Post your files to your channels — in order, with reactions, link buttons and clean names. Now or later.",
            "Open the bot and send /addchannel"),
           ("addchannel", "STEP 1", "Add your channel", "/addchannel @yourchannel — the bot must be an admin there. Then 📝 New post."),
           ("files", "STEP 2", "Send your files", "Up to 30 per post: videos, documents, photos, text."),
           ("dressed", "STEP 3", "Dress up each file", "Reactions your members tap, and a link button."),
           ("rename", "RENAME", "A clean file name", "✏️ Edit File → Rename: the file itself is renamed, up to 2 GB."),
           ("send", "STEP 4", "Send now", "Episodes sent together go out in episode order."),
           ("channel_post", "IN YOUR CHANNEL", "Ready for your members", "In order, with counters on the reactions and your link."),
           ("schedule", "LATER", "…or schedule it", "Today, tomorrow or overmorrow, at your time — even if the bot restarts."),
           ("title", BOT, "Your channel, fed on time.", "Send /start to begin")],
    "fr": [("title", BOT, "Publie tes fichiers sur tes chaînes — dans l'ordre, avec réactions, bouton lien et noms propres. Maintenant ou plus tard.",
            "Ouvre le bot et envoie /addchannel"),
           ("addchannel", "ÉTAPE 1", "Ajoute ta chaîne", "/addchannel @tachaine — le bot doit y être admin. Puis 📝 New post."),
           ("files", "ÉTAPE 2", "Envoie tes fichiers", "Jusqu'à 30 par post : vidéos, documents, photos, texte."),
           ("dressed", "ÉTAPE 3", "Habille chaque fichier", "Des réactions que tes membres touchent, et un bouton lien."),
           ("rename", "RENOMMER", "Un nom de fichier propre", "✏️ Edit File → Rename : le fichier lui-même est renommé, jusqu'à 2 Go."),
           ("send", "ÉTAPE 4", "Envoie maintenant", "Les épisodes envoyés ensemble partent dans l'ordre des épisodes."),
           ("channel_post", "SUR TA CHAÎNE", "Prêt pour tes membres", "Dans l'ordre, avec les compteurs de réactions et ton lien."),
           ("schedule", "PLUS TARD", "…ou planifie-le", "Aujourd'hui, demain ou après-demain, à ton heure — même si le bot redémarre."),
           ("title", BOT, "Ta chaîne, alimentée à l'heure.", "Envoie /start pour commencer")],
}


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def main():
    OUT.mkdir(exist_ok=True)
    thumbs = {n: poster(WORK / f"thumb{n}.jpg", (320, 180), "BLUE HORIZON", f"EP {n:02d}") for n in (1, 2, 3)}
    cover = poster(WORK / "cover.jpg", (640, 360), "BLUE HORIZON", "EP 02")
    shots = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=2, viewport={"width": 700, "height": 900})
        for name, screen in screens({k: str(v) for k, v in thumbs.items()}, str(cover)).items():
            page.set_content(chat(screen))
            page.evaluate("document.fonts.ready")    # the fallback emoji font
            page.wait_for_timeout(150)
            path = OUT / f"{name}.png"
            page.locator(".phone").screenshot(path=str(path), omit_background=True)
            shots[name] = path
        page.set_content(NAMES_CARD)
        page.evaluate("document.fonts.ready")
        page.locator(".c").screenshot(path=str(OUT / "features.png"), omit_background=True)

        # the animated flows (GIF: plays inline on Telegraph and in Telegram)
        for flow, names in FLOWS.items():
            frames = WORK / flow
            frames.mkdir(exist_ok=True)
            big = max(Image.open(shots[n]).size[1] for n in names)
            for i, n in enumerate(names):          # same canvas for every frame: no jumping
                im = Image.open(shots[n]).convert("RGBA")
                canvas = Image.new("RGBA", (im.size[0], big), (14, 22, 33, 255))
                canvas.paste(im, (0, big - im.size[1]), im)
                canvas.convert("RGB").save(frames / f"{i:02d}.png")
            lst = frames / "list.txt"
            lst.write_text("".join(f"file '{(frames / f'{i:02d}.png').as_posix()}'\nduration 2.2\n" for i in range(len(names)))
                           + f"file '{(frames / f'{len(names) - 1:02d}.png').as_posix()}'\n")
            ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-vf",
                   "fps=8,scale=420:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160[p];[b][p]paletteuse=dither=bayer",
                   "-loop", "0", str(OUT / f"flow_{flow}.gif"))

        # the explainer videos: slides, crossfaded
        for lang, slides in VIDEO.items():
            paths = []
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            for i, s in enumerate(slides):
                page.set_content(title_slide(*s[1:]) if s[0] == "title" else slide(s[1], s[2], s[3], shots[s[0]]))
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(120)
                path = WORK / f"{lang}_{i:02d}.png"
                page.screenshot(path=str(path))
                paths.append(path)
            page.close()
            dur, fade = 3.6, 0.6
            inputs = []
            for path in paths:
                inputs += ["-loop", "1", "-t", str(dur), "-i", str(path)]
            chain, last = [], "[0:v]"
            for i in range(1, len(paths)):
                out = f"[v{i}]"
                chain.append(f"{last}[{i}:v]xfade=transition=fade:duration={fade}:offset={i * (dur - fade):.2f}{out}")
                last = out
            ffmpeg(*inputs, "-filter_complex", ";".join(chain) + f";{last}format=yuv420p[out]", "-map", "[out]",
                   "-r", "30", "-c:v", "libx264", "-crf", "24", "-movflags", "+faststart", str(OUT / f"explainer_{lang}.mp4"))
        browser.close()
    shutil.rmtree(WORK, ignore_errors=True)
    for f in sorted(OUT.iterdir()):
        print(f"{f.name:28} {f.stat().st_size // 1024:6} KB")


if __name__ == "__main__":
    main()

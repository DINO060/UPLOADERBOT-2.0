import logging
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from utils.message_utils import send_message, PostType, MessageError
from database.manager import DatabaseManager
from utils.error_handler import handle_error
from conversation_states import MAIN_MENU, POST_CONTENT, SCHEDULE_SEND, SETTINGS, WAITING_CHANNEL_INFO
from database.channel_repo import list_user_channels, get_channel_by_username as repo_get_channel_by_username, add_channel as repo_add_channel
from i18n import get_user_lang, t

logger = logging.getLogger('TelegramBot')


WELCOME_TEXT = (
    "👋 Welcome to UPLOADER BOT!\n\n"
    "I help you rename captions/filenames, set a custom thumbnail, and schedule your posts to your channels.\n\n"
    "📋 Features:\n"
    "• Rename caption/filename\n"
    "• Schedule post sending\n\n"
    "🎯 Commands:\n"
    "/start - Show this message\n"
    "/help - Show help and usage\n"
    "/addchannel - Add a new channel (Name @username or just @username)\n"
    "/settings - Open settings\n\n"
    "🛠 Admin commands:\n"
    "/adm - Admin panel\n"
    "/status - Bot status\n"
)

class CommandHandlers:
    """Gestionnaire des commandes du bot"""

    def __init__(
            self,
            db_manager: DatabaseManager,
            scheduled_tasks: Optional['ScheduledTasks'] = None
    ):
        """
        Initialise le gestionnaire de commandes

        Args:
            db_manager: Gestionnaire de base de données
            scheduled_tasks: Gestionnaire de tâches planifiées (optionnel)
        """
        self.db_manager = db_manager
        self.scheduled_tasks = scheduled_tasks

        logger.debug("Command handlers initialized")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles the /start command"""
        user = update.effective_user
        user_id = user.id
        
        # Get user language preference
        lang = get_user_lang(user.id, user.language_code)

        # Initialisation de la structure de données utilisateur si nécessaire
        if 'posts' not in context.user_data:
            context.user_data['posts'] = []
        if 'selected_channel' not in context.user_data:
            context.user_data['selected_channel'] = None

        # Create inline keyboard (aligned with callback_handlers.py)
        keyboard = [
            [InlineKeyboardButton("📝 New post", callback_data="create_publication", api_kwargs={"style": "success"})],
            [InlineKeyboardButton("📅 Scheduled posts", callback_data="planifier_post", api_kwargs={"style": "primary"})],
            [InlineKeyboardButton("⚙️ Settings", callback_data="settings", api_kwargs={"style": "primary"})]
        ]

        # Add redirect buttons from admin config
        try:
            from bot import get_redirect_buttons_keyboard
            redirect_buttons = await get_redirect_buttons_keyboard()
            keyboard.extend(redirect_buttons)
        except Exception:
            pass

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Envoyer le message avec le clavier
        await update.message.reply_text(t(lang, "start.welcome"), reply_markup=reply_markup)

        # Save user timezone if not set
        timezone = self.db_manager.get_user_timezone(user_id)
        if not timezone:
            self.db_manager.set_user_timezone(user_id, 'Europe/Paris')  # Default timezone

        logger.debug(f"User {user_id} started the bot")

        return MAIN_MENU

    async def _start_publication_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                      is_scheduled: bool = False) -> int:
        """Generic function to start create/schedule flow"""
        user_id = update.effective_user.id

        # Explanatory message for scheduling
        if is_scheduled:
            await update.message.reply_text(
                "Scheduling lets you automatically send your posts at a chosen time.\n\n"
                "Let's create your post first, then set the send time."
            )

        # Réinitialiser les données utilisateur pour cette session
        context.user_data['posts'] = []
        context.user_data['selected_channel'] = None
        if is_scheduled:
            context.user_data['is_scheduled'] = True

        # Fetch user channels (only connected channels where bot+user are admins)
        repo_channels = list_user_channels(user_id)
        # Keep only channels that have a public @username (UI flow expects username)
        channels = []
        for ch in repo_channels:
            username = ch.get('username')
            if username:
                channels.append({
                    'name': ch.get('title') or username,
                    'username': username
                })

        if not channels:
            await update.message.reply_text(
                "You haven't configured any channels yet. "
                "Please add a channel in Settings first."
            )
            return ConversationHandler.END

        # Créer un clavier avec les canaux disponibles
        keyboard = []
        for channel in channels:
            button = [InlineKeyboardButton(
                f"@{channel['username']} - {channel['name']}",
                callback_data=f"channel_{channel['username']}"
            )]
            keyboard.append(button)

        # Add cancel button
        keyboard.append([InlineKeyboardButton("Cancel", callback_data="cancel")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Message adapted to the flow type
        message = (
            "Please select the channel where you want to schedule a post:"
            if is_scheduled else
            "Please select the channel where you want to publish:"
        )
        
        await update.message.reply_text(message, reply_markup=reply_markup)

        action = "scheduling" if is_scheduled else "creation"
        logger.debug(f"User {user_id} started {action} flow")

        return SCHEDULE_SEND if is_scheduled else MAIN_MENU

    async def create_publication(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles /create command"""
        return await self._start_publication_flow(update, context, is_scheduled=False)

    async def planifier_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles /schedule command"""
        return await self._start_publication_flow(update, context, is_scheduled=True)

    async def settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles /settings command"""
        user_id = update.effective_user.id

        # Create inline keyboard for settings
        keyboard = [
            [InlineKeyboardButton("🌐 Manage my channels", callback_data='manage_channels')],
            [InlineKeyboardButton("⏰ Timezone", callback_data='timezone_settings')],
            [InlineKeyboardButton("🔄 Scheduled posts", callback_data='scheduled_posts')],
            [InlineKeyboardButton("🏠 Back to main menu", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Envoyer le message avec le clavier
        await update.message.reply_text(
            "⚙️ *Settings*\n\n"
            "Configure your preferences and manage your Telegram channels here.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

        logger.debug(f"User {user_id} opened settings")

        return SETTINGS

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancels the current conversation"""
        user_id = update.effective_user.id

        # Réinitialiser les données utilisateur
        if 'posts' in context.user_data:
            context.user_data['posts'] = []
        if 'selected_channel' in context.user_data:
            context.user_data['selected_channel'] = None

        await update.message.reply_text(
            "🛑 Operation cancelled. What would you like to do next?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back to main menu", callback_data="main_menu")]
            ])
        )

        logger.debug(f"User {user_id} cancelled current operation")

        return MAIN_MENU

    async def list_publications(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles /list command

        Args:
            update: Telegram update
            context: Bot context
        """
        try:
            # Fetch scheduled posts
            posts = self.db_manager.get_future_scheduled_posts()

            if not posts:
                await update.message.reply_text("No scheduled posts.")
                return

            # Format list
            message = "📋 Scheduled posts:\n\n"
            for post in posts:
                channel = self.db_manager.get_channel(post['channel_id'])
                message += (
                    f"📅 {post['scheduled_time']}\n"
                    f"📢 {channel['name']}\n"
                    f"📝 {post['caption'][:50]}...\n\n"
                )

            await update.message.reply_text(message)

        except Exception as e:
            await handle_error(update, context, e)

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles /help command

        Args:
            update: Telegram update
            context: Bot context
        """
        help_text = (
            "📘 Bot features description\n"
            "This Telegram bot helps you manage and publish content to your channels. "
            "It provides an intuitive interface with buttons to automate your publications.\n\n"

            "🔹 Main menu\n"
            "The bot shows three main options at startup:\n"
            "• 📝 New post - Create a new post. Select the target channel, then send your content (text, photo, video or document). The bot accepts up to 30 files per post; episodes sent together go out in episode order.\n"
            "• 📅 Scheduled posts - Your next scheduled posts (up to 10), with their channel and send time. Open one to edit or cancel it.\n"
            "• ⚙️ Settings - Configure the bot, including channel management and timezone.\n\n"

            "🔧 Post editing features\n"
            "Once your content is added, you can enhance it with:\n"
            "• ✨ Add reactions - Add reaction buttons under your post. Users can click them and they will be counted. Up to 8 reactions.\n"
            "• 🔗 Add URL button - Add a clickable button with an external link (website, channel, or any online resource).\n"
            "• ✏️ Edit File → Rename - The file itself gets its new name (up to 2 GB), the caption too.\n"
            "• ❌ Delete - Remove a file from the current post.\n\n"

            "📤 Sending options\n"
            "When your post is ready, you can:\n"
            "• Send now - Immediately send the post to the selected channel.\n"
            "• Schedule - Send at a specific date and time (choose Today or Tomorrow, then pick the time).\n"
            "• Set auto-destruction time - Auto-delete the message after a defined delay (5 minutes to 24 hours).\n\n"

            "📺 Channel management\n"
            "In Settings, you can manage your Telegram channels:\n"
            "• ➕ Add a channel - Register a new channel where you are an admin.\n"
            "• 🏷️ Add a hashtag - Configure automatic hashtags added to all posts for that channel.\n\n"

            "⌨️ Control buttons during creation\n"
            "During post creation, four buttons remain visible:\n"
            "• 📋 Preview - Show a preview of the post as it will appear in the channel.\n"
            "• 🚀 Send - Open sending options (immediate, scheduled, or auto-destruction).\n"
            "• 🗑️ Delete all - Clear all added files to start over.\n"
            "• ❌ Cancel - Abort the current creation and return to the main menu.\n\n"

            "This bot greatly simplifies managing your Telegram publications by centralizing all essential features in a clear and accessible interface."
        )

        # (it promised a thumbnail option and a thumbnail menu that no button leads to)
        from utils.whats_new import GUIDE_EN, GUIDE_FR
        guide = InlineKeyboardMarkup([[InlineKeyboardButton("📖 Guide (English)", url=GUIDE_EN)],
                                      [InlineKeyboardButton("📖 Mode d'emploi (Français)", url=GUIDE_FR)]])
        await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=guide)

        logger.debug(f"User {update.effective_user.id} requested help")

        return None

    async def addchannel_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Add a channel via command. Usage: /addchannel Name @username | @username | https://t.me/username"""
        user_id = update.effective_user.id
        args_text = " ".join(context.args).strip()

        if not args_text:
            # Prompt for input
            await update.message.reply_text(
                "➕ *Add a channel*\n\n"
                "Send the channel @username or its t.me link.\n\n"
                "Examples:\n"
                "• `@mychannel`\n"
                "• `https://t.me/mychannel`\n\n"
                "The bot will use the channel's default name automatically.\n"
                "⚠️ Ensure the bot is an administrator of the channel.",
                parse_mode='Markdown'
            )
            context.user_data['waiting_for_channel_info'] = True
            return WAITING_CHANNEL_INFO

        # Parse inline args
        channel_username = None
        display_name = None
        text = args_text
        if text.startswith('https://t.me/'):
            channel_username = text.replace('https://t.me/', '').strip().lstrip('@')
            display_name = channel_username
        elif text.startswith('@') and ' ' not in text:
            channel_username = text.lstrip('@')
            display_name = channel_username
        elif '@' in text:
            parts = text.rsplit('@', 1)
            if len(parts) == 2:
                display_name = parts[0].strip()
                channel_username = parts[1].strip().lstrip('@')

        if not channel_username:
            await update.message.reply_text(
                "❌ Invalid format. Use one of:\n"
                "• `Channel name @username`\n"
                "• `@username`\n"
                "• `https://t.me/username`",
                parse_mode='Markdown'
            )
            return SETTINGS

        # Check duplicate using channel repository (authoritative for channels)
        if repo_get_channel_by_username(channel_username, user_id):
            await update.message.reply_text(
                "ℹ️ Channel already registered.")
            return SETTINGS

        # Resolve official channel title from Telegram
        name_to_use = display_name or channel_username
        try:
            try:
                chat_ident = f"@{channel_username}" if not channel_username.startswith('@') else channel_username
                chat = await context.bot.get_chat(chat_ident)
                if getattr(chat, 'title', None):
                    name_to_use = chat.title
            except Exception:
                pass

            # Persist channel using repository (manages membership and schema)
            repo_add_channel(name_to_use, channel_username, user_id)
            await update.message.reply_text(
                f"✅ Channel added!\n\n📺 {name_to_use} (@{channel_username})")
            return SETTINGS
        except Exception:
            await update.message.reply_text("❌ Error while adding channel.")
            return SETTINGS


    async def language_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles the /language command"""
        user_id = update.effective_user.id
        
        from i18n import get_user_lang, t, SUPPORTED
        
        # Récupérer la langue actuelle
        current_lang = get_user_lang(user_id, update.effective_user.language_code)
        current_lang_info = SUPPORTED.get(current_lang, SUPPORTED["en"])
        
        # Construire le clavier avec toutes les langues disponibles
        keyboard = []
        for lang_code, lang_info in SUPPORTED.items():
            flag = lang_info["flag"]
            name = lang_info["name"]
            # Ajouter un indicateur pour la langue actuelle
            if lang_code == current_lang:
                keyboard.append([InlineKeyboardButton(f"{flag} {name} ✅", callback_data=f"set_language_{lang_code}")])
            else:
                keyboard.append([InlineKeyboardButton(f"{flag} {name}", callback_data=f"set_language_{lang_code}")])
        
        # Bouton retour
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="main_menu")])
        
        await update.message.reply_text(
            f"{t(current_lang, 'language.title')}\n\n"
            f"{t(current_lang, 'language.current').format(lang_flag=current_lang_info['flag'], lang_name=current_lang_info['name'])}\n\n"
            f"{t(current_lang, 'language.choose')}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
        return SETTINGS

    async def adm(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Admin panel - /adm command (admin only)"""
        from config.settings import bot_config

        user_id = update.effective_user.id
        admin_ids = bot_config.get("admin_ids", [])

        # Check if user is admin
        if user_id not in admin_ids:
            await update.message.reply_text("❌ You don't have permission to use this command.")
            return MAIN_MENU

        # Admin panel keyboard
        keyboard = [
            [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast")],
            [InlineKeyboardButton("👥 Force Join Channels", callback_data="adm_fsub")],
            [InlineKeyboardButton("🚫 Ban/Unban User", callback_data="adm_ban")],
            [InlineKeyboardButton("📊 Bot Stats", callback_data="adm_stats")],
            [InlineKeyboardButton("🔗 Short Links Config", callback_data="adm_shortlinks")],
            [InlineKeyboardButton("↩️ Main Menu", callback_data="main_menu")]
        ]

        # Get some quick stats
        total_users = self.db_manager.get_total_users() if hasattr(self.db_manager, 'get_total_users') else "N/A"

        admin_text = (
            "🛠 **Admin Panel**\n\n"
            f"👥 Total users: `{total_users}`\n\n"
            "Select an option below:"
        )

        await update.message.reply_text(
            admin_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

        return MAIN_MENU


# Fonction d'erreur générique pour les commandes
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles errors during command execution"""
    logger.error(f"An error occurred: {context.error}")

    # Envoyer un message d'erreur à l'utilisateur si possible
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "An error occurred while processing your request. "
            "Please try again or contact the bot administrator."
        )

    # Journaliser les détails de l'erreur
    logger.error(f"Update {update} caused error {context.error}", exc_info=True)
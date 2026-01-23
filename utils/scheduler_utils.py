"""
Utilitaires de planification pour le bot Telegram.
"""
import logging
import sqlite3
import asyncio
import json
from typing import Dict, Any, Optional
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

logger = logging.getLogger('SchedulerUtils')

# Configuration des limites
DAILY_LIMIT_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
COOLDOWN_SECONDS = 30  # 30 secondes

# Variable globale pour stocker l'application
_global_application = None

# Variable globale pour le scheduler manager
_global_scheduler_manager = None

def set_global_scheduler_manager(scheduler_manager):
    """Définit le scheduler manager global"""
    global _global_scheduler_manager
    _global_scheduler_manager = scheduler_manager
    logger.info("✅ Scheduler manager global défini dans scheduler_utils")

def get_global_scheduler_manager():
    """Récupère le scheduler manager global"""
    global _global_scheduler_manager
    
    try:
        # Priorité 1 : Utiliser le scheduler global s'il est défini
        if _global_scheduler_manager is not None:
            logger.info("✅ Scheduler manager récupéré depuis la variable globale")
            return _global_scheduler_manager
        
        # Priorité 2 : Essayer de récupérer depuis le module bot
        try:
            import sys
            if 'bot' in sys.modules:
                bot_module = sys.modules['bot']
                if hasattr(bot_module, 'application') and bot_module.application.bot_data.get('scheduler_manager'):
                    logger.info("✅ Scheduler manager récupéré depuis le module bot")
                    return bot_module.application.bot_data['scheduler_manager']
        except Exception as e:
            logger.debug(f"Impossible de récupérer depuis le module bot: {e}")
        
        logger.warning("⚠️ Scheduler manager non trouvé")
        return None
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du scheduler manager: {e}")
        return None

def set_global_application(app: Application):
    """Définit l'application globale pour les tâches planifiées"""
    global _global_application
    _global_application = app
    logger.info("✅ Application globale définie dans scheduler_utils")

def get_global_application() -> Optional[Application]:
    """Récupère l'application globale"""
    global _global_application
    logger.info(f"🔍 Récupération application globale: {_global_application is not None}")
    return _global_application

async def send_scheduled_file(post: Dict[str, Any], app: Optional[Application] = None) -> bool:
    """
    Envoie un fichier planifié au canal spécifié.
    
    Args:
        post: Les données du post à envoyer
        app: L'application Telegram (optionnel, utilise l'application globale si None)
        
    Returns:
        bool: True si l'envoi a réussi
    """
    try:
        logger.info("🚀 === START send_scheduled_file ===")
        logger.info(f"📤 Sending scheduled file: {post.get('id')}")
        logger.info(f"📊 Received post data: {post}")
        logger.info(f"🕐 Execution time: {datetime.now()}")
        
        # Récupérer l'application Telegram
        if app is None:
            logger.info("🔍 Application not provided, fetching from global")
            app = get_global_application()
        else:
            logger.info("✅ Application provided via parameter")
            
        if not app:
            logger.error("❌ Telegram Application not found")
            logger.error("🔍 Available global variables:")
            logger.error(f"   _global_application: {_global_application}")
            logger.error("🔍 Attempting to get scheduler manager...")
            scheduler_manager = get_global_scheduler_manager()
            if scheduler_manager:
                logger.info(f"✅ Scheduler manager found: {scheduler_manager}")
                logger.info(f"🔍 Scheduler running: {scheduler_manager.scheduler.running}")
            else:
                logger.error("❌ No scheduler manager found either")
            return False

        logger.info(f"✅ Telegram Application found: {type(app)}")
        logger.info(f"🔍 Application bot_data keys: {list(app.bot_data.keys()) if hasattr(app, 'bot_data') else 'No bot_data'}")

        # ✅ VALIDATION DES DONNÉES DU POST
        post_id = post.get('id')
        if not post_id:
            logger.error("❌ ID du post manquant")
            logger.error(f"📊 Contenu post reçu: {post}")
            return False
        
        logger.info(f"📋 Post ID: {post_id}")
        
        # ✅ VÉRIFICATION PRÉALABLE DE L'EXISTENCE DU POST
        try:
            from config import settings
            db_path = settings.db_config.get("path", "bot.db")
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM posts WHERE id = ?", (post_id,))
                exists = cursor.fetchone()[0] > 0
                
                if not exists:
                    logger.error(f"❌ Post {post_id} not found in database")
                    logger.error(f"❌ This post was likely deleted or never existed")
                    logger.info(f"🧹 Tentative de suppression du job orphelin post_{post_id}")
                    
                    # Essayer de supprimer le job du scheduler si possible
                    try:
                        from utils.scheduler_utils import get_global_scheduler_manager
                        scheduler_manager = get_global_scheduler_manager()
                        if scheduler_manager:
                            try:
                                scheduler_manager.scheduler.remove_job(f"post_{post_id}")
                                logger.info(f"✅ Job orphelin post_{post_id} supprimé")
                            except:
                                pass  # Job n'existe pas ou déjà supprimé
                    except:
                        pass
                    
                    return False
                    
        except Exception as db_check_error:
            logger.error(f"❌ Error checking post existence: {db_check_error}")
            return False
        
        # 📋 RÉCUPÉRER LES DONNÉES COMPLÈTES DEPUIS LA BASE DE DONNÉES
        try:
            import os  # ✅ Import d'os au début
            logger.info("🔍 Fetching data from the database...")
            from config import settings
            db_path = settings.db_config.get("path", "bot.db")
            logger.info(f"📁 DB Path: {os.path.abspath(db_path)}")  # ✅ Chemin absolu pour debug
            
            # Vérifier que le fichier DB existe
            if not os.path.exists(db_path):
                logger.error(f"❌ Database file not found: {db_path}")
                return False
            
            logger.info(f"✅ DB file found: {db_path}")
            
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                
                # ✅ RÉCUPÉRATION ROBUSTE AVEC VALIDATION STRICTE
                cursor.execute("""
                    SELECT p.id, p.post_type, p.content, p.caption, p.scheduled_time,
                           p.channel_id, p.buttons, p.reactions, p.status
                    FROM posts p 
                    WHERE p.id = ?
                """, (post_id,))
                
                result = cursor.fetchone()
                
                if not result:
                    logger.error(f"❌ Post {post_id} not found in database")
                    return False
                
                (db_post_id, post_type, content, caption, scheduled_time, 
                 channel_id, buttons, reactions, status) = result
                
                # ✅ VALIDATION CRITIQUE du channel_id
                if not channel_id:
                    logger.error(f"❌ Post {post_id} has NULL channel_id")
                    cursor.execute("UPDATE posts SET status = ? WHERE id = ?", ('missing_channel', post_id))
                    conn.commit()
                    return False
                
                # ✅ RÉSOLUTION DU CHAT avec fallback
                try:
                    if isinstance(channel_id, int):
                        # Channel ID numérique - utiliser directement
                        logger.info(f"🔍 Resolving chat with ID: {channel_id}")
                        chat = await app.bot.get_chat(channel_id)
                        resolved_channel = str(channel_id)
                    else:
                        # Channel username - résoudre d'abord
                        logger.info(f"🔍 Resolving chat with username: {channel_id}")
                        chat = await app.bot.get_chat(channel_id)
                        resolved_channel = channel_id
                        
                except Exception as chat_error:
                    logger.error(f"❌ Failed to resolve chat {channel_id}: {chat_error}")
                    cursor.execute("UPDATE posts SET status = ? WHERE id = ?", ('missing_channel', post_id))
                    conn.commit()
                    return False
                
                logger.info(f"✅ Chat resolved: {chat.title} (ID: {chat.id})")
                
                # Construire une requête compatible selon le schéma réel
                cursor.execute("PRAGMA table_info(posts)")
                post_cols = [c[1] for c in cursor.fetchall()]
                # Déterminer l'expression du nom de canal sans référencer des colonnes inexistantes
                cursor.execute("PRAGMA table_info(channels)")
                ch_cols = [c[1] for c in cursor.fetchall()]
                has_name = 'name' in ch_cols
                has_title = 'title' in ch_cols
                if has_name and has_title:
                    channel_name_expr = "COALESCE(c.title, c.name) AS channel_name"
                elif has_title:
                    channel_name_expr = "c.title AS channel_name"
                elif has_name:
                    channel_name_expr = "c.name AS channel_name"
                else:
                    channel_name_expr = "c.username AS channel_name"

                if 'post_type' in post_cols and 'type' in post_cols:
                    # Les deux colonnes existent → préférer post_type sinon fallback type
                    sql_query = (
                        f"""
                        SELECT p.id,
                               COALESCE(NULLIF(p.post_type, ''), p.type) AS post_type,
                               p.content, p.caption, p.scheduled_time,
                               COALESCE(c.title, c.username, p.channel_id) AS channel_name,
                               COALESCE(c.username, p.channel_id) AS channel_username,
                               p.buttons, p.reactions
                        FROM posts p
                        LEFT JOIN channels c ON (p.channel_id = c.id OR p.channel_id = c.username OR p.channel_id = '@' || c.username)
                        WHERE p.id = ?
                        """
                    )
                elif 'post_type' in post_cols:
                    sql_query = (
                        f"""
                        SELECT p.id, p.post_type AS post_type,
                               p.content, p.caption, p.scheduled_time,
                               COALESCE(c.title, c.username, p.channel_id) AS channel_name,
                               COALESCE(c.username, p.channel_id) AS channel_username,
                               p.buttons, p.reactions
                        FROM posts p
                        LEFT JOIN channels c ON (p.channel_id = c.id OR p.channel_id = c.username OR p.channel_id = '@' || c.username)
                        WHERE p.id = ?
                        """
                    )
                else:
                    # Fallback très ancien schéma: seulement 'type'
                    sql_query = (
                        f"""
                        SELECT p.id, p.type AS post_type,
                               p.content, p.caption, p.scheduled_time,
                               COALESCE(c.title, c.username, p.channel_id) AS channel_name,
                               COALESCE(c.username, p.channel_id) AS channel_username, 
                               p.buttons, p.reactions
                        FROM posts p
                        LEFT JOIN channels c ON (p.channel_id = c.id OR p.channel_id = c.username OR p.channel_id = '@' || c.username)
                        WHERE p.id = ?
                        """
                    )

                logger.info(f"🔍 Executing dynamically built SQL query")
                logger.debug(f"SQL: {sql_query}")
                logger.info(f"🔍 Paramètre: post_id={post_id}")

                cursor.execute(sql_query, (post_id,))
                result = cursor.fetchone()
                
                logger.info(f"📊 Raw DB result: {result}")
                
                if not result:
                    logger.error(f"❌ Post {post_id} not found in database")
                    
                    # Debug: vérifier tous les posts
                    cursor.execute("SELECT id, scheduled_time FROM posts ORDER BY id DESC LIMIT 5")
                    all_posts = cursor.fetchall()
                    logger.error(f"🔍 Last posts in DB: {all_posts}")
                    
                    return False
                
                # Mettre à jour les données du post avec les infos de la DB
                post_id, post_type, content, caption, scheduled_time, channel_name, channel_username, buttons, reactions = result

                # Normaliser le type si manquant
                if not post_type:
                    logger.warning("Type de post manquant en DB, fallback 'document'")
                    post_type = 'document'
                
                logger.info(f"✅ Data extracted from DB:")
                logger.info(f"   📋 ID: {post_id}")
                logger.info(f"   📝 Type: {post_type}")
                logger.info(f"   📄 Content (50 premiers chars): {str(content)[:50]}...")
                logger.info(f"   📝 Caption: {caption}")
                logger.info(f"   ⏰ Scheduled time: {scheduled_time}")
                logger.info(f"   📺 Channel name: {channel_name}")
                logger.info(f"   📺 Channel username: {channel_username}")
                logger.info(f"   🔘 Buttons: {buttons}")
                
                # Construire les données complètes du post
                complete_post = {
                    'id': post_id,
                    'type': post_type,
                    'content': content,
                    'caption': caption or '',
                    'scheduled_time': scheduled_time,
                    'channel_name': channel_name,
                    'channel_username': channel_username,
                    'buttons': buttons or [],
                    'reactions': reactions or []
                }
                
                logger.info(f"✅ Post {post_id} data loaded from DB")
                logger.info(f"📊 Built complete post: {complete_post}")
                
        except Exception as db_error:
            logger.error(f"❌ Error fetching post {post_id} data: {db_error}")
            logger.exception("🔍 Full traceback (DB error):")
            # Utiliser les données fournies en paramètre si la DB échoue
            complete_post = post
            logger.info("⚠️ Utilisation des données fournies en paramètre")
        
        # Utiliser les données complètes
        post_type = complete_post.get('type')
        content = complete_post.get('content')
        caption = complete_post.get('caption', '')
        channel = complete_post.get('channel_username')
        
        # Vérifier si le canal est manquant et utiliser un fallback
        # ✅ Gérer les types channel (int/str) avant strip()
        if not channel or (isinstance(channel, str) and channel.strip() == ""):
            logger.warning(f"⚠️ Channel missing for post {post_id}")
            logger.warning(f"   Channel: {channel}")
            logger.warning(f"   Channel name: {complete_post.get('channel_name')}")
            
            # Essayer de récupérer le channel_id original depuis la base
            try:
                from config import settings
                db_path = settings.db_config.get("path", "bot.db")
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT channel_id FROM posts WHERE id = ?", (post_id,))
                    result = cursor.fetchone()
                    if result and result[0]:
                        original_channel_id = result[0]
                        logger.info(f"🔍 Original channel_id from DB: {original_channel_id}")
                        channel = original_channel_id
                        complete_post['channel_username'] = channel
                        logger.info(f"✅ Using original channel_id as fallback: {channel}")
                    else:
                        logger.error(f"❌ Post {post_id} not found in database or has no channel_id")
                        logger.error(f"❌ This post was likely created without a channel or the channel was lost")
                        # Mark the post in the DB so it can be inspected and fixed later
                        try:
                            cursor.execute("UPDATE posts SET status = ? WHERE id = ?", ('missing_channel', post_id))
                            conn.commit()
                            logger.info(f"🔁 Post {post_id} status set to 'missing_channel' in DB")
                        except Exception as mark_err:
                            logger.warning(f"⚠️ Unable to mark post {post_id} as missing_channel: {mark_err}")
                        return False
            except Exception as fallback_error:
                logger.error(f"❌ Error retrieving original channel_id: {fallback_error}")
                return False

        # === LIMITES: 2GB/jour et cooldown 60s par utilisateur (propriétaire du canal) ===
        try:
            # Récupérer le user_id propriétaire du canal
            from config import settings
            import sqlite3 as _sqlite
            db_path = settings.db_config.get("path", "bot.db")
            with _sqlite.connect(db_path) as _conn:
                _cur = _conn.cursor()
                # Détecter si channels.user_id existe
                try:
                    _cur.execute("PRAGMA table_info(channels)")
                    _cols = [c[1] for c in _cur.fetchall()]
                except Exception:
                    _cols = []

                # ✅ Convertir channel en string pour éviter l'erreur lstrip sur int
                channel_str = str(channel) if channel is not None else None
                clean_un = channel_str.lstrip('@') if channel_str else None
                owner_user_id = None
                if 'user_id' in _cols:
                    # Schéma récent: user_id sur channels
                    _cur.execute("SELECT user_id FROM channels WHERE username = ?", (clean_un,))
                    _row = _cur.fetchone()
                    owner_user_id = _row[0] if _row else None
                else:
                    # Legacy: user_id via channel_members
                    try:
                        _cur.execute(
                            """
                            SELECT cm.user_id
                            FROM channels c
                            JOIN channel_members cm ON cm.channel_id = c.id
                            WHERE c.username = ?
                            LIMIT 1
                            """,
                            (clean_un,)
                        )
                        _row = _cur.fetchone()
                        owner_user_id = _row[0] if _row else None
                    except Exception:
                        owner_user_id = None

            # Estimer la taille du fichier si c'est un média
            estimated_size = 0
            if post_type in ("photo", "video", "document") and content:
                try:
                    file_obj = await app.bot.get_file(content)
                    estimated_size = getattr(file_obj, 'file_size', 0) or 0
                except Exception:
                    estimated_size = 0

            # Vérifier limites via DatabaseManager
            if owner_user_id is not None:
                from database.manager import DatabaseManager
                dbm = DatabaseManager()
                lim = dbm.check_limits(owner_user_id, estimated_size, DAILY_LIMIT_BYTES, COOLDOWN_SECONDS)
                if not lim.get('ok'):
                    if lim.get('reason') == 'daily':
                        logger.warning(f"⛔ Quota journalier atteint pour user {owner_user_id}: {lim}")
                    elif lim.get('reason') == 'cooldown':
                        logger.warning(f"⏳ Cooldown actif pour user {owner_user_id}: attendre {lim.get('wait_seconds')}s")
                    return False
        except Exception as limit_err:
            logger.warning(f"Limites non vérifiées (erreur): {limit_err}")
        
        logger.info(f"📝 Final data for send:")
        logger.info(f"   📝 Type: {post_type}")
        logger.info(f"   📄 Content: {str(content)[:50] if content else 'None'}...")
        logger.info(f"   📝 Caption: {str(caption)[:50] if caption else 'None'}...")
        logger.info(f"   📺 Channel: {channel}")
        
        if not post_type or not content:
            logger.error(f"❌ Missing type or content for post {post_id}")
            logger.error(f"   Type: {post_type}")
            logger.error(f"   Content: {content}")
            return False
            
        if not channel:
            logger.error(f"❌ Channel missing for post {post_id}")
            logger.error(f"   Channel: {channel}")
            # Persist status to DB so admins can locate and fix the post
            try:
                import sqlite3 as _sqlite
                from config import settings
                db_path = settings.db_config.get("path", "bot.db")
                with _sqlite.connect(db_path) as _conn2:
                    _cur2 = _conn2.cursor()
                    _cur2.execute("UPDATE posts SET status = ? WHERE id = ?", ('missing_channel', post_id))
                    _conn2.commit()
                    logger.info(f"🔁 Post {post_id} status set to 'missing_channel' in DB")
            except Exception as mark_err:
                logger.warning(f"⚠️ Unable to mark post {post_id} as missing_channel: {mark_err}")
            return False
        
        # Ajouter @ au canal si nécessaire
        original_channel = channel
        # ✅ Convertir channel en string pour éviter l'erreur startswith sur int
        channel_str = str(channel) if channel is not None else ""
        if not channel_str.startswith('@') and not channel_str.startswith('-'):
            channel = f"@{channel_str}"
        else:
            channel = channel_str
        
        logger.info(f"📍 Normalized channel: '{original_channel}' → '{channel}'")
        logger.info(f"📍 Sending to {channel} - Type: {post_type}")
        
        # Construire le clavier avec les réactions et boutons URL
        keyboard = None
        keyboard_buttons = []
        
        # ✅ AJOUTER LES RÉACTIONS
        if complete_post.get('reactions'):
            logger.info("⭐ Building reactions...")
            try:
                reactions_data = complete_post['reactions']
                logger.info(f"⭐ Raw reactions data: {reactions_data}")
                
                if isinstance(reactions_data, str):
                    try:
                        reactions = json.loads(reactions_data)
                        logger.info(f"⭐ Reactions parsed from JSON: {reactions}")
                    except json.JSONDecodeError as json_err:
                        logger.warning(f"Impossible de décoder les réactions comme JSON: {json_err}")
                        reactions = []
                else:
                    reactions = reactions_data
                    logger.info(f"⭐ Reactions used directly: {reactions}")
                    
                if reactions:
                    # Ajouter les réactions en ligne (4 par ligne max)
                    current_row = []
                    for reaction in reactions:
                        current_row.append(InlineKeyboardButton(
                            reaction,
                            callback_data=f"react_{post_id}_{reaction}"
                        ))
                        # 4 réactions par ligne maximum
                        if len(current_row) == 4:
                            keyboard_buttons.append(current_row)
                            current_row = []
                    # Ajouter la dernière ligne si elle n'est pas vide
                    if current_row:
                        keyboard_buttons.append(current_row)
                    
                    logger.info(f"⭐ {len(reactions)} reaction(s) added")
                    
            except Exception as reaction_error:
                logger.error(f"Error while parsing reactions: {reaction_error}")
                logger.exception("🔍 Reactions traceback:")
        
        # ✅ AJOUTER LES BOUTONS URL
        if complete_post.get('buttons'):
            logger.info("🔘 Building URL buttons...")
            try:
                buttons_data = complete_post['buttons']
                logger.info(f"🔘 Raw buttons data: {buttons_data}")
                
                if isinstance(buttons_data, str):
                    try:
                        buttons = json.loads(buttons_data)
                        logger.info(f"🔘 Buttons parsed from JSON: {buttons}")
                    except json.JSONDecodeError as json_err:
                        logger.warning(f"Impossible de décoder les boutons comme JSON: {json_err}")
                        buttons = []
                else:
                    buttons = buttons_data
                    logger.info(f"🔘 Buttons used directly: {buttons}")
                    
                if buttons:
                    for btn in buttons:
                        if isinstance(btn, dict) and 'text' in btn and 'url' in btn:
                            keyboard_buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
                        logger.info(f"🔘 Button added: {btn['text']} → {btn['url']}")
                    
            except Exception as btn_error:
                logger.error(f"Error while parsing buttons: {btn_error}")
                logger.exception("🔍 Buttons traceback:")
        
        # Créer le markup final si on a des éléments
        reply_markup = None
        if keyboard_buttons:
            reply_markup = InlineKeyboardMarkup(keyboard_buttons)
            total_reactions = len(complete_post.get('reactions') or [])
            total_buttons = len(complete_post.get('buttons') or [])
            logger.info(f"✅ Inline keyboard created - {total_reactions} reaction(s), {total_buttons} button(s)")

        # Envoyer le message selon son type
        logger.info(f"📤 === START SENDING MESSAGE ===")
        logger.info(f"📤 Type: {post_type}")
        logger.info(f"📤 Channel: {channel}")
        logger.info(f"📤 App bot: {app.bot}")
        logger.info(f"📤 Reply markup: {reply_markup is not None}")
        
        sent_message = None
        try:
            if post_type == "photo":
                logger.info("📸 Sending photo...")
                logger.info(f"📸 Photo ID: {content}")
                logger.info(f"📸 Caption: {caption}")
                sent_message = await app.bot.send_photo(
                    chat_id=channel,
                    photo=content,
                    caption=caption,
                    reply_markup=reply_markup
                )
                logger.info(f"📸 Photo sent successfully")
                
            elif post_type == "video":
                logger.info("🎥 Sending video...")
                logger.info(f"🎥 Video ID: {content}")
                logger.info(f"🎥 Caption: {caption}")
                sent_message = await app.bot.send_video(
                    chat_id=channel,
                    video=content,
                    caption=caption,
                    reply_markup=reply_markup
                )
                logger.info(f"🎥 Video sent successfully")
                
            elif post_type == "document":
                logger.info("📄 Sending document...")
                logger.info(f"📄 Document ID: {content}")
                logger.info(f"📄 Caption: {caption}")
                sent_message = await app.bot.send_document(
                    chat_id=channel,
                    document=content,
                    caption=caption,
                    reply_markup=reply_markup
                )
                logger.info(f"📄 Document sent successfully")
                
            elif post_type == "text":
                logger.info("📝 Sending text message...")
                logger.info(f"📝 Texte: {content[:100]}...")
                sent_message = await app.bot.send_message(
                    chat_id=channel,
                    text=content,
                    reply_markup=reply_markup
                )
                logger.info(f"📝 Text sent successfully")
                
            else:
                logger.error(f"❌ Unsupported post type: {post_type}")
                return False
                
            logger.info(f"📬 Message sent: {sent_message is not None}")
            if sent_message:
                logger.info(f"📬 Message ID: {sent_message.message_id}")
                logger.info(f"📬 Chat ID: {sent_message.chat_id}")
                
        except Exception as send_error:
            logger.error(f"❌ Error while sending to {channel}: {send_error}")
            logger.exception("🔍 Full traceback (send):")
            
            # Debug supplémentaire pour les erreurs d'envoi
            logger.error(f"🔍 Détails de l'erreur d'envoi:")
            logger.error(f"   Type d'erreur: {type(send_error)}")
            logger.error(f"   Message d'erreur: {str(send_error)}")
            
            return False

        if sent_message:
            logger.info(f"✅ Scheduled message sent successfully: {post_id}")

            # Enregistrer l'usage après envoi
            try:
                if post_type in ("photo", "video", "document") and content and owner_user_id is not None:
                    sent_size = 0
                    try:
                        file_obj = await app.bot.get_file(content)
                        sent_size = getattr(file_obj, 'file_size', 0) or 0
                    except Exception:
                        sent_size = 0
                    from database.manager import DatabaseManager
                    DatabaseManager().add_usage_after_post(owner_user_id, sent_size)
            except Exception as upd_err:
                logger.warning(f"Erreur mise à jour usage après envoi: {upd_err}")
            
            # ✅ CORRECTION : Supprimer le post SEULEMENT si l'envoi a réussi
            try:
                logger.info("🗑️ Deleting post from database...")
                from config import settings
                db_path = settings.db_config.get("path", "bot.db")
                
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM posts WHERE id = ?", (post_id,))
                    rows_affected = cursor.rowcount
                    conn.commit()
                    
                if rows_affected > 0:
                    logger.info(f"✅ Post {post_id} deleted from database ({rows_affected} row(s))")
                else:
                    logger.warning(f"⚠️ No row deleted for post {post_id}")
                    
            except Exception as db_error:
                logger.error(f"❌ Error deleting post {post_id} from DB: {db_error}")
                logger.exception("🔍 DB delete traceback:")
            
            logger.info("🎉 === END send_scheduled_file - SUCCESS ===")
            return True
        else:
            # Do not delete the post if sending failed
            logger.error(f"❌ Failed to send scheduled message: {post_id}")
            logger.error(f"❌ sent_message is None")
            
            # 🔄 RETRY : Reprogrammer le post pour dans 5 minutes
            try:
                from datetime import timedelta
                import pytz
                
                # Calculer la nouvelle heure (dans 5 minutes)
                new_time = datetime.now(pytz.UTC) + timedelta(minutes=5)
                logger.info(f"🔄 Rescheduling for {new_time}")
                
                # Mettre à jour l'heure dans la base de données
                from config import settings
                db_path = settings.db_config.get("path", "bot.db")
                
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE posts SET scheduled_time = ? WHERE id = ?",
                        (new_time.strftime('%Y-%m-%d %H:%M:%S'), post_id)
                    )
                    conn.commit()
                
                logger.warning(f"⚠️ Post {post_id} rescheduled for {new_time} (in 5 minutes)")
                
                # Essayer de reprogrammer le job si possible
                try:
                    # Récupérer le scheduler manager global
                    scheduler_manager = get_global_scheduler_manager()
                    if scheduler_manager:
                        job_id = f"post_{post_id}"
                        
                        # Supprimer l'ancien job s'il existe
                        if scheduler_manager.scheduler.get_job(job_id):
                            scheduler_manager.scheduler.remove_job(job_id)
                            logger.info(f"🗑️ Old job {job_id} removed")
                        
                        # Créer un nouveau job avec retry
                        def retry_send_post():
                            import asyncio
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            app = get_global_application()
                            loop.run_until_complete(send_scheduled_file(complete_post, app))
                            loop.close()
                        
                        scheduler_manager.scheduler.add_job(
                            func=retry_send_post,
                            trigger="date",
                            run_date=new_time,
                            id=job_id,
                            replace_existing=True
                        )
                        logger.info(f"✅ Retry job created for {new_time}")
                        
                except Exception as retry_error:
                    logger.error(f"❌ Unable to reschedule job: {retry_error}")
                    logger.exception("🔍 Reschedule job traceback:")
                    
            except Exception as retry_error:
                logger.error(f"❌ Error while rescheduling: {retry_error}")
                logger.exception("🔍 Rescheduling traceback:")
            
            logger.info("💥 === END send_scheduled_file - FAILURE (retry scheduled) ===")
            return False

    except Exception as e:
        logger.error(f"❌ General error while sending scheduled file: {e}")
        logger.exception("🔍 Full traceback (general):")
        logger.info("💥 === END send_scheduled_file - ERROR ===")
        return False 
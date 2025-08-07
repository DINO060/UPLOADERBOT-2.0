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
        logger.info("🚀 === DÉBUT send_scheduled_file ===")
        logger.info(f"📤 Envoi du fichier planifié : {post.get('id')}")
        logger.info(f"📊 Données post reçues: {post}")
        logger.info(f"🕐 Heure d'exécution: {datetime.now()}")
        
        # Récupérer l'application Telegram
        if app is None:
            logger.info("🔍 Application non fournie, récupération depuis global")
            app = get_global_application()
        else:
            logger.info("✅ Application fournie en paramètre")
            
        if not app:
            logger.error("❌ Application Telegram introuvable")
            logger.error("🔍 Variables globales disponibles:")
            logger.error(f"   _global_application: {_global_application}")
            return False

        logger.info(f"✅ Application Telegram trouvée: {type(app)}")

        # ✅ VALIDATION DES DONNÉES DU POST
        post_id = post.get('id')
        if not post_id:
            logger.error("❌ ID du post manquant")
            logger.error(f"📊 Contenu post reçu: {post}")
            return False
        
        logger.info(f"📋 Post ID: {post_id}")
        
        # 📋 RÉCUPÉRER LES DONNÉES COMPLÈTES DEPUIS LA BASE DE DONNÉES
        try:
            logger.info("🔍 Récupération des données depuis la base de données...")
            from config import settings
            db_path = settings.db_config.get("path", "bot.db")
            logger.info(f"📁 Chemin DB: {db_path}")
            
            # Vérifier que le fichier DB existe
            import os
            if not os.path.exists(db_path):
                logger.error(f"❌ Fichier de base de données introuvable: {db_path}")
                return False
            
            logger.info(f"✅ Fichier DB trouvé: {db_path}")
            
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                
                # Log de la requête SQL
                sql_query = """
                    SELECT p.id, p.type, p.content, p.caption, p.scheduled_time, 
                           c.name, c.username, p.buttons
                    FROM posts p
                    JOIN channels c ON p.channel_id = c.id
                    WHERE p.id = ?
                """
                logger.info(f"🔍 Exécution requête SQL: {sql_query}")
                logger.info(f"🔍 Paramètre: post_id={post_id}")
                
                cursor.execute(sql_query, (post_id,))
                result = cursor.fetchone()
                
                logger.info(f"📊 Résultat DB brut: {result}")
                
                if not result:
                    logger.error(f"❌ Post {post_id} introuvable dans la base de données")
                    
                    # Debug: vérifier tous les posts
                    cursor.execute("SELECT id, scheduled_time FROM posts ORDER BY id DESC LIMIT 5")
                    all_posts = cursor.fetchall()
                    logger.error(f"🔍 Derniers posts dans la DB: {all_posts}")
                    
                    return False
                
                # Mettre à jour les données du post avec les infos de la DB
                post_id, post_type, content, caption, scheduled_time, channel_name, channel_username, buttons = result
                
                logger.info(f"✅ Données extraites de la DB:")
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
                    'buttons': buttons
                }
                
                logger.info(f"✅ Données du post {post_id} récupérées depuis la DB")
                logger.info(f"📊 Post complet construit: {complete_post}")
                
        except Exception as db_error:
            logger.error(f"❌ Erreur récupération données post {post_id}: {db_error}")
            logger.exception("🔍 Traceback complet de l'erreur DB:")
            # Utiliser les données fournies en paramètre si la DB échoue
            complete_post = post
            logger.info("⚠️ Utilisation des données fournies en paramètre")
        
        # Utiliser les données complètes
        post_type = complete_post.get('type')
        content = complete_post.get('content')
        caption = complete_post.get('caption', '')
        channel = complete_post.get('channel_username')
        
        logger.info(f"📝 Données finales pour envoi:")
        logger.info(f"   📝 Type: {post_type}")
        logger.info(f"   📄 Content: {str(content)[:50] if content else 'None'}...")
        logger.info(f"   📝 Caption: {str(caption)[:50] if caption else 'None'}...")
        logger.info(f"   📺 Channel: {channel}")
        
        if not post_type or not content:
            logger.error(f"❌ Type ou contenu manquant pour le post {post_id}")
            logger.error(f"   Type: {post_type}")
            logger.error(f"   Content: {content}")
            return False
            
        if not channel:
            logger.error(f"❌ Canal manquant pour le post {post_id}")
            logger.error(f"   Channel: {channel}")
            return False
        
        # Ajouter @ au canal si nécessaire
        original_channel = channel
        if not channel.startswith('@') and not channel.startswith('-'):
            channel = f"@{channel}"
        
        logger.info(f"📍 Canal normalisé: '{original_channel}' → '{channel}'")
        logger.info(f"📍 Envoi vers {channel} - Type: {post_type}")
        
        # Construire le clavier avec les réactions et boutons URL
        keyboard = None
        keyboard_buttons = []
        
        # ✅ AJOUTER LES RÉACTIONS
        if complete_post.get('reactions'):
            logger.info("⭐ Construction des réactions...")
            try:
                reactions_data = complete_post['reactions']
                logger.info(f"⭐ Données réactions brutes: {reactions_data}")
                
                if isinstance(reactions_data, str):
                    try:
                        reactions = json.loads(reactions_data)
                        logger.info(f"⭐ Réactions parsées depuis JSON: {reactions}")
                    except json.JSONDecodeError as json_err:
                        logger.warning(f"Impossible de décoder les réactions comme JSON: {json_err}")
                        reactions = []
                else:
                    reactions = reactions_data
                    logger.info(f"⭐ Réactions utilisées directement: {reactions}")
                    
                if reactions:
                    # Ajouter les réactions en ligne (4 par ligne max)
                    current_row = []
                    for reaction in reactions:
                        current_row.append(InlineKeyboardButton(
                            reaction,
                            callback_data=f"reaction_{post_id}_{reaction}"
                        ))
                        # 4 réactions par ligne maximum
                        if len(current_row) == 4:
                            keyboard_buttons.append(current_row)
                            current_row = []
                    # Ajouter la dernière ligne si elle n'est pas vide
                    if current_row:
                        keyboard_buttons.append(current_row)
                    
                    logger.info(f"⭐ {len(reactions)} réaction(s) ajoutée(s)")
                    
            except Exception as reaction_error:
                logger.error(f"Erreur lors de la conversion des réactions : {reaction_error}")
                logger.exception("🔍 Traceback réactions:")
        
        # ✅ AJOUTER LES BOUTONS URL
        if complete_post.get('buttons'):
            logger.info("🔘 Construction des boutons...")
            try:
                buttons_data = complete_post['buttons']
                logger.info(f"🔘 Données boutons brutes: {buttons_data}")
                
                if isinstance(buttons_data, str):
                    try:
                        buttons = json.loads(buttons_data)
                        logger.info(f"🔘 Boutons parsés depuis JSON: {buttons}")
                    except json.JSONDecodeError as json_err:
                        logger.warning(f"Impossible de décoder les boutons comme JSON: {json_err}")
                        buttons = []
                else:
                    buttons = buttons_data
                    logger.info(f"🔘 Boutons utilisés directement: {buttons}")
                    
                if buttons:
                    for btn in buttons:
                        if isinstance(btn, dict) and 'text' in btn and 'url' in btn:
                            keyboard_buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
                            logger.info(f"🔘 Bouton ajouté: {btn['text']} → {btn['url']}")
                    
            except Exception as btn_error:
                logger.error(f"Erreur lors de la conversion des boutons : {btn_error}")
                logger.exception("🔍 Traceback boutons:")
        
        # Créer le markup final si on a des éléments
        reply_markup = None
        if keyboard_buttons:
            reply_markup = InlineKeyboardMarkup(keyboard_buttons)
            total_reactions = len(complete_post.get('reactions', []))
            total_buttons = len(complete_post.get('buttons', []))
            logger.info(f"✅ Clavier créé - {total_reactions} réaction(s), {total_buttons} bouton(s)")

        # Envoyer le message selon son type
        logger.info(f"📤 === DÉBUT ENVOI MESSAGE ===")
        logger.info(f"📤 Type: {post_type}")
        logger.info(f"📤 Canal: {channel}")
        logger.info(f"📤 App bot: {app.bot}")
        logger.info(f"📤 Reply markup: {reply_markup is not None}")
        
        sent_message = None
        try:
            if post_type == "photo":
                logger.info("📸 Envoi photo...")
                logger.info(f"📸 Photo ID: {content}")
                logger.info(f"📸 Caption: {caption}")
                sent_message = await app.bot.send_photo(
                    chat_id=channel,
                    photo=content,
                    caption=caption,
                    reply_markup=reply_markup
                )
                logger.info(f"📸 Photo envoyée avec succès")
                
            elif post_type == "video":
                logger.info("🎥 Envoi vidéo...")
                logger.info(f"🎥 Video ID: {content}")
                logger.info(f"🎥 Caption: {caption}")
                sent_message = await app.bot.send_video(
                    chat_id=channel,
                    video=content,
                    caption=caption,
                    reply_markup=reply_markup
                )
                logger.info(f"🎥 Vidéo envoyée avec succès")
                
            elif post_type == "document":
                logger.info("📄 Envoi document...")
                logger.info(f"📄 Document ID: {content}")
                logger.info(f"📄 Caption: {caption}")
                sent_message = await app.bot.send_document(
                    chat_id=channel,
                    document=content,
                    caption=caption,
                    reply_markup=reply_markup
                )
                logger.info(f"📄 Document envoyé avec succès")
                
            elif post_type == "text":
                logger.info("📝 Envoi texte...")
                logger.info(f"📝 Texte: {content[:100]}...")
                sent_message = await app.bot.send_message(
                    chat_id=channel,
                    text=content,
                    reply_markup=reply_markup
                )
                logger.info(f"📝 Texte envoyé avec succès")
                
            else:
                logger.error(f"❌ Type de post non supporté: {post_type}")
                return False
                
            logger.info(f"📬 Message envoyé: {sent_message is not None}")
            if sent_message:
                logger.info(f"📬 Message ID: {sent_message.message_id}")
                logger.info(f"📬 Chat ID: {sent_message.chat_id}")
                
        except Exception as send_error:
            logger.error(f"❌ Erreur lors de l'envoi vers {channel}: {send_error}")
            logger.exception("🔍 Traceback complet envoi:")
            
            # Debug supplémentaire pour les erreurs d'envoi
            logger.error(f"🔍 Détails de l'erreur d'envoi:")
            logger.error(f"   Type d'erreur: {type(send_error)}")
            logger.error(f"   Message d'erreur: {str(send_error)}")
            
            return False

        if sent_message:
            logger.info(f"✅ Message planifié envoyé avec succès : {post_id}")
            
            # ✅ CORRECTION : Supprimer le post SEULEMENT si l'envoi a réussi
            try:
                logger.info("🗑️ Suppression du post de la base de données...")
                from config import settings
                db_path = settings.db_config.get("path", "bot.db")
                
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM posts WHERE id = ?", (post_id,))
                    rows_affected = cursor.rowcount
                    conn.commit()
                    
                if rows_affected > 0:
                    logger.info(f"✅ Post {post_id} supprimé de la base de données ({rows_affected} ligne(s))")
                else:
                    logger.warning(f"⚠️ Aucune ligne supprimée pour le post {post_id}")
                    
            except Exception as db_error:
                logger.error(f"❌ Erreur lors de la suppression du post {post_id} de la DB : {db_error}")
                logger.exception("🔍 Traceback suppression DB:")
            
            logger.info("🎉 === FIN send_scheduled_file - SUCCÈS ===")
            return True
        else:
            # ❌ CORRECTION : NE PAS supprimer le post si l'envoi a échoué
            logger.error(f"❌ Échec de l'envoi du message planifié : {post_id}")
            logger.error(f"❌ sent_message est None")
            
            # 🔄 RETRY : Reprogrammer le post pour dans 5 minutes
            try:
                from datetime import datetime, timedelta
                import pytz
                
                # Calculer la nouvelle heure (dans 5 minutes)
                new_time = datetime.now(pytz.UTC) + timedelta(minutes=5)
                logger.info(f"🔄 Reprogrammation pour {new_time}")
                
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
                
                logger.warning(f"⚠️ Post {post_id} reprogrammé pour {new_time} (dans 5 minutes)")
                
                # Essayer de reprogrammer le job si possible
                try:
                    # Récupérer le scheduler manager global
                    scheduler_manager = get_global_scheduler_manager()
                    if scheduler_manager:
                        job_id = f"post_{post_id}"
                        
                        # Supprimer l'ancien job s'il existe
                        if scheduler_manager.scheduler.get_job(job_id):
                            scheduler_manager.scheduler.remove_job(job_id)
                            logger.info(f"🗑️ Ancien job {job_id} supprimé")
                        
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
                        logger.info(f"✅ Job de retry créé pour {new_time}")
                        
                except Exception as retry_error:
                    logger.error(f"❌ Impossible de reprogrammer le job : {retry_error}")
                    logger.exception("🔍 Traceback reprogrammation job:")
                    
            except Exception as retry_error:
                logger.error(f"❌ Erreur lors de la reprogrammation : {retry_error}")
                logger.exception("🔍 Traceback reprogrammation:")
            
            logger.info("💥 === FIN send_scheduled_file - ÉCHEC (retry programmé) ===")
            return False

    except Exception as e:
        logger.error(f"❌ Erreur générale lors de l'envoi du fichier planifié : {e}")
        logger.exception("🔍 Traceback complet général:")
        logger.info("💥 === FIN send_scheduled_file - ERREUR ===")
        return False 
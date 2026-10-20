"""
Fonctions de gestion des réactions et boutons URL pour le bot Telegram
"""

import json
import logging
from typing import List, Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import settings
from conversation_states import (
    WAITING_REACTION_INPUT,
    WAITING_URL_INPUT,
    MAIN_MENU,
    POST_ACTIONS,
    WAITING_PUBLICATION_CONTENT,
)

logger = logging.getLogger(__name__)

async def handle_reactions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gère la sélection des réactions pour une publication"""
    query = update.callback_query
    await query.answer()

    # Récupérer les réactions actuelles ou initialiser une liste vide
    reactions = context.user_data.get('current_post', {}).get('reactions', [])
    
    # Ajouter la nouvelle réaction si elle n'existe pas déjà
    new_reaction = query.data.split('_')[1]  # Format: "reaction_emoji"
    if new_reaction not in reactions:
        reactions.append(new_reaction)
        context.user_data['current_post']['reactions'] = reactions
    
    # Mettre à jour le message avec les réactions sélectionnées
    keyboard = create_reactions_keyboard(reactions)
    await query.edit_message_text(
        text=f"Réactions sélectionnées: {' '.join(reactions)}\n\n"
             f"Sélectionnez d'autres réactions ou cliquez sur 'Terminé'",
        reply_markup=keyboard
    )
    
    return REACTIONS

def create_reactions_keyboard(selected_reactions: List[str]) -> InlineKeyboardMarkup:
    """Crée le clavier pour la sélection des réactions"""
    keyboard = []
    row = []
    
    # Ajouter les boutons de réaction
    for emoji in settings.bot_config["default_reactions"]:
        if len(row) == settings.bot_config["max_buttons_per_row"]:
            keyboard.append(row)
            row = []
        
        # Ajouter un indicateur si la réaction est déjà sélectionnée
        text = f"{emoji} ✓" if emoji in selected_reactions else emoji
        row.append(InlineKeyboardButton(text, callback_data=f"reaction_{emoji}"))
    
    if row:
        keyboard.append(row)
    
    # Ajouter le bouton Terminé
    keyboard.append([InlineKeyboardButton("Done", callback_data="reactions_done")])
    
    return InlineKeyboardMarkup(keyboard)

async def handle_url_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gère l'ajout de boutons URL à une publication"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "url_done":
        return POST_ACTIONS
    
    # Récupérer les boutons actuels ou initialiser une liste vide
    buttons = context.user_data.get('current_post', {}).get('buttons', [])
    
    # Ajouter le nouveau bouton
    button_data = query.data.split('_')[1:]  # Format: "url_text_url"
    if len(button_data) == 2:
        text, url = button_data
        buttons.append({"text": text, "url": url})
        context.user_data['current_post']['buttons'] = buttons
    
    # Mettre à jour le message avec les boutons sélectionnés
    keyboard = create_url_buttons_keyboard(buttons)
    await query.edit_message_text(
        text=f"Boutons URL sélectionnés:\n" + 
             "\n".join([f"{b['text']}: {b['url']}" for b in buttons]) +
             "\n\nSélectionnez d'autres boutons ou cliquez sur 'Terminé'",
        reply_markup=keyboard
    )
    
    return URL_BUTTONS

def create_url_buttons_keyboard(selected_buttons: List[Dict[str, str]]) -> InlineKeyboardMarkup:
    """Crée le clavier pour la sélection des boutons URL"""
    keyboard = []
    
    # Ajouter les boutons URL prédéfinis
    for button in settings.bot_config.get("default_url_buttons", []):
        keyboard.append([
            InlineKeyboardButton(
                button["text"],
                callback_data=f"url_{button['text']}_{button['url']}"
            )
        ])
    
    # Ajouter le bouton Terminé
    keyboard.append([InlineKeyboardButton("Done", callback_data="url_done")])
    
    return InlineKeyboardMarkup(keyboard)

async def save_post_with_reactions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sauvegarde la publication avec ses réactions et boutons URL"""
    query = update.callback_query
    await query.answer()
    
    if query.data != "reactions_done":
        return REACTIONS
    
    # Récupérer les données du post
    post_data = context.user_data.get('current_post', {})
    if not post_data:
        await query.edit_message_text("Error: No publication data found")
        return MAIN_MENU
    
    try:
        # Convertir les réactions et boutons en JSON
        reactions_json = json.dumps(post_data.get('reactions', []))
        buttons_json = json.dumps(post_data.get('buttons', []))
        
        # Sauvegarder dans la base de données
        db = context.bot_data.get('db')
        post_id = db.add_post(
            channel_id=post_data['channel_id'],
            post_type=post_data['type'],
            content=post_data['content'],
            caption=post_data.get('caption'),
            buttons=buttons_json,
            reactions=reactions_json,
            scheduled_time=post_data.get('scheduled_time')
        )
        
        # Nettoyer les données temporaires
        context.user_data.pop('current_post', None)
        
        await query.edit_message_text(
            f"Publication sauvegardée avec succès!\n"
            f"ID: {post_id}\n"
            f"Réactions: {', '.join(post_data.get('reactions', []))}\n"
            f"Boutons URL: {len(post_data.get('buttons', []))}"
        )
        
        return MAIN_MENU
        
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde de la publication: {e}")
        await query.edit_message_text(
            f"Erreur lors de la sauvegarde de la publication: {str(e)}"
        )
        return MAIN_MENU

async def add_reactions_to_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gère l'ajout de réactions à un post existant"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Extraire l'index du post du callback_data
        post_index = int(query.data.split('_')[-1])
        
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            try:
                await query.edit_message_text(
                    "❌ Post introuvable.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="main_menu")]])
                )
            except Exception:
                await query.message.reply_text(
                    "❌ Post introuvable.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="main_menu")]])
                )
            return MAIN_MENU
        
        # Stocker l'index du post en cours de modification
        context.user_data['current_post_index'] = post_index
        context.user_data['waiting_for_reactions'] = True
        
        # Demander les réactions à l'utilisateur et mémoriser le prompt pour nettoyage
        prompt = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📝 Send me the reactions, separated by '/'.\n"
                 "Example: 👍/❤️/🔥/😂\n\n"
                 "Up to 8 reactions.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_waiting_reactions")]])
        )
        context.user_data['reaction_input_ctx'] = {
            'prompt_chat_id': prompt.chat_id,
            'prompt_message_id': prompt.message_id,
            'post_index': post_index
        }
        
        return WAITING_REACTION_INPUT
        
    except Exception as e:
        logger.error(f"Erreur lors de l'ajout des réactions : {e}")
        try:
            await query.edit_message_text(
                "❌ Erreur lors de l'ajout des réactions.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="main_menu")]])
            )
        except Exception:
            await query.message.reply_text(
                "❌ Erreur lors de l'ajout des réactions.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="main_menu")]])
            )
        return MAIN_MENU

async def add_url_button_to_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gère l'ajout d'un bouton URL à un post existant"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Extraire l'index du post du callback_data
        post_index = int(query.data.split('_')[-1])
        
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            try:
                await query.edit_message_text(
                    "❌ Post introuvable.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="main_menu")]])
                )
            except Exception:
                await query.message.reply_text(
                    "❌ Post introuvable.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="main_menu")]])
                )
            return MAIN_MENU
        
        # Stocker l'index du post en cours de modification
        context.user_data['current_post_index'] = post_index
        context.user_data['waiting_for_url'] = True
        
        # Demander le bouton URL à l'utilisateur
        # Envoyer un nouveau message au lieu d'éditer (pour compatibilité avec les médias)
        ask_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📝 Send me the URL button as:\n"
                 "Button text | URL\n\n"
                 "Example: Visit the site | https://example.com",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_waiting_url")]])
        )
        # Mémoriser pour suppression
        context.user_data['last_prompt_message_id'] = ask_msg.message_id
        
        return WAITING_URL_INPUT
        
    except Exception as e:
        logger.error(f"Erreur lors de l'ajout du bouton URL : {e}")
        try:
            await query.edit_message_text(
                "❌ Erreur lors de l'ajout du bouton URL.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="main_menu")]])
            )
        except Exception:
            await query.message.reply_text(
                "❌ Erreur lors de l'ajout du bouton URL.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="main_menu")]])
            )
        return MAIN_MENU

async def handle_reaction_input(update, context):
    """Gère l'input des réactions pour un post."""
    if 'waiting_for_reactions' not in context.user_data or 'current_post_index' not in context.user_data:
        return WAITING_PUBLICATION_CONTENT
    try:
        post_index = context.user_data['current_post_index']
        text = update.message.text
        
        # Les boutons ReplyKeyboard sont maintenant gérés par le handler contextuel
        # Cette fonction ne traite que les vraies réactions
        
        if text == '/cancel':
            context.user_data.pop('waiting_for_reactions', None)
            context.user_data.pop('current_post_index', None)
            await update.message.reply_text("❌ Adding reactions cancelled.")
            return WAITING_PUBLICATION_CONTENT

        reactions = [r.strip() for r in text.split('/') if r.strip()]
        if len(reactions) > 8:
            reactions = reactions[:8]
            await update.message.reply_text("⚠️ Maximum 8 reactions allowed. Only the first 8 have been kept.")
        if not reactions:
            await update.message.reply_text(
                "❌ No valid reactions detected. Please try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="main_menu")]])
            )
            return WAITING_PUBLICATION_CONTENT
        # Mise à jour du post dans le contexte
        context.user_data['posts'][post_index]['reactions'] = reactions
        logger.info(f"✅ Réactions ajoutées au post {post_index}: {reactions}")
        logger.info(f"✅ Post complet après ajout: {context.user_data['posts'][post_index]}")
        # Supprimer le précédent aperçu si présent
        prev = context.user_data.get('preview_messages', {}).get(post_index)
        if prev:
            try:
                await context.bot.delete_message(chat_id=prev['chat_id'], message_id=prev['message_id'])
            except Exception:
                pass

        # Construction du nouveau clavier
        keyboard = []
        current_row = []
        for reaction in reactions:
            current_row.append(InlineKeyboardButton(
                f"{reaction}",
                callback_data=f"r:{reaction}:{post_index}"
            ))
            if len(current_row) == 4:
                keyboard.append(current_row)
                current_row = []
        if current_row:
            keyboard.append(current_row)
        # Ajout des boutons d'action
        keyboard.extend([
            [InlineKeyboardButton("Remove Reactions", callback_data=f"remove_reactions_{post_index}")],
            [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
            [InlineKeyboardButton("✏️ Edit File", callback_data=f"edit_file_{post_index}", api_kwargs={"style": "primary"})],
            [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}", api_kwargs={"style": "danger"})]
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        # Suppression de l'ancien message d'aperçu s'il existe
        preview_info = context.user_data.get('preview_messages', {}).get(post_index)
        if preview_info:
            try:
                await context.bot.delete_message(
                    chat_id=preview_info['chat_id'],
                    message_id=preview_info['message_id']
                )
            except Exception:
                pass
        # Supprimer le précédent aperçu si présent
        if 'preview_messages' in context.user_data:
            prev = context.user_data['preview_messages'].get(post_index)
            if prev:
                try:
                    await context.bot.delete_message(chat_id=prev['chat_id'], message_id=prev['message_id'])
                except Exception:
                    pass

        # Envoi du nouveau message avec les réactions
        post = context.user_data['posts'][post_index]
        sent_message = None
        if post["type"] == "photo":
            sent_message = await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=post["content"],
                caption=post.get("caption"),
                reply_markup=reply_markup
            )
        elif post["type"] == "video":
            sent_message = await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=post["content"],
                caption=post.get("caption"),
                reply_markup=reply_markup
            )
        elif post["type"] == "document":
            sent_message = await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=post["content"],
                caption=post.get("caption"),
                reply_markup=reply_markup
            )
        elif post["type"] == "text":
            sent_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=post["content"],
                reply_markup=reply_markup
            )
        if sent_message:
            if 'preview_messages' not in context.user_data:
                context.user_data['preview_messages'] = {}
            context.user_data['preview_messages'][post_index] = {
                'message_id': sent_message.message_id,
                'chat_id': update.effective_chat.id
            }
        # Supprimer le prompt et le message utilisateur
        ctx = context.user_data.pop('reaction_input_ctx', {})
        try:
            if ctx:
                await context.bot.delete_message(ctx['prompt_chat_id'], ctx['prompt_message_id'])
        except Exception:
            pass
        try:
            await update.message.delete()
        except Exception:
            pass
        del context.user_data['waiting_for_reactions']
        del context.user_data['current_post_index']
        return WAITING_PUBLICATION_CONTENT
    except Exception as e:
        logger.error(f"Erreur lors du traitement des réactions : {e}")
        await update.message.reply_text(
            "❌ Erreur lors du traitement des réactions.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")]])
        )
        return WAITING_PUBLICATION_CONTENT

async def handle_url_input(update, context):
    """Gère l'input des boutons URL pour un post."""
    if 'waiting_for_url' not in context.user_data or 'current_post_index' not in context.user_data:
        return WAITING_PUBLICATION_CONTENT
    try:
        post_index = context.user_data['current_post_index']
        text = update.message.text.strip()
        
        # Les boutons ReplyKeyboard sont maintenant gérés par le handler contextuel
        # Cette fonction ne traite que les vraies URLs
        
        if text == '/cancel':
            context.user_data.pop('waiting_for_url', None)
            context.user_data.pop('current_post_index', None)
            await update.message.reply_text("❌ Adding URL button cancelled.")
            return WAITING_PUBLICATION_CONTENT
        if '|' not in text:
            await update.message.reply_text(
                "❌ Incorrect format. Use: Button text | URL\nExample: Visit site | https://example.com"
            )
            return WAITING_PUBLICATION_CONTENT
        button_text, url = [part.strip() for part in text.split('|', 1)]
        if not url.startswith(('http://', 'https://')):
            await update.message.reply_text(
                "❌ L'URL doit commencer par http:// ou https://"
            )
            return WAITING_PUBLICATION_CONTENT
        if 'buttons' not in context.user_data['posts'][post_index]:
            context.user_data['posts'][post_index]['buttons'] = []
        context.user_data['posts'][post_index]['buttons'].append({
            'text': button_text,
            'url': url
        })
        # Construction du nouveau clavier
        keyboard = []
        # Normaliser les réactions (peut être une liste ou une string JSON "[]")
        reactions_val = context.user_data['posts'][post_index].get('reactions', [])
        if isinstance(reactions_val, str):
            try:
                reactions_list = json.loads(reactions_val)
                if not isinstance(reactions_list, list):
                    reactions_list = []
            except Exception:
                reactions_list = []
        else:
            reactions_list = reactions_val or []

        has_reactions = len(reactions_list) > 0

        if has_reactions:
            current_row = []
            for reaction in reactions_list:
                current_row.append(InlineKeyboardButton(
                    f"{reaction}",
                    callback_data=f"r:{reaction}:{post_index}"
                ))
                if len(current_row) == 4:
                    keyboard.append(current_row)
                    current_row = []
            if current_row:
                keyboard.append(current_row)

        for btn in context.user_data['posts'][post_index]['buttons']:
            keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])

        # Bouton réactions dynamique: ajouter si aucune réaction, supprimer si présentes
        if has_reactions:
            keyboard.append([InlineKeyboardButton("🗑️ Remove Reactions", callback_data=f"remove_reactions_{post_index}")])
        else:
            keyboard.append([InlineKeyboardButton("✨ Add Reactions", callback_data=f"add_reactions_{post_index}", api_kwargs={"style": "success"})])

        # Additional buttons
        keyboard.extend([
            [InlineKeyboardButton("Remove URL Buttons", callback_data=f"remove_url_buttons_{post_index}")],
            [InlineKeyboardButton("✏️ Edit File", callback_data=f"edit_file_{post_index}", api_kwargs={"style": "primary"})],
            [InlineKeyboardButton("❌ Delete", callback_data=f"delete_post_{post_index}", api_kwargs={"style": "danger"})]
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        preview_info = context.user_data.get('preview_messages', {}).get(post_index)
        if preview_info:
            try:
                await context.bot.delete_message(
                    chat_id=preview_info['chat_id'],
                    message_id=preview_info['message_id']
                )
            except Exception:
                pass
        post = context.user_data['posts'][post_index]
        sent_message = None
        if post["type"] == "photo":
            sent_message = await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=post["content"],
                caption=post.get("caption"),
                reply_markup=reply_markup
            )
        elif post["type"] == "video":
            sent_message = await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=post["content"],
                caption=post.get("caption"),
                reply_markup=reply_markup
            )
        elif post["type"] == "document":
            sent_message = await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=post["content"],
                caption=post.get("caption"),
                reply_markup=reply_markup
            )
        elif post["type"] == "text":
            sent_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=post["content"],
                reply_markup=reply_markup
            )
        if sent_message:
            if 'preview_messages' not in context.user_data:
                context.user_data['preview_messages'] = {}
            context.user_data['preview_messages'][post_index] = {
                'message_id': sent_message.message_id,
                'chat_id': update.effective_chat.id
            }
        # Supprimer le prompt si présent
        if context.user_data.get('last_prompt_message_id'):
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=context.user_data['last_prompt_message_id'])
            except Exception:
                pass
            context.user_data.pop('last_prompt_message_id', None)

        try:
            await update.message.delete()
        except Exception:
            pass
        del context.user_data['waiting_for_url']
        del context.user_data['current_post_index']
        return WAITING_PUBLICATION_CONTENT
    except Exception as e:
        logger.error(f"Erreur lors du traitement du bouton URL : {e}")
        await update.message.reply_text(
            "❌ Erreur lors du traitement du bouton URL.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Main menu", callback_data="main_menu")]])
        )
        return WAITING_PUBLICATION_CONTENT

async def remove_reactions(update, context):
    """Supprime toutes les réactions d'un post"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Extraire l'index du post
        post_index = int(query.data.split('_')[-1])
        
        # Supprimer les réactions du post
        if 'posts' in context.user_data and post_index < len(context.user_data['posts']):
            context.user_data['posts'][post_index]['reactions'] = []
            
            # Rebuild keyboard without reactions
            keyboard = [
                [InlineKeyboardButton("➕ Add Reactions", callback_data=f"add_reactions_{post_index}")],
                [InlineKeyboardButton("🔗 Add URL Button", callback_data=f"add_url_button_{post_index}", api_kwargs={"style": "primary"})],
                [InlineKeyboardButton("❌ Delete", callback_data=f"delete_post_{post_index}", api_kwargs={"style": "danger"})],
                [InlineKeyboardButton("✏️ Edit File", callback_data=f"edit_file_{post_index}", api_kwargs={"style": "primary"})]
            ]
            
            # Mettre à jour le message
            try:
                await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Erreur lors de la mise à jour du message: {e}")
            
            await query.message.reply_text("✅ Reactions removed successfully!")
            
        return WAITING_PUBLICATION_CONTENT
        
    except Exception as e:
        logger.error(f"Erreur dans remove_reactions: {e}")
        await query.answer("Error removing reactions")
        return WAITING_PUBLICATION_CONTENT

async def remove_url_buttons(update, context):
    """Supprime tous les boutons URL d'un post"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Extraire l'index du post
        post_index = int(query.data.split('_')[-1])
        
        # Supprimer les boutons URL du post
        if 'posts' in context.user_data and post_index < len(context.user_data['posts']):
            context.user_data['posts'][post_index]['buttons'] = []
            
            # Rebuild keyboard without URL buttons
            keyboard = [
                [InlineKeyboardButton("➕ Add Reactions", callback_data=f"add_reactions_{post_index}")],
                [InlineKeyboardButton("🔗 Add URL Button", callback_data=f"add_url_button_{post_index}", api_kwargs={"style": "primary"})],
                [InlineKeyboardButton("❌ Delete", callback_data=f"delete_post_{post_index}", api_kwargs={"style": "danger"})],
                [InlineKeyboardButton("✏️ Edit File", callback_data=f"edit_file_{post_index}", api_kwargs={"style": "primary"})]
            ]
            
            # Mettre à jour le message
            try:
                await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Erreur lors de la mise à jour du message: {e}")
            
            await query.message.reply_text("✅ URL buttons removed successfully!")
            
        return WAITING_PUBLICATION_CONTENT
        
    except Exception as e:
        logger.error(f"Erreur dans remove_url_buttons: {e}")
        await query.answer("Erreur lors de la suppression des boutons URL")
        return WAITING_PUBLICATION_CONTENT 
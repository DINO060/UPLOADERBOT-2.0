from pyrogram import filters
from pyrogram.types import CallbackQuery
from services.reaction_service import reaction_service, DEFAULT_EMOJIS
from database.manager import get_db_session

async def setup_reaction_handlers(app):
    @app.on_callback_query(filters.regex(r"^r:"))
    async def on_reaction_click(client: 'Client', callback_query: CallbackQuery):
        """Handle reaction button clicks"""
        data = callback_query.data
        emoji = data[2:]  # Remove 'r:' prefix
        
        msg = callback_query.message
        chat_id = msg.chat.id
        message_id = msg.id
        user_id = callback_query.from_user.id
        
        # Check if it's a reset command (admin only)
        if emoji == "__reset":
            # Verify admin status (you'll need to implement is_admin check)
            if not await is_admin(client, chat_id, user_id):
                await callback_query.answer("Only admins can reset reactions", show_alert=True)
                return
                
            await reaction_service.reset_reactions(chat_id, message_id)
            markup = reaction_service.build_markup(chat_id, message_id)
            await client.edit_message_reply_markup(chat_id, message_id, reply_markup=markup)
            await callback_query.answer("Reactions reset", show_alert=False)
            return
            
        # Verify it's a valid emoji
        if emoji not in DEFAULT_EMOJIS:
            await callback_query.answer("Invalid reaction", show_alert=True)
            return
            
        # Toggle the reaction
        is_added, new_count = await reaction_service.toggle_reaction(
            chat_id, message_id, user_id, emoji
        )
        
        # Update the message markup with new counts
        markup = reaction_service.build_markup(chat_id, message_id)
        await client.edit_message_reply_markup(chat_id, message_id, reply_markup=markup)
        
        # Provide feedback to the user
        action = "added" if is_added else "removed"
        await callback_query.answer(f"{action} {emoji}", show_alert=False)

async def is_admin(client, chat_id: int, user_id: int) -> bool:
    """Check if user is an admin in the chat"""
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in ["creator", "administrator"]
    except Exception:
        return False

# Helper function to add reactions to a message
async def attach_reactions(client, chat_id: int, message_id: int):
    """Attach reaction buttons to a message"""
    markup = reaction_service.build_markup(chat_id, message_id)
    await client.edit_message_reply_markup(chat_id, message_id, reply_markup=markup)

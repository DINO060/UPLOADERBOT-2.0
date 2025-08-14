"""
Gestion de l'état d'édition des posts.
"""
from typing import Optional, Dict, Any

class PostEditingState:
    def __init__(self):
        self.current_post: Optional[Dict[str, Any]] = None
        self.editing_field: Optional[str] = None
        self.original_content: Optional[str] = None

    def start_editing(self, post: Dict[str, Any], field: str):
        """Starts editing a post."""
        self.current_post = post
        self.editing_field = field
        self.original_content = post.get(field)

    def save_edit(self, new_content: str) -> bool:
        """Saves post modifications."""
        if self.current_post and self.editing_field:
            self.current_post[self.editing_field] = new_content
            return True
        return False

    def cancel_edit(self):
        """Cancels current modifications."""
        if self.current_post and self.editing_field and self.original_content:
            self.current_post[self.editing_field] = self.original_content
        self.reset()

    def reset(self):
        """Resets editing state."""
        self.current_post = None
        self.editing_field = None
        self.original_content = None 
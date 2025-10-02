"""
AI model helper utilities.

Provides a single place to decide which AI model string to use for different
clients. Honors the global ENABLE_GPT5_MINI toggle from `config.settings`.
"""
from typing import Optional
from config import settings, AI_MODEL, ENABLE_GPT5_MINI


def get_model_for_client(client_name: Optional[str] = None) -> str:
    """Return the model string to use for a given client.

    - If ENABLE_GPT5_MINI is True, this always returns 'gpt-5-mini'.
    - Otherwise returns AI_MODEL (from environment or default).

    Args:
        client_name: optional client identifier (unused now, present for future
                     per-client overrides).

    Returns:
        A model name string.
    """
    if ENABLE_GPT5_MINI:
        return 'gpt-5-mini'
    return AI_MODEL or settings.ai_model


def is_gpt5_enabled() -> bool:
    """Convenience check whether GPT-5 mini is globally enabled."""
    return ENABLE_GPT5_MINI

"""Notify-only Telegram notification MCP server package."""

__version__ = "0.2.0"

from .config import (
    ALLOWED_NOTIFICATION_EVENTS,
    TelegramConfig,
    format_notification_message,
    load_telegram_config,
    normalize_message,
)
from .messaging import send_telegram_message

__all__ = [
    "__version__",
    "ALLOWED_NOTIFICATION_EVENTS",
    "TelegramConfig",
    "format_notification_message",
    "load_telegram_config",
    "normalize_message",
    "send_telegram_message",
]

"""Telegram notification MCP server with bidirectional reply support."""

__version__ = "0.1.0"

from .config import (
    ALLOWED_NOTIFICATION_EVENTS,
    MAX_CALLBACK_DATA_BYTES,
    MAX_POLL_OPTIONS,
    MAX_POLL_QUESTION_LENGTH,
    TelegramConfig,
    format_notification_message,
    load_telegram_config,
    normalize_message,
)
from .inbox import (
    INPUT_MODE_INLINE,
    INPUT_MODE_POLL,
    INPUT_MODE_TEXT,
    STATUS_CANCELLED,
    STATUS_CONSUMED,
    STATUS_EXPIRED,
    STATUS_RESOLVED,
    STATUS_WAITING,
    ParsedReplyCommand,
    initialize_inbox_db,
)
from .messaging import (
    answer_telegram_callback_query,
    send_telegram_inline_keyboard,
    send_telegram_message,
    send_telegram_poll,
)
from .singleton import (
    SingletonAcquireError,
    SingletonLease,
    acquire_singleton_or_preempt,
    release_singleton,
)

__all__ = [
    "__version__",
    "ALLOWED_NOTIFICATION_EVENTS",
    "MAX_CALLBACK_DATA_BYTES",
    "MAX_POLL_OPTIONS",
    "MAX_POLL_QUESTION_LENGTH",
    "TelegramConfig",
    "format_notification_message",
    "load_telegram_config",
    "normalize_message",
    "INPUT_MODE_INLINE",
    "INPUT_MODE_POLL",
    "INPUT_MODE_TEXT",
    "STATUS_CANCELLED",
    "STATUS_CONSUMED",
    "STATUS_EXPIRED",
    "STATUS_RESOLVED",
    "STATUS_WAITING",
    "ParsedReplyCommand",
    "initialize_inbox_db",
    "answer_telegram_callback_query",
    "send_telegram_inline_keyboard",
    "send_telegram_message",
    "send_telegram_poll",
    "SingletonAcquireError",
    "SingletonLease",
    "acquire_singleton_or_preempt",
    "release_singleton",
]

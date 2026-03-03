"""Telegram configuration, constants, and message formatting."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any, Mapping

ALLOWED_NOTIFICATION_EVENTS = {
    "question",
    "plan_ready",
    "final",
    "attention_needed",
    "error",
}
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
MAX_POLL_QUESTION_LENGTH = 300
MIN_POLL_OPTIONS = 2
MAX_POLL_OPTIONS = 12
MAX_POLL_OPTION_LENGTH = 100
MIN_CALLBACK_DATA_BYTES = 1
MAX_CALLBACK_DATA_BYTES = 64
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_RETRY_DELAY_SECONDS = 1.0
TRUNCATION_SUFFIX = "\n...[truncated]"
_LEGACY_HEADER_RE = re.compile(r"^\[[^\]]+\]\[[^\]]+\]\s*")

_EVENT_STYLE: dict[str, dict[str, str]] = {
    "attention_needed": {"emoji": "\U0001F6A8", "label": "ATTENTION"},
    "error": {"emoji": "\u274C", "label": "ERROR"},
    "question": {"emoji": "\u2753", "label": "QUESTION"},
    "plan_ready": {"emoji": "\U0001F4DD", "label": "PLAN READY"},
    "final": {"emoji": "\u2705", "label": "FINAL"},
}


@dataclass(frozen=True)
class TelegramConfig:
    """Immutable Telegram bot configuration."""

    bot_token: str
    chat_id: str
    parse_mode: str | None = None
    disable_notification: bool = False
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


def _parse_bool(raw: str | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_timeout(raw: str | None) -> float:
    if raw is None or not raw.strip():
        return DEFAULT_TIMEOUT_SECONDS
    timeout_seconds = float(raw)
    if timeout_seconds <= 0:
        raise ValueError("TELEGRAM_TIMEOUT_SECONDS must be > 0")
    return timeout_seconds


def load_telegram_config(env: Mapping[str, str] | None = None) -> TelegramConfig:
    """Load Telegram configuration from environment variables."""
    source = os.environ if env is None else env
    disable_notification = _parse_bool(
        source.get("TELEGRAM_DISABLE_NOTIFICATION"),
        default=False,
    )
    timeout_seconds = _parse_timeout(source.get("TELEGRAM_TIMEOUT_SECONDS"))
    bot_token = (source.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (source.get("TELEGRAM_CHAT_ID") or "").strip()
    parse_mode = (source.get("TELEGRAM_PARSE_MODE") or "").strip() or None

    if not disable_notification:
        missing: list[str] = []
        if not bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing required Telegram environment variables: {joined}")

    return TelegramConfig(
        bot_token=bot_token,
        chat_id=chat_id,
        parse_mode=parse_mode,
        disable_notification=disable_notification,
        timeout_seconds=timeout_seconds,
    )


def normalize_message(
    message: str,
    *,
    max_length: int = MAX_TELEGRAM_MESSAGE_LENGTH,
    truncation_suffix: str = TRUNCATION_SUFFIX,
) -> str:
    """Truncate message to Telegram's maximum length."""
    text = str(message or "")
    if len(text) <= max_length:
        return text
    if len(truncation_suffix) >= max_length:
        return text[:max_length]
    limit = max_length - len(truncation_suffix)
    return f"{text[:limit]}{truncation_suffix}"


def format_notification_message(
    *,
    task: str,
    event: str,
    message: str,
    requires_action: bool = False,
    session_id: str | None = None,
    run_id: str | None = None,
) -> str:
    """Format a structured notification message."""
    event_key = (event or "").strip().lower()
    if event_key not in ALLOWED_NOTIFICATION_EVENTS:
        raise ValueError(f"Unsupported notification event: {event}")

    style = _EVENT_STYLE.get(event_key, {"emoji": "\u2139\ufe0f", "label": event_key.upper()})
    details = _clean_message_lines(str(message or ""))
    summary = _shorten(details[0] if details else "No details provided.", limit=140)
    task_label = _shorten(str(task or "").strip() or "unknown-task", limit=80)
    lines = [
        f"{style['emoji']} {style['label']} | {task_label}",
        summary,
    ]
    if requires_action:
        lines.append("\U0001F6A8 ACTION REQUIRED")
    for detail in details[1:5]:
        lines.append(f"- {detail}")

    id_parts: list[str] = []
    if run_id:
        id_parts.append(f"run_id={run_id}")
    if session_id:
        id_parts.append(f"session_id={session_id}")
    if id_parts:
        lines.append(" | ".join(id_parts))
    return "\n".join(lines)


def _clean_message_lines(message: str) -> list[str]:
    cleaned: list[str] = []
    for raw in str(message or "").splitlines():
        line = _LEGACY_HEADER_RE.sub("", raw.strip())
        if not line:
            continue
        lower = line.lower()
        if lower.startswith("timestamp_"):
            continue
        if lower in {"action_required=true", "action_required=false"}:
            continue
        cleaned.append(line)
    return cleaned


def _shorten(text: str, *, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."

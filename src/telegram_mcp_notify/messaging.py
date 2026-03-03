"""Telegram Bot API message-sending functions."""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping, Protocol

import httpx

from .config import (
    DEFAULT_RETRY_DELAY_SECONDS,
    MAX_CALLBACK_DATA_BYTES,
    MAX_POLL_OPTION_LENGTH,
    MAX_POLL_QUESTION_LENGTH,
    MIN_CALLBACK_DATA_BYTES,
    MIN_POLL_OPTIONS,
    MAX_POLL_OPTIONS,
    TelegramConfig,
    normalize_message,
)


class _SupportsPost(Protocol):
    def post(self, url: str, *, json: Mapping[str, Any], timeout: float) -> Any:
        ...


def _coerce_message_id(data: Mapping[str, Any]) -> int | None:
    result = data.get("result") if isinstance(data, Mapping) else None
    if not isinstance(result, Mapping):
        return None
    message_id = result.get("message_id")
    if isinstance(message_id, int):
        return message_id
    if isinstance(message_id, str) and message_id.strip().isdigit():
        return int(message_id.strip())
    return None


def _coerce_poll_id(data: Mapping[str, Any]) -> str | None:
    result = data.get("result") if isinstance(data, Mapping) else None
    if not isinstance(result, Mapping):
        return None
    poll = result.get("poll")
    if isinstance(poll, Mapping):
        poll_id = poll.get("id")
        if isinstance(poll_id, str) and poll_id.strip():
            return poll_id.strip()
    return None


def _extract_retry_after_seconds(data: Mapping[str, Any]) -> float | None:
    params = data.get("parameters") if isinstance(data, Mapping) else None
    if not isinstance(params, Mapping):
        return None
    retry_after = params.get("retry_after")
    if isinstance(retry_after, (int, float)) and retry_after > 0:
        return float(retry_after)
    if isinstance(retry_after, str):
        try:
            parsed = float(retry_after.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _extract_error_description(data: Mapping[str, Any], fallback: str = "") -> str:
    if isinstance(data, Mapping):
        description = data.get("description")
        if isinstance(description, str) and description.strip():
            return description.strip()
    return fallback or "Telegram API request failed"


def _send_json_with_client(
    *,
    endpoint: str,
    payload: Mapping[str, Any],
    config: TelegramConfig,
    client: _SupportsPost,
    sleep_fn: Callable[[float], None],
    max_retries: int,
    retry_delay_seconds: float,
) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{config.bot_token}/{endpoint}"
    attempts = max(0, int(max_retries))

    for attempt in range(attempts + 1):
        try:
            response = client.post(url, json=payload, timeout=float(config.timeout_seconds))
        except Exception as exc:
            if attempt < attempts:
                sleep_fn(retry_delay_seconds)
                continue
            return {
                "ok": False,
                "status_code": None,
                "message_id": None,
                "poll_id": None,
                "error": f"Telegram request error: {exc}",
            }

        status_code = int(getattr(response, "status_code", 0)) or None
        try:
            data = response.json()
        except Exception:
            data = {}
        if not isinstance(data, Mapping):
            data = {}

        if status_code == 200 and data.get("ok") is True:
            return {
                "ok": True,
                "status_code": status_code,
                "message_id": _coerce_message_id(data),
                "poll_id": _coerce_poll_id(data),
                "error": None,
            }

        if status_code == 429 and attempt < attempts:
            retry_after = _extract_retry_after_seconds(data) or retry_delay_seconds
            sleep_fn(retry_after)
            continue

        response_text = getattr(response, "text", "") or ""
        return {
            "ok": False,
            "status_code": status_code,
            "message_id": None,
            "poll_id": None,
            "error": _extract_error_description(data, fallback=response_text.strip()),
        }

    return {
        "ok": False,
        "status_code": None,
        "message_id": None,
        "poll_id": None,
        "error": f"Telegram {endpoint} request failed after retries",
    }


def _send_json_request(
    *,
    endpoint: str,
    payload: Mapping[str, Any],
    config: TelegramConfig,
    client: _SupportsPost | None,
    sleep_fn: Callable[[float], None],
    max_retries: int,
    retry_delay_seconds: float,
) -> dict[str, Any]:
    if config.disable_notification:
        return {
            "ok": True,
            "status_code": None,
            "message_id": None,
            "poll_id": None,
            "error": None,
        }

    if not config.bot_token or not config.chat_id:
        return {
            "ok": False,
            "status_code": None,
            "message_id": None,
            "poll_id": None,
            "error": "Telegram configuration requires bot token and chat id",
        }

    if client is not None:
        return _send_json_with_client(
            endpoint=endpoint,
            payload=payload,
            config=config,
            client=client,
            sleep_fn=sleep_fn,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
        )

    with httpx.Client() as httpx_client:
        return _send_json_with_client(
            endpoint=endpoint,
            payload=payload,
            config=config,
            client=httpx_client,
            sleep_fn=sleep_fn,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
        )


def send_telegram_message(
    text: str,
    *,
    config: TelegramConfig,
    client: _SupportsPost | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_retries: int = 1,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> dict[str, Any]:
    """Send a text message via Telegram Bot API."""
    payload: dict[str, Any] = {
        "chat_id": config.chat_id,
        "text": normalize_message(text),
        "disable_notification": config.disable_notification,
    }
    if config.parse_mode:
        payload["parse_mode"] = config.parse_mode
    raw = _send_json_request(
        endpoint="sendMessage",
        payload=payload,
        config=config,
        client=client,
        sleep_fn=sleep_fn,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
    )
    return {
        "ok": bool(raw.get("ok")),
        "status_code": raw.get("status_code"),
        "message_id": raw.get("message_id"),
        "error": raw.get("error"),
    }


def send_telegram_poll(
    question: str,
    options: list[str] | tuple[str, ...],
    *,
    allows_multiple_answers: bool = False,
    config: TelegramConfig,
    client: _SupportsPost | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_retries: int = 1,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> dict[str, Any]:
    """Send a poll via Telegram Bot API."""
    normalized_question = str(question or "").strip()
    if not (1 <= len(normalized_question) <= MAX_POLL_QUESTION_LENGTH):
        raise ValueError("Poll question length must be between 1 and 300 characters.")

    normalized_options = [str(item).strip() for item in options if str(item).strip()]
    if not (MIN_POLL_OPTIONS <= len(normalized_options) <= MAX_POLL_OPTIONS):
        raise ValueError("Poll options must include between 2 and 12 entries.")
    for option in normalized_options:
        if len(option) > MAX_POLL_OPTION_LENGTH:
            raise ValueError("Poll option length must be at most 100 characters.")

    payload = {
        "chat_id": config.chat_id,
        "question": normalized_question,
        "options": [{"text": option} for option in normalized_options],
        "type": "regular",
        "is_anonymous": False,
        "allows_multiple_answers": bool(allows_multiple_answers),
        "disable_notification": config.disable_notification,
    }
    raw = _send_json_request(
        endpoint="sendPoll",
        payload=payload,
        config=config,
        client=client,
        sleep_fn=sleep_fn,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
    )
    return {
        "ok": bool(raw.get("ok")),
        "status_code": raw.get("status_code"),
        "message_id": raw.get("message_id"),
        "poll_id": raw.get("poll_id"),
        "error": raw.get("error"),
    }


def send_telegram_inline_keyboard(
    text: str,
    inline_keyboard: list[list[dict[str, str]]],
    *,
    config: TelegramConfig,
    client: _SupportsPost | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_retries: int = 1,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> dict[str, Any]:
    """Send a message with an inline keyboard via Telegram Bot API."""
    normalized_text = normalize_message(str(text or "").strip())
    if not normalized_text:
        raise ValueError("Inline keyboard message text is required.")
    if not inline_keyboard:
        raise ValueError("inline_keyboard must not be empty.")

    for row in inline_keyboard:
        if not row:
            raise ValueError("inline_keyboard rows must not be empty.")
        for button in row:
            label = str(button.get("text") or "").strip()
            callback_data = str(button.get("callback_data") or "")
            if not label:
                raise ValueError("Inline keyboard button text is required.")
            callback_len = len(callback_data.encode("utf-8"))
            if callback_len < MIN_CALLBACK_DATA_BYTES or callback_len > MAX_CALLBACK_DATA_BYTES:
                raise ValueError("Inline keyboard callback_data must be 1..64 bytes.")

    payload: dict[str, Any] = {
        "chat_id": config.chat_id,
        "text": normalized_text,
        "disable_notification": config.disable_notification,
        "reply_markup": {"inline_keyboard": inline_keyboard},
    }
    if config.parse_mode:
        payload["parse_mode"] = config.parse_mode
    raw = _send_json_request(
        endpoint="sendMessage",
        payload=payload,
        config=config,
        client=client,
        sleep_fn=sleep_fn,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
    )
    return {
        "ok": bool(raw.get("ok")),
        "status_code": raw.get("status_code"),
        "message_id": raw.get("message_id"),
        "error": raw.get("error"),
    }


def answer_telegram_callback_query(
    callback_query_id: str,
    *,
    text: str | None = None,
    show_alert: bool = False,
    cache_time: int = 0,
    config: TelegramConfig,
    client: _SupportsPost | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_retries: int = 1,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> dict[str, Any]:
    """Answer a callback query from an inline keyboard button press."""
    normalized_id = str(callback_query_id or "").strip()
    if not normalized_id:
        raise ValueError("callback_query_id is required.")
    payload: dict[str, Any] = {
        "callback_query_id": normalized_id,
        "show_alert": bool(show_alert),
        "cache_time": max(0, int(cache_time)),
    }
    if text is not None and str(text).strip():
        normalized_text = str(text).strip()
        if len(normalized_text) > 200:
            raise ValueError("answerCallbackQuery text must be <= 200 characters.")
        payload["text"] = normalized_text

    raw = _send_json_request(
        endpoint="answerCallbackQuery",
        payload=payload,
        config=config,
        client=client,
        sleep_fn=sleep_fn,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
    )
    return {
        "ok": bool(raw.get("ok")),
        "status_code": raw.get("status_code"),
        "message_id": None,
        "error": raw.get("error"),
    }

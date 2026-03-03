"""Background Telegram reply listener for pending prompt inbox."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping

import httpx

from .config import TelegramConfig, load_telegram_config
from .inbox import (
    RESPONSE_SELECTION,
    get_listener_state,
    get_waiting_prompt_by_callback_namespace,
    get_waiting_prompt_by_poll_id,
    initialize_inbox_db,
    mark_prompt_resolved,
    parse_reply_command,
    record_inbound_message,
    resolve_listener_log_path,
    set_listener_error,
    update_listener_state,
)
from .messaging import answer_telegram_callback_query
from .singleton import (
    SingletonAcquireError,
    SingletonLease,
    acquire_singleton_or_preempt,
    release_singleton,
)

LISTENER_VERSION = "1"
SINGLETON_LOCK_NAME = "telegram_reply_listener"
DEFAULT_SINGLETON_POLICY = "strict_single_owner"
DEFAULT_SINGLETON_RETRIES = 5
DEFAULT_SINGLETON_RETRY_DELAY_SECONDS = 0.2
CALLBACK_DATA_RE = re.compile(r"^c:([A-Za-z0-9_-]{4,40}):(\d{1,2})$")
CALLBACK_TOAST_TEXT_MAX_CHARS = 200
CALLBACK_TOAST_PREFIX = "Selection confirmed: "
CALLBACK_TOAST_FALLBACK = "Selection confirmed."
CALLBACK_TOAST_ELLIPSIS = "..."
_CURRENT_LOG_PATH: Path | None = None
_SUPPORTED_SINGLETON_POLICIES = {"machine_kill_old", "strict_single_owner"}


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stderr(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _log(message: str, *, level: str = "INFO") -> None:
    line = f"{_utc_iso_now()} [{str(level).upper()}] [telegram_reply_listener] {str(message).strip()}"
    _stderr(line)
    target = _CURRENT_LOG_PATH
    if target is None:
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        return


def _parse_non_negative_int_env(key: str, default: int) -> int:
    raw = str(os.getenv(key) or "").strip()
    if not raw:
        return int(default)
    parsed = int(raw)
    if parsed < 0:
        raise ValueError(f"{key} must be >= 0")
    return parsed


def _parse_non_negative_float_env(key: str, default: float) -> float:
    raw = str(os.getenv(key) or "").strip()
    if not raw:
        return float(default)
    parsed = float(raw)
    if parsed < 0:
        raise ValueError(f"{key} must be >= 0")
    return parsed


def _load_singleton_settings() -> tuple[str, int, float]:
    policy = str(os.getenv("TELEGRAM_SINGLETON_POLICY") or DEFAULT_SINGLETON_POLICY).strip().lower()
    retries = _parse_non_negative_int_env("TELEGRAM_SINGLETON_RETRIES", DEFAULT_SINGLETON_RETRIES)
    retry_delay_seconds = _parse_non_negative_float_env(
        "TELEGRAM_SINGLETON_RETRY_DELAY_SECONDS",
        DEFAULT_SINGLETON_RETRY_DELAY_SECONDS,
    )
    return policy, retries, retry_delay_seconds


def _acquire_listener_singleton() -> SingletonLease:
    policy, retries, retry_delay_seconds = _load_singleton_settings()
    if policy not in _SUPPORTED_SINGLETON_POLICIES:
        raise ValueError(
            f"Unsupported TELEGRAM_SINGLETON_POLICY: {policy}. "
            f"Supported values: {', '.join(sorted(_SUPPORTED_SINGLETON_POLICIES))}"
        )
    lease = acquire_singleton_or_preempt(
        lock_name=SINGLETON_LOCK_NAME,
        owner_label=SINGLETON_LOCK_NAME,
        retries=retries,
        retry_delay_s=retry_delay_seconds,
        preempt_alive_owner=(policy == "machine_kill_old"),
    )
    for replaced_pid in lease.preempted_pids:
        _log(f"preempted existing process pid={replaced_pid}", level="WARNING")
    return lease


def _is_token_conflict_error(exc: Exception) -> bool:
    status_error_cls = getattr(httpx, "HTTPStatusError", None)
    if isinstance(status_error_cls, type) and isinstance(exc, status_error_cls):
        try:
            if int(exc.response.status_code) == 409:
                return True
        except Exception:
            pass
    text = str(exc or "").strip().lower()
    return ("409" in text) and ("conflict" in text)


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _extract_message(update: Mapping[str, Any]) -> Mapping[str, Any] | None:
    message = update.get("message")
    if isinstance(message, Mapping):
        return message
    edited = update.get("edited_message")
    if isinstance(edited, Mapping):
        return edited
    return None


def _extract_chat_id(message: Mapping[str, Any] | None) -> str:
    if not isinstance(message, Mapping):
        return ""
    chat = message.get("chat")
    if isinstance(chat, Mapping):
        chat_id = chat.get("id")
        if chat_id is not None:
            return str(chat_id).strip()
    return ""


def _extract_text(message: Mapping[str, Any]) -> str:
    text = message.get("text")
    if isinstance(text, str):
        return text.strip()
    caption = message.get("caption")
    if isinstance(caption, str):
        return caption.strip()
    return ""


def _extract_user_id(payload: Mapping[str, Any] | None) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    user_id = payload.get("id")
    if user_id is None:
        return None
    return str(user_id).strip() or None


def _parse_callback_data(callback_data: str | None) -> tuple[str, int] | None:
    raw = str(callback_data or "").strip()
    match = CALLBACK_DATA_RE.match(raw)
    if match is None:
        return None
    namespace = str(match.group(1)).strip()
    option_idx = int(match.group(2))
    return namespace, option_idx


def _get_selected_options(choices: Any, option_ids: list[int]) -> list[str]:
    if not isinstance(choices, list):
        return []
    selected: list[str] = []
    for option_id in option_ids:
        if 0 <= int(option_id) < len(choices):
            selected.append(str(choices[int(option_id)]))
    return selected


def _build_choice_callback_toast_text(selected_option: str) -> str:
    option_text = " ".join(str(selected_option or "").split()).strip()
    if not option_text:
        return CALLBACK_TOAST_FALLBACK
    message = f"{CALLBACK_TOAST_PREFIX}{option_text}"
    if len(message) <= CALLBACK_TOAST_TEXT_MAX_CHARS:
        return message
    allowed_option_chars = max(
        0,
        CALLBACK_TOAST_TEXT_MAX_CHARS - len(CALLBACK_TOAST_PREFIX) - len(CALLBACK_TOAST_ELLIPSIS),
    )
    trimmed_option = option_text[:allowed_option_chars].rstrip()
    if not trimmed_option:
        return CALLBACK_TOAST_FALLBACK
    return f"{CALLBACK_TOAST_PREFIX}{trimmed_option}{CALLBACK_TOAST_ELLIPSIS}"


def _poll_updates(
    *,
    client: httpx.Client,
    bot_token: str,
    offset: int,
    timeout_seconds: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    response = client.get(
        f"https://api.telegram.org/bot{bot_token}/getUpdates",
        params={
            "offset": offset,
            "timeout": timeout_seconds,
            "limit": max(1, min(int(limit), 100)),
            "allowed_updates": ["message", "edited_message", "callback_query", "poll_answer"],
        },
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, Mapping) or payload.get("ok") is not True:
        return []
    results = payload.get("result")
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


def _preflight_get_updates(*, client: httpx.Client, bot_token: str) -> None:
    response = client.get(
        f"https://api.telegram.org/bot{bot_token}/getUpdates",
        params={
            "offset": 0,
            "timeout": 0,
            "limit": 1,
            "allowed_updates": ["message", "edited_message", "callback_query", "poll_answer"],
        },
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, Mapping) or payload.get("ok") is not True:
        raise RuntimeError("Telegram getUpdates preflight failed.")


def _process_text_update(
    *,
    update_id: int,
    message: Mapping[str, Any],
    trusted_chat_id: str,
    db_path: Path,
) -> None:
    chat_id = _extract_chat_id(message)
    message_id = _to_int(message.get("message_id"))
    text = _extract_text(message)
    parsed = parse_reply_command(text)
    accepted = bool(chat_id and chat_id == trusted_chat_id and parsed is not None)
    record_inbound_message(
        update_id=update_id,
        chat_id=chat_id or "unknown",
        message_id=message_id,
        text=text,
        parsed_command=parsed.command if parsed else None,
        prompt_id=parsed.prompt_id if parsed else None,
        accepted=accepted,
        update_type="message",
        created_at_utc=_utc_iso_now(),
        db_path=db_path,
    )
    if not accepted or parsed is None:
        return
    mark_prompt_resolved(
        prompt_id=parsed.prompt_id,
        response_type=parsed.response_type,
        response_text=parsed.response_text,
        source_message_id=message_id,
        response_payload={
            "source": "text",
            "command": parsed.command,
            "response_text": parsed.response_text,
            "selected_option_ids": None,
            "selected_options": None,
        },
        db_path=db_path,
    )


def _process_callback_update(
    *,
    update_id: int,
    callback_query: Mapping[str, Any],
    trusted_chat_id: str,
    config: TelegramConfig,
    db_path: Path,
) -> None:
    callback_query_id = str(callback_query.get("id") or "").strip()
    callback_data = str(callback_query.get("data") or "").strip()
    callback_parsed = _parse_callback_data(callback_data)
    message = callback_query.get("message")
    message_payload = message if isinstance(message, Mapping) else None
    chat_id = _extract_chat_id(message_payload)
    message_id = _to_int(message_payload.get("message_id")) if isinstance(message_payload, Mapping) else None
    from_user = callback_query.get("from")
    from_user_id = _extract_user_id(from_user if isinstance(from_user, Mapping) else None)

    prompt = None
    prompt_id: str | None = None
    selected_option_ids: list[int] = []
    selected_options: list[str] = []
    prompt_kind = ""
    if callback_parsed is not None:
        namespace, option_idx = callback_parsed
        prompt = get_waiting_prompt_by_callback_namespace(callback_namespace=namespace, db_path=db_path)
        if prompt is not None:
            prompt_id = str(prompt.get("prompt_id") or "").strip() or None
            prompt_kind = str(prompt.get("prompt_kind") or "").strip().lower()
            selected_option_ids = [option_idx]
            selected_options = _get_selected_options(prompt.get("choices"), selected_option_ids)

    accepted = bool(
        chat_id
        and chat_id == trusted_chat_id
        and prompt_id
        and selected_options
    )
    record_inbound_message(
        update_id=update_id,
        chat_id=chat_id or "unknown",
        message_id=message_id,
        text=callback_data,
        parsed_command="callback_select" if callback_parsed else None,
        prompt_id=prompt_id,
        accepted=accepted,
        update_type="callback_query",
        callback_query_id=callback_query_id or None,
        callback_data=callback_data or None,
        from_user_id=from_user_id,
        created_at_utc=_utc_iso_now(),
        db_path=db_path,
    )

    callback_text: str | None = None
    if accepted and prompt_kind == "choice" and selected_options:
        callback_text = _build_choice_callback_toast_text(selected_options[0])

    try:
        if callback_query_id:
            answer_kwargs: dict[str, Any] = {
                "callback_query_id": callback_query_id,
                "config": config,
                "max_retries": 1,
            }
            if callback_text:
                answer_kwargs["text"] = callback_text
            answer_telegram_callback_query(**answer_kwargs)
    except Exception:
        pass

    if not accepted or prompt_id is None:
        return
    selected_text = selected_options[0]
    mark_prompt_resolved(
        prompt_id=prompt_id,
        response_type=RESPONSE_SELECTION,
        response_text=selected_text,
        source_message_id=message_id,
        response_payload={
            "source": "inline",
            "callback_query_id": callback_query_id or None,
            "callback_data": callback_data or None,
            "from_user_id": from_user_id,
            "selected_option_ids": selected_option_ids,
            "selected_options": selected_options,
        },
        db_path=db_path,
    )


def _extract_poll_answer_options(payload: Mapping[str, Any]) -> list[int]:
    raw = payload.get("option_ids")
    if not isinstance(raw, list):
        return []
    values: list[int] = []
    for item in raw:
        parsed = _to_int(item)
        if parsed is not None:
            values.append(parsed)
    return values


def _process_poll_answer_update(
    *,
    update_id: int,
    poll_answer: Mapping[str, Any],
    db_path: Path,
) -> None:
    poll_id = str(poll_answer.get("poll_id") or "").strip()
    option_ids = _extract_poll_answer_options(poll_answer)
    user_payload = poll_answer.get("user")
    from_user_id = _extract_user_id(user_payload if isinstance(user_payload, Mapping) else None)
    prompt = get_waiting_prompt_by_poll_id(poll_id=poll_id, db_path=db_path)
    prompt_id = str(prompt.get("prompt_id") or "").strip() if prompt is not None else None
    selected_options = _get_selected_options(prompt.get("choices"), option_ids) if prompt is not None else []
    accepted = bool(prompt_id and option_ids and selected_options)

    record_inbound_message(
        update_id=update_id,
        chat_id="poll_answer",
        message_id=None,
        text=",".join(str(option_id) for option_id in option_ids),
        parsed_command="poll_answer",
        prompt_id=prompt_id,
        accepted=accepted,
        update_type="poll_answer",
        poll_id=poll_id or None,
        from_user_id=from_user_id,
        created_at_utc=_utc_iso_now(),
        db_path=db_path,
    )
    if not accepted or prompt_id is None:
        return
    response_text = ", ".join(selected_options)
    mark_prompt_resolved(
        prompt_id=prompt_id,
        response_type=RESPONSE_SELECTION,
        response_text=response_text,
        source_message_id=poll_id,
        response_payload={
            "source": "poll",
            "poll_id": poll_id,
            "from_user_id": from_user_id,
            "selected_option_ids": option_ids,
            "selected_options": selected_options,
        },
        db_path=db_path,
    )


def _process_update(
    *,
    update: Mapping[str, Any],
    trusted_chat_id: str,
    config: TelegramConfig,
    db_path: Path,
) -> None:
    update_id = _to_int(update.get("update_id"))
    if update_id is None:
        return

    message = _extract_message(update)
    if isinstance(message, Mapping):
        _process_text_update(
            update_id=update_id,
            message=message,
            trusted_chat_id=trusted_chat_id,
            db_path=db_path,
        )
        return

    callback_query = update.get("callback_query")
    if isinstance(callback_query, Mapping):
        _process_callback_update(
            update_id=update_id,
            callback_query=callback_query,
            trusted_chat_id=trusted_chat_id,
            config=config,
            db_path=db_path,
        )
        return

    poll_answer = update.get("poll_answer")
    if isinstance(poll_answer, Mapping):
        _process_poll_answer_update(
            update_id=update_id,
            poll_answer=poll_answer,
            db_path=db_path,
        )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Telegram reply listener daemon.")
    parser.add_argument("--db-path", type=str, default=None)
    parser.add_argument("--instance-id", type=str, default=None)
    parser.add_argument("--log-path", type=str, default=None)
    parser.add_argument("--poll-timeout-seconds", type=int, default=25)
    parser.add_argument("--error-sleep-seconds", type=float, default=2.0)
    return parser


def run_listener(
    *,
    db_path: str | None,
    instance_id: str | None,
    log_path: str | None,
    poll_timeout_seconds: int,
    error_sleep_seconds: float,
) -> None:
    """Run the long-polling listener loop."""
    global _CURRENT_LOG_PATH

    _CURRENT_LOG_PATH = resolve_listener_log_path(log_path)
    inbox_db = initialize_inbox_db(db_path)
    resolved_instance_id = str(instance_id or f"li_{os.getpid()}_{int(time.time())}").strip()
    pid = int(os.getpid())
    update_listener_state(
        heartbeat_utc=_utc_iso_now(),
        pid=pid,
        version=LISTENER_VERSION,
        instance_id=resolved_instance_id,
        state_status="starting",
        startup_confirmed=False,
        started_at_utc=_utc_iso_now(),
        last_error=None,
        last_error_utc=None,
        db_path=inbox_db,
    )
    _log(f"listener booting pid={pid} instance_id={resolved_instance_id} db_path={inbox_db}")

    try:
        config = load_telegram_config()
        if config.disable_notification:
            raise RuntimeError("Telegram notifications are disabled; listener cannot run.")
        trusted_chat_id = str(config.chat_id).strip()
        if not trusted_chat_id:
            raise RuntimeError("TELEGRAM_CHAT_ID is required.")

        state = get_listener_state(inbox_db)
        last_update_id = int(state.get("last_update_id") or 0)
        offset = max(1, last_update_id + 1)
        timeout = max(1, int(poll_timeout_seconds))
        sleep_s = max(0.1, float(error_sleep_seconds))
        client_timeout = max(float(config.timeout_seconds), float(timeout + 5))

        with httpx.Client(timeout=client_timeout) as client:
            try:
                _preflight_get_updates(client=client, bot_token=config.bot_token)
            except Exception as exc:
                conflict = _is_token_conflict_error(exc)
                state_status = "token_conflict" if conflict else "error"
                prefix = "token_conflict" if conflict else "startup preflight getUpdates failed"
                error_msg = f"{prefix}: {exc}"
                update_listener_state(
                    heartbeat_utc=_utc_iso_now(),
                    pid=pid,
                    version=LISTENER_VERSION,
                    instance_id=resolved_instance_id,
                    state_status=state_status,
                    startup_confirmed=False,
                    last_error=str(error_msg),
                    last_error_utc=_utc_iso_now(),
                    db_path=inbox_db,
                )
                _log(error_msg, level="ERROR")
                raise

            update_listener_state(
                heartbeat_utc=_utc_iso_now(),
                pid=pid,
                version=LISTENER_VERSION,
                instance_id=resolved_instance_id,
                state_status="running",
                startup_confirmed=True,
                last_error=None,
                last_error_utc=None,
                db_path=inbox_db,
            )
            _log("listener startup confirmed; entering main poll loop")

            while True:
                try:
                    updates = _poll_updates(
                        client=client,
                        bot_token=config.bot_token,
                        offset=offset,
                        timeout_seconds=timeout,
                    )
                    max_update_id = last_update_id
                    for update in updates:
                        update_id = _to_int(update.get("update_id"))
                        if update_id is not None and update_id > max_update_id:
                            max_update_id = update_id
                        try:
                            _process_update(
                                update=update,
                                trusted_chat_id=trusted_chat_id,
                                config=config,
                                db_path=inbox_db,
                            )
                        except Exception as exc:
                            _log(f"update processing error update_id={update_id}: {exc}", level="WARNING")

                    now_utc = _utc_iso_now()
                    if max_update_id > last_update_id:
                        last_update_id = max_update_id
                        offset = last_update_id + 1
                    update_listener_state(
                        last_update_id=last_update_id,
                        heartbeat_utc=now_utc,
                        pid=pid,
                        version=LISTENER_VERSION,
                        instance_id=resolved_instance_id,
                        state_status="running",
                        startup_confirmed=True,
                        db_path=inbox_db,
                    )
                except KeyboardInterrupt:
                    _log("listener interrupted; shutting down")
                    break
                except Exception as exc:
                    error_text = str(exc)
                    is_conflict = _is_token_conflict_error(exc)
                    status = "token_conflict" if is_conflict else "degraded"
                    if is_conflict and not error_text.lower().startswith("token_conflict"):
                        error_text = f"token_conflict: {error_text}"
                    update_listener_state(
                        heartbeat_utc=_utc_iso_now(),
                        pid=pid,
                        version=LISTENER_VERSION,
                        instance_id=resolved_instance_id,
                        state_status=status,
                        startup_confirmed=True,
                        last_error=error_text,
                        last_error_utc=_utc_iso_now(),
                        db_path=inbox_db,
                    )
                    _log(f"listener loop error: {error_text}", level="ERROR")
                    if is_conflict:
                        _log("listener exiting due to token conflict; avoid rapid respawn loop", level="WARNING")
                        break
                    time.sleep(sleep_s)
    finally:
        update_listener_state(
            heartbeat_utc=_utc_iso_now(),
            pid=None,
            version=LISTENER_VERSION,
            instance_id=None,
            state_status="stopped",
            startup_confirmed=False,
            db_path=inbox_db,
        )
        _log("listener stopped")


def _run_listener_with_singleton() -> int:
    global _CURRENT_LOG_PATH
    lease: SingletonLease | None = None
    args = _build_arg_parser().parse_args()
    _CURRENT_LOG_PATH = resolve_listener_log_path(args.log_path)
    try:
        lease = _acquire_listener_singleton()
        run_listener(
            db_path=args.db_path,
            instance_id=args.instance_id,
            log_path=args.log_path,
            poll_timeout_seconds=args.poll_timeout_seconds,
            error_sleep_seconds=args.error_sleep_seconds,
        )
        return 0
    except SingletonAcquireError as exc:
        _log(f"singleton acquire failed: {exc}; payload={exc.payload}", level="ERROR")
        return 1
    except Exception as exc:
        _log(f"startup error: {exc}", level="ERROR")
        try:
            inbox_db = initialize_inbox_db(args.db_path)
            set_listener_error(
                error_text=f"startup error: {exc}",
                state_status="error",
                db_path=inbox_db,
            )
        except Exception:
            pass
        return 1
    finally:
        if lease is not None:
            release_singleton(lease)


def main() -> int:
    """Entry point for the telegram-mcp-listener console script."""
    return _run_listener_with_singleton()


if __name__ == "__main__":
    raise SystemExit(main())

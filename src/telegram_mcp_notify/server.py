"""Notify-only Telegram MCP server (stdio)."""

from __future__ import annotations

import os
import re
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import ALLOWED_NOTIFICATION_EVENTS, format_notification_message, load_telegram_config
from .messaging import send_telegram_message

SERVER = FastMCP(name="telegram_notify")
TASK_ENV_KEYS = (
    "CODEX_TASK_NAME",
    "CODEX_TASK",
    "TASK_NAME",
    "TASK",
    "CODEX_SESSION_TITLE",
)
DEFAULT_TASK_NAME = "notification"
EVENT_TOKENS = {
    "question",
    "plan ready",
    "final",
    "attention",
    "error",
    "input required",
}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

_TOOL_GROUP_NOTIFICATION = ("send_telegram_notification",)
_TOOL_GROUP_HIGH_LEVEL_INPUT: tuple[str, ...] = ()
_TOOL_GROUP_LOW_LEVEL_INPUT: tuple[str, ...] = ()
_TOOL_GROUP_LIFECYCLE: tuple[str, ...] = ()
_TOOL_GROUP_DIAGNOSTICS = ("telegram_notify_capabilities",)

EXPOSED_TOOL_NAMES = (
    *_TOOL_GROUP_NOTIFICATION,
    *_TOOL_GROUP_DIAGNOSTICS,
)


def _to_error_payload(error_text: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status_code": None,
        "message_id": None,
        "error": error_text,
    }


def _stderr(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _resolve_task_name(
    *,
    task_name: str | None = None,
    run_id: str | None = None,
    session_id: str | None = None,
    message: str | None = None,
) -> str:
    explicit = str(task_name or "").strip()
    if explicit:
        return explicit
    for key in TASK_ENV_KEYS:
        value = str(os.getenv(key) or "").strip()
        if value:
            return value
    inferred = _infer_task_name_from_message(message)
    if inferred:
        return inferred
    if run_id and str(run_id).strip():
        return str(run_id).strip()
    if session_id and str(session_id).strip():
        return str(session_id).strip()
    return DEFAULT_TASK_NAME


def _clean_task_candidate(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    value = value.strip("|:-")
    value = re.sub(r"^[^A-Za-z0-9]+", "", value)
    return value[:80]


def _is_event_token(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return bool(lowered and lowered in EVENT_TOKENS)


def _is_slug(value: str) -> bool:
    return bool(SLUG_RE.fullmatch(str(value or "").strip().lower()))


def _infer_task_name_from_message(message: str | None) -> str | None:
    for raw in str(message or "").splitlines():
        line = str(raw or "").strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("timestamp_"):
            continue
        if lowered in {"action_required=true", "action_required=false"}:
            continue
        if "|" in line:
            parts = [_clean_task_candidate(part) for part in line.split("|")]
            parts = [part for part in parts if part]
            for part in reversed(parts):
                if _is_event_token(part):
                    continue
                if _is_slug(part) and len(parts) > 1:
                    continue
                return part
            if parts:
                return parts[-1]
        candidate = _clean_task_candidate(line)
        if candidate:
            return candidate
    return None


@SERVER.tool(
    name="send_telegram_notification",
    description="Send a Telegram notification for questions, plans, final responses, errors, and attention-needed events. Progress events are not supported to prevent spam.",
)
def send_telegram_notification(
    event: str,
    message: str,
    session_id: str | None = None,
    run_id: str | None = None,
    task_name: str | None = None,
    requires_action: bool = False,
) -> dict[str, Any]:
    event_key = (event or "").strip().lower()
    if event_key not in ALLOWED_NOTIFICATION_EVENTS:
        return _to_error_payload(f"Unsupported notification event: {event}")

    try:
        config = load_telegram_config()
        text = format_notification_message(
            task=_resolve_task_name(task_name=task_name, run_id=run_id, session_id=session_id, message=message),
            event=event_key,
            message=message,
            requires_action=requires_action,
            session_id=session_id,
            run_id=run_id,
        )
        return send_telegram_message(text, config=config, max_retries=1)
    except Exception as exc:
        _stderr(f"telegram_notify_server error: {exc}")
        return _to_error_payload(str(exc))


@SERVER.tool(
    name="telegram_notify_capabilities",
    description="Return the server's exposed tool names and capability groups.",
)
def telegram_notify_capabilities() -> dict[str, Any]:
    return {
        "ok": True,
        "server": "telegram_notify",
        "tool_count": len(EXPOSED_TOOL_NAMES),
        "tools": list(EXPOSED_TOOL_NAMES),
        "tools_by_category": {
            "notification": list(_TOOL_GROUP_NOTIFICATION),
            "high_level_input": list(_TOOL_GROUP_HIGH_LEVEL_INPUT),
            "low_level_input": list(_TOOL_GROUP_LOW_LEVEL_INPUT),
            "lifecycle": list(_TOOL_GROUP_LIFECYCLE),
            "diagnostics": list(_TOOL_GROUP_DIAGNOSTICS),
        },
        "supports": {
            "notifications": True,
            "pending_prompts": False,
            "listener_lifecycle": False,
            "listener_stop_restart": False,
            "sync_wait_for_prompt": False,
            "custom_choice_text": False,
        },
    }


def main() -> int:
    """Entry point for the telegram-mcp-notify console script."""
    try:
        SERVER.run(transport="stdio")
        return 0
    except Exception as exc:
        _stderr(f"telegram_notify_server startup error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

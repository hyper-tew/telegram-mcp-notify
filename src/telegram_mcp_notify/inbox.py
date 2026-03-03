"""SQLite-backed inbox for pending prompts, inbound messages, and listener state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
from typing import Any, Mapping

STATUS_WAITING = "waiting"
STATUS_RESOLVED = "resolved"
STATUS_CONSUMED = "consumed"
STATUS_EXPIRED = "expired"
STATUS_CANCELLED = "cancelled"

INPUT_MODE_TEXT = "text"
INPUT_MODE_POLL = "poll"
INPUT_MODE_INLINE = "inline"

RESPONSE_ANSWER = "answer"
RESPONSE_APPROVE = "approve"
RESPONSE_DECLINE = "decline"
RESPONSE_SELECTION = "selection"

_PROMPT_ID_RE = r"[a-zA-Z0-9][a-zA-Z0-9_-]{2,127}"
_ANSWER_RE = re.compile(rf"^\s*answer\s+({_PROMPT_ID_RE})\s+(.+?)\s*$", re.IGNORECASE)
_APPROVE_RE = re.compile(rf"^\s*approve\s+({_PROMPT_ID_RE})\s*$", re.IGNORECASE)
_DECLINE_RE = re.compile(rf"^\s*decline\s+({_PROMPT_ID_RE})\s*$", re.IGNORECASE)
_SUPPORTED_STATUS = {
    STATUS_WAITING,
    STATUS_RESOLVED,
    STATUS_CONSUMED,
    STATUS_EXPIRED,
    STATUS_CANCELLED,
}
_SUPPORTED_INPUT_MODE = {
    INPUT_MODE_TEXT,
    INPUT_MODE_POLL,
    INPUT_MODE_INLINE,
}
_SUPPORTED_RESPONSE_TYPES = {
    RESPONSE_ANSWER,
    RESPONSE_APPROVE,
    RESPONSE_DECLINE,
    RESPONSE_SELECTION,
}

_DATA_HOME = Path.home() / ".telegram-mcp-notify"
_DEFAULT_DB_PATH = _DATA_HOME / "inbox.db"
_DEFAULT_LISTENER_LOG_PATH = _DATA_HOME / "listener.log"
_LISTENER_VERSION = "1"
_UNSET = object()


@dataclass(frozen=True)
class ParsedReplyCommand:
    """Parsed text reply command from a user message."""

    command: str
    prompt_id: str
    response_type: str
    response_text: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso_now() -> str:
    return _utc_now().replace(microsecond=0).isoformat()


def _parse_iso(raw: str | None) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def resolve_inbox_db_path(db_path: str | Path | None = None) -> Path:
    """Resolve the inbox SQLite database path."""
    candidate = str(db_path or os.getenv("TELEGRAM_INBOX_DB_PATH") or "").strip()
    return Path(candidate) if candidate else _DEFAULT_DB_PATH


def resolve_listener_log_path(log_path: str | Path | None = None) -> Path:
    """Resolve the listener log file path."""
    candidate = str(log_path or os.getenv("TELEGRAM_LISTENER_LOG_PATH") or "").strip()
    path = Path(candidate) if candidate else _DEFAULT_LISTENER_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = resolve_inbox_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    names: set[str] = set()
    for row in rows:
        if isinstance(row, sqlite3.Row):
            names.add(str(row["name"]))
        elif isinstance(row, tuple) and len(row) > 1:
            names.add(str(row[1]))
    return names


def _ensure_columns(connection: sqlite3.Connection, table_name: str, definitions: Mapping[str, str]) -> None:
    existing = _table_columns(connection, table_name)
    for column_name, definition in definitions.items():
        if column_name in existing:
            continue
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {definition}")


def initialize_inbox_db(db_path: str | Path | None = None) -> Path:
    """Create or migrate the inbox database schema. Returns the resolved path."""
    path = resolve_inbox_db_path(db_path)
    with _connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS pending_prompts (
                prompt_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                run_id TEXT,
                prompt_text TEXT NOT NULL,
                prompt_kind TEXT NOT NULL DEFAULT 'question',
                choices_json TEXT,
                input_mode TEXT NOT NULL DEFAULT 'text',
                telegram_poll_id TEXT,
                telegram_message_id INTEGER,
                callback_namespace TEXT,
                status TEXT NOT NULL DEFAULT 'waiting',
                created_at_utc TEXT NOT NULL,
                expires_at_utc TEXT,
                resolved_at_utc TEXT,
                consumed_at_utc TEXT,
                response_type TEXT,
                response_text TEXT,
                response_payload_json TEXT,
                source_message_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_pending_prompts_session_status
                ON pending_prompts(session_id, status);

            CREATE TABLE IF NOT EXISTS inbound_messages (
                update_id INTEGER PRIMARY KEY,
                chat_id TEXT NOT NULL,
                message_id INTEGER,
                text TEXT,
                parsed_command TEXT,
                prompt_id TEXT,
                update_type TEXT,
                callback_query_id TEXT,
                callback_data TEXT,
                poll_id TEXT,
                from_user_id TEXT,
                created_at_utc TEXT NOT NULL,
                accepted INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS listener_state (
                singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                last_update_id INTEGER NOT NULL DEFAULT 0,
                heartbeat_utc TEXT,
                pid INTEGER,
                version TEXT NOT NULL DEFAULT '1',
                instance_id TEXT,
                state_status TEXT NOT NULL DEFAULT 'stopped',
                startup_confirmed INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                last_error_utc TEXT,
                restart_count INTEGER NOT NULL DEFAULT 0,
                last_restart_reason TEXT,
                started_at_utc TEXT,
                consecutive_start_failures INTEGER NOT NULL DEFAULT 0,
                last_start_attempt_utc TEXT,
                last_start_failure_reason TEXT
            );
            """
        )
        _ensure_columns(
            connection,
            "pending_prompts",
            {
                "input_mode": "input_mode TEXT NOT NULL DEFAULT 'text'",
                "telegram_poll_id": "telegram_poll_id TEXT",
                "telegram_message_id": "telegram_message_id INTEGER",
                "callback_namespace": "callback_namespace TEXT",
                "response_payload_json": "response_payload_json TEXT",
            },
        )
        _ensure_columns(
            connection,
            "inbound_messages",
            {
                "update_type": "update_type TEXT",
                "callback_query_id": "callback_query_id TEXT",
                "callback_data": "callback_data TEXT",
                "poll_id": "poll_id TEXT",
                "from_user_id": "from_user_id TEXT",
            },
        )
        _ensure_columns(
            connection,
            "listener_state",
            {
                "instance_id": "instance_id TEXT",
                "state_status": "state_status TEXT NOT NULL DEFAULT 'stopped'",
                "startup_confirmed": "startup_confirmed INTEGER NOT NULL DEFAULT 0",
                "last_error": "last_error TEXT",
                "last_error_utc": "last_error_utc TEXT",
                "restart_count": "restart_count INTEGER NOT NULL DEFAULT 0",
                "last_restart_reason": "last_restart_reason TEXT",
                "started_at_utc": "started_at_utc TEXT",
                "consecutive_start_failures": "consecutive_start_failures INTEGER NOT NULL DEFAULT 0",
                "last_start_attempt_utc": "last_start_attempt_utc TEXT",
                "last_start_failure_reason": "last_start_failure_reason TEXT",
            },
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO listener_state(singleton_id, last_update_id, version)
            VALUES (1, 0, ?)
            """,
            (_LISTENER_VERSION,),
        )
        connection.commit()
    return path


def _parse_json_list(raw: Any) -> list[Any]:
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _parse_json_object(raw: Any) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_selected_option_ids(raw: Any) -> list[int] | None:
    if not isinstance(raw, list):
        return None
    values: list[int] = []
    for item in raw:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            values.append(item)
            continue
        if isinstance(item, str) and item.strip().isdigit():
            values.append(int(item.strip()))
    return values if values else None


def _normalize_selected_options(raw: Any) -> list[str] | None:
    if not isinstance(raw, list):
        return None
    values = [str(item).strip() for item in raw if str(item).strip()]
    return values if values else None


def _row_to_dict(row: sqlite3.Row | Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    payload = dict(row)
    payload["choices"] = _parse_json_list(payload.get("choices_json"))
    response_payload = _parse_json_object(payload.get("response_payload_json"))
    payload["response_payload"] = response_payload
    payload["selected_option_ids"] = _normalize_selected_option_ids(
        response_payload.get("selected_option_ids") if isinstance(response_payload, dict) else None
    )
    payload["selected_options"] = _normalize_selected_options(
        response_payload.get("selected_options") if isinstance(response_payload, dict) else None
    )
    payload.pop("choices_json", None)
    payload.pop("response_payload_json", None)
    return payload


def _coerce_choices(choices: list[str] | tuple[str, ...] | None) -> str | None:
    if not choices:
        return None
    values = [str(item).strip() for item in choices if str(item).strip()]
    if not values:
        return None
    return json.dumps(values, ensure_ascii=True)


def _coerce_response_payload(payload: Mapping[str, Any] | None) -> str | None:
    if not payload:
        return None
    return json.dumps(dict(payload), ensure_ascii=True)


def _normalize_status(status: str | None) -> str:
    key = str(status or STATUS_WAITING).strip().lower()
    if key not in _SUPPORTED_STATUS:
        return STATUS_WAITING
    return key


def _normalize_input_mode(input_mode: str | None) -> str:
    key = str(input_mode or INPUT_MODE_TEXT).strip().lower()
    if key not in _SUPPORTED_INPUT_MODE:
        return INPUT_MODE_TEXT
    return key


def _normalize_prompt_id(prompt_id: str | None) -> str:
    text = str(prompt_id or "").strip()
    if text:
        return text
    return f"tp_{uuid.uuid4().hex[:16]}"


def create_expiry_timestamp(minutes: int | None) -> str | None:
    """Create an ISO-format expiry timestamp N minutes from now."""
    if minutes is None:
        return None
    ttl = int(minutes)
    if ttl <= 0:
        return None
    expires = _utc_now() + timedelta(minutes=ttl)
    return expires.replace(microsecond=0).isoformat()


def upsert_pending_prompt(
    *,
    session_id: str,
    prompt_text: str,
    prompt_id: str | None = None,
    run_id: str | None = None,
    prompt_kind: str = "question",
    choices: list[str] | tuple[str, ...] | None = None,
    input_mode: str = INPUT_MODE_TEXT,
    telegram_poll_id: str | None = None,
    telegram_message_id: int | None = None,
    callback_namespace: str | None = None,
    expires_at_utc: str | None = None,
    created_at_utc: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Insert or update a pending prompt record."""
    normalized_prompt_id = _normalize_prompt_id(prompt_id)
    created_at = str(created_at_utc or _utc_iso_now())
    normalized_kind = str(prompt_kind or "question").strip().lower() or "question"
    normalized_choices = _coerce_choices(choices)
    normalized_input_mode = _normalize_input_mode(input_mode)
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO pending_prompts(
                prompt_id,
                session_id,
                run_id,
                prompt_text,
                prompt_kind,
                choices_json,
                input_mode,
                telegram_poll_id,
                telegram_message_id,
                callback_namespace,
                status,
                created_at_utc,
                expires_at_utc,
                resolved_at_utc,
                consumed_at_utc,
                response_type,
                response_text,
                response_payload_json,
                source_message_id
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL)
            ON CONFLICT(prompt_id) DO UPDATE SET
                session_id = excluded.session_id,
                run_id = excluded.run_id,
                prompt_text = excluded.prompt_text,
                prompt_kind = excluded.prompt_kind,
                choices_json = excluded.choices_json,
                input_mode = excluded.input_mode,
                telegram_poll_id = excluded.telegram_poll_id,
                telegram_message_id = excluded.telegram_message_id,
                callback_namespace = excluded.callback_namespace,
                status = excluded.status,
                created_at_utc = excluded.created_at_utc,
                expires_at_utc = excluded.expires_at_utc,
                resolved_at_utc = NULL,
                consumed_at_utc = NULL,
                response_type = NULL,
                response_text = NULL,
                response_payload_json = NULL,
                source_message_id = NULL
            """,
            (
                normalized_prompt_id,
                str(session_id).strip(),
                str(run_id).strip() if run_id else None,
                str(prompt_text or "").strip(),
                normalized_kind,
                normalized_choices,
                normalized_input_mode,
                str(telegram_poll_id).strip() if telegram_poll_id else None,
                int(telegram_message_id) if telegram_message_id is not None else None,
                str(callback_namespace).strip() if callback_namespace else None,
                STATUS_WAITING,
                created_at,
                str(expires_at_utc).strip() if expires_at_utc else None,
            ),
        )
        connection.commit()
    record = get_pending_prompt(prompt_id=normalized_prompt_id, session_id=session_id, db_path=db_path)
    if record is None:
        raise RuntimeError("Failed to persist pending prompt record.")
    return record


def update_prompt_delivery(
    *,
    prompt_id: str,
    telegram_message_id: int | None = None,
    telegram_poll_id: str | None = None,
    callback_namespace: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Update Telegram delivery metadata on a prompt."""
    updates: list[str] = []
    params: list[Any] = []
    if telegram_message_id is not None:
        updates.append("telegram_message_id = ?")
        params.append(int(telegram_message_id))
    if telegram_poll_id is not None:
        updates.append("telegram_poll_id = ?")
        params.append(str(telegram_poll_id).strip())
    if callback_namespace is not None:
        updates.append("callback_namespace = ?")
        params.append(str(callback_namespace).strip())
    if not updates:
        return get_pending_prompt(prompt_id=prompt_id, db_path=db_path)

    params.append(str(prompt_id).strip())
    with _connect(db_path) as connection:
        connection.execute(
            f"UPDATE pending_prompts SET {', '.join(updates)} WHERE prompt_id = ?",
            tuple(params),
        )
        connection.commit()
    return get_pending_prompt(prompt_id=prompt_id, db_path=db_path)


def get_pending_prompt(
    *,
    prompt_id: str,
    session_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Look up a single pending prompt."""
    query = "SELECT * FROM pending_prompts WHERE prompt_id = ?"
    params: list[Any] = [str(prompt_id).strip()]
    if session_id:
        query += " AND session_id = ?"
        params.append(str(session_id).strip())
    with _connect(db_path) as connection:
        row = connection.execute(query, tuple(params)).fetchone()
    return _row_to_dict(row)


def get_waiting_prompt_by_poll_id(
    *,
    poll_id: str,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Find a waiting prompt by its Telegram poll ID."""
    normalized = str(poll_id or "").strip()
    if not normalized:
        return None
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT * FROM pending_prompts
            WHERE telegram_poll_id = ? AND status = ?
            ORDER BY created_at_utc DESC
            LIMIT 1
            """,
            (normalized, STATUS_WAITING),
        ).fetchone()
    return _row_to_dict(row)


def get_waiting_prompt_by_callback_namespace(
    *,
    callback_namespace: str,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Find a waiting prompt by its callback namespace."""
    normalized = str(callback_namespace or "").strip()
    if not normalized:
        return None
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT * FROM pending_prompts
            WHERE callback_namespace = ? AND status = ?
            ORDER BY created_at_utc DESC
            LIMIT 1
            """,
            (normalized, STATUS_WAITING),
        ).fetchone()
    return _row_to_dict(row)


def list_pending_prompts(
    *,
    session_id: str,
    status_filter: str | None = None,
    limit: int = 20,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """List pending prompts for a session."""
    capped_limit = max(1, min(int(limit), 200))
    query = "SELECT * FROM pending_prompts WHERE session_id = ?"
    params: list[Any] = [str(session_id).strip()]
    normalized_status = _normalize_status(status_filter) if status_filter else None
    if normalized_status and status_filter:
        query += " AND status = ?"
        params.append(normalized_status)
    query += " ORDER BY created_at_utc DESC LIMIT ?"
    params.append(capped_limit)
    with _connect(db_path) as connection:
        rows = connection.execute(query, tuple(params)).fetchall()
    return [payload for payload in (_row_to_dict(row) for row in rows) if payload is not None]


def mark_prompt_resolved(
    *,
    prompt_id: str,
    response_type: str,
    response_text: str,
    source_message_id: str | int | None = None,
    resolved_at_utc: str | None = None,
    response_payload: Mapping[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Mark a waiting prompt as resolved with a response."""
    normalized_response_type = str(response_type or "").strip().lower()
    if normalized_response_type not in _SUPPORTED_RESPONSE_TYPES:
        raise ValueError(f"Unsupported response_type: {response_type}")
    resolved_at = str(resolved_at_utc or _utc_iso_now())
    payload_json = _coerce_response_payload(response_payload)
    with _connect(db_path) as connection:
        connection.execute(
            """
            UPDATE pending_prompts
            SET
                status = ?,
                resolved_at_utc = ?,
                consumed_at_utc = NULL,
                response_type = ?,
                response_text = ?,
                response_payload_json = ?,
                source_message_id = ?
            WHERE prompt_id = ? AND status = ?
            """,
            (
                STATUS_RESOLVED,
                resolved_at,
                normalized_response_type,
                str(response_text or "").strip(),
                payload_json,
                str(source_message_id) if source_message_id is not None else None,
                str(prompt_id).strip(),
                STATUS_WAITING,
            ),
        )
        connection.commit()
    return get_pending_prompt(prompt_id=prompt_id, db_path=db_path)


def consume_prompt(
    *,
    prompt_id: str,
    session_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Mark a resolved prompt as consumed."""
    with _connect(db_path) as connection:
        query = "UPDATE pending_prompts SET status = ?, consumed_at_utc = ? WHERE prompt_id = ? AND status = ?"
        params: list[Any] = [STATUS_CONSUMED, _utc_iso_now(), str(prompt_id).strip(), STATUS_RESOLVED]
        if session_id:
            query += " AND session_id = ?"
            params.append(str(session_id).strip())
        connection.execute(query, tuple(params))
        connection.commit()
    return get_pending_prompt(prompt_id=prompt_id, session_id=session_id, db_path=db_path)


def cancel_prompt(
    *,
    prompt_id: str,
    session_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Cancel a waiting prompt."""
    with _connect(db_path) as connection:
        query = "UPDATE pending_prompts SET status = ? WHERE prompt_id = ? AND status = ?"
        params: list[Any] = [STATUS_CANCELLED, str(prompt_id).strip(), STATUS_WAITING]
        if session_id:
            query += " AND session_id = ?"
            params.append(str(session_id).strip())
        connection.execute(query, tuple(params))
        connection.commit()
    return get_pending_prompt(prompt_id=prompt_id, session_id=session_id, db_path=db_path)


def expire_prompt_if_needed(
    *,
    prompt_id: str,
    session_id: str | None = None,
    now_utc: datetime | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Expire a prompt if it has passed its expiry time."""
    record = get_pending_prompt(prompt_id=prompt_id, session_id=session_id, db_path=db_path)
    if not record:
        return None
    if record.get("status") != STATUS_WAITING:
        return record
    expires_at = _parse_iso(record.get("expires_at_utc"))
    if expires_at is None:
        return record
    comparison = now_utc or _utc_now()
    if expires_at > comparison:
        return record
    with _connect(db_path) as connection:
        connection.execute(
            "UPDATE pending_prompts SET status = ? WHERE prompt_id = ? AND status = ?",
            (STATUS_EXPIRED, str(prompt_id).strip(), STATUS_WAITING),
        )
        connection.commit()
    return get_pending_prompt(prompt_id=prompt_id, session_id=session_id, db_path=db_path)


def get_recent_inbound_messages(
    *,
    limit: int = 10,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Retrieve recent inbound messages from the inbox."""
    capped_limit = max(1, min(int(limit), 200))
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM inbound_messages ORDER BY update_id DESC LIMIT ?",
            (capped_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def record_inbound_message(
    *,
    update_id: int,
    chat_id: str,
    message_id: int | None,
    text: str,
    parsed_command: str | None,
    prompt_id: str | None,
    accepted: bool,
    update_type: str | None = None,
    callback_query_id: str | None = None,
    callback_data: str | None = None,
    poll_id: str | None = None,
    from_user_id: str | int | None = None,
    created_at_utc: str | None = None,
    db_path: str | Path | None = None,
) -> None:
    """Record an inbound message from Telegram."""
    timestamp = str(created_at_utc or _utc_iso_now())
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO inbound_messages(
                update_id,
                chat_id,
                message_id,
                text,
                parsed_command,
                prompt_id,
                update_type,
                callback_query_id,
                callback_data,
                poll_id,
                from_user_id,
                created_at_utc,
                accepted
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(update_id),
                str(chat_id).strip(),
                int(message_id) if message_id is not None else None,
                str(text or ""),
                str(parsed_command).strip() if parsed_command else None,
                str(prompt_id).strip() if prompt_id else None,
                str(update_type).strip() if update_type else None,
                str(callback_query_id).strip() if callback_query_id else None,
                str(callback_data).strip() if callback_data else None,
                str(poll_id).strip() if poll_id else None,
                str(from_user_id).strip() if from_user_id is not None else None,
                timestamp,
                1 if accepted else 0,
            ),
        )
        connection.commit()


def get_listener_state(db_path: str | Path | None = None) -> dict[str, Any]:
    """Get the current listener state from the database."""
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT
                singleton_id,
                last_update_id,
                heartbeat_utc,
                pid,
                version,
                instance_id,
                state_status,
                startup_confirmed,
                last_error,
                last_error_utc,
                restart_count,
                last_restart_reason,
                started_at_utc,
                consecutive_start_failures,
                last_start_attempt_utc,
                last_start_failure_reason
            FROM listener_state
            WHERE singleton_id = 1
            """
        ).fetchone()
    if row is None:
        return {
            "last_update_id": 0,
            "heartbeat_utc": None,
            "pid": None,
            "version": _LISTENER_VERSION,
            "instance_id": None,
            "state_status": "stopped",
            "startup_confirmed": 0,
            "last_error": None,
            "last_error_utc": None,
            "restart_count": 0,
            "last_restart_reason": None,
            "started_at_utc": None,
            "consecutive_start_failures": 0,
            "last_start_attempt_utc": None,
            "last_start_failure_reason": None,
        }
    return {
        "last_update_id": int(row["last_update_id"] or 0),
        "heartbeat_utc": row["heartbeat_utc"],
        "pid": row["pid"],
        "version": row["version"],
        "instance_id": row["instance_id"],
        "state_status": row["state_status"] or "stopped",
        "startup_confirmed": int(row["startup_confirmed"] or 0),
        "last_error": row["last_error"],
        "last_error_utc": row["last_error_utc"],
        "restart_count": int(row["restart_count"] or 0),
        "last_restart_reason": row["last_restart_reason"],
        "started_at_utc": row["started_at_utc"],
        "consecutive_start_failures": int(row["consecutive_start_failures"] or 0),
        "last_start_attempt_utc": row["last_start_attempt_utc"],
        "last_start_failure_reason": row["last_start_failure_reason"],
    }


def update_listener_state(
    *,
    last_update_id: int | object = _UNSET,
    heartbeat_utc: str | None | object = _UNSET,
    pid: int | None | object = _UNSET,
    version: str | object = _UNSET,
    instance_id: str | None | object = _UNSET,
    state_status: str | None | object = _UNSET,
    startup_confirmed: bool | int | None | object = _UNSET,
    last_error: str | None | object = _UNSET,
    last_error_utc: str | None | object = _UNSET,
    restart_count: int | object = _UNSET,
    last_restart_reason: str | None | object = _UNSET,
    started_at_utc: str | None | object = _UNSET,
    consecutive_start_failures: int | object = _UNSET,
    last_start_attempt_utc: str | None | object = _UNSET,
    last_start_failure_reason: str | None | object = _UNSET,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Update listener state fields in the database."""
    updates: list[str] = []
    params: list[Any] = []
    if last_update_id is not _UNSET:
        updates.append("last_update_id = ?")
        params.append(int(last_update_id))  # type: ignore[arg-type]
    if heartbeat_utc is not _UNSET:
        updates.append("heartbeat_utc = ?")
        params.append(str(heartbeat_utc) if heartbeat_utc is not None else None)
    if pid is not _UNSET:
        updates.append("pid = ?")
        params.append(int(pid) if pid is not None else None)  # type: ignore[arg-type]
    if version is not _UNSET:
        updates.append("version = ?")
        params.append(str(version))
    if instance_id is not _UNSET:
        updates.append("instance_id = ?")
        params.append(str(instance_id) if instance_id is not None else None)
    if state_status is not _UNSET:
        updates.append("state_status = ?")
        params.append(str(state_status) if state_status is not None else None)
    if startup_confirmed is not _UNSET:
        updates.append("startup_confirmed = ?")
        if startup_confirmed is None:
            params.append(0)
        else:
            params.append(1 if bool(startup_confirmed) else 0)
    if last_error is not _UNSET:
        updates.append("last_error = ?")
        params.append(str(last_error) if last_error is not None else None)
    if last_error_utc is not _UNSET:
        updates.append("last_error_utc = ?")
        params.append(str(last_error_utc) if last_error_utc is not None else None)
    if restart_count is not _UNSET:
        updates.append("restart_count = ?")
        params.append(int(restart_count))  # type: ignore[arg-type]
    if last_restart_reason is not _UNSET:
        updates.append("last_restart_reason = ?")
        params.append(str(last_restart_reason) if last_restart_reason is not None else None)
    if started_at_utc is not _UNSET:
        updates.append("started_at_utc = ?")
        params.append(str(started_at_utc) if started_at_utc is not None else None)
    if consecutive_start_failures is not _UNSET:
        updates.append("consecutive_start_failures = ?")
        params.append(int(consecutive_start_failures))  # type: ignore[arg-type]
    if last_start_attempt_utc is not _UNSET:
        updates.append("last_start_attempt_utc = ?")
        params.append(str(last_start_attempt_utc) if last_start_attempt_utc is not None else None)
    if last_start_failure_reason is not _UNSET:
        updates.append("last_start_failure_reason = ?")
        params.append(str(last_start_failure_reason) if last_start_failure_reason is not None else None)
    if updates:
        with _connect(db_path) as connection:
            connection.execute(f"UPDATE listener_state SET {', '.join(updates)} WHERE singleton_id = 1", tuple(params))
            connection.commit()
    return get_listener_state(db_path)


def set_listener_error(
    *,
    error_text: str,
    state_status: str = "error",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Record a listener error in the database."""
    return update_listener_state(
        state_status=state_status,
        startup_confirmed=False,
        last_error=str(error_text),
        last_error_utc=_utc_iso_now(),
        db_path=db_path,
    )


def reset_listener_runtime_state(
    *,
    state_status: str = "stopped",
    last_restart_reason: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Reset listener runtime state to stopped."""
    return update_listener_state(
        heartbeat_utc=None,
        pid=None,
        instance_id=None,
        state_status=state_status,
        startup_confirmed=False,
        last_error=None,
        last_error_utc=None,
        last_restart_reason=last_restart_reason,
        started_at_utc=None,
        consecutive_start_failures=0,
        last_start_attempt_utc=None,
        last_start_failure_reason=None,
        db_path=db_path,
    )


def increment_listener_restart_count(
    *,
    reason: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Increment the listener restart counter."""
    state = get_listener_state(db_path)
    current = int(state.get("restart_count") or 0)
    return update_listener_state(
        restart_count=current + 1,
        last_restart_reason=reason,
        db_path=db_path,
    )


def parse_reply_command(text: str | None) -> ParsedReplyCommand | None:
    """Parse a text reply command (ANSWER, APPROVE, DECLINE)."""
    raw = str(text or "").strip()
    if not raw:
        return None
    answer_match = _ANSWER_RE.match(raw)
    if answer_match:
        prompt_id = answer_match.group(1).strip()
        response_text = answer_match.group(2).strip()
        return ParsedReplyCommand(
            command="answer",
            prompt_id=prompt_id,
            response_type=RESPONSE_ANSWER,
            response_text=response_text,
        )
    approve_match = _APPROVE_RE.match(raw)
    if approve_match:
        prompt_id = approve_match.group(1).strip()
        return ParsedReplyCommand(
            command="approve",
            prompt_id=prompt_id,
            response_type=RESPONSE_APPROVE,
            response_text="approve",
        )
    decline_match = _DECLINE_RE.match(raw)
    if decline_match:
        prompt_id = decline_match.group(1).strip()
        return ParsedReplyCommand(
            command="decline",
            prompt_id=prompt_id,
            response_type=RESPONSE_DECLINE,
            response_text="decline",
        )
    return None


def is_process_alive(pid: int | None) -> bool:
    """Check if a process is alive (used by listener health checks)."""
    if pid is None:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False
    except Exception:
        return False

"""Telegram notification MCP server (stdio) with bidirectional input tools."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import (
    ALLOWED_NOTIFICATION_EVENTS,
    MAX_CALLBACK_DATA_BYTES,
    MAX_POLL_OPTIONS,
    format_notification_message,
    load_telegram_config,
)
from .inbox import (
    INPUT_MODE_INLINE,
    INPUT_MODE_POLL,
    INPUT_MODE_TEXT,
    STATUS_CANCELLED,
    STATUS_RESOLVED,
    cancel_prompt as cancel_prompt_in_db,
    consume_prompt,
    create_expiry_timestamp,
    expire_prompt_if_needed,
    get_listener_state,
    get_recent_inbound_messages,
    increment_listener_restart_count,
    initialize_inbox_db,
    list_pending_prompts as list_pending_prompts_from_store,
    reset_listener_runtime_state,
    resolve_inbox_db_path,
    resolve_listener_log_path,
    update_listener_state,
    update_prompt_delivery,
    upsert_pending_prompt,
)
from .messaging import (
    send_telegram_inline_keyboard,
    send_telegram_message,
    send_telegram_poll,
)
from .singleton import (
    SingletonAcquireError,
    SingletonLease,
    acquire_singleton_or_preempt,
    inspect_lock,
    is_process_alive as singleton_is_process_alive,
    release_singleton,
    remove_lock_file,
    resolve_lock_path,
    terminate_pid,
)

SERVER = FastMCP(name="telegram_notify")
TASK_ENV_KEYS = (
    "CODEX_TASK_NAME",
    "CODEX_TASK",
    "TASK_NAME",
    "TASK",
    "CODEX_SESSION_TITLE",
)
DEFAULT_TASK_NAME = "notification"
DEFAULT_PROMPT_EXPIRY_MINUTES = 5
SINGLETON_LOCK_NAME = "telegram_reply_listener"
SERVER_LOCK_NAME = "telegram_notify_server"
DEFAULT_SINGLETON_POLICY = "machine_kill_old"
DEFAULT_SINGLETON_RETRIES = 5
DEFAULT_SINGLETON_RETRY_DELAY_SECONDS = 0.2
DEFAULT_INLINE_COLUMNS = 2
VALID_INPUT_MODES = {INPUT_MODE_TEXT, INPUT_MODE_POLL, INPUT_MODE_INLINE}
LISTENER_STARTUP_TIMEOUT_SECONDS = 10.0
LISTENER_STARTUP_POLL_SECONDS = 0.25
LISTENER_START_MAX_ATTEMPTS = 2
LISTENER_HEARTBEAT_STALE_SECONDS = 90.0
EVENT_TOKENS = {
    "question",
    "plan ready",
    "final",
    "attention",
    "error",
    "input required",
}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _to_error_payload(error_text: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status_code": None,
        "message_id": None,
        "error": error_text,
    }


def _stderr(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


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


def _parse_iso(raw: str | None) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def _acquire_server_singleton() -> SingletonLease:
    policy, retries, retry_delay_seconds = _load_singleton_settings()
    if policy != DEFAULT_SINGLETON_POLICY:
        raise ValueError(
            f"Unsupported TELEGRAM_SINGLETON_POLICY: {policy}. "
            f"Supported value: {DEFAULT_SINGLETON_POLICY}"
        )
    lease = acquire_singleton_or_preempt(
        lock_name=SERVER_LOCK_NAME,
        owner_label=SERVER_LOCK_NAME,
        retries=retries,
        retry_delay_s=retry_delay_seconds,
    )
    for replaced_pid in lease.preempted_pids:
        _stderr(f"telegram_notify_server preempted existing process pid={replaced_pid}")
    return lease


def _run_server_with_singleton() -> int:
    lease: SingletonLease | None = None
    try:
        lease = _acquire_server_singleton()
        SERVER.run(transport="stdio")
        return 0
    except SingletonAcquireError as exc:
        _stderr(f"telegram_notify_server singleton acquire failed: {exc}; payload={exc.payload}")
        return 1
    except Exception as exc:
        _stderr(f"telegram_notify_server startup error: {exc}")
        return 1
    finally:
        if lease is not None:
            release_singleton(lease)


def _append_listener_log(*, message: str, level: str = "INFO", log_path: str | Path | None = None) -> None:
    try:
        target = resolve_listener_log_path(log_path)
        line = f"{_utc_iso_now()} [{str(level).upper()}] [telegram_notify_server] {str(message).strip()}\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:
        return


def _tail_text(path: Path, lines: int) -> str:
    if not path.exists() or lines <= 0:
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    if not content:
        return ""
    return "\n".join(content[-max(1, int(lines)):])


def _normalize_for_match(text: str | Path) -> str:
    return str(text).replace("\\", "/").lower()


def _get_process_commandline(pid: int) -> str | None:
    if int(pid) <= 0:
        return None

    proc_path = Path(f"/proc/{int(pid)}/cmdline")
    if proc_path.exists():
        try:
            raw = proc_path.read_bytes()
            text = raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()
            if text:
                return text
        except Exception:
            pass

    if os.name == "nt":
        try:
            command = (
                "$p = Get-CimInstance Win32_Process -Filter \"ProcessId="
                + str(int(pid))
                + "\"; if ($p) { $p.CommandLine }"
            )
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            output = str(completed.stdout or "").strip()
            if output:
                return output
        except Exception:
            return None
    else:
        try:
            completed = subprocess.run(
                ["ps", "-p", str(int(pid)), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            output = str(completed.stdout or "").strip()
            if output:
                return output
        except Exception:
            return None
    return None


_LISTENER_MODULE_FRAGMENTS = ("telegram_mcp_notify.listener", "telegram_reply_listener")


def _is_listener_commandline_match(commandline: str | None, db_path: Path) -> bool:
    if not commandline:
        return False
    normalized = _normalize_for_match(commandline)
    has_script_fragment = any(frag in normalized for frag in _LISTENER_MODULE_FRAGMENTS)
    if not has_script_fragment:
        return False
    db_fragment = _normalize_for_match(str(db_path))
    return db_fragment in normalized


def _is_matching_listener_process(pid: int | None, db_path: Path) -> bool:
    parsed_pid = _safe_int(pid)
    if parsed_pid is None or not singleton_is_process_alive(parsed_pid):
        return False
    commandline = _get_process_commandline(parsed_pid)
    return _is_listener_commandline_match(commandline, db_path)


def _derive_health_reason(
    *,
    running: bool,
    pid: int | None,
    state_status: str,
    startup_confirmed: bool,
    heartbeat_age_seconds: float | None,
    lock_status: str,
) -> tuple[str, str]:
    status = str(state_status or "stopped").strip().lower() or "stopped"
    if running and startup_confirmed and status == "running":
        if heartbeat_age_seconds is not None and heartbeat_age_seconds > LISTENER_HEARTBEAT_STALE_SECONDS:
            return "heartbeat_stale", "Run repair_telegram_listener to refresh stale heartbeat state."
        return "healthy", "No action required."
    if running and not startup_confirmed:
        return "startup_unconfirmed", "Wait briefly; if it persists, run repair_telegram_listener."
    if not running and pid is not None:
        return "stale_pid", "Run repair_telegram_listener to clear stale PID/runtime state."
    if lock_status == "stale":
        return "stale_lock", "Run repair_telegram_listener to clear stale lock state."
    if status == "degraded":
        return "degraded", "Inspect log tail and run repair_telegram_listener."
    if status == "error":
        return "error", "Inspect last_error/log_tail and run repair_telegram_listener."
    if status == "starting":
        return "starting", "Wait briefly; if startup does not confirm, run repair_telegram_listener."
    return "stopped", "Call start_telegram_listener to start the background listener."


def _listener_health_payload(
    db_path: str | Path | None = None,
    *,
    include_log_tail: bool = False,
    log_tail_lines: int = 20,
) -> dict[str, Any]:
    resolved_db_path = resolve_inbox_db_path(initialize_inbox_db(db_path))
    state = get_listener_state(resolved_db_path)

    pid_int = _safe_int(state.get("pid"))
    try:
        running = singleton_is_process_alive(pid_int)
    except Exception:
        running = False
    heartbeat = state.get("heartbeat_utc")
    heartbeat_age_seconds: float | None = None
    parsed_heartbeat = _parse_iso(str(heartbeat or ""))
    if parsed_heartbeat is not None:
        heartbeat_age_seconds = max(0.0, (datetime.now(timezone.utc) - parsed_heartbeat).total_seconds())

    lock_path = resolve_lock_path(SINGLETON_LOCK_NAME)
    lock_info = inspect_lock(SINGLETON_LOCK_NAME)
    lock_status = str(lock_info.get("status") or "unknown")

    state_status = str(state.get("state_status") or "stopped").strip().lower() or "stopped"
    startup_confirmed = bool(state.get("startup_confirmed"))
    health_reason, recommended_action = _derive_health_reason(
        running=running,
        pid=pid_int,
        state_status=state_status,
        startup_confirmed=startup_confirmed,
        heartbeat_age_seconds=heartbeat_age_seconds,
        lock_status=lock_status,
    )

    log_path = resolve_listener_log_path(None)
    payload: dict[str, Any] = {
        "ok": True,
        "running": running,
        "pid": pid_int,
        "last_update_id": int(state.get("last_update_id") or 0),
        "heartbeat_utc": heartbeat,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "db_path": str(resolved_db_path),
        "state_status": state_status,
        "instance_id": state.get("instance_id"),
        "startup_confirmed": startup_confirmed,
        "last_error": state.get("last_error"),
        "last_error_utc": state.get("last_error_utc"),
        "restart_count": int(state.get("restart_count") or 0),
        "lock_path": str(lock_path),
        "lock_status": lock_status,
        "health_reason": health_reason,
        "recommended_action": recommended_action,
        "log_path": str(log_path),
    }
    if include_log_tail:
        payload["log_tail"] = _tail_text(log_path, max(1, int(log_tail_lines)))
    return payload


def _spawn_listener_process(
    *,
    db_path: Path,
    instance_id: str,
    log_path: Path,
) -> subprocess.Popen[Any]:
    command = [
        sys.executable,
        "-m",
        "telegram_mcp_notify.listener",
        "--db-path",
        str(db_path),
        "--instance-id",
        str(instance_id),
        "--log-path",
        str(log_path),
    ]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        creation_flags = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        kwargs["creationflags"] = creation_flags
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)


def _wait_for_startup_confirmation(
    *,
    db_path: Path,
    instance_id: str,
    timeout_seconds: float,
    poll_seconds: float,
) -> tuple[bool, dict[str, Any]]:
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    latest = _listener_health_payload(db_path)
    while time.monotonic() <= deadline:
        latest = _listener_health_payload(db_path)
        if (
            bool(latest.get("running"))
            and bool(latest.get("startup_confirmed"))
            and str(latest.get("state_status") or "") == "running"
            and str(latest.get("instance_id") or "") == str(instance_id)
        ):
            return True, latest
        time.sleep(max(0.05, float(poll_seconds)))
    return False, latest


def _terminate_if_matching_listener(
    *,
    pid: int | None,
    db_path: Path,
    actions: list[str],
    errors: list[str],
) -> None:
    parsed_pid = _safe_int(pid)
    if parsed_pid is None:
        return
    if not _is_matching_listener_process(parsed_pid, db_path):
        actions.append(f"skip_terminate_pid:{parsed_pid}:not_matching_listener")
        return
    if terminate_pid(parsed_pid):
        actions.append(f"terminated_pid:{parsed_pid}")
    else:
        errors.append(f"failed_to_terminate_pid:{parsed_pid}")


def _remove_stale_lock_if_safe(
    *,
    db_path: Path,
    actions: list[str],
    errors: list[str],
) -> None:
    lock_info = inspect_lock(SINGLETON_LOCK_NAME)
    lock_status = str(lock_info.get("status") or "unknown")
    if lock_status != "stale":
        return

    owner_pid = _safe_int(lock_info.get("owner_pid"))
    if owner_pid is not None and _is_matching_listener_process(owner_pid, db_path):
        actions.append(f"skip_remove_lock:owner_listener_alive:{owner_pid}")
        return

    try:
        removed = remove_lock_file(SINGLETON_LOCK_NAME)
        if removed:
            actions.append("removed_stale_lock")
        else:
            actions.append("lock_already_absent")
    except Exception as exc:
        errors.append(f"remove_lock_failed:{exc}")


def _apply_balanced_self_heal(
    *,
    db_path: Path,
    reason: str,
) -> tuple[list[str], list[str]]:
    actions: list[str] = []
    errors: list[str] = []

    state = get_listener_state(db_path)
    _terminate_if_matching_listener(
        pid=_safe_int(state.get("pid")),
        db_path=db_path,
        actions=actions,
        errors=errors,
    )

    _remove_stale_lock_if_safe(db_path=db_path, actions=actions, errors=errors)

    reset_listener_runtime_state(
        state_status="stopped",
        last_restart_reason=reason,
        db_path=db_path,
    )
    actions.append("reset_runtime_state")
    _append_listener_log(message=f"self-heal applied reason={reason}; actions={actions}; errors={errors}")
    return actions, errors


def _start_listener_once(
    *,
    db_path: Path,
    reason: str,
) -> dict[str, Any]:
    instance_id = f"li_{uuid.uuid4().hex}"
    log_path = resolve_listener_log_path(None)

    increment_listener_restart_count(reason=reason, db_path=db_path)
    update_listener_state(
        state_status="starting",
        startup_confirmed=False,
        instance_id=instance_id,
        pid=None,
        last_restart_reason=reason,
        started_at_utc=_utc_iso_now(),
        db_path=db_path,
    )

    process = _spawn_listener_process(db_path=db_path, instance_id=instance_id, log_path=log_path)
    _append_listener_log(
        message=(
            f"spawned listener pid={process.pid} instance_id={instance_id} "
            f"db_path={db_path} reason={reason}"
        )
    )

    startup_timeout = _parse_non_negative_float_env(
        "TELEGRAM_LISTENER_STARTUP_TIMEOUT_SECONDS",
        LISTENER_STARTUP_TIMEOUT_SECONDS,
    )
    startup_poll = _parse_non_negative_float_env(
        "TELEGRAM_LISTENER_STARTUP_POLL_SECONDS",
        LISTENER_STARTUP_POLL_SECONDS,
    )
    started, diagnostics = _wait_for_startup_confirmation(
        db_path=db_path,
        instance_id=instance_id,
        timeout_seconds=startup_timeout,
        poll_seconds=startup_poll,
    )
    diagnostics = dict(diagnostics)
    diagnostics["spawned_pid"] = int(process.pid)
    if started:
        _append_listener_log(message=f"listener startup confirmed instance_id={instance_id} pid={process.pid}")
    else:
        _append_listener_log(
            level="WARNING",
            message=(
                f"listener startup confirmation timeout instance_id={instance_id} pid={process.pid}; "
                f"state_status={diagnostics.get('state_status')} reason={diagnostics.get('health_reason')}"
            ),
        )
    return {
        "started": started,
        "startup_confirmed": bool(diagnostics.get("startup_confirmed")),
        "diagnostics": diagnostics,
    }


def _ensure_listener_running(
    db_path: str | Path | None = None,
    *,
    self_heal: bool = True,
) -> dict[str, Any]:
    resolved_db_path = resolve_inbox_db_path(initialize_inbox_db(db_path))
    diagnostics = _listener_health_payload(resolved_db_path)
    if bool(diagnostics.get("running")) and bool(diagnostics.get("startup_confirmed")):
        diagnostics["health_reason"] = "healthy"
        diagnostics["recommended_action"] = "No action required."
        return {
            "ok": True,
            "running": True,
            "started": False,
            "startup_confirmed": True,
            "attempts": 0,
            "diagnostics": diagnostics,
        }

    max_attempts = max(1, _parse_non_negative_int_env("TELEGRAM_LISTENER_START_MAX_ATTEMPTS", LISTENER_START_MAX_ATTEMPTS))
    latest = diagnostics
    for attempt in range(1, max_attempts + 1):
        if self_heal:
            actions, errors = _apply_balanced_self_heal(
                db_path=resolved_db_path,
                reason=f"start_attempt_{attempt}",
            )
            latest = _listener_health_payload(resolved_db_path)
            latest["self_heal_actions"] = actions
            if errors:
                latest["self_heal_errors"] = errors

        start_result = _start_listener_once(
            db_path=resolved_db_path,
            reason=f"start_attempt_{attempt}",
        )
        latest = dict(start_result.get("diagnostics") or {})
        if bool(start_result.get("started")) and bool(start_result.get("startup_confirmed")):
            return {
                "ok": True,
                "running": True,
                "started": True,
                "startup_confirmed": True,
                "attempts": attempt,
                "diagnostics": latest,
            }

    latest = _listener_health_payload(resolved_db_path)
    latest["health_reason"] = "startup_confirmation_timeout"
    latest["recommended_action"] = "Run repair_telegram_listener(include_log_tail=true) and inspect errors."
    return {
        "ok": False,
        "running": bool(latest.get("running")),
        "started": False,
        "startup_confirmed": bool(latest.get("startup_confirmed")),
        "attempts": max_attempts,
        "diagnostics": latest,
    }


def _normalize_choices(choices: list[str] | None) -> list[str]:
    return [str(choice).strip() for choice in (choices or []) if str(choice).strip()]


def _normalize_input_mode(input_mode: str | None) -> str:
    return str(input_mode or INPUT_MODE_TEXT).strip().lower()


def _resolve_expiry_minutes(*, expires_at_utc: str | None, fallback_minutes: int) -> int:
    parsed = _parse_iso(expires_at_utc)
    if parsed is None:
        return max(1, int(fallback_minutes))
    delta_seconds = max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
    if delta_seconds <= 0:
        return 1
    return max(1, int(math.ceil(delta_seconds / 60.0)))


def _build_pending_prompt_message(
    *,
    task_name: str,
    session_id: str,
    run_id: str | None,
    prompt_id: str,
    prompt_text: str,
    prompt_kind: str,
    choices: list[str] | None,
    expires_at_utc: str | None,
) -> str:
    lines = [
        f"INPUT REQUIRED | {task_name}",
        str(prompt_text or "").strip() or "No details provided.",
        f"prompt_kind={str(prompt_kind or 'question').strip().lower()}",
        f"prompt_id={prompt_id}",
        f"session_id={session_id}",
    ]
    if run_id and str(run_id).strip():
        lines.append(f"run_id={str(run_id).strip()}")
    if choices:
        lines.append(f"choices={', '.join(choices)}")
    if expires_at_utc and str(expires_at_utc).strip():
        lines.append(f"expires_at_utc={str(expires_at_utc).strip()}")
    lines.extend(
        [
            "Reply with:",
            f"ANSWER {prompt_id} <text>",
            f"APPROVE {prompt_id}",
            f"DECLINE {prompt_id}",
        ]
    )
    return "\n".join(lines)


def _build_inline_prompt_message(
    *,
    task_name: str,
    prompt_text: str,
    expires_in_minutes: int,
) -> str:
    lines = [
        f"\u2753 QUESTION | {task_name}",
        str(prompt_text or "").strip() or "Please choose an option.",
        "Tap one option below.",
        f"Expires in {max(1, int(expires_in_minutes))} minutes.",
    ]
    return "\n".join(lines)


def _new_callback_namespace() -> str:
    return f"cb_{uuid.uuid4().hex[:10]}"


def _build_inline_keyboard(
    *,
    callback_namespace: str,
    choices: list[str],
    inline_columns: int,
) -> list[list[dict[str, str]]]:
    columns = max(1, min(int(inline_columns), 4))
    rows: list[list[dict[str, str]]] = []
    for index, choice in enumerate(choices):
        callback_data = f"c:{callback_namespace}:{index}"
        if len(callback_data.encode("utf-8")) > MAX_CALLBACK_DATA_BYTES:
            raise ValueError("Generated callback_data exceeded Telegram 64-byte limit.")
        button = {"text": choice, "callback_data": callback_data}
        if not rows or len(rows[-1]) >= columns:
            rows.append([button])
        else:
            rows[-1].append(button)
    return rows


# ---------------------------------------------------------------------------
# Existing tools
# ---------------------------------------------------------------------------


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
    name="register_pending_prompt",
    description="Register a pending prompt and optionally send text/poll/inline Telegram input prompts.",
)
def register_pending_prompt(
    session_id: str,
    prompt_text: str,
    prompt_id: str | None = None,
    run_id: str | None = None,
    task_name: str | None = None,
    prompt_kind: str = "question",
    choices: list[str] | None = None,
    input_mode: str = INPUT_MODE_TEXT,
    allows_multiple_answers: bool = False,
    inline_columns: int = DEFAULT_INLINE_COLUMNS,
    expires_at_utc: str | None = None,
    expires_in_minutes: int = DEFAULT_PROMPT_EXPIRY_MINUTES,
    send_notification: bool = True,
    ensure_listener: bool = True,
    db_path: str | None = None,
) -> dict[str, Any]:
    try:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return {"ok": False, "error": "session_id is required."}
        normalized_prompt_text = str(prompt_text or "").strip()
        if not normalized_prompt_text:
            return {"ok": False, "error": "prompt_text is required."}

        normalized_input_mode = _normalize_input_mode(input_mode)
        if normalized_input_mode not in VALID_INPUT_MODES:
            return {"ok": False, "error": f"Unsupported input_mode: {input_mode}"}

        normalized_choices = _normalize_choices(choices)
        if normalized_input_mode in {INPUT_MODE_POLL, INPUT_MODE_INLINE} and not normalized_choices:
            return {"ok": False, "error": f"choices are required when input_mode={normalized_input_mode}"}
        if normalized_input_mode == INPUT_MODE_POLL and len(normalized_choices) > MAX_POLL_OPTIONS:
            return {"ok": False, "error": "Poll input mode supports at most 12 options."}
        if normalized_input_mode == INPUT_MODE_INLINE and not (1 <= int(inline_columns) <= 4):
            return {"ok": False, "error": "inline_columns must be between 1 and 4."}

        initialize_inbox_db(db_path)
        normalized_expires_in_minutes = int(expires_in_minutes)
        ttl_target = (
            str(expires_at_utc).strip()
            if expires_at_utc and str(expires_at_utc).strip()
            else create_expiry_timestamp(normalized_expires_in_minutes)
        )
        display_expiry_minutes = _resolve_expiry_minutes(
            expires_at_utc=ttl_target,
            fallback_minutes=normalized_expires_in_minutes,
        )
        callback_namespace = _new_callback_namespace() if normalized_input_mode == INPUT_MODE_INLINE else None

        record = upsert_pending_prompt(
            session_id=normalized_session_id,
            prompt_text=normalized_prompt_text,
            prompt_id=prompt_id,
            run_id=run_id,
            prompt_kind=prompt_kind,
            choices=normalized_choices,
            input_mode=normalized_input_mode,
            callback_namespace=callback_namespace,
            expires_at_utc=ttl_target,
            db_path=db_path,
        )
        persisted_prompt_id = str(record.get("prompt_id") or "")

        delivery: dict[str, Any] = {"ok": True, "message_id": None, "poll_id": None, "error": None}
        if send_notification:
            config = load_telegram_config()
            resolved_task = _resolve_task_name(
                task_name=task_name,
                run_id=run_id,
                session_id=normalized_session_id,
                message=normalized_prompt_text,
            )
            if normalized_input_mode == INPUT_MODE_TEXT:
                msg = _build_pending_prompt_message(
                    task_name=resolved_task,
                    session_id=normalized_session_id,
                    run_id=run_id,
                    prompt_id=persisted_prompt_id,
                    prompt_text=normalized_prompt_text,
                    prompt_kind=prompt_kind,
                    choices=normalized_choices,
                    expires_at_utc=ttl_target,
                )
                delivery = send_telegram_message(msg, config=config, max_retries=1)
            elif normalized_input_mode == INPUT_MODE_POLL:
                delivery = send_telegram_poll(
                    question=normalized_prompt_text,
                    options=normalized_choices,
                    allows_multiple_answers=bool(allows_multiple_answers),
                    config=config,
                    max_retries=1,
                )
            else:
                msg = _build_inline_prompt_message(
                    task_name=resolved_task,
                    prompt_text=normalized_prompt_text,
                    expires_in_minutes=display_expiry_minutes,
                )
                keyboard = _build_inline_keyboard(
                    callback_namespace=str(callback_namespace),
                    choices=normalized_choices,
                    inline_columns=int(inline_columns),
                )
                delivery = send_telegram_inline_keyboard(
                    text=msg,
                    inline_keyboard=keyboard,
                    config=config,
                    max_retries=1,
                )

        updated_record = update_prompt_delivery(
            prompt_id=persisted_prompt_id,
            telegram_message_id=delivery.get("message_id"),
            telegram_poll_id=delivery.get("poll_id"),
            callback_namespace=callback_namespace,
            db_path=db_path,
        )
        if updated_record is not None:
            record = updated_record

        listener_payload: dict[str, Any] | None = None
        if ensure_listener:
            listener_payload = _ensure_listener_running(db_path, self_heal=True)
        return {
            "ok": bool(delivery.get("ok", True)),
            "prompt_id": record.get("prompt_id"),
            "status": record.get("status"),
            "session_id": record.get("session_id"),
            "run_id": record.get("run_id"),
            "input_mode": record.get("input_mode"),
            "expires_at_utc": record.get("expires_at_utc"),
            "telegram_message_id": record.get("telegram_message_id"),
            "telegram_poll_id": record.get("telegram_poll_id"),
            "delivery_error": delivery.get("error"),
            "listener": listener_payload,
            "prompt": record,
        }
    except Exception as exc:
        _stderr(f"telegram_notify_server register_pending_prompt error: {exc}")
        return {"ok": False, "error": str(exc)}


@SERVER.tool(
    name="check_pending_prompt",
    description="Check pending prompt status and optionally consume a resolved response.",
)
def check_pending_prompt(
    session_id: str,
    prompt_id: str,
    consume: bool = False,
    db_path: str | None = None,
) -> dict[str, Any]:
    try:
        normalized_session_id = str(session_id or "").strip()
        normalized_prompt_id = str(prompt_id or "").strip()
        if not normalized_session_id or not normalized_prompt_id:
            return {"ok": False, "error": "session_id and prompt_id are required."}
        initialize_inbox_db(db_path)
        record = expire_prompt_if_needed(
            prompt_id=normalized_prompt_id,
            session_id=normalized_session_id,
            db_path=db_path,
        )
        if record is None:
            return {"ok": False, "error": "Pending prompt not found.", "prompt_id": normalized_prompt_id}
        if consume and str(record.get("status")) == STATUS_RESOLVED:
            consumed_record = consume_prompt(
                prompt_id=normalized_prompt_id,
                session_id=normalized_session_id,
                db_path=db_path,
            )
            if consumed_record is not None:
                record = consumed_record
        return {
            "ok": True,
            "prompt_id": record.get("prompt_id"),
            "session_id": record.get("session_id"),
            "run_id": record.get("run_id"),
            "input_mode": record.get("input_mode"),
            "status": record.get("status"),
            "response_type": record.get("response_type"),
            "response_text": record.get("response_text"),
            "response_payload": record.get("response_payload"),
            "selected_option_ids": record.get("selected_option_ids"),
            "selected_options": record.get("selected_options"),
            "telegram_message_id": record.get("telegram_message_id"),
            "telegram_poll_id": record.get("telegram_poll_id"),
            "resolved_at_utc": record.get("resolved_at_utc"),
            "consumed_at_utc": record.get("consumed_at_utc"),
            "expires_at_utc": record.get("expires_at_utc"),
        }
    except Exception as exc:
        _stderr(f"telegram_notify_server check_pending_prompt error: {exc}")
        return {"ok": False, "error": str(exc)}


@SERVER.tool(
    name="list_pending_prompts",
    description="List pending prompts for a session with optional status filter.",
)
def list_pending_prompts(
    session_id: str,
    status_filter: str | None = None,
    limit: int = 20,
    db_path: str | None = None,
) -> dict[str, Any]:
    try:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return {"ok": False, "error": "session_id is required."}
        initialize_inbox_db(db_path)
        records = list_pending_prompts_from_store(
            session_id=normalized_session_id,
            status_filter=status_filter,
            limit=int(limit),
            db_path=db_path,
        )
        for record in records:
            if str(record.get("status")) == "waiting":
                refreshed = expire_prompt_if_needed(
                    prompt_id=str(record.get("prompt_id") or ""),
                    session_id=normalized_session_id,
                    db_path=db_path,
                )
                if refreshed is not None:
                    record.update(refreshed)
        return {"ok": True, "session_id": normalized_session_id, "count": len(records), "pending_prompts": records}
    except Exception as exc:
        _stderr(f"telegram_notify_server list_pending_prompts error: {exc}")
        return {"ok": False, "error": str(exc)}


@SERVER.tool(
    name="telegram_listener_health",
    description="Return health for the Telegram reply listener daemon.",
)
def telegram_listener_health(
    db_path: str | None = None,
    include_log_tail: bool = False,
    log_tail_lines: int = 20,
) -> dict[str, Any]:
    try:
        return _listener_health_payload(
            db_path,
            include_log_tail=bool(include_log_tail),
            log_tail_lines=max(1, int(log_tail_lines)),
        )
    except Exception as exc:
        _stderr(f"telegram_notify_server telegram_listener_health error: {exc}")
        return {
            "ok": False,
            "error": str(exc),
            "state_status": "error",
            "health_reason": "health_exception",
            "recommended_action": "Run repair_telegram_listener and inspect logs.",
        }


@SERVER.tool(
    name="start_telegram_listener",
    description="Start the Telegram reply listener daemon if it is not already running.",
)
def start_telegram_listener(
    db_path: str | None = None,
    self_heal: bool = True,
) -> dict[str, Any]:
    try:
        result = _ensure_listener_running(db_path, self_heal=bool(self_heal))
        return {
            "ok": bool(result.get("ok")),
            "running": bool(result.get("running")),
            "started": bool(result.get("started")),
            "startup_confirmed": bool(result.get("startup_confirmed")),
            "attempts": int(result.get("attempts") or 0),
            "diagnostics": result.get("diagnostics"),
        }
    except Exception as exc:
        _stderr(f"telegram_notify_server start_telegram_listener error: {exc}")
        return {"ok": False, "error": str(exc)}


@SERVER.tool(
    name="repair_telegram_listener",
    description="Repair Telegram listener stale PID/lock/runtime state and optionally restart.",
)
def repair_telegram_listener(
    db_path: str | None = None,
    restart: bool = True,
    reason: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    actions: list[str] = []
    try:
        resolved_db_path = resolve_inbox_db_path(initialize_inbox_db(db_path))
        repair_reason = str(reason or "manual_repair").strip() or "manual_repair"
        before = _listener_health_payload(resolved_db_path, include_log_tail=True, log_tail_lines=20)

        heal_actions, heal_errors = _apply_balanced_self_heal(db_path=resolved_db_path, reason=repair_reason)
        actions.extend(heal_actions)
        errors.extend(heal_errors)

        after: dict[str, Any]
        if bool(restart):
            start_result = _ensure_listener_running(resolved_db_path, self_heal=False)
            actions.append("restart_attempted")
            if not bool(start_result.get("ok")):
                errors.append("restart_failed")
            after = dict(start_result.get("diagnostics") or _listener_health_payload(resolved_db_path))
        else:
            after = _listener_health_payload(resolved_db_path, include_log_tail=True, log_tail_lines=20)

        return {
            "ok": len(errors) == 0 and (not bool(restart) or bool(after.get("startup_confirmed"))),
            "actions_taken": actions,
            "before": before,
            "after": after,
            "errors": errors,
        }
    except Exception as exc:
        errors.append(str(exc))
        _stderr(f"telegram_notify_server repair_telegram_listener error: {exc}")
        return {
            "ok": False,
            "actions_taken": actions,
            "before": None,
            "after": None,
            "errors": errors,
        }


# ---------------------------------------------------------------------------
# New high-level input tools
# ---------------------------------------------------------------------------


@SERVER.tool(
    name="ask_user",
    description=(
        "Send a text question to the user via Telegram and register it as a pending prompt. "
        "Returns the prompt_id for later checking with check_pending_prompt. "
        "Combines send_telegram_notification + register_pending_prompt in one call."
    ),
)
def ask_user(
    question: str,
    session_id: str,
    task_name: str | None = None,
    run_id: str | None = None,
    timeout_minutes: int = DEFAULT_PROMPT_EXPIRY_MINUTES,
    db_path: str | None = None,
) -> dict[str, Any]:
    try:
        normalized_question = str(question or "").strip()
        normalized_session_id = str(session_id or "").strip()
        if not normalized_question:
            return {"ok": False, "error": "question is required."}
        if not normalized_session_id:
            return {"ok": False, "error": "session_id is required."}

        return register_pending_prompt(
            session_id=normalized_session_id,
            prompt_text=normalized_question,
            run_id=run_id,
            task_name=task_name,
            prompt_kind="question",
            input_mode=INPUT_MODE_TEXT,
            expires_in_minutes=max(1, int(timeout_minutes)),
            send_notification=True,
            ensure_listener=True,
            db_path=db_path,
        )
    except Exception as exc:
        _stderr(f"telegram_notify_server ask_user error: {exc}")
        return {"ok": False, "error": str(exc)}


@SERVER.tool(
    name="ask_user_confirmation",
    description=(
        "Send a Yes/No confirmation question to the user via Telegram inline keyboard. "
        "Returns the prompt_id for later checking with check_pending_prompt."
    ),
)
def ask_user_confirmation(
    question: str,
    session_id: str,
    task_name: str | None = None,
    run_id: str | None = None,
    timeout_minutes: int = DEFAULT_PROMPT_EXPIRY_MINUTES,
    db_path: str | None = None,
) -> dict[str, Any]:
    try:
        normalized_question = str(question or "").strip()
        normalized_session_id = str(session_id or "").strip()
        if not normalized_question:
            return {"ok": False, "error": "question is required."}
        if not normalized_session_id:
            return {"ok": False, "error": "session_id is required."}

        return register_pending_prompt(
            session_id=normalized_session_id,
            prompt_text=normalized_question,
            run_id=run_id,
            task_name=task_name,
            prompt_kind="confirmation",
            choices=["Yes", "No"],
            input_mode=INPUT_MODE_INLINE,
            inline_columns=2,
            expires_in_minutes=max(1, int(timeout_minutes)),
            send_notification=True,
            ensure_listener=True,
            db_path=db_path,
        )
    except Exception as exc:
        _stderr(f"telegram_notify_server ask_user_confirmation error: {exc}")
        return {"ok": False, "error": str(exc)}


@SERVER.tool(
    name="ask_user_choice",
    description=(
        "Send a multiple-choice question to the user via Telegram. "
        "Uses inline keyboard for <=4 choices, poll for >4 (or set input_mode explicitly). "
        "Returns the prompt_id for later checking with check_pending_prompt."
    ),
)
def ask_user_choice(
    question: str,
    choices: list[str],
    session_id: str,
    task_name: str | None = None,
    run_id: str | None = None,
    input_mode: str = "auto",
    timeout_minutes: int = DEFAULT_PROMPT_EXPIRY_MINUTES,
    db_path: str | None = None,
) -> dict[str, Any]:
    try:
        normalized_question = str(question or "").strip()
        normalized_session_id = str(session_id or "").strip()
        if not normalized_question:
            return {"ok": False, "error": "question is required."}
        if not normalized_session_id:
            return {"ok": False, "error": "session_id is required."}
        normalized_choices = _normalize_choices(choices)
        if len(normalized_choices) < 2:
            return {"ok": False, "error": "At least 2 choices are required."}

        mode = str(input_mode or "auto").strip().lower()
        if mode == "auto":
            mode = INPUT_MODE_INLINE if len(normalized_choices) <= 4 else INPUT_MODE_POLL

        return register_pending_prompt(
            session_id=normalized_session_id,
            prompt_text=normalized_question,
            run_id=run_id,
            task_name=task_name,
            prompt_kind="choice",
            choices=normalized_choices,
            input_mode=mode,
            expires_in_minutes=max(1, int(timeout_minutes)),
            send_notification=True,
            ensure_listener=True,
            db_path=db_path,
        )
    except Exception as exc:
        _stderr(f"telegram_notify_server ask_user_choice error: {exc}")
        return {"ok": False, "error": str(exc)}


@SERVER.tool(
    name="cancel_prompt",
    description="Cancel a pending prompt so it is no longer awaited.",
)
def tool_cancel_prompt(
    session_id: str,
    prompt_id: str,
    db_path: str | None = None,
) -> dict[str, Any]:
    try:
        normalized_session_id = str(session_id or "").strip()
        normalized_prompt_id = str(prompt_id or "").strip()
        if not normalized_session_id or not normalized_prompt_id:
            return {"ok": False, "error": "session_id and prompt_id are required."}

        initialize_inbox_db(db_path)
        record = cancel_prompt_in_db(
            prompt_id=normalized_prompt_id,
            session_id=normalized_session_id,
            db_path=db_path,
        )
        if record is None:
            return {"ok": False, "error": "Prompt not found.", "prompt_id": normalized_prompt_id}

        cancelled = str(record.get("status")) == STATUS_CANCELLED
        return {
            "ok": cancelled,
            "prompt_id": record.get("prompt_id"),
            "previous_status": "waiting" if cancelled else record.get("status"),
            "current_status": record.get("status"),
        }
    except Exception as exc:
        _stderr(f"telegram_notify_server cancel_prompt error: {exc}")
        return {"ok": False, "error": str(exc)}


@SERVER.tool(
    name="get_recent_messages",
    description="Retrieve recent inbound messages from the inbox database (useful for context or reviewing user replies).",
)
def tool_get_recent_messages(
    limit: int = 10,
    db_path: str | None = None,
) -> dict[str, Any]:
    try:
        initialize_inbox_db(db_path)
        messages = get_recent_inbound_messages(
            limit=max(1, min(int(limit), 100)),
            db_path=db_path,
        )
        return {
            "ok": True,
            "count": len(messages),
            "messages": messages,
        }
    except Exception as exc:
        _stderr(f"telegram_notify_server get_recent_messages error: {exc}")
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Entry point for the telegram-mcp-notify console script."""
    return _run_server_with_singleton()


if __name__ == "__main__":
    raise SystemExit(main())

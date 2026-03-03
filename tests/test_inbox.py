from __future__ import annotations

from datetime import datetime, timedelta, timezone

import telegram_mcp_notify.inbox as inbox_module
from telegram_mcp_notify.inbox import (
    INPUT_MODE_INLINE,
    INPUT_MODE_POLL,
    STATUS_CONSUMED,
    STATUS_EXPIRED,
    STATUS_RESOLVED,
    STATUS_WAITING,
    consume_prompt,
    expire_prompt_if_needed,
    get_waiting_prompt_by_callback_namespace,
    get_waiting_prompt_by_poll_id,
    get_listener_state,
    increment_listener_restart_count,
    initialize_inbox_db,
    list_pending_prompts,
    mark_prompt_resolved,
    parse_reply_command,
    reset_listener_runtime_state,
    set_listener_error,
    update_listener_state,
    update_prompt_delivery,
    upsert_pending_prompt,
)


def test_parse_reply_command_supports_answer_and_approval_tokens() -> None:
    answer = parse_reply_command("ANSWER prompt_123 model confidence low")
    approve = parse_reply_command("APPROVE prompt_123")
    decline = parse_reply_command("decline prompt_123")

    assert answer is not None
    assert answer.command == "answer"
    assert answer.prompt_id == "prompt_123"
    assert answer.response_text == "model confidence low"
    assert answer.response_type == "answer"

    assert approve is not None
    assert approve.command == "approve"
    assert approve.response_type == "approve"

    assert decline is not None
    assert decline.command == "decline"
    assert decline.response_type == "decline"


def test_pending_prompt_resolve_and_consume_flow(tmp_path) -> None:
    db_path = tmp_path / "telegram_inbox.db"
    initialize_inbox_db(db_path)

    created = upsert_pending_prompt(
        session_id="session-1",
        run_id="run-1",
        prompt_id="prompt-1",
        prompt_text="Need approval for command execution",
        prompt_kind="approval",
        db_path=db_path,
    )
    assert created["status"] == STATUS_WAITING

    resolved = mark_prompt_resolved(
        prompt_id="prompt-1",
        response_type="approve",
        response_text="approve",
        source_message_id=42,
        db_path=db_path,
    )
    assert resolved is not None
    assert resolved["status"] == STATUS_RESOLVED
    assert resolved["response_type"] == "approve"

    consumed = consume_prompt(
        prompt_id="prompt-1",
        session_id="session-1",
        db_path=db_path,
    )
    assert consumed is not None
    assert consumed["status"] == STATUS_CONSUMED


def test_expire_prompt_if_needed_marks_waiting_record_expired(tmp_path) -> None:
    db_path = tmp_path / "telegram_inbox.db"
    initialize_inbox_db(db_path)
    expired_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(microsecond=0).isoformat()
    upsert_pending_prompt(
        session_id="session-1",
        prompt_id="prompt-expired",
        prompt_text="Provide missing context",
        expires_at_utc=expired_at,
        db_path=db_path,
    )

    expired = expire_prompt_if_needed(
        prompt_id="prompt-expired",
        session_id="session-1",
        db_path=db_path,
    )
    assert expired is not None
    assert expired["status"] == STATUS_EXPIRED

    rows = list_pending_prompts(session_id="session-1", db_path=db_path)
    assert len(rows) == 1
    assert rows[0]["status"] == STATUS_EXPIRED


def test_waiting_prompt_lookup_supports_poll_and_callback_namespace(tmp_path) -> None:
    db_path = tmp_path / "telegram_inbox.db"
    initialize_inbox_db(db_path)
    created = upsert_pending_prompt(
        session_id="session-lookup",
        prompt_id="prompt-lookup",
        prompt_text="Choose option",
        input_mode=INPUT_MODE_INLINE,
        callback_namespace="cb_lookup",
        choices=["A", "B"],
        db_path=db_path,
    )
    assert created["input_mode"] == INPUT_MODE_INLINE
    update_prompt_delivery(prompt_id="prompt-lookup", telegram_poll_id="poll_lookup", db_path=db_path)

    by_callback = get_waiting_prompt_by_callback_namespace(callback_namespace="cb_lookup", db_path=db_path)
    assert by_callback is not None
    assert by_callback["prompt_id"] == "prompt-lookup"

    by_poll = get_waiting_prompt_by_poll_id(poll_id="poll_lookup", db_path=db_path)
    assert by_poll is not None
    assert by_poll["prompt_id"] == "prompt-lookup"


def test_selection_response_payload_is_projected_to_selected_fields(tmp_path) -> None:
    db_path = tmp_path / "telegram_inbox.db"
    initialize_inbox_db(db_path)
    upsert_pending_prompt(
        session_id="session-select",
        prompt_id="prompt-select",
        prompt_text="Pick options",
        input_mode=INPUT_MODE_POLL,
        choices=["X", "Y", "Z"],
        db_path=db_path,
    )
    resolved = mark_prompt_resolved(
        prompt_id="prompt-select",
        response_type="selection",
        response_text="X, Z",
        response_payload={
            "source": "poll",
            "selected_option_ids": [0, 2],
            "selected_options": ["X", "Z"],
        },
        db_path=db_path,
    )
    assert resolved is not None
    assert resolved["status"] == STATUS_RESOLVED
    assert resolved["selected_option_ids"] == [0, 2]
    assert resolved["selected_options"] == ["X", "Z"]


def test_listener_state_extended_fields_and_helpers(tmp_path) -> None:
    db_path = tmp_path / "telegram_inbox.db"
    initialize_inbox_db(db_path)

    state = get_listener_state(db_path)
    assert state["state_status"] == "stopped"
    assert state["startup_confirmed"] == 0
    assert state["restart_count"] == 0
    assert state["consecutive_start_failures"] == 0
    assert state["last_start_attempt_utc"] is None
    assert state["last_start_failure_reason"] is None

    update_listener_state(
        pid=1234,
        instance_id="li_test",
        state_status="running",
        startup_confirmed=True,
        db_path=db_path,
    )
    running = get_listener_state(db_path)
    assert running["pid"] == 1234
    assert running["instance_id"] == "li_test"
    assert running["state_status"] == "running"
    assert running["startup_confirmed"] == 1
    assert running["consecutive_start_failures"] == 0

    set_listener_error(error_text="boom", state_status="degraded", db_path=db_path)
    degraded = get_listener_state(db_path)
    assert degraded["state_status"] == "degraded"
    assert degraded["last_error"] == "boom"

    increment_listener_restart_count(reason="test-restart", db_path=db_path)
    restarted = get_listener_state(db_path)
    assert restarted["restart_count"] == 1
    assert restarted["last_restart_reason"] == "test-restart"

    reset_listener_runtime_state(db_path=db_path)
    reset_state = get_listener_state(db_path)
    assert reset_state["pid"] is None
    assert reset_state["state_status"] == "stopped"
    assert reset_state["startup_confirmed"] == 0
    assert reset_state["consecutive_start_failures"] == 0
    assert reset_state["last_start_attempt_utc"] is None
    assert reset_state["last_start_failure_reason"] is None


def test_parse_iso_handles_unexpected_parser_exception(monkeypatch) -> None:
    class _BrokenDateTime:
        @staticmethod
        def fromisoformat(_text: str):
            raise RuntimeError("parser-crash")

    monkeypatch.setattr(inbox_module, "datetime", _BrokenDateTime)
    assert inbox_module._parse_iso("2026-03-03T10:00:00+08:00") is None

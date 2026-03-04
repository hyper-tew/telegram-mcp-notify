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
    count_compatible_waiting_prompts_for_light_guess,
    find_compatible_waiting_prompt_for_light_guess,
    get_waiting_custom_text_prompt_for_user,
    get_waiting_prompt_by_alias,
    expire_prompt_if_needed,
    get_waiting_prompt_by_callback_namespace,
    get_waiting_prompt_by_poll_id,
    get_pending_prompt,
    get_listener_state,
    increment_listener_restart_count,
    initialize_inbox_db,
    mark_prompt_resolved,
    parse_reply_command,
    reset_listener_runtime_state,
    set_prompt_waiting_custom_text,
    set_listener_error,
    update_listener_state,
    update_prompt_delivery,
    upsert_pending_prompt,
    clear_prompt_waiting_custom_text,
)


def test_parse_reply_command_supports_answer_and_approval_tokens() -> None:
    answer = parse_reply_command("ANSWER prompt_123 model confidence low")
    approve = parse_reply_command("APPROVE prompt_123")
    decline = parse_reply_command("decline prompt_123")
    alias_by_strict_answer = parse_reply_command("answer 123 use model D")
    alias_by_strict_approve = parse_reply_command("approve 123")
    alias_approve = parse_reply_command("yes to 123")
    alias_answer = parse_reply_command("123 answer use model C")
    natural_yes = parse_reply_command("approved")

    assert answer is not None
    assert answer.command == "answer"
    assert answer.prompt_ref == "prompt_123"
    assert answer.prompt_ref_type == "id"
    assert answer.response_text == "model confidence low"
    assert answer.response_type == "answer"

    assert approve is not None
    assert approve.command == "approve"
    assert approve.prompt_ref == "prompt_123"
    assert approve.prompt_ref_type == "id"
    assert approve.response_type == "approve"

    assert decline is not None
    assert decline.command == "decline"
    assert decline.prompt_ref == "prompt_123"
    assert decline.prompt_ref_type == "id"
    assert decline.response_type == "decline"

    assert alias_approve is not None
    assert alias_approve.command == "approve"
    assert alias_approve.prompt_ref == "123"
    assert alias_approve.prompt_ref_type == "alias"

    assert alias_by_strict_approve is not None
    assert alias_by_strict_approve.command == "approve"
    assert alias_by_strict_approve.prompt_ref == "123"
    assert alias_by_strict_approve.prompt_ref_type == "alias"

    assert alias_by_strict_answer is not None
    assert alias_by_strict_answer.command == "answer"
    assert alias_by_strict_answer.prompt_ref == "123"
    assert alias_by_strict_answer.prompt_ref_type == "alias"
    assert alias_by_strict_answer.response_text == "use model D"

    assert alias_answer is not None
    assert alias_answer.command == "answer"
    assert alias_answer.prompt_ref == "123"
    assert alias_answer.prompt_ref_type == "alias"
    assert alias_answer.response_text == "use model C"

    assert natural_yes is not None
    assert natural_yes.command == "approve"
    assert natural_yes.prompt_ref is None
    assert natural_yes.prompt_ref_type is None


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

    row = get_pending_prompt(prompt_id="prompt-expired", session_id="session-1", db_path=db_path)
    assert row is not None
    assert row["status"] == STATUS_EXPIRED


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


def test_prompt_alias_custom_state_and_light_guess_helpers(tmp_path) -> None:
    db_path = tmp_path / "telegram_inbox.db"
    initialize_inbox_db(db_path)
    confirmation = upsert_pending_prompt(
        session_id="session-alias",
        prompt_id="prompt-confirm",
        prompt_text="Approve deployment?",
        prompt_kind="confirmation",
        input_mode=INPUT_MODE_INLINE,
        choices=["Yes", "No"],
        db_path=db_path,
    )
    choice = upsert_pending_prompt(
        session_id="session-alias",
        prompt_id="prompt-choice",
        prompt_text="Pick strategy",
        prompt_kind="choice",
        input_mode=INPUT_MODE_INLINE,
        choices=["A", "B"],
        custom_text_enabled=True,
        db_path=db_path,
    )

    assert str(confirmation.get("prompt_alias") or "").isdigit()
    assert len(str(confirmation.get("prompt_alias") or "")) == 3
    assert str(choice.get("prompt_alias") or "").isdigit()
    assert len(str(choice.get("prompt_alias") or "")) == 3

    by_alias = get_waiting_prompt_by_alias(alias=str(choice["prompt_alias"]), db_path=db_path)
    assert by_alias is not None
    assert by_alias["prompt_id"] == "prompt-choice"

    set_prompt_waiting_custom_text(prompt_id="prompt-choice", user_id="42", db_path=db_path)
    waiting_custom = get_waiting_custom_text_prompt_for_user(user_id="42", db_path=db_path)
    assert waiting_custom is not None
    assert waiting_custom["prompt_id"] == "prompt-choice"
    assert waiting_custom["awaiting_custom_text"] == 1

    cleared = clear_prompt_waiting_custom_text(prompt_id="prompt-choice", db_path=db_path)
    assert cleared is not None
    assert cleared["awaiting_custom_text"] == 0

    guessed_confirmation = find_compatible_waiting_prompt_for_light_guess(text="yes", db_path=db_path)
    assert guessed_confirmation is not None
    assert guessed_confirmation["prompt_id"] == "prompt-confirm"
    assert count_compatible_waiting_prompts_for_light_guess(text="yes", db_path=db_path) == 1

    guessed_choice = find_compatible_waiting_prompt_for_light_guess(text="my own answer", db_path=db_path)
    assert guessed_choice is not None
    assert guessed_choice["prompt_id"] == "prompt-choice"
    assert count_compatible_waiting_prompts_for_light_guess(text="my own answer", db_path=db_path) == 1


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

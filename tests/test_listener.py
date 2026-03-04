from __future__ import annotations

from telegram_mcp_notify.config import TelegramConfig
from telegram_mcp_notify.inbox import (
    get_pending_prompt,
    initialize_inbox_db,
    upsert_pending_prompt,
)
from telegram_mcp_notify import listener


def test_process_callback_update_resolves_inline_prompt(monkeypatch, tmp_path) -> None:
    callback_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        listener, "answer_telegram_callback_query",
        lambda **kwargs: callback_calls.append(kwargs) or {"ok": True},
    )

    db_path = tmp_path / "telegram_inbox.db"
    initialize_inbox_db(db_path)
    upsert_pending_prompt(
        session_id="session-inline",
        prompt_id="prompt-inline",
        prompt_text="Choose one",
        prompt_kind="choice",
        input_mode="inline",
        callback_namespace="cb_test",
        choices=["A", "B"],
        db_path=db_path,
    )

    listener._process_callback_update(
        update_id=11,
        callback_query={
            "id": "cbq-1",
            "data": "c:cb_test:1",
            "from": {"id": 7},
            "message": {"message_id": 55, "chat": {"id": "trusted-chat"}},
        },
        trusted_chat_id="trusted-chat",
        config=TelegramConfig(bot_token="token", chat_id="trusted-chat"),
        db_path=db_path,
    )

    record = get_pending_prompt(prompt_id="prompt-inline", db_path=db_path)
    assert record is not None
    assert record["status"] == "resolved"
    assert record["response_type"] == "selection"
    assert record["selected_option_ids"] == [1]
    assert record["selected_options"] == ["B"]
    assert len(callback_calls) == 1
    assert callback_calls[0]["text"] == "Selection confirmed: B"


def test_process_callback_update_does_not_send_toast_for_non_choice_prompt(monkeypatch, tmp_path) -> None:
    callback_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        listener,
        "answer_telegram_callback_query",
        lambda **kwargs: callback_calls.append(kwargs) or {"ok": True},
    )

    db_path = tmp_path / "telegram_inbox.db"
    initialize_inbox_db(db_path)
    upsert_pending_prompt(
        session_id="session-inline-confirm",
        prompt_id="prompt-inline-confirm",
        prompt_text="Approve change?",
        prompt_kind="confirmation",
        input_mode="inline",
        callback_namespace="cb_confirm",
        choices=["Yes", "No"],
        db_path=db_path,
    )

    listener._process_callback_update(
        update_id=13,
        callback_query={
            "id": "cbq-2",
            "data": "c:cb_confirm:0",
            "from": {"id": 8},
            "message": {"message_id": 56, "chat": {"id": "trusted-chat"}},
        },
        trusted_chat_id="trusted-chat",
        config=TelegramConfig(bot_token="token", chat_id="trusted-chat"),
        db_path=db_path,
    )

    record = get_pending_prompt(prompt_id="prompt-inline-confirm", db_path=db_path)
    assert record is not None
    assert record["status"] == "resolved"
    assert record["selected_options"] == ["Yes"]
    assert len(callback_calls) == 1
    assert "text" not in callback_calls[0]


def test_process_callback_custom_option_waits_for_text_then_resolves(monkeypatch, tmp_path) -> None:
    callback_calls: list[dict[str, object]] = []
    sent_messages: list[str] = []
    monkeypatch.setattr(
        listener,
        "answer_telegram_callback_query",
        lambda **kwargs: callback_calls.append(kwargs) or {"ok": True},
    )
    monkeypatch.setattr(
        listener,
        "send_telegram_message",
        lambda text, **_kwargs: sent_messages.append(str(text)) or {"ok": True},
    )

    db_path = tmp_path / "telegram_inbox.db"
    initialize_inbox_db(db_path)
    upsert_pending_prompt(
        session_id="session-inline-custom",
        prompt_id="prompt-inline-custom",
        prompt_text="Choose one",
        prompt_kind="choice",
        input_mode="inline",
        callback_namespace="cb_custom",
        choices=["A", "B"],
        custom_text_enabled=True,
        db_path=db_path,
    )

    cfg = TelegramConfig(bot_token="token", chat_id="trusted-chat")
    listener._process_callback_update(
        update_id=21,
        callback_query={
            "id": "cbq-custom",
            "data": "c:cb_custom:o",
            "from": {"id": 99},
            "message": {"message_id": 77, "chat": {"id": "trusted-chat"}},
        },
        trusted_chat_id="trusted-chat",
        config=cfg,
        db_path=db_path,
    )

    waiting = get_pending_prompt(prompt_id="prompt-inline-custom", db_path=db_path)
    assert waiting is not None
    assert waiting["status"] == "waiting"
    assert waiting["awaiting_custom_text"] == 1
    assert waiting["awaiting_custom_text_user_id"] == "99"
    assert len(callback_calls) == 1
    assert callback_calls[0]["text"] == "Type your answer now."
    assert sent_messages

    listener._process_text_update(
        update_id=22,
        message={
            "message_id": 78,
            "text": "Use option C",
            "from": {"id": 99},
            "chat": {"id": "trusted-chat"},
        },
        trusted_chat_id="trusted-chat",
        config=cfg,
        db_path=db_path,
    )
    resolved = get_pending_prompt(prompt_id="prompt-inline-custom", db_path=db_path)
    assert resolved is not None
    assert resolved["status"] == "resolved"
    assert resolved["response_type"] == "answer"
    assert resolved["response_text"] == "Use option C"
    assert resolved["awaiting_custom_text"] == 0


def test_process_text_update_resolves_confirmation_from_natural_text(tmp_path) -> None:
    db_path = tmp_path / "telegram_inbox.db"
    initialize_inbox_db(db_path)
    upsert_pending_prompt(
        session_id="session-confirm-text",
        prompt_id="prompt-confirm-text",
        prompt_text="Approve change?",
        prompt_kind="confirmation",
        input_mode="inline",
        choices=["Yes", "No"],
        db_path=db_path,
    )

    listener._process_text_update(
        update_id=31,
        message={
            "message_id": 88,
            "text": "approved",
            "from": {"id": 10},
            "chat": {"id": "trusted-chat"},
        },
        trusted_chat_id="trusted-chat",
        config=TelegramConfig(bot_token="token", chat_id="trusted-chat"),
        db_path=db_path,
    )
    resolved = get_pending_prompt(prompt_id="prompt-confirm-text", db_path=db_path)
    assert resolved is not None
    assert resolved["status"] == "resolved"
    assert resolved["response_type"] == "approve"
    assert resolved["response_text"] == "approve"


def test_process_text_update_ambiguous_confirmation_sends_guidance(monkeypatch, tmp_path) -> None:
    sent_messages: list[str] = []
    monkeypatch.setattr(
        listener,
        "send_telegram_message",
        lambda text, **_kwargs: sent_messages.append(str(text)) or {"ok": True},
    )

    db_path = tmp_path / "telegram_inbox.db"
    initialize_inbox_db(db_path)
    upsert_pending_prompt(
        session_id="session-confirm-a",
        prompt_id="prompt-confirm-a",
        prompt_text="Approve A?",
        prompt_kind="confirmation",
        input_mode="inline",
        choices=["Yes", "No"],
        db_path=db_path,
    )
    upsert_pending_prompt(
        session_id="session-confirm-b",
        prompt_id="prompt-confirm-b",
        prompt_text="Approve B?",
        prompt_kind="confirmation",
        input_mode="inline",
        choices=["Yes", "No"],
        db_path=db_path,
    )

    listener._process_text_update(
        update_id=32,
        message={
            "message_id": 89,
            "text": "yes",
            "from": {"id": 11},
            "chat": {"id": "trusted-chat"},
        },
        trusted_chat_id="trusted-chat",
        config=TelegramConfig(bot_token="token", chat_id="trusted-chat"),
        db_path=db_path,
    )
    first = get_pending_prompt(prompt_id="prompt-confirm-a", db_path=db_path)
    second = get_pending_prompt(prompt_id="prompt-confirm-b", db_path=db_path)
    assert first is not None and second is not None
    assert first["status"] == "waiting"
    assert second["status"] == "waiting"
    assert any("could not map" in msg.lower() for msg in sent_messages)


def test_process_poll_answer_update_resolves_poll_prompt(tmp_path) -> None:
    db_path = tmp_path / "telegram_inbox.db"
    initialize_inbox_db(db_path)
    upsert_pending_prompt(
        session_id="session-poll",
        prompt_id="prompt-poll",
        prompt_text="Pick two",
        input_mode="poll",
        telegram_poll_id="poll-id-1",
        choices=["X", "Y", "Z"],
        db_path=db_path,
    )

    listener._process_poll_answer_update(
        update_id=12,
        poll_answer={"poll_id": "poll-id-1", "option_ids": [0, 2], "user": {"id": 100}},
        db_path=db_path,
    )

    record = get_pending_prompt(prompt_id="prompt-poll", db_path=db_path)
    assert record is not None
    assert record["status"] == "resolved"
    assert record["selected_option_ids"] == [0, 2]
    assert record["selected_options"] == ["X", "Z"]


class _FakeHttpxClient:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self) -> "_FakeHttpxClient":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> bool:
        return False


class _FakeHttpxModule:
    Client = _FakeHttpxClient


def test_run_listener_marks_degraded_on_loop_exception(monkeypatch, tmp_path) -> None:
    updates: list[dict[str, object]] = []
    original_update = listener.update_listener_state

    def _capture_update_listener_state(**kwargs):
        updates.append(dict(kwargs))
        return original_update(**kwargs)

    sequence = iter([RuntimeError("loop failed"), KeyboardInterrupt()])

    def _fake_poll_updates(**_kwargs):
        value = next(sequence)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(listener, "httpx", _FakeHttpxModule)
    monkeypatch.setattr(listener, "load_telegram_config", lambda: TelegramConfig(bot_token="token", chat_id="trusted-chat"))
    monkeypatch.setattr(listener, "_preflight_get_updates", lambda **_kwargs: None)
    monkeypatch.setattr(listener, "_poll_updates", _fake_poll_updates)
    monkeypatch.setattr(listener, "_process_update", lambda **_kwargs: None)
    monkeypatch.setattr(listener, "time", type("T", (), {"sleep": staticmethod(lambda _s: None), "time": staticmethod(lambda: 0)})())
    monkeypatch.setattr(listener, "update_listener_state", _capture_update_listener_state)

    db_path = tmp_path / "telegram_inbox.db"
    listener.run_listener(
        db_path=str(db_path),
        instance_id="li_test_degraded",
        log_path=str(tmp_path / "listener.log"),
        poll_timeout_seconds=1,
        error_sleep_seconds=0.01,
    )

    assert any(call.get("state_status") == "degraded" for call in updates)


def test_run_listener_marks_error_on_preflight_failure(monkeypatch, tmp_path) -> None:
    updates: list[dict[str, object]] = []
    original_update = listener.update_listener_state

    def _capture_update_listener_state(**kwargs):
        updates.append(dict(kwargs))
        return original_update(**kwargs)

    monkeypatch.setattr(listener, "httpx", _FakeHttpxModule)
    monkeypatch.setattr(listener, "load_telegram_config", lambda: TelegramConfig(bot_token="token", chat_id="trusted-chat"))
    monkeypatch.setattr(listener, "_preflight_get_updates", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("preflight failed")))
    monkeypatch.setattr(listener, "update_listener_state", _capture_update_listener_state)

    db_path = tmp_path / "telegram_inbox.db"
    try:
        listener.run_listener(
            db_path=str(db_path),
            instance_id="li_test_error",
            log_path=str(tmp_path / "listener.log"),
            poll_timeout_seconds=1,
            error_sleep_seconds=0.01,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("run_listener should raise on preflight failure")

    assert any(call.get("state_status") == "error" for call in updates)


def test_run_listener_marks_token_conflict_on_preflight_conflict(monkeypatch, tmp_path) -> None:
    updates: list[dict[str, object]] = []
    original_update = listener.update_listener_state

    def _capture_update_listener_state(**kwargs):
        updates.append(dict(kwargs))
        return original_update(**kwargs)

    monkeypatch.setattr(listener, "httpx", _FakeHttpxModule)
    monkeypatch.setattr(listener, "load_telegram_config", lambda: TelegramConfig(bot_token="token", chat_id="trusted-chat"))
    monkeypatch.setattr(listener, "_preflight_get_updates", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("409 Conflict")))
    monkeypatch.setattr(listener, "update_listener_state", _capture_update_listener_state)

    db_path = tmp_path / "telegram_inbox.db"
    try:
        listener.run_listener(
            db_path=str(db_path),
            instance_id="li_test_conflict",
            log_path=str(tmp_path / "listener.log"),
            poll_timeout_seconds=1,
            error_sleep_seconds=0.01,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("run_listener should raise on preflight token conflict")

    assert any(call.get("state_status") == "token_conflict" for call in updates)

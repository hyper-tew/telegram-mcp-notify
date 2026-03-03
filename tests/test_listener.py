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

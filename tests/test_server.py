from __future__ import annotations

from types import SimpleNamespace

from telegram_mcp_notify import server


def test_infer_task_name_from_pipe_message_uses_descriptive_segment() -> None:
    message = "PROGRESS | aem-lit-data6 | Test telegram notification\ntimestamp_cn=2026-03-02T10:00:00+08:00"
    assert server._infer_task_name_from_message(message) == "Test telegram notification"


def test_resolve_task_name_uses_inferred_message_when_task_is_missing(monkeypatch) -> None:
    for key in ("CODEX_TASK_NAME", "CODEX_TASK", "TASK_NAME", "TASK", "CODEX_SESSION_TITLE"):
        monkeypatch.delenv(key, raising=False)
    assert (
        server._resolve_task_name(message="FINAL | aem-lit-data6 | test v4 graph with DOI")
        == "test v4 graph with DOI"
    )


def test_resolve_task_name_uses_default_when_no_other_source(monkeypatch) -> None:
    for key in ("CODEX_TASK_NAME", "CODEX_TASK", "TASK_NAME", "TASK", "CODEX_SESSION_TITLE"):
        monkeypatch.delenv(key, raising=False)
    assert server._resolve_task_name(message="timestamp_cn=2026-03-02T10:00:00+08:00") == server.DEFAULT_TASK_NAME


def test_send_notification_rejects_unsupported_event() -> None:
    result = server.send_telegram_notification(event="progress", message="not allowed")
    assert result == {
        "ok": False,
        "status_code": None,
        "message_id": None,
        "error": "Unsupported notification event: progress",
    }


def test_send_notification_success_calls_config_and_messaging(monkeypatch) -> None:
    calls: dict[str, object] = {}
    fake_config = SimpleNamespace(bot_token="token", chat_id="chat")

    def _fake_format(**kwargs):
        calls["format_kwargs"] = kwargs
        return "formatted-message"

    def _fake_send(text, *, config, max_retries=1):
        calls["send_text"] = text
        calls["send_config"] = config
        calls["send_retries"] = max_retries
        return {"ok": True, "status_code": 200, "message_id": 123, "error": None}

    monkeypatch.setattr(server, "load_telegram_config", lambda: fake_config)
    monkeypatch.setattr(server, "format_notification_message", _fake_format)
    monkeypatch.setattr(server, "send_telegram_message", _fake_send)

    result = server.send_telegram_notification(
        event="final",
        message="Deployment complete",
        session_id="s-1",
        run_id="r-1",
        task_name="release-task",
        requires_action=False,
    )
    assert result["ok"] is True
    assert calls["send_text"] == "formatted-message"
    assert calls["send_config"] is fake_config
    assert calls["send_retries"] == 1
    assert calls["format_kwargs"] == {
        "task": "release-task",
        "event": "final",
        "message": "Deployment complete",
        "requires_action": False,
        "session_id": "s-1",
        "run_id": "r-1",
    }


def test_send_notification_failure_returns_standard_error_payload(monkeypatch) -> None:
    monkeypatch.setattr(server, "load_telegram_config", lambda: (_ for _ in ()).throw(ValueError("bad config")))
    errors: list[str] = []
    monkeypatch.setattr(server, "_stderr", lambda message: errors.append(message))

    result = server.send_telegram_notification(event="question", message="Need decision")
    assert result == {
        "ok": False,
        "status_code": None,
        "message_id": None,
        "error": "bad config",
    }
    assert len(errors) == 1
    assert errors[0].startswith("telegram_notify_server error:")


def test_telegram_notify_capabilities_exposes_only_target_tools() -> None:
    expected_tools = {
        "send_telegram_notification",
        "telegram_notify_capabilities",
    }

    result = server.telegram_notify_capabilities()
    assert result["ok"] is True
    assert set(result["tools"]) == expected_tools
    assert result["tool_count"] == 2
    assert result["supports"]["notifications"] is True
    assert result["supports"]["pending_prompts"] is False
    assert result["supports"]["listener_lifecycle"] is False
    assert result["supports"]["listener_stop_restart"] is False
    assert result["supports"]["sync_wait_for_prompt"] is False
    assert result["supports"]["custom_choice_text"] is False


def test_main_runs_server_without_singleton(monkeypatch) -> None:
    called: dict[str, object] = {}
    monkeypatch.setattr(
        server,
        "SERVER",
        SimpleNamespace(run=lambda *, transport: called.setdefault("transport", transport)),
    )
    assert server.main() == 0
    assert called["transport"] == "stdio"


def test_main_returns_one_on_startup_exception(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "SERVER",
        SimpleNamespace(run=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))),
    )
    errors: list[str] = []
    monkeypatch.setattr(server, "_stderr", lambda message: errors.append(message))

    assert server.main() == 1
    assert len(errors) == 1
    assert errors[0] == "telegram_notify_server startup error: boom"

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

from telegram_mcp_notify.inbox import mark_prompt_resolved
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


def test_register_pending_prompt_and_check_pending_prompt_flow(monkeypatch, tmp_path) -> None:
    sent: dict[str, object] = {}

    def _fake_send(message, *, config, max_retries=1):
        sent["message"] = message
        return {"ok": True, "status_code": 200, "message_id": 88, "error": None}

    monkeypatch.setattr(server, "load_telegram_config", lambda: SimpleNamespace())
    monkeypatch.setattr(server, "send_telegram_message", _fake_send)
    monkeypatch.setattr(
        server,
        "_ensure_listener_running",
        lambda db_path=None, self_heal=True: {
            "ok": True, "running": True, "started": False,
            "startup_confirmed": True, "attempts": 0, "diagnostics": {},
        },
    )

    db_path = str(tmp_path / "telegram_inbox.db")
    created = server.register_pending_prompt(
        session_id="session-1",
        prompt_text="Please approve deployment",
        prompt_id="prompt-1",
        run_id="run-1",
        prompt_kind="approval",
        send_notification=True,
        ensure_listener=True,
        db_path=db_path,
    )
    assert created["ok"] is True
    assert created["prompt_id"] == "prompt-1"
    assert created["status"] == "waiting"
    assert created["telegram_message_id"] == 88
    assert "ANSWER prompt-1 <text>" in str(sent.get("message"))

    waiting = server.check_pending_prompt(session_id="session-1", prompt_id="prompt-1", db_path=db_path)
    assert waiting["ok"] is True
    assert waiting["status"] == "waiting"

    mark_prompt_resolved(
        prompt_id="prompt-1",
        response_type="approve",
        response_text="approve",
        db_path=db_path,
    )
    resolved = server.check_pending_prompt(session_id="session-1", prompt_id="prompt-1", db_path=db_path)
    assert resolved["status"] == "resolved"

    consumed = server.check_pending_prompt(session_id="session-1", prompt_id="prompt-1", consume=True, db_path=db_path)
    assert consumed["status"] == "consumed"


def test_list_pending_prompts_filters_status(tmp_path) -> None:
    db_path = str(tmp_path / "telegram_inbox.db")
    created = server.register_pending_prompt(
        session_id="session-2", prompt_id="prompt-2", prompt_text="Need answer",
        send_notification=False, ensure_listener=False, db_path=db_path,
    )
    assert created["status"] == "waiting"
    mark_prompt_resolved(prompt_id="prompt-2", response_type="answer", response_text="done", db_path=db_path)

    server.register_pending_prompt(
        session_id="session-2", prompt_id="prompt-3", prompt_text="still waiting",
        send_notification=False, ensure_listener=False, db_path=db_path,
    )

    resolved = server.list_pending_prompts(session_id="session-2", status_filter="resolved", db_path=db_path)
    assert resolved["ok"] is True
    assert resolved["count"] == 1
    assert resolved["pending_prompts"][0]["prompt_id"] == "prompt-2"


def test_register_pending_prompt_poll_mode_persists_poll_id(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def _fake_send_poll(question, options, *, allows_multiple_answers=False, config, max_retries=1):
        captured["question"] = question
        captured["options"] = options
        captured["allows_multiple_answers"] = allows_multiple_answers
        return {"ok": True, "status_code": 200, "message_id": 99, "poll_id": "poll-1", "error": None}

    monkeypatch.setattr(server, "load_telegram_config", lambda: SimpleNamespace())
    monkeypatch.setattr(server, "send_telegram_poll", _fake_send_poll)
    monkeypatch.setattr(
        server, "_ensure_listener_running",
        lambda db_path=None, self_heal=True: {"ok": True, "running": True, "started": False, "startup_confirmed": True, "attempts": 0, "diagnostics": {}},
    )

    db_path = str(tmp_path / "telegram_inbox.db")
    created = server.register_pending_prompt(
        session_id="session-poll", prompt_id="prompt-poll", prompt_text="Pick two",
        input_mode="poll", choices=["A", "B", "C"], allows_multiple_answers=True,
        send_notification=True, ensure_listener=False, db_path=db_path,
    )
    assert created["ok"] is True
    assert created["input_mode"] == "poll"
    assert created["telegram_poll_id"] == "poll-1"
    assert captured["question"] == "Pick two"
    assert captured["allows_multiple_answers"] is True


def test_register_pending_prompt_inline_mode_builds_callback_buttons(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def _fake_send_inline(text, inline_keyboard, *, config, max_retries=1):
        captured["text"] = text
        captured["inline_keyboard"] = inline_keyboard
        return {"ok": True, "status_code": 200, "message_id": 101, "error": None}

    monkeypatch.setattr(server, "load_telegram_config", lambda: SimpleNamespace())
    monkeypatch.setattr(server, "send_telegram_inline_keyboard", _fake_send_inline)
    monkeypatch.setattr(
        server, "_ensure_listener_running",
        lambda db_path=None, self_heal=True: {"ok": True, "running": True, "started": False, "startup_confirmed": True, "attempts": 0, "diagnostics": {}},
    )

    db_path = str(tmp_path / "telegram_inbox.db")
    created = server.register_pending_prompt(
        session_id="session-inline", prompt_id="prompt-inline", prompt_text="Pick one",
        input_mode="inline", choices=["X", "Y", "Z"], inline_columns=2,
        send_notification=True, ensure_listener=False, db_path=db_path,
    )
    assert created["ok"] is True
    assert created["input_mode"] == "inline"
    assert "\u2753 QUESTION |" in str(captured["text"])
    keyboard = captured["inline_keyboard"]
    assert isinstance(keyboard, list)
    assert keyboard[0][0]["callback_data"].startswith("c:cb_")


def test_ask_user_sends_text_question(monkeypatch, tmp_path) -> None:
    sent: dict[str, object] = {}

    def _fake_send(message, *, config, max_retries=1):
        sent["message"] = message
        return {"ok": True, "status_code": 200, "message_id": 200, "error": None}

    monkeypatch.setattr(server, "load_telegram_config", lambda: SimpleNamespace())
    monkeypatch.setattr(server, "send_telegram_message", _fake_send)
    monkeypatch.setattr(
        server, "_ensure_listener_running",
        lambda db_path=None, self_heal=True: {"ok": True, "running": True, "started": False, "startup_confirmed": True, "attempts": 0, "diagnostics": {}},
    )

    db_path = str(tmp_path / "telegram_inbox.db")
    result = server.ask_user(
        question="Should I proceed with deployment?",
        session_id="session-ask",
        db_path=db_path,
    )
    assert result["ok"] is True
    assert result["prompt_id"] is not None
    assert result["status"] == "waiting"
    assert "Should I proceed with deployment?" in str(sent.get("message"))


def test_ask_user_confirmation_sends_inline_yes_no(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def _fake_send_inline(text, inline_keyboard, *, config, max_retries=1):
        captured["text"] = text
        captured["keyboard"] = inline_keyboard
        return {"ok": True, "status_code": 200, "message_id": 201, "error": None}

    monkeypatch.setattr(server, "load_telegram_config", lambda: SimpleNamespace())
    monkeypatch.setattr(server, "send_telegram_inline_keyboard", _fake_send_inline)
    monkeypatch.setattr(
        server, "_ensure_listener_running",
        lambda db_path=None, self_heal=True: {"ok": True, "running": True, "started": False, "startup_confirmed": True, "attempts": 0, "diagnostics": {}},
    )

    db_path = str(tmp_path / "telegram_inbox.db")
    result = server.ask_user_confirmation(
        question="Approve this change?",
        session_id="session-confirm",
        db_path=db_path,
    )
    assert result["ok"] is True
    assert result["input_mode"] == "inline"
    buttons = [btn["text"] for row in captured["keyboard"] for btn in row]
    assert "Yes" in buttons
    assert "No" in buttons


def test_ask_user_choice_auto_selects_mode(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def _fake_send_inline(text, inline_keyboard, *, config, max_retries=1):
        captured["mode"] = "inline"
        return {"ok": True, "status_code": 200, "message_id": 202, "error": None}

    def _fake_send_poll(question, options, *, allows_multiple_answers=False, config, max_retries=1):
        captured["mode"] = "poll"
        return {"ok": True, "status_code": 200, "message_id": 203, "poll_id": "p1", "error": None}

    monkeypatch.setattr(server, "load_telegram_config", lambda: SimpleNamespace())
    monkeypatch.setattr(server, "send_telegram_inline_keyboard", _fake_send_inline)
    monkeypatch.setattr(server, "send_telegram_poll", _fake_send_poll)
    monkeypatch.setattr(
        server, "_ensure_listener_running",
        lambda db_path=None, self_heal=True: {"ok": True, "running": True, "started": False, "startup_confirmed": True, "attempts": 0, "diagnostics": {}},
    )

    db_path = str(tmp_path / "telegram_inbox.db")

    result = server.ask_user_choice(
        question="Pick one", choices=["A", "B", "C"],
        session_id="session-choice", db_path=db_path,
    )
    assert result["ok"] is True
    assert captured["mode"] == "inline"

    captured.clear()
    result = server.ask_user_choice(
        question="Pick many", choices=["A", "B", "C", "D", "E"],
        session_id="session-choice", db_path=db_path,
    )
    assert result["ok"] is True
    assert captured["mode"] == "poll"


def test_cancel_prompt_cancels_waiting_prompt(tmp_path) -> None:
    db_path = str(tmp_path / "telegram_inbox.db")
    server.register_pending_prompt(
        session_id="session-cancel", prompt_id="prompt-cancel", prompt_text="Question",
        send_notification=False, ensure_listener=False, db_path=db_path,
    )
    result = server.tool_cancel_prompt(session_id="session-cancel", prompt_id="prompt-cancel", db_path=db_path)
    assert result["ok"] is True
    assert result["current_status"] == "cancelled"


def test_get_recent_messages_returns_empty_list(tmp_path) -> None:
    db_path = str(tmp_path / "telegram_inbox.db")
    from telegram_mcp_notify.inbox import initialize_inbox_db
    initialize_inbox_db(db_path)
    result = server.tool_get_recent_messages(limit=5, db_path=db_path)
    assert result["ok"] is True
    assert result["count"] == 0
    assert result["messages"] == []


def test_run_server_with_singleton_invokes_server_and_releases_lease(monkeypatch) -> None:
    lease = SimpleNamespace(preempted_pids=(), released=False)
    called: dict[str, object] = {}
    fake_server = SimpleNamespace(run=lambda transport: called.setdefault("transport", transport))

    monkeypatch.setattr(server, "_acquire_server_singleton", lambda: lease)
    monkeypatch.setattr(server, "SERVER", fake_server)
    monkeypatch.setattr(server, "release_singleton", lambda _lease: called.setdefault("released", True))
    monkeypatch.setattr(server, "_stderr", lambda _message: None)

    assert server._run_server_with_singleton() == 0
    assert called["transport"] == "stdio"
    assert called["released"] is True


def test_repair_telegram_listener_restart_returns_after_snapshot(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "telegram_inbox.db"
    monkeypatch.setattr(server, "initialize_inbox_db", lambda _db_path=None: db_path)
    monkeypatch.setattr(server, "resolve_inbox_db_path", lambda value: Path(value))
    monkeypatch.setattr(
        server, "_listener_health_payload",
        lambda _db_path, **_kwargs: {
            "ok": True, "running": False, "state_status": "stopped",
            "startup_confirmed": False, "lock_status": "stale", "health_reason": "stale_lock",
        },
    )
    monkeypatch.setattr(
        server, "_apply_balanced_self_heal",
        lambda **_kwargs: (["removed_stale_lock", "reset_runtime_state"], []),
    )
    monkeypatch.setattr(
        server, "_ensure_listener_running",
        lambda *_args, **_kwargs: {
            "ok": True, "running": True, "started": True, "startup_confirmed": True, "attempts": 1,
            "diagnostics": {"running": True, "state_status": "running", "startup_confirmed": True, "health_reason": "healthy"},
        },
    )

    result = server.repair_telegram_listener(db_path=str(db_path), restart=True, reason="test")
    assert result["ok"] is True
    assert "removed_stale_lock" in result["actions_taken"]
    assert "restart_attempted" in result["actions_taken"]


def test_wait_pending_prompt_resolves_after_retry(monkeypatch) -> None:
    responses = iter(
        (
            {"ok": True, "status": "waiting", "prompt_id": "p1"},
            {"ok": True, "status": "resolved", "prompt_id": "p1", "response_text": "ok"},
        )
    )
    calls: list[tuple[str, str, bool, str | None]] = []

    def _fake_check(session_id: str, prompt_id: str, consume: bool = False, db_path: str | None = None):
        calls.append((session_id, prompt_id, consume, db_path))
        return dict(next(responses))

    monkeypatch.setattr(server, "check_pending_prompt", _fake_check)
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)

    result = server.wait_pending_prompt(
        session_id="session-wait",
        prompt_id="p1",
        timeout_seconds=5,
        poll_interval_seconds=0.1,
        consume=True,
        db_path=None,
    )
    assert result["ok"] is True
    assert result["timed_out"] is False
    assert result["status"] == "resolved"
    assert result["poll_count"] == 2
    assert all(call[2] is True for call in calls)


def test_wait_pending_prompt_times_out(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "check_pending_prompt",
        lambda **_kwargs: {"ok": True, "status": "waiting", "prompt_id": "p-timeout"},
    )

    result = server.wait_pending_prompt(
        session_id="session-timeout",
        prompt_id="p-timeout",
        timeout_seconds=0,
        poll_interval_seconds=0.1,
        consume=True,
    )
    assert result["ok"] is True
    assert result["status"] == "waiting"
    assert result["timed_out"] is True
    assert result["poll_count"] == 1


def test_wait_pending_prompt_default_timeout_is_five_minutes() -> None:
    signature = inspect.signature(server.wait_pending_prompt)
    assert signature.parameters["timeout_seconds"].default == 300.0


def test_parse_iso_handles_unexpected_parser_exception(monkeypatch) -> None:
    class _BrokenDateTime:
        @staticmethod
        def fromisoformat(_text: str):
            raise RuntimeError("parser-crash")

    monkeypatch.setattr(server, "datetime", _BrokenDateTime)
    assert server._parse_iso("2026-03-03T10:00:00+08:00") is None


def test_telegram_notify_capabilities_includes_new_tools() -> None:
    result = server.telegram_notify_capabilities()
    assert result["ok"] is True
    assert "wait_pending_prompt" in result["tools"]
    assert "stop_telegram_listener" in result["tools"]
    assert "restart_telegram_listener" in result["tools"]
    assert "telegram_notify_capabilities" in result["tools"]
    assert result["tool_count"] == len(result["tools"])
    assert result["supports"]["sync_wait_for_prompt"] is True


def test_stop_telegram_listener_uses_runtime_stop(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "telegram_inbox.db"
    monkeypatch.setattr(server, "initialize_inbox_db", lambda _db_path=None: db_path)
    monkeypatch.setattr(server, "resolve_inbox_db_path", lambda value: Path(value))
    monkeypatch.setattr(
        server,
        "_stop_listener_runtime",
        lambda **_kwargs: {
            "ok": True,
            "actions_taken": ["terminated_pid:100:pid_only", "reset_runtime_state"],
            "errors": [],
            "diagnostics": {"health_reason": "stopped"},
        },
    )

    result = server.stop_telegram_listener(db_path=str(db_path), force=False, reason="test-stop")
    assert result["ok"] is True
    assert "reset_runtime_state" in result["actions_taken"]


def test_restart_telegram_listener_runs_stop_then_start(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "telegram_inbox.db"
    monkeypatch.setattr(server, "initialize_inbox_db", lambda _db_path=None: db_path)
    monkeypatch.setattr(server, "resolve_inbox_db_path", lambda value: Path(value))
    monkeypatch.setattr(
        server,
        "_stop_listener_runtime",
        lambda **_kwargs: {"ok": True, "actions_taken": ["reset_runtime_state"], "errors": [], "diagnostics": {}},
    )
    monkeypatch.setattr(server, "update_listener_state", lambda **_kwargs: {})
    monkeypatch.setattr(
        server,
        "_ensure_listener_running",
        lambda *_args, **_kwargs: {
            "ok": True,
            "running": True,
            "started": True,
            "startup_confirmed": True,
            "attempts": 1,
            "diagnostics": {"health_reason": "healthy"},
        },
    )

    result = server.restart_telegram_listener(db_path=str(db_path), reason="test-restart")
    assert result["ok"] is True
    assert result["start"]["ok"] is True


def test_ensure_listener_running_respects_backoff_in_v2(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "telegram_inbox.db"
    monkeypatch.setattr(server, "_is_lifecycle_v2_enabled", lambda: True)
    monkeypatch.setattr(server, "_listener_mode", lambda: "daemon")
    monkeypatch.setattr(server, "_listener_autorestart_enabled", lambda: True)
    monkeypatch.setattr(server, "_is_start_backoff_active", lambda _state: (True, 3.0))
    monkeypatch.setattr(server, "_listener_health_payload", lambda *_args, **_kwargs: {"ok": True, "running": False, "startup_confirmed": False, "health_reason": "stale_pid"})
    monkeypatch.setattr(server, "initialize_inbox_db", lambda _db_path=None: db_path)
    monkeypatch.setattr(server, "resolve_inbox_db_path", lambda value: Path(value))
    monkeypatch.setattr(server, "get_listener_state", lambda _db_path: {"consecutive_start_failures": 1, "last_start_attempt_utc": "2026-03-03T00:00:00+00:00"})

    result = server._ensure_listener_running(db_path=str(db_path), self_heal=True)
    assert result["ok"] is False
    assert result["attempts"] == 0
    assert result["diagnostics"]["health_reason"] == "start_backoff_active"

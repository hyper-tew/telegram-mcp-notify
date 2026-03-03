from __future__ import annotations

import os

import pytest

from telegram_mcp_notify import singleton


def test_acquire_and_release_singleton_when_lock_is_free(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TELEGRAM_SINGLETON_LOCK_DIR", str(tmp_path))
    lease = singleton.acquire_singleton_or_preempt(
        lock_name="singleton_free_case",
        owner_label="test-owner",
        retries=0,
        retry_delay_s=0.0,
    )
    try:
        assert lease.lock_name == "singleton_free_case"
        assert lease.acquired_pid == os.getpid()
        assert lease.preempted_pids == ()
        assert lease.lock_path.exists()
    finally:
        singleton.release_singleton(lease)
    assert lease.released is True


def test_acquire_retries_when_owner_pid_is_dead(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TELEGRAM_SINGLETON_LOCK_DIR", str(tmp_path))
    attempts = iter([False, True])

    monkeypatch.setattr(singleton, "_try_acquire_file_lock", lambda _handle: next(attempts))
    monkeypatch.setattr(singleton, "_read_owner_pid", lambda _path: 4242)
    monkeypatch.setattr(singleton, "_is_process_alive", lambda _pid: False)
    monkeypatch.setattr(singleton.time, "sleep", lambda _delay: None)

    lease = singleton.acquire_singleton_or_preempt(
        lock_name="singleton_dead_owner_case",
        owner_label="test-owner",
        retries=2,
        retry_delay_s=0.0,
    )
    try:
        assert lease.preempted_pids == ()
    finally:
        singleton.release_singleton(lease)


def test_acquire_preempts_alive_owner_and_succeeds(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TELEGRAM_SINGLETON_LOCK_DIR", str(tmp_path))
    attempts = iter([False, True])
    terminated: list[int] = []

    monkeypatch.setattr(singleton, "_try_acquire_file_lock", lambda _handle: next(attempts))
    monkeypatch.setattr(singleton, "_read_owner_pid", lambda _path: 5151)
    monkeypatch.setattr(singleton, "_is_process_alive", lambda _pid: True)
    monkeypatch.setattr(
        singleton, "_terminate_pid", lambda pid, wait_seconds=1.5: terminated.append(pid) or True
    )
    monkeypatch.setattr(singleton.time, "sleep", lambda _delay: None)

    lease = singleton.acquire_singleton_or_preempt(
        lock_name="singleton_preempt_case",
        owner_label="test-owner",
        retries=3,
        retry_delay_s=0.0,
    )
    try:
        assert lease.preempted_pids == (5151,)
        assert terminated == [5151]
    finally:
        singleton.release_singleton(lease)


def test_acquire_raises_with_deterministic_payload_after_retries(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TELEGRAM_SINGLETON_LOCK_DIR", str(tmp_path))
    monkeypatch.setattr(singleton, "_try_acquire_file_lock", lambda _handle: False)
    monkeypatch.setattr(singleton, "_read_owner_pid", lambda _path: None)
    monkeypatch.setattr(singleton.time, "sleep", lambda _delay: None)

    with pytest.raises(singleton.SingletonAcquireError) as exc_info:
        singleton.acquire_singleton_or_preempt(
            lock_name="singleton_retry_exhausted_case",
            owner_label="test-owner",
            retries=2,
            retry_delay_s=0.0,
        )

    payload = exc_info.value.payload
    assert payload["lock_name"] == "singleton_retry_exhausted_case"
    assert payload["attempts"] == 3
    assert payload["retries"] == 2
    assert payload["last_owner_pid"] is None


def test_is_process_alive_returns_false_on_unexpected_os_exception(monkeypatch) -> None:
    monkeypatch.setattr(singleton.os, "kill", lambda _pid, _sig: (_ for _ in ()).throw(RuntimeError("boom")))
    assert singleton.is_process_alive(12345) is False


def test_inspect_lock_stale_and_remove(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TELEGRAM_SINGLETON_LOCK_DIR", str(tmp_path))
    lock_name = "singleton_inspect_case"
    lock_path = singleton.resolve_lock_path(lock_name)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text('{"pid": 987654}\n', encoding="utf-8")
    monkeypatch.setattr(singleton, "_is_process_alive", lambda _pid: False)

    info = singleton.inspect_lock(lock_name)
    assert info["status"] == "stale"
    assert info["owner_pid"] == 987654

    removed = singleton.remove_lock_file(lock_name)
    assert removed is True
    assert lock_path.exists() is False

"""File-based singleton process lock with preemption support."""

from __future__ import annotations

import atexit
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import threading
import time
from typing import Any, TextIO

try:
    import fcntl  # type: ignore[attr-defined]
except ImportError:
    fcntl = None

try:
    import msvcrt  # type: ignore[attr-defined]
except ImportError:
    msvcrt = None

_DATA_HOME = Path.home() / ".telegram-mcp-notify"
_DEFAULT_LOCK_ROOT = _DATA_HOME / "locks"
_LOCK_ROOT_ENV_KEY = "TELEGRAM_SINGLETON_LOCK_DIR"
_LOCK_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

_ACTIVE_LEASES: list["SingletonLease"] = []
_ACTIVE_LEASES_LOCK = threading.Lock()
_CLEANUP_HOOKS_READY = False


class SingletonAcquireError(RuntimeError):
    """Raised when a singleton lease cannot be acquired after retries."""

    def __init__(self, message: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.payload: dict[str, Any] = payload or {}


@dataclass(slots=True)
class SingletonLease:
    """Represents a held singleton lock lease."""

    lock_name: str
    owner_label: str
    lock_path: Path
    handle: TextIO = field(repr=False)
    acquired_pid: int
    acquired_at_utc: str
    preempted_pids: tuple[int, ...] = ()
    released: bool = False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_lock_name(lock_name: str) -> str:
    value = str(lock_name or "").strip()
    if not value:
        raise ValueError("lock_name is required.")
    if not _LOCK_NAME_RE.fullmatch(value):
        raise ValueError(f"Invalid lock_name: {lock_name!r}")
    return value


def _resolve_lock_root() -> Path:
    candidate = str(os.getenv(_LOCK_ROOT_ENV_KEY) or "").strip()
    if candidate:
        return Path(candidate)
    return _DEFAULT_LOCK_ROOT


def _resolve_lock_path(lock_name: str) -> Path:
    root = _resolve_lock_root()
    return root / f"{lock_name}.lock"


def _open_lock_file(lock_path: Path) -> TextIO:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write("\n")
        handle.flush()
    handle.seek(0)
    return handle


def _try_acquire_file_lock(handle: TextIO) -> bool:
    if os.name == "nt":
        if msvcrt is None:
            raise RuntimeError("msvcrt is unavailable on this platform.")
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    if fcntl is None:
        raise RuntimeError("fcntl is unavailable on this platform.")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    except OSError:
        return False


def _unlock_file_lock(handle: TextIO) -> None:
    if os.name == "nt":
        if msvcrt is None:
            return
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            return
        return

    if fcntl is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        return


def _safe_close(handle: TextIO | None) -> None:
    if handle is None:
        return
    try:
        handle.close()
    except Exception:
        return


def _parse_pid(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.isdigit():
            parsed = int(candidate)
            if parsed > 0:
                return parsed
    return None


def _extract_owner_pid_from_text(raw: str) -> int | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        pid = _parse_pid(payload.get("pid"))
        if pid is not None:
            return pid

    matches = re.findall(r'"pid"\s*:\s*"?(?P<pid>\d+)"?', text)
    if matches:
        return _parse_pid(matches[0])
    return None


def _read_owner_pid(lock_path: Path) -> int | None:
    try:
        content = lock_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    return _extract_owner_pid_from_text(content)


def _is_process_alive(pid: int | None) -> bool:
    parsed_pid = _parse_pid(pid)
    if parsed_pid is None:
        return False
    try:
        os.kill(parsed_pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    except Exception:
        return False


def _terminate_signals() -> list[int]:
    signals = [signal.SIGTERM]
    sigkill = getattr(signal, "SIGKILL", None)
    if isinstance(sigkill, int) and sigkill != signal.SIGTERM:
        signals.append(sigkill)
    return signals


def _terminate_pid(pid: int, *, wait_seconds: float = 1.5) -> bool:
    target_pid = int(pid)
    if target_pid <= 0 or target_pid == os.getpid():
        return False

    for sig in _terminate_signals():
        try:
            os.kill(target_pid, sig)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        except OSError:
            continue

        deadline = time.monotonic() + max(0.1, float(wait_seconds))
        while time.monotonic() < deadline:
            if not _is_process_alive(target_pid):
                return True
            time.sleep(0.05)

    return not _is_process_alive(target_pid)


def _write_owner_metadata(lock_name: str, owner_label: str, handle: TextIO) -> str:
    acquired_at_utc = _utc_now_iso()
    payload = {
        "lock_name": lock_name,
        "owner_label": owner_label,
        "pid": int(os.getpid()),
        "acquired_at_utc": acquired_at_utc,
    }
    handle.seek(0)
    handle.truncate(0)
    json.dump(payload, handle, ensure_ascii=True, sort_keys=True)
    handle.write("\n")
    handle.flush()
    try:
        os.fsync(handle.fileno())
    except OSError:
        pass
    return acquired_at_utc


def _register_lease(lease: SingletonLease) -> None:
    _ensure_cleanup_hooks()
    with _ACTIVE_LEASES_LOCK:
        _ACTIVE_LEASES.append(lease)


def _unregister_lease(lease: SingletonLease) -> None:
    with _ACTIVE_LEASES_LOCK:
        if lease in _ACTIVE_LEASES:
            _ACTIVE_LEASES.remove(lease)


def _release_all_leases() -> None:
    with _ACTIVE_LEASES_LOCK:
        leases = list(_ACTIVE_LEASES)
    for lease in leases:
        release_singleton(lease)


def _handle_exit_signal(signum: int, frame: Any) -> None:
    _release_all_leases()
    raise SystemExit(128 + int(signum))


def _ensure_cleanup_hooks() -> None:
    global _CLEANUP_HOOKS_READY
    if _CLEANUP_HOOKS_READY:
        return

    atexit.register(_release_all_leases)
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if not isinstance(sig, int):
            continue
        try:
            current = signal.getsignal(sig)
        except Exception:
            continue
        if current is signal.SIG_DFL:
            try:
                signal.signal(sig, _handle_exit_signal)
            except Exception:
                continue
    _CLEANUP_HOOKS_READY = True


def acquire_singleton_or_preempt(
    lock_name: str,
    owner_label: str,
    retries: int,
    retry_delay_s: float,
) -> SingletonLease:
    """Acquire a file-based singleton lock, preempting stale owners."""
    normalized_lock_name = _normalize_lock_name(lock_name)
    normalized_owner_label = str(owner_label or "").strip() or normalized_lock_name
    max_retries = max(0, int(retries))
    retry_delay_seconds = max(0.0, float(retry_delay_s))
    lock_path = _resolve_lock_path(normalized_lock_name)
    preempted: list[int] = []

    for attempt in range(max_retries + 1):
        try:
            handle = _open_lock_file(lock_path)
        except OSError as exc:
            raise SingletonAcquireError(
                f"Failed to open singleton lock file: {lock_path}",
                payload={
                    "lock_name": normalized_lock_name,
                    "owner_label": normalized_owner_label,
                    "lock_path": str(lock_path),
                    "attempts": attempt + 1,
                    "retries": max_retries,
                    "retry_delay_seconds": retry_delay_seconds,
                    "error": str(exc),
                },
            ) from exc

        if _try_acquire_file_lock(handle):
            acquired_at = _write_owner_metadata(normalized_lock_name, normalized_owner_label, handle)
            lease = SingletonLease(
                lock_name=normalized_lock_name,
                owner_label=normalized_owner_label,
                lock_path=lock_path,
                handle=handle,
                acquired_pid=int(os.getpid()),
                acquired_at_utc=acquired_at,
                preempted_pids=tuple(preempted),
            )
            _register_lease(lease)
            return lease

        _safe_close(handle)
        owner_pid = _read_owner_pid(lock_path)
        if owner_pid is not None and owner_pid != os.getpid() and _is_process_alive(owner_pid):
            terminated = _terminate_pid(owner_pid)
            if terminated and owner_pid not in preempted:
                preempted.append(owner_pid)
        if attempt < max_retries:
            time.sleep(retry_delay_seconds)

    last_owner_pid = _read_owner_pid(lock_path)
    payload = {
        "lock_name": normalized_lock_name,
        "owner_label": normalized_owner_label,
        "lock_path": str(lock_path),
        "attempts": max_retries + 1,
        "retries": max_retries,
        "retry_delay_seconds": retry_delay_seconds,
        "last_owner_pid": last_owner_pid,
        "preempted_pids": list(preempted),
    }
    raise SingletonAcquireError(
        f"Unable to acquire singleton lock '{normalized_lock_name}' after {max_retries + 1} attempt(s).",
        payload=payload,
    )


def release_singleton(lease: SingletonLease) -> None:
    """Release a held singleton lock."""
    if lease.released:
        return
    try:
        _unlock_file_lock(lease.handle)
    finally:
        _safe_close(lease.handle)
        lease.released = True
        _unregister_lease(lease)


def resolve_lock_path(lock_name: str) -> Path:
    """Return the file path for a named lock."""
    return _resolve_lock_path(_normalize_lock_name(lock_name))


def inspect_lock(lock_name: str) -> dict[str, Any]:
    """Inspect a lock file and return its status."""
    normalized_lock_name = _normalize_lock_name(lock_name)
    lock_path = _resolve_lock_path(normalized_lock_name)
    exists = lock_path.exists()
    owner_pid: int | None = None
    read_error: str | None = None
    if exists:
        try:
            owner_pid = _read_owner_pid(lock_path)
        except Exception as exc:
            read_error = str(exc)
            owner_pid = None
    owner_alive = _is_process_alive(owner_pid) if owner_pid is not None else False
    if not exists:
        status = "free"
    elif owner_pid is not None and owner_alive:
        status = "held"
    elif read_error:
        status = "unknown"
    else:
        status = "stale"
    return {
        "lock_name": normalized_lock_name,
        "lock_path": str(lock_path),
        "exists": exists,
        "owner_pid": owner_pid,
        "owner_alive": owner_alive,
        "status": status,
        "read_error": read_error,
    }


def remove_lock_file(lock_name: str) -> bool:
    """Remove a lock file if it exists."""
    lock_path = resolve_lock_path(lock_name)
    if not lock_path.exists():
        return False
    lock_path.unlink()
    return True


def is_process_alive(pid: int | None) -> bool:
    """Check whether a process is alive by PID."""
    return _is_process_alive(pid)


def terminate_pid(pid: int, *, wait_seconds: float = 1.5) -> bool:
    """Terminate a process by PID."""
    return _terminate_pid(pid, wait_seconds=wait_seconds)


__all__ = [
    "SingletonAcquireError",
    "SingletonLease",
    "acquire_singleton_or_preempt",
    "inspect_lock",
    "is_process_alive",
    "remove_lock_file",
    "resolve_lock_path",
    "release_singleton",
    "terminate_pid",
]

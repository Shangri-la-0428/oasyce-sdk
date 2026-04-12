"""Cross-platform background daemon management.

Starts/stops the agent as a detached process. Works on macOS, Linux, Windows
with zero platform-specific dependencies — just subprocess.Popen flags.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from typing import Optional, Tuple

OASYCE_DIR = os.path.join(os.path.expanduser("~"), ".oasyce")
PID_FILE = os.path.join(OASYCE_DIR, "agent.pid")
LOG_FILE = os.path.join(OASYCE_DIR, "agent.log")
STARTING_STATE = "starting"
RUNNING_STATE = "running"
STARTING_STALE_SECONDS = 10.0
STOP_WAIT_SECONDS = 5.0


def _ensure_dir():
    os.makedirs(OASYCE_DIR, exist_ok=True)


def _pidfile_payload(pid: int, *, state: str) -> dict[str, object]:
    return {
        "pid": pid,
        "state": state,
        "written_at": time.time(),
    }


def _read_pid_payload() -> dict[str, object] | None:
    if not os.path.exists(PID_FILE):
        return None
    try:
        raw = open(PID_FILE).read().strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        try:
            return {"pid": int(raw), "state": RUNNING_STATE}
        except ValueError:
            return None
    if not isinstance(data, dict):
        return None
    return data


def _atomic_write_pidfile(payload: dict[str, object]) -> None:
    _ensure_dir()
    fd, tmp_name = tempfile.mkstemp(prefix=".agent.pid.", dir=OASYCE_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp_name, PID_FILE)
    except Exception:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


def _pid_looks_like_agent(pid: int) -> bool:
    if not _is_alive(pid):
        return False
    if sys.platform == "win32":
        return True
    try:
        proc = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except Exception:
        return True
    command = (proc.stdout or "").strip()
    if not command:
        return True
    return "oasyce_sdk.agent" in command


def _read_pid() -> Optional[int]:
    """Read PID from file, return None if missing or stale."""
    payload = _read_pid_payload()
    if payload is None:
        return None
    try:
        pid = int(payload.get("pid", 0))
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        _cleanup_pid()
        return None
    state = str(payload.get("state") or RUNNING_STATE)
    if state == STARTING_STATE:
        written_at = float(payload.get("written_at", 0) or 0)
        if written_at and (time.time() - written_at) <= STARTING_STALE_SECONDS:
            return None
        _cleanup_pid()
        return None
    if not _pid_looks_like_agent(pid):
        _cleanup_pid()
        return None
    return pid


def _is_alive(pid: int) -> bool:
    """Check if process is still running."""
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _cleanup_pid():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def _claim_start_slot() -> Optional[str]:
    _ensure_dir()
    for _ in range(2):
        try:
            fd = os.open(PID_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            payload = _read_pid_payload()
            if payload is None:
                _cleanup_pid()
                continue
            state = str(payload.get("state") or RUNNING_STATE)
            try:
                pid = int(payload.get("pid", 0))
            except (TypeError, ValueError):
                pid = 0
            if state == STARTING_STATE:
                written_at = float(payload.get("written_at", 0) or 0)
                if written_at and (time.time() - written_at) <= STARTING_STALE_SECONDS:
                    return "Agent is already starting"
                _cleanup_pid()
                continue
            if pid > 0 and _pid_looks_like_agent(pid):
                return f"Agent already running (PID {pid})"
            _cleanup_pid()
            continue
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(_pidfile_payload(0, state=STARTING_STATE), handle)
            return None
    return "Agent is already starting"


def start() -> Tuple[bool, str]:
    """Start agent daemon. Returns (success, message)."""
    claim_error = _claim_start_slot()
    if claim_error:
        return False, claim_error

    log_handle = open(LOG_FILE, "a")

    # Launch self in 'run' mode, detached from terminal
    cmd = [sys.executable, "-m", "oasyce_sdk.agent", "run"]

    kwargs = dict(
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )

    if sys.platform == "win32":
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)

    # Brief wait to confirm it didn't die immediately
    time.sleep(0.5)
    if proc.poll() is not None:
        _cleanup_pid()
        return False, f"Agent exited immediately. Check {LOG_FILE}"

    _atomic_write_pidfile(_pidfile_payload(proc.pid, state=RUNNING_STATE))

    return True, f"Agent started (PID {proc.pid}). Logs: {LOG_FILE}"


def stop() -> Tuple[bool, str]:
    """Stop agent daemon. Returns (success, message)."""
    pid = _read_pid()
    if not pid:
        return False, "Agent is not running"

    if sys.platform == "win32":
        import ctypes
        PROCESS_TERMINATE = 0x0001
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if handle:
            kernel32.TerminateProcess(handle, 0)
            kernel32.CloseHandle(handle)
    else:
        os.kill(pid, signal.SIGTERM)

    # Wait for exit
    deadline = time.time() + STOP_WAIT_SECONDS
    while time.time() < deadline:
        time.sleep(0.25)
        if not _is_alive(pid):
            current = _read_pid_payload()
            if current is None or int(current.get("pid", 0) or 0) == pid:
                _cleanup_pid()
            return True, f"Agent stopped (was PID {pid})"
        if not _pid_looks_like_agent(pid):
            break

    return False, f"Agent did not stop after {STOP_WAIT_SECONDS:.0f}s (PID {pid})"


def status() -> Tuple[bool, str]:
    """Check agent status. Returns (running, message)."""
    pid = _read_pid()
    if not pid:
        return False, "Agent is not running"

    # Read last few lines of log for context
    info = f"Agent running (PID {pid})"
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE) as f:
                lines = f.readlines()
                last = [l.rstrip() for l in lines[-5:] if l.strip()]
                if last:
                    info += "\n\nRecent log:\n" + "\n".join(last)
        except OSError:
            pass

    return True, info

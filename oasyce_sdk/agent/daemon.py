"""Cross-platform background daemon management.

Starts/stops the agent as a detached process. Works on macOS, Linux, Windows
with zero platform-specific dependencies — just subprocess.Popen flags.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Optional, Tuple

OASYCE_DIR = os.path.join(os.path.expanduser("~"), ".oasyce")
PID_FILE = os.path.join(OASYCE_DIR, "agent.pid")
LOG_FILE = os.path.join(OASYCE_DIR, "agent.log")


def _ensure_dir():
    os.makedirs(OASYCE_DIR, exist_ok=True)


def _read_pid() -> Optional[int]:
    """Read PID from file, return None if missing or stale."""
    if not os.path.exists(PID_FILE):
        return None
    try:
        pid = int(open(PID_FILE).read().strip())
    except (ValueError, OSError):
        return None
    if not _is_alive(pid):
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


def start() -> Tuple[bool, str]:
    """Start agent daemon. Returns (success, message)."""
    existing = _read_pid()
    if existing:
        return False, f"Agent already running (PID {existing})"

    _ensure_dir()
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

    # Write PID
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))

    # Brief wait to confirm it didn't die immediately
    time.sleep(0.5)
    if proc.poll() is not None:
        _cleanup_pid()
        return False, f"Agent exited immediately. Check {LOG_FILE}"

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
    for _ in range(20):
        time.sleep(0.25)
        if not _is_alive(pid):
            break

    _cleanup_pid()
    return True, f"Agent stopped (was PID {pid})"


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

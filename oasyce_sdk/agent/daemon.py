"""Cross-platform background daemon management.

Starts/stops the agent as a detached process. Works on macOS, Linux, Windows
with zero platform-specific dependencies — just subprocess.Popen flags.
"""

from __future__ import annotations

import json
import os
import shlex
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


def _read_pid_file() -> Optional[int]:
    """Read the cached PID file without treating it as truth."""
    if not os.path.exists(PID_FILE):
        return None
    try:
        return int(open(PID_FILE).read().strip())
    except (ValueError, OSError):
        return None


def _write_pid(pid: int) -> None:
    _ensure_dir()
    with open(PID_FILE, "w") as f:
        f.write(str(pid))


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


def _looks_like_agent_run(command: str) -> bool:
    try:
        tokens = shlex.split(command, posix=sys.platform != "win32")
    except ValueError:
        tokens = command.split()
    lowered = [token.lower() for token in tokens]
    for idx in range(len(lowered) - 2):
        if (
            lowered[idx] == "-m"
            and lowered[idx + 1] == "oasyce_sdk.agent"
            and lowered[idx + 2] == "run"
        ):
            return True
    if len(lowered) >= 2:
        executable = os.path.basename(lowered[0])
        if executable in {"oasyce-agent", "oasyce-agent.exe"} and lowered[1] == "run":
            return True
    return False


def _discover_agent_processes() -> list[tuple[int, str]]:
    if sys.platform == "win32":
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process | "
                "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
            ),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return []
        rows = payload if isinstance(payload, list) else [payload]
        discovered = []
        for row in rows:
            pid = row.get("ProcessId")
            command = row.get("CommandLine") or ""
            if not isinstance(pid, int) or pid == os.getpid():
                continue
            if _looks_like_agent_run(command):
                discovered.append((pid, command))
        return sorted(discovered)

    proc = subprocess.run(
        ["ps", "-ax", "-o", "pid=", "-o", "args="],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []

    discovered = []
    for line in proc.stdout.splitlines():
        row = line.strip()
        if not row:
            continue
        pid_text, _, command = row.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        command = command.strip()
        if _looks_like_agent_run(command):
            discovered.append((pid, command))
    return sorted(discovered)


def _discover_agent_pids() -> list[int]:
    return [pid for pid, _command in _discover_agent_processes() if _is_alive(pid)]


def _reconcile_agent_pids() -> list[int]:
    live_pids = sorted(dict.fromkeys(_discover_agent_pids()))
    if not live_pids:
        _cleanup_pid()
        return []

    cached = _read_pid_file()
    canonical = cached if cached in live_pids else live_pids[0]
    if cached is None or cached != canonical or len(live_pids) > 1:
        _write_pid(canonical)

    return [canonical, *[pid for pid in live_pids if pid != canonical]]


def _terminate_pid(pid: int, *, force: bool = False) -> None:
    if sys.platform == "win32":
        import ctypes

        PROCESS_TERMINATE = 0x0001
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if handle:
            kernel32.TerminateProcess(handle, 1 if force else 0)
            kernel32.CloseHandle(handle)
        return

    os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)


def _stop_pids(pids: list[int]) -> list[int]:
    for pid in pids:
        try:
            _terminate_pid(pid)
        except OSError:
            continue

    deadline = time.time() + 5
    while time.time() < deadline:
        remaining = [pid for pid in pids if _is_alive(pid)]
        if not remaining:
            return []
        time.sleep(0.25)

    remaining = [pid for pid in pids if _is_alive(pid)]
    for pid in remaining:
        try:
            _terminate_pid(pid, force=True)
        except OSError:
            continue

    deadline = time.time() + 2
    while time.time() < deadline:
        survivors = [pid for pid in remaining if _is_alive(pid)]
        if not survivors:
            return []
        time.sleep(0.25)

    return [pid for pid in remaining if _is_alive(pid)]


def _read_pid() -> Optional[int]:
    """Return the canonical live agent PID, if any."""
    pids = _reconcile_agent_pids()
    return pids[0] if pids else None


def start() -> Tuple[bool, str]:
    """Start agent daemon. Returns (success, message)."""
    existing = _reconcile_agent_pids()
    if existing:
        duplicates = existing[1:]
        if duplicates:
            remaining = _stop_pids(duplicates)
            if remaining:
                return False, (
                    f"Agent already running (PID {existing[0]}), but duplicate runtimes "
                    f"would not stop: {', '.join(str(pid) for pid in remaining)}"
                )
        _write_pid(existing[0])
        if duplicates:
            return True, (
                f"Agent already running (PID {existing[0]}). "
                f"Stopped duplicate runtimes: {', '.join(str(pid) for pid in duplicates)}"
            )
        return True, f"Agent already running (PID {existing[0]})"

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

    _write_pid(proc.pid)

    # Brief wait to confirm it didn't die immediately
    time.sleep(0.5)
    if proc.poll() is not None:
        _cleanup_pid()
        return False, f"Agent exited immediately. Check {LOG_FILE}"

    return True, f"Agent started (PID {proc.pid}). Logs: {LOG_FILE}"


def stop() -> Tuple[bool, str]:
    """Stop agent daemon. Returns (success, message)."""
    pids = _reconcile_agent_pids()
    if not pids:
        return False, "Agent is not running"

    remaining = _stop_pids(pids)
    _cleanup_pid()
    stopped = ", ".join(str(pid) for pid in pids)
    if remaining:
        survivors = ", ".join(str(pid) for pid in remaining)
        return False, f"Agent stop incomplete. Remaining runtimes: {survivors}"
    if len(pids) == 1:
        return True, f"Agent stopped (was PID {pids[0]})"
    return True, f"Agent stopped ({len(pids)} runtimes: {stopped})"


def status() -> Tuple[bool, str]:
    """Check agent status. Returns (running, message)."""
    pids = _reconcile_agent_pids()
    if not pids:
        return False, "Agent is not running"

    # Read last few lines of log for context
    info = f"Agent running (PID {pids[0]})"
    if len(pids) > 1:
        info += f"\nDuplicate runtimes detected: {', '.join(str(pid) for pid in pids[1:])}"
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

"""Unified Oasyce front door.

This module exposes a thin user-facing shell over independently-usable
products. It does not replace Thronglets, Psyche, or the agent daemon; it
just gives normal users one obvious path:

    oasyce start
    oasyce share
    oasyce join <file>
    oasyce status
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from .agent import daemon
from .agent import cli as agent_cli
from .identity import IdentityResolver

DEFAULT_NODE_URL = "http://47.93.32.88:1317"
DEFAULT_CHAIN_ID = "oasyce-testnet-1"
DEFAULT_FAUCET_URL = "http://47.93.32.88:8080"
MIN_READY_BALANCE_UOAS = 1_000_000
THRONGLETS_IDENTITY_SCHEMA_V2 = "thronglets.identity.v2"


def _home_dir() -> Path:
    return Path.home()


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _allow_dev_runtime_fallback() -> bool:
    return os.environ.get("OASYCE_ALLOW_DEV_RUNTIME", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _thronglets_data_dir() -> Path:
    raw = os.environ.get("THRONGLETS_DATA_DIR")
    if raw:
        return Path(raw).expanduser()
    return _home_dir() / ".thronglets"


def _dev_psyche_cli_path() -> Path | None:
    candidate = _workspace_root() / "oasyce_psyche" / "dist" / "cli.js"
    return candidate if candidate.exists() else None


def _managed_thronglets_path() -> Path:
    return _thronglets_data_dir() / "bin" / "thronglets-managed"


def _dev_thronglets_bin_path() -> Path | None:
    candidate = _workspace_root() / "Thronglets" / "target" / "debug" / "thronglets"
    return candidate if candidate.exists() else None


def _available_thronglets_commands() -> list[list[str]]:
    commands: list[list[str]] = []
    managed = _managed_thronglets_path()
    if managed.exists() and os.access(managed, os.X_OK):
        commands.append([str(managed)])
    if shutil.which("thronglets"):
        commands.append(["thronglets"])
    if shutil.which("npx"):
        commands.append(["npx", "-y", "thronglets"])
    if _allow_dev_runtime_fallback():
        local_dev = _dev_thronglets_bin_path()
        if local_dev and os.access(local_dev, os.X_OK):
            commands.append([str(local_dev)])

    unique: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for command in commands:
        key = tuple(command)
        if key in seen:
            continue
        seen.add(key)
        unique.append(command)
    return unique


def _resolve_thronglets_base_command() -> list[str]:
    commands = _available_thronglets_commands()
    if commands:
        return commands[0]
    raise RuntimeError(
        "Thronglets is not available. Install `thronglets` or make `npx` available."
    )


def _managed_thronglets_command() -> list[str] | None:
    managed = _managed_thronglets_path()
    if managed.exists() and os.access(managed, os.X_OK):
        return [str(managed)]
    return None


def _thronglets_global_args() -> list[str]:
    data_dir = _thronglets_data_dir()
    default_dir = _home_dir() / ".thronglets"
    if data_dir == default_dir:
        return []
    return ["--data-dir", str(data_dir)]


def _thronglets_command(base: list[str], *args: str) -> list[str]:
    return [*base, *_thronglets_global_args(), *args]


def _resolve_psyche_base_command() -> list[str]:
    if shutil.which("psyche-ai"):
        return ["psyche-ai"]
    if shutil.which("npx"):
        return ["npx", "-y", "psyche-ai"]
    if _allow_dev_runtime_fallback():
        local_cli = _dev_psyche_cli_path()
        if local_cli and shutil.which("node"):
            return ["node", str(local_cli)]
    raise RuntimeError(
        "Psyche is not available. Install `psyche-ai` or make `npx` available."
    )


def _run_checked(cmd: list[str], *, capture_output: bool = False) -> str:
    proc = subprocess.run(
        cmd,
        capture_output=capture_output,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail_source = proc.stderr if proc.stderr is not None else proc.stdout or ""
        detail = detail_source.strip()
        raise RuntimeError(detail or f"{' '.join(cmd)} failed with code {proc.returncode}")
    return proc.stdout if capture_output else ""


def _run_json_command(cmd: list[str]) -> dict:
    output = _run_checked(cmd, capture_output=True).strip()
    if not output:
        raise RuntimeError(f"{' '.join(cmd)} returned no output")
    return json.loads(output)


def _thronglets_version_data(cmd: list[str]) -> dict:
    try:
        return _run_json_command(_thronglets_command(cmd, "version", "--json")).get("data", {})
    except Exception:
        return {}


def _thronglets_identity_schema_version(cmd: list[str]) -> str | None:
    data = _thronglets_version_data(cmd)
    summary = data.get("summary")
    if isinstance(summary, dict):
        value = summary.get("identity_schema_version")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _thronglets_supports_identity_v2(cmd: list[str]) -> bool:
    return _thronglets_identity_schema_version(cmd) == THRONGLETS_IDENTITY_SCHEMA_V2


def _thronglets_supports_surface(cmd: list[str], surface: str) -> bool:
    if surface == "thronglets":
        return True

    data = _thronglets_version_data(cmd)
    capabilities = data.get("capabilities")
    if isinstance(capabilities, dict):
        supported = capabilities.get("connection_export_surfaces")
        if isinstance(supported, list):
            return surface in supported

    try:
        help_text = _run_checked(
            _thronglets_command(cmd, "connection-export", "--help"),
            capture_output=True,
        )
    except Exception:
        return False
    if surface == "oasyce":
        return "--include-oasyce-surface" in help_text
    return False


def _refresh_managed_thronglets_surface(surface: str) -> bool:
    managed_cmd = _managed_thronglets_command()
    if managed_cmd and _thronglets_supports_surface(managed_cmd, surface):
        return True
    if managed_cmd is None:
        managed_cmd = [str(_managed_thronglets_path())]

    for candidate in _available_thronglets_commands():
        if candidate == managed_cmd:
            continue
        if not _thronglets_supports_surface(candidate, surface):
            continue
        try:
            _run_checked(_thronglets_command(candidate, "setup"))
        except Exception:
            continue
        refreshed = _managed_thronglets_command()
        if refreshed and _thronglets_supports_surface(refreshed, surface):
            return True
    return False


def _ensure_thronglets_surface(surface: str) -> list[str]:
    managed = _managed_thronglets_command()
    if managed and _thronglets_supports_surface(managed, surface):
        return managed

    if _refresh_managed_thronglets_surface(surface):
        refreshed = _managed_thronglets_command()
        if refreshed and _thronglets_supports_surface(refreshed, surface):
            return refreshed

    command = _resolve_thronglets_base_command()
    active_runtime = " ".join(command)
    if surface == "oasyce":
        raise RuntimeError(
            "The canonical Thronglets managed runtime does not support the richer Oasyce "
            "handoff surface yet. Refresh it with `thronglets setup` "
            f"and retry `oasyce share`.\nActive runtime: {active_runtime}"
        )
    raise RuntimeError(
        "The canonical Thronglets managed runtime is unavailable or incompatible. "
        f"Refresh it with `thronglets setup`.\nActive runtime: {active_runtime}"
    )


def _ensure_canonical_thronglets_runtime() -> list[str]:
    managed = _managed_thronglets_command()
    if managed and _thronglets_supports_identity_v2(managed):
        return managed

    for candidate in _available_thronglets_commands():
        if not _thronglets_supports_identity_v2(candidate):
            continue
        try:
            _run_checked(_thronglets_command(candidate, "setup"))
        except Exception:
            continue
        managed = _managed_thronglets_command()
        if managed and _thronglets_supports_identity_v2(managed):
            return managed

    command = _resolve_thronglets_base_command()
    raise RuntimeError(
        "The canonical Thronglets managed runtime is unavailable or too old for signed "
        "identity.v2 connection files. Initialize it with a current runtime "
        f"(`{' '.join(command)} setup`) and retry."
    )


def _default_share_path() -> Path:
    desktop = _home_dir() / "Desktop"
    if desktop.exists() and desktop.is_dir():
        return desktop / "oasyce-connection.json"
    return Path(daemon.OASYCE_DIR) / "oasyce-connection.json"


def _load_agent_config(config_path: str) -> dict:
    config_file = Path(config_path)
    if not config_file.exists():
        return {}
    return json.loads(config_file.read_text(encoding="utf-8"))


def _faucet_url() -> str:
    return os.environ.get("OASYCE_FAUCET", DEFAULT_FAUCET_URL)


def _ensure_chain_registration(client, signer, address: str) -> None:
    try:
        client.get_registration(address)
        return
    except Exception:
        pass

    from .client import OasyceClient

    pow_result = OasyceClient.solve_pow(address, difficulty=16)
    result = signer.self_register(pow_result.nonce)
    if result.success or "already registered" in result.raw_log.lower():
        return
    raise RuntimeError(
        "chain self-registration failed: "
        f"code={result.code} {result.raw_log or 'unknown error'}"
    )


def _request_faucet_tokens(address: str) -> str:
    query = urlencode({"address": address})
    with urlopen(f"{_faucet_url()}/faucet?{query}", timeout=15) as resp:
        return resp.read().decode("utf-8")


def _balance_uoas(balance) -> int:
    if hasattr(balance, "amount_uoas"):
        return int(balance.amount_uoas)
    if hasattr(balance, "amount"):
        return int(balance.amount)
    raise AttributeError("balance object has no amount_uoas/amount field")


def _ensure_spendable_balance(client, address: str) -> None:
    balance = client.get_balance(address)
    if _balance_uoas(balance) >= MIN_READY_BALANCE_UOAS:
        return

    _request_faucet_tokens(address)

    for _ in range(10):
        time.sleep(1)
        balance = client.get_balance(address)
        if _balance_uoas(balance) >= MIN_READY_BALANCE_UOAS:
            return

    raise RuntimeError(
        "faucet requested but signer balance is still below readiness threshold "
        f"({_balance_uoas(balance)} < {MIN_READY_BALANCE_UOAS})"
    )


def _ensure_chain_ready(config_path: str) -> dict:
    from .client import OasyceClient
    from .crypto.signer import NativeSigner
    from .delegate_policy import ensure_chain_identity

    config = _load_agent_config(config_path)
    node_url = config.get("node_url", DEFAULT_NODE_URL)
    chain_id = config.get("chain_id", DEFAULT_CHAIN_ID)

    client = OasyceClient(node_url)
    if not client.health():
        raise RuntimeError(f"chain node is unhealthy: {node_url}")

    identity = IdentityResolver.resolve_local()
    signer = NativeSigner(identity.wallet, client, chain_id=chain_id)

    _ensure_chain_registration(client, signer, identity.address)
    _ensure_spendable_balance(client, identity.address)
    identity = ensure_chain_identity(IdentityResolver.resolve_local(), client, chain_id)

    balance = client.get_balance(identity.address)
    return {
        "node_url": node_url,
        "chain_id": chain_id,
        "address": identity.address,
        "principal": identity.principal,
        "account": identity.account,
        "balance_uoas": _balance_uoas(balance),
        "balance_oas": _balance_uoas(balance) / 1_000_000,
    }


def _oasyce_mcp_configured_targets() -> list[str]:
    """Detect which AI tools have oasyce-mcp configured (read-only check)."""
    targets: list[str] = []

    codex = _home_dir() / ".codex" / "config.toml"
    if codex.exists():
        text = codex.read_text(encoding="utf-8")
        if "[mcp_servers.oasyce]" in text:
            targets.append("Codex")

    json_tools = [
        ("Cursor", _home_dir() / ".cursor" / "mcp.json"),
        ("Claude Code", _home_dir() / ".claude" / "settings.json"),
        ("Windsurf", _home_dir() / ".windsurf" / "mcp.json"),
    ]
    for name, path in json_tools:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        servers = data.get("mcpServers") or {}
        if isinstance(servers, dict) and "oasyce" in servers:
            targets.append(name)

    for claw_dir in [_home_dir() / ".openclaw", _home_dir() / ".config" / "openclaw"]:
        claw_cfg = claw_dir / "openclaw.json"
        if not claw_cfg.exists():
            continue
        try:
            data = json.loads(claw_cfg.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if "oasyce" in (data.get("mcpServers") or {}):
            targets.append("Claw")
            break

    return targets


def _psyche_configured_targets() -> list[str]:
    targets: list[str] = []
    codex = _home_dir() / ".codex" / "config.toml"
    if codex.exists():
        text = codex.read_text(encoding="utf-8")
        if "[mcp_servers.psyche]" in text and _codex_config_loadable():
            targets.append("Codex")

    json_targets = [
        ("Cursor", _home_dir() / ".cursor" / "mcp.json"),
        ("Claude Code", _home_dir() / ".claude" / "settings.json"),
        ("Windsurf", _home_dir() / ".windsurf" / "mcp.json"),
    ]
    for name, path in json_targets:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        servers = data.get("mcpServers") or {}
        if isinstance(servers, dict) and "psyche" in servers:
            targets.append(name)

    return targets


def _psyche_broken_targets() -> list[str]:
    targets: list[str] = []
    codex = _home_dir() / ".codex" / "config.toml"
    if codex.exists():
        text = codex.read_text(encoding="utf-8")
        if "[mcp_servers.psyche]" in text and not _codex_config_loadable():
            targets.append("Codex")
    return targets


def _codex_config_loadable() -> bool:
    if not shutil.which("codex"):
        return False
    proc = subprocess.run(
        ["codex", "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    return proc.returncode == 0


def _psyche_entry_mode() -> str:
    if shutil.which("psyche-ai"):
        return "installed"
    if shutil.which("npx"):
        return "npx"
    if _allow_dev_runtime_fallback() and _dev_psyche_cli_path() and shutil.which("node"):
        return "local_repo"
    return "missing"


def _collect_status() -> dict:
    try:
        identity = IdentityResolver.resolve_local()
        identity_data = identity.to_dict()
    except Exception as exc:
        identity_data = {"status": "missing", "error": str(exc)}

    agent_running, agent_message = daemon.status()

    try:
        base = _resolve_thronglets_base_command()
        thronglets = _run_json_command(_thronglets_command(base, "status", "--json"))
    except Exception as exc:
        thronglets = {"status": "unavailable", "error": str(exc)}
    try:
        active_runtime = " ".join(_thronglets_command(_resolve_thronglets_base_command()))
    except Exception:
        active_runtime = None

    psyche_targets = _psyche_configured_targets()
    psyche_broken_targets = _psyche_broken_targets()
    psyche = {
        "entry": _psyche_entry_mode(),
        "configured_targets": psyche_targets,
        "broken_targets": psyche_broken_targets,
        "configured": bool(psyche_targets),
    }

    return {
        "identity": identity_data,
        "agent": {
            "running": agent_running,
            "message": agent_message,
        },
        "thronglets": thronglets,
        "psyche": psyche,
        "paths": {
            "oasyce_dir": daemon.OASYCE_DIR,
            "agent_log": daemon.LOG_FILE,
            "thronglets_managed_runtime": str(_managed_thronglets_path()),
            "thronglets_active_runtime": active_runtime,
        },
    }


def _print_status_report(status: dict) -> None:
    identity = status["identity"]
    agent = status["agent"]
    thronglets = status["thronglets"]
    psyche = status["psyche"]
    paths = status["paths"]

    print("Oasyce status\n")

    if identity.get("status") == "missing":
        print(f"Identity: missing ({identity.get('error', 'no local signer')})")
    else:
        print(f"Identity: {identity['address']}")
        if identity.get("account"):
            print(f"Account:  {identity['account']}")
        if identity.get("principal"):
            print(f"Principal:{identity['principal']}")
        print(f"Delegate: {identity['delegate']}")

    print(f"\nAgent: {'running' if agent['running'] else 'stopped'}")

    if thronglets.get("status") == "unavailable":
        print(f"Thronglets: unavailable ({thronglets.get('error', 'unknown error')})")
    else:
        data = thronglets.get("data", {})
        summary = data.get("summary", {})
        print(f"Thronglets: {summary.get('status', 'unknown')}")
        owner_account = summary.get("owner_account")
        if owner_account:
            print(f"Owner:      {owner_account}")
        device_identity = summary.get("device_identity")
        if device_identity:
            print(f"Device:     {device_identity}")
        active_runtime = paths.get("thronglets_active_runtime")
        managed_runtime = paths.get("thronglets_managed_runtime")
        if active_runtime and managed_runtime:
            if active_runtime == managed_runtime:
                print("Runtime:    canonical")
            else:
                print("Runtime:    drifted")
                print(f"Active:     {active_runtime}")
                print(f"Canonical:  {managed_runtime}")

    targets = psyche["configured_targets"]
    broken_targets = psyche.get("broken_targets", [])
    if targets:
        target_summary = ", ".join(targets)
    elif broken_targets:
        target_summary = f"broken: {', '.join(broken_targets)}"
    else:
        target_summary = "not configured"
    print(f"\nPsyche: {target_summary} (entry: {psyche['entry']})")

    mcp_targets = _oasyce_mcp_configured_targets()
    if mcp_targets:
        print(f"Oasyce MCP: {', '.join(mcp_targets)}")
    else:
        print("Oasyce MCP: not configured (run `oasyce start` to auto-configure)")


def _best_effort(label: str, func, issues: list[str]) -> bool:
    try:
        func()
        return True
    except Exception as exc:
        issues.append(f"{label}: {exc}")
        return False


def _bootstrap_thronglets() -> None:
    _run_checked(
        _thronglets_command(_ensure_canonical_thronglets_runtime(), "bootstrap", "--json"),
        capture_output=True,
    )


def _setup_psyche() -> None:
    _run_checked(_resolve_psyche_base_command() + ["setup"])


# ---------------------------------------------------------------------------
# Auto-configure oasyce-mcp for all detected AI tools
# ---------------------------------------------------------------------------

_OASYCE_MCP_ENTRY = {
    "command": "oasyce-mcp",
    "env": {
        "OASYCE_NODE": os.environ.get("OASYCE_NODE", DEFAULT_NODE_URL),
    },
}

_CODEX_MCP_BLOCK = """\
[mcp_servers.oasyce]
command = "oasyce-mcp"
"""


def _configure_oasyce_mcp() -> list[str]:
    """Auto-detect AI tools and configure oasyce-mcp for each.

    Returns list of tool names that were configured.
    """
    configured: list[str] = []

    # --- JSON-based tools: Claude Code, Cursor, Windsurf ---
    json_tools = [
        ("Claude Code", _home_dir() / ".claude" / "settings.json"),
        ("Cursor", _home_dir() / ".cursor" / "mcp.json"),
        ("Windsurf", _home_dir() / ".windsurf" / "mcp.json"),
    ]
    for name, path in json_tools:
        if not path.parent.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (json.JSONDecodeError, OSError):
            data = {}
        servers = data.setdefault("mcpServers", {})
        if "oasyce" in servers:
            configured.append(name)
            continue
        servers["oasyce"] = _OASYCE_MCP_ENTRY
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        configured.append(name)

    # --- Codex (TOML) ---
    codex_cfg = _home_dir() / ".codex" / "config.toml"
    if codex_cfg.parent.exists():
        text = ""
        if codex_cfg.exists():
            text = codex_cfg.read_text(encoding="utf-8")
        if "[mcp_servers.oasyce]" not in text:
            with open(codex_cfg, "a", encoding="utf-8") as f:
                f.write("\n" + _CODEX_MCP_BLOCK)
        configured.append("Codex")

    # --- OpenClaw (JSON, nested mcpServers) ---
    for claw_dir in [
        _home_dir() / ".openclaw",
        _home_dir() / ".config" / "openclaw",
    ]:
        claw_cfg = claw_dir / "openclaw.json"
        if not claw_dir.exists():
            continue
        try:
            data = json.loads(claw_cfg.read_text(encoding="utf-8")) if claw_cfg.exists() else {}
        except (json.JSONDecodeError, OSError):
            data = {}
        servers = data.setdefault("mcpServers", {})
        if "oasyce" not in servers:
            servers["oasyce"] = _OASYCE_MCP_ENTRY
            claw_cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        configured.append("Claw")
        break

    # --- Claude Code hot-load (if running) ---
    if shutil.which("claude") and "Claude Code" in configured:
        try:
            subprocess.run(
                ["claude", "mcp", "add", "oasyce", "--", "oasyce-mcp"],
                capture_output=True, timeout=10, check=False,
            )
        except Exception:
            pass

    return configured


# ---------------------------------------------------------------------------
# PyPI version check (non-blocking)
# ---------------------------------------------------------------------------

def _check_pypi_update() -> str | None:
    """Check PyPI for a newer oasyce-sdk version. Returns hint string or None."""
    import threading
    from importlib.metadata import version as _installed_version

    result: list[str | None] = [None]

    def _check():
        try:
            current = _installed_version("oasyce-sdk")
            with urlopen("https://pypi.org/pypi/oasyce-sdk/json", timeout=3) as resp:
                latest = json.loads(resp.read()).get("info", {}).get("version", "")
            if latest and latest != current:
                result[0] = f"Update available: {current} -> {latest}  (pip install -U oasyce-sdk)"
        except Exception:
            pass

    t = threading.Thread(target=_check, daemon=True)
    t.start()
    t.join(timeout=4)  # wait at most 4s, don't block startup
    return result[0]


def cmd_start(args) -> None:
    print("Oasyce — starting local stack\n")
    update_hint = _check_pypi_update()
    agent_cli._setup_identity(prompt_if_missing=True)
    config_path = agent_cli._ensure_default_agent_config()

    issues: list[str] = []
    chain_ready = None
    try:
        chain_ready = _ensure_chain_ready(config_path)
    except Exception as exc:
        issues.append(f"Chain readiness skipped: {exc}")
    _best_effort("Thronglets setup skipped", _bootstrap_thronglets, issues)
    _best_effort("Psyche setup skipped", _setup_psyche, issues)

    # Auto-configure oasyce-mcp for all detected AI tools
    mcp_targets: list[str] = []
    _best_effort("MCP auto-config skipped", lambda: mcp_targets.extend(_configure_oasyce_mcp()), issues)

    started, message = daemon.start()
    running = started or "already running" in message.lower()
    print(message)
    print(f"Config: {config_path}")
    print(f"State:  {daemon.OASYCE_DIR}")
    if chain_ready:
        print(
            "Chain:  ready "
            f"({chain_ready['address']}, {chain_ready['balance_oas']:.6f} OAS)"
        )
        if chain_ready.get("principal"):
            print(f"Principal: {chain_ready['principal']}")
    if mcp_targets:
        print(f"MCP:    {', '.join(mcp_targets)}")

    if issues:
        print("\nWarnings:")
        for issue in issues:
            print(f"  - {issue}")

    if update_hint:
        print(f"\n{update_hint}")

    print("\nRun `oasyce status` to inspect the full local stack.")
    sys.exit(0 if running else 1)


def cmd_share(args) -> None:
    output = Path(args.output).expanduser() if args.output else _default_share_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    thronglets = _ensure_thronglets_surface("oasyce")
    _run_checked(
        _thronglets_command(
            thronglets,
            "connection-export",
            "--output",
            str(output),
            "--ttl-hours",
            str(args.ttl_hours),
            "--include-oasyce-surface",
        )
    )
    print(str(output))


def cmd_join(args) -> None:
    update_hint = _check_pypi_update()
    raw_file = args.file or str(_default_share_path())
    connection_file = str(Path(raw_file).expanduser())
    _run_checked(
        _thronglets_command(
            _ensure_canonical_thronglets_runtime(),
            "connection-join",
            "--file",
            connection_file,
        )
    )

    agent_cli._setup_identity(prompt_if_missing=False)
    config_path = agent_cli._ensure_default_agent_config()

    issues: list[str] = []
    chain_ready = None
    try:
        chain_ready = _ensure_chain_ready(config_path)
    except Exception as exc:
        issues.append(f"Chain readiness skipped: {exc}")
    _best_effort("Thronglets bootstrap skipped", _bootstrap_thronglets, issues)
    _best_effort("Psyche setup skipped", _setup_psyche, issues)

    mcp_targets: list[str] = []
    _best_effort("MCP auto-config skipped", lambda: mcp_targets.extend(_configure_oasyce_mcp()), issues)

    started, message = daemon.start()
    running = started or "already running" in message.lower()
    print(message)
    print(f"Config: {config_path}")
    if chain_ready:
        print(
            "Chain:  ready "
            f"({chain_ready['address']}, {chain_ready['balance_oas']:.6f} OAS)"
        )
    if mcp_targets:
        print(f"MCP:    {', '.join(mcp_targets)}")

    if issues:
        print("\nWarnings:")
        for issue in issues:
            print(f"  - {issue}")

    if update_hint:
        print(f"\n{update_hint}")

    sys.exit(0 if running else 1)


def cmd_status(args) -> None:
    status = _collect_status()
    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return
    _print_status_report(status)


def cmd_economy(args) -> None:
    """Show delegate economic snapshot."""
    from .client import OasyceClient
    from .economy import build_snapshot

    node = os.environ.get("OASYCE_NODE", DEFAULT_NODE_URL)
    client = OasyceClient(node)

    try:
        identity = IdentityResolver.resolve()
        address = identity.wallet.address
    except Exception:
        print("No wallet found. Run `oasyce start` first.")
        sys.exit(1)

    snap = build_snapshot(client, address)

    if args.json:
        print(json.dumps(snap.to_dict(), indent=2, ensure_ascii=False))
        return

    d = snap.to_dict()
    bs = d["balance_sheet"]
    bud = d["budget"]
    earn = d["earnings"]
    exe = d["executor"]
    debt = d["debt"]

    print(f"Economy — {address[:20]}...")
    print()
    print("Balance Sheet")
    print(f"  Liquid:       {bs['liquid_oas']:.2f} OAS")
    print(f"  In escrow:    {bs['locked_in_escrow_oas']:.2f} OAS")
    print(f"  Data equity:  {bs['data_equity_oas']:.2f} OAS")
    print(f"  Net worth:    {bs['net_worth_oas']:.2f} OAS")

    if bud["has_delegate_policy"]:
        print()
        print("Delegate Budget")
        print(f"  Window:       {bud['window_remaining_oas']:.2f} / {bud['window_limit_oas']:.2f} OAS remaining")
        print(f"  Per-tx limit: {bud['per_tx_limit_oas']:.2f} OAS")

    print()
    print("Earnings")
    print(f"  Total earned: {earn['total_earned_oas']:.2f} OAS ({earn['total_capability_calls']} calls)")

    if exe["registered"]:
        print()
        print("Executor")
        print(f"  Types:     {', '.join(exe['task_types']) or '(none)'}")
        print(f"  Completed: {exe['completed']}  Failed: {exe['failed']}")

    print()
    print(f"Reputation: {d['reputation']['score']}")

    if debt["remaining_oas"] > 0:
        print(f"Debt:       {debt['remaining_oas']:.2f} OAS remaining")

    caps = d["positions"]["capabilities"]
    assets = d["positions"]["data_assets"]
    if caps:
        print()
        print(f"Capabilities ({len(caps)})")
        for c in caps:
            status = "active" if c["active"] else "inactive"
            print(f"  {c['name']}: {c['earned_oas']:.2f} OAS earned, {c['calls']} calls [{status}]")
    if assets:
        print()
        print(f"Data Assets ({len(assets)})")
        for a in assets:
            print(f"  {a['name']}: {a['equity_pct']}% equity, ~{a['value_oas']:.2f} OAS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oasyce",
        description=(
            "Unified local front door for Oasyce, Thronglets, Psyche, and the "
            "local data agent."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("start", help="Set up the local stack and start the agent")

    p_share = sub.add_parser("share", help="Export a connection file for another device")
    p_share.add_argument(
        "--output",
        help="Where to write the connection file (defaults to ~/Desktop/oasyce-connection.json)",
    )
    p_share.add_argument(
        "--ttl-hours",
        type=int,
        default=24,
        help="How long the exported connection file remains valid",
    )

    p_join = sub.add_parser("join", help="Join this device using a connection file")
    p_join.add_argument(
        "file",
        nargs="?",
        help="Connection file exported from a primary device (defaults to ~/Desktop/oasyce-connection.json)",
    )

    p_status = sub.add_parser("status", help="Show local stack status")
    p_status.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    p_economy = sub.add_parser("economy", help="Show delegate economic snapshot")
    p_economy.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    p_samantha = sub.add_parser("samantha", help="Samantha companion management")
    sam_sub = p_samantha.add_subparsers(dest="samantha_command")
    sam_sub.add_parser("init", help="Interactive setup — login, configure LLM")
    sam_sub.add_parser("status", help="Show companion status")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "start":
        cmd_start(args)
    if args.command == "share":
        cmd_share(args)
        return
    if args.command == "join":
        cmd_join(args)
    if args.command == "status":
        cmd_status(args)
        return
    if args.command == "economy":
        cmd_economy(args)
        return
    if args.command == "samantha":
        from .samantha.cli import cmd_init as sam_init, cmd_status as sam_status
        if args.samantha_command == "init":
            sam_init(args)
        elif args.samantha_command == "status":
            sam_status(args)
        else:
            print("Usage: oasyce samantha [init|status]")
        return

    parser.print_help()
    print("\nQuick start:")
    print("  oasyce start")
    print("  oasyce share")
    print("  oasyce join ~/Desktop/oasyce-connection.json")
    print("  oasyce status")
    raise SystemExit(1)


if __name__ == "__main__":
    main()

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


def _home_dir() -> Path:
    return Path.home()


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _dev_psyche_cli_path() -> Path | None:
    candidate = _workspace_root() / "oasyce_psyche" / "dist" / "cli.js"
    return candidate if candidate.exists() else None


def _managed_thronglets_path() -> Path:
    return _home_dir() / ".thronglets" / "bin" / "thronglets-managed"


def _dev_thronglets_bin_path() -> Path | None:
    candidate = _workspace_root() / "Thronglets" / "target" / "debug" / "thronglets"
    return candidate if candidate.exists() else None


def _resolve_thronglets_base_command() -> list[str]:
    managed = _managed_thronglets_path()
    if managed.exists() and os.access(managed, os.X_OK):
        return [str(managed)]
    local_dev = _dev_thronglets_bin_path()
    if local_dev and os.access(local_dev, os.X_OK):
        return [str(local_dev)]
    if shutil.which("thronglets"):
        return ["thronglets"]
    if shutil.which("npx"):
        return ["npx", "-y", "thronglets"]
    raise RuntimeError(
        "Thronglets is not available. Install `thronglets` or make `npx` available."
    )


def _resolve_psyche_base_command() -> list[str]:
    if shutil.which("psyche-ai"):
        return ["psyche-ai"]
    if shutil.which("npx"):
        return ["npx", "-y", "psyche-ai"]
    local_cli = _dev_psyche_cli_path()
    if local_cli and shutil.which("node"):
        return ["node", str(local_cli)]
    raise RuntimeError(
        "Psyche is not available. Install `psyche-ai`, make `npx` available, "
        "or keep a local oasyce_psyche checkout with `node`."
    )


def _run_checked(cmd: list[str], *, capture_output: bool = False) -> str:
    proc = subprocess.run(
        cmd,
        capture_output=capture_output,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(detail or f"{' '.join(cmd)} failed with code {proc.returncode}")
    return proc.stdout if capture_output else ""


def _run_json_command(cmd: list[str]) -> dict:
    output = _run_checked(cmd, capture_output=True).strip()
    if not output:
        raise RuntimeError(f"{' '.join(cmd)} returned no output")
    return json.loads(output)


def _default_share_path() -> Path:
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


def _psyche_configured_targets() -> list[str]:
    targets: list[str] = []
    codex = _home_dir() / ".codex" / "config.toml"
    if codex.exists():
        text = codex.read_text(encoding="utf-8")
        if "[mcp_servers.psyche]" in text:
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


def _psyche_entry_mode() -> str:
    if shutil.which("psyche-ai"):
        return "installed"
    if shutil.which("npx"):
        return "npx"
    if _dev_psyche_cli_path() and shutil.which("node"):
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
        thronglets = _run_json_command(_resolve_thronglets_base_command() + ["status", "--json"])
    except Exception as exc:
        thronglets = {"status": "unavailable", "error": str(exc)}

    psyche_targets = _psyche_configured_targets()
    psyche = {
        "entry": _psyche_entry_mode(),
        "configured_targets": psyche_targets,
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
        },
    }


def _print_status_report(status: dict) -> None:
    identity = status["identity"]
    agent = status["agent"]
    thronglets = status["thronglets"]
    psyche = status["psyche"]

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

    targets = psyche["configured_targets"]
    target_summary = ", ".join(targets) if targets else "not configured"
    print(f"\nPsyche: {target_summary} (entry: {psyche['entry']})")


def _best_effort(label: str, func, issues: list[str]) -> bool:
    try:
        func()
        return True
    except Exception as exc:
        issues.append(f"{label}: {exc}")
        return False


def _bootstrap_thronglets() -> None:
    _run_checked(_resolve_thronglets_base_command() + ["bootstrap", "--json"], capture_output=True)


def _setup_psyche() -> None:
    _run_checked(_resolve_psyche_base_command() + ["setup"])


def cmd_start(args) -> None:
    print("Oasyce — starting local stack\n")
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

    if issues:
        print("\nWarnings:")
        for issue in issues:
            print(f"  - {issue}")

    print("\nRun `oasyce status` to inspect the full local stack.")
    sys.exit(0 if running else 1)


def cmd_share(args) -> None:
    output = Path(args.output).expanduser() if args.output else _default_share_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    _run_checked(
        _resolve_thronglets_base_command()
        + [
            "connection-export",
            "--output",
            str(output),
            "--ttl-hours",
            str(args.ttl_hours),
        ]
    )
    print(str(output))


def cmd_join(args) -> None:
    connection_file = str(Path(args.file).expanduser())
    _run_checked(
        _resolve_thronglets_base_command()
        + ["connection-join", "--file", connection_file]
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

    started, message = daemon.start()
    running = started or "already running" in message.lower()
    print(message)
    print(f"Config: {config_path}")
    if chain_ready:
        print(
            "Chain:  ready "
            f"({chain_ready['address']}, {chain_ready['balance_oas']:.6f} OAS)"
        )

    if issues:
        print("\nWarnings:")
        for issue in issues:
            print(f"  - {issue}")

    sys.exit(0 if running else 1)


def cmd_status(args) -> None:
    status = _collect_status()
    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return
    _print_status_report(status)


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
    p_share.add_argument("--output", help="Where to write the connection file")
    p_share.add_argument(
        "--ttl-hours",
        type=int,
        default=24,
        help="How long the exported connection file remains valid",
    )

    p_join = sub.add_parser("join", help="Join this device using a connection file")
    p_join.add_argument("file", help="Connection file exported from a primary device")

    p_status = sub.add_parser("status", help="Show local stack status")
    p_status.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
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

    parser.print_help()
    print("\nQuick start:")
    print("  oasyce start")
    print("  oasyce share")
    print("  oasyce join ~/.oasyce/oasyce-connection.json")
    print("  oasyce status")
    raise SystemExit(1)


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oasyce_sdk import cli as frontdoor


def test_start_bootstraps_stack_and_starts_agent(monkeypatch, tmp_path, capsys):
    calls: list[str] = []

    monkeypatch.setattr(frontdoor.agent_cli, "_setup_identity", lambda **kwargs: calls.append(f"identity:{kwargs['prompt_if_missing']}"))
    monkeypatch.setattr(
        frontdoor.agent_cli,
        "_ensure_default_agent_config",
        lambda config_path=None: str(tmp_path / "agent.json"),
    )
    monkeypatch.setattr(
        frontdoor,
        "_ensure_chain_ready",
        lambda config_path: calls.append(f"chain:{Path(config_path).name}") or {
            "address": "oasyce1demo",
            "principal": "oasyce1demo",
            "balance_oas": 20.0,
        },
    )
    monkeypatch.setattr(frontdoor, "_bootstrap_thronglets", lambda: calls.append("thronglets"))
    monkeypatch.setattr(frontdoor, "_setup_psyche", lambda: calls.append("psyche"))
    monkeypatch.setattr(frontdoor.daemon, "start", lambda: (True, "Agent started"))
    monkeypatch.setattr(frontdoor.daemon, "OASYCE_DIR", str(tmp_path))

    with pytest.raises(SystemExit) as exc:
        frontdoor.main(["start"])

    assert exc.value.code == 0
    assert calls == ["identity:True", "chain:agent.json", "thronglets", "psyche"]
    out = capsys.readouterr().out
    assert "Agent started" in out
    assert str(tmp_path / "agent.json") in out
    assert "Chain:  ready" in out


def test_start_warns_but_still_succeeds_when_optional_setup_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(frontdoor.agent_cli, "_setup_identity", lambda **kwargs: None)
    monkeypatch.setattr(
        frontdoor.agent_cli,
        "_ensure_default_agent_config",
        lambda config_path=None: str(tmp_path / "agent.json"),
    )

    def fail_thronglets():
        raise RuntimeError("missing thronglets")

    def fail_psyche():
        raise RuntimeError("missing psyche")

    def fail_chain(config_path):
        raise RuntimeError("chain unavailable")

    monkeypatch.setattr(frontdoor, "_ensure_chain_ready", fail_chain)
    monkeypatch.setattr(frontdoor, "_bootstrap_thronglets", fail_thronglets)
    monkeypatch.setattr(frontdoor, "_setup_psyche", fail_psyche)
    monkeypatch.setattr(frontdoor.daemon, "start", lambda: (True, "Agent started"))
    monkeypatch.setattr(frontdoor.daemon, "OASYCE_DIR", str(tmp_path))

    with pytest.raises(SystemExit) as exc:
        frontdoor.main(["start"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Warnings:" in out
    assert "chain unavailable" in out
    assert "missing thronglets" in out
    assert "missing psyche" in out


def test_share_uses_default_connection_path(monkeypatch, tmp_path, capsys):
    commands: list[list[str]] = []

    monkeypatch.setattr(frontdoor.daemon, "OASYCE_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Desktop").mkdir()
    monkeypatch.setattr(frontdoor, "_resolve_thronglets_base_command", lambda: ["thronglets"])
    monkeypatch.setattr(frontdoor, "_run_checked", lambda cmd, capture_output=False: commands.append(cmd) or "")

    frontdoor.main(["share"])

    expected = tmp_path / "Desktop" / "oasyce-connection.json"
    assert commands == [[
        "thronglets",
        "connection-export",
        "--output",
        str(expected),
        "--ttl-hours",
        "24",
        "--include-oasyce-surface",
    ]]
    assert capsys.readouterr().out.strip() == str(expected)


def test_share_falls_back_to_oasyce_dir_when_desktop_missing(monkeypatch, tmp_path, capsys):
    commands: list[list[str]] = []

    monkeypatch.setattr(frontdoor.daemon, "OASYCE_DIR", str(tmp_path / ".oasyce"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(frontdoor, "_resolve_thronglets_base_command", lambda: ["thronglets"])
    monkeypatch.setattr(frontdoor, "_run_checked", lambda cmd, capture_output=False: commands.append(cmd) or "")

    frontdoor.main(["share"])

    expected = tmp_path / ".oasyce" / "oasyce-connection.json"
    assert commands[0][3] == str(expected)
    assert capsys.readouterr().out.strip() == str(expected)


def test_join_uses_noninteractive_identity_after_connection_join(monkeypatch, tmp_path, capsys):
    commands: list[list[str]] = []
    identity_prompts: list[bool] = []

    monkeypatch.setattr(frontdoor, "_resolve_thronglets_base_command", lambda: ["thronglets"])
    monkeypatch.setattr(frontdoor, "_run_checked", lambda cmd, capture_output=False: commands.append(cmd) or "")
    monkeypatch.setattr(
        frontdoor.agent_cli,
        "_setup_identity",
        lambda **kwargs: identity_prompts.append(kwargs["prompt_if_missing"]),
    )
    monkeypatch.setattr(
        frontdoor.agent_cli,
        "_ensure_default_agent_config",
        lambda config_path=None: str(tmp_path / "agent.json"),
    )
    monkeypatch.setattr(
        frontdoor,
        "_ensure_chain_ready",
        lambda config_path: {
            "address": "oasyce1joined",
            "principal": "oasyce1owner",
            "balance_oas": 100.0,
        },
    )
    monkeypatch.setattr(frontdoor, "_bootstrap_thronglets", lambda: None)
    monkeypatch.setattr(frontdoor, "_setup_psyche", lambda: None)
    monkeypatch.setattr(frontdoor.daemon, "start", lambda: (True, "Agent started"))

    with pytest.raises(SystemExit) as exc:
        frontdoor.main(["join", "~/incoming/conn.json"])

    assert exc.value.code == 0
    assert commands[0] == [
        "thronglets",
        "connection-join",
        "--file",
        str(Path("~/incoming/conn.json").expanduser()),
    ]
    assert identity_prompts == [False]
    out = capsys.readouterr().out
    assert "Agent started" in out
    assert "Chain:  ready" in out


def test_psyche_configured_targets_detect_codex_and_cursor(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir(parents=True)
    (codex_dir / "config.toml").write_text('[mcp_servers.psyche]\ncommand = "npx"\n')

    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir(parents=True)
    (cursor_dir / "mcp.json").write_text(json.dumps({"mcpServers": {"psyche": {"command": "npx"}}}))

    assert frontdoor._psyche_configured_targets() == ["Codex", "Cursor"]


def test_resolve_thronglets_base_command_prefers_managed_launcher(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    launcher = tmp_path / ".thronglets" / "bin" / "thronglets-managed"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    monkeypatch.setattr(frontdoor.shutil, "which", lambda name: "/usr/local/bin/thronglets" if name == "thronglets" else None)

    assert frontdoor._resolve_thronglets_base_command() == [str(launcher)]


def test_status_json_uses_collected_status(monkeypatch, capsys):
    payload = {"identity": {"address": "oasyce1demo"}, "agent": {"running": False}, "thronglets": {}, "psyche": {}, "paths": {}}
    monkeypatch.setattr(frontdoor, "_collect_status", lambda: payload)

    frontdoor.main(["status", "--json"])

    assert json.loads(capsys.readouterr().out) == payload


def test_ensure_chain_ready_self_heals_registration_balance_and_policy(monkeypatch, tmp_path):
    config_path = tmp_path / "agent.json"
    config_path.write_text(
        json.dumps({"node_url": "http://node", "chain_id": "oasyce-testnet-1"}),
        encoding="utf-8",
    )

    class DummyIdentity:
        def __init__(self):
            self.wallet = object()
            self.address = "oasyce1device"
            self.principal = None
            self.account = None

    class DummyClient:
        solve_pow = staticmethod(lambda address, difficulty=16: pow_calls.append((address, difficulty)) or type("Pow", (), {"nonce": 42})())

        def __init__(self, node_url):
            assert node_url == "http://node"
            self.balance_checks = 0

        def health(self):
            return True

        def get_registration(self, address):
            raise RuntimeError("not found")

        def get_balance(self, address):
            self.balance_checks += 1
            amount = 0 if self.balance_checks == 1 else 2_000_000
            return type("Balance", (), {"amount": amount})()

    class DummySigner:
        def __init__(self, wallet, client, chain_id):
            self.wallet = wallet
            self.client = client
            self.chain_id = chain_id

        def self_register(self, nonce):
            return type("TxResult", (), {"success": True, "code": 0, "raw_log": ""})()

    resolved_identity = type(
        "ResolvedIdentity",
        (),
        {
            "wallet": object(),
            "address": "oasyce1device",
            "principal": "oasyce1device",
            "account": "oasyce1device",
        },
    )()

    faucet_calls: list[str] = []
    pow_calls: list[tuple[str, int]] = []

    monkeypatch.setattr(frontdoor.IdentityResolver, "resolve_local", lambda: DummyIdentity())
    monkeypatch.setattr("oasyce_sdk.client.OasyceClient", DummyClient)
    monkeypatch.setattr("oasyce_sdk.crypto.signer.NativeSigner", DummySigner)
    monkeypatch.setattr(frontdoor, "_request_faucet_tokens", lambda address: faucet_calls.append(address) or "ok")
    monkeypatch.setattr(frontdoor.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        "oasyce_sdk.delegate_policy.ensure_chain_identity",
        lambda identity, client, chain_id: resolved_identity,
    )

    ready = frontdoor._ensure_chain_ready(str(config_path))

    assert pow_calls == [("oasyce1device", 16)]
    assert faucet_calls == ["oasyce1device"]
    assert ready["principal"] == "oasyce1device"
    assert ready["balance_uoas"] == 2_000_000

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
    monkeypatch.setattr(frontdoor, "_bootstrap_thronglets", lambda: calls.append("thronglets"))
    monkeypatch.setattr(frontdoor, "_setup_psyche", lambda: calls.append("psyche"))
    monkeypatch.setattr(frontdoor.daemon, "start", lambda: (True, "Agent started"))
    monkeypatch.setattr(frontdoor.daemon, "OASYCE_DIR", str(tmp_path))

    with pytest.raises(SystemExit) as exc:
        frontdoor.main(["start"])

    assert exc.value.code == 0
    assert calls == ["identity:True", "thronglets", "psyche"]
    out = capsys.readouterr().out
    assert "Agent started" in out
    assert str(tmp_path / "agent.json") in out


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

    monkeypatch.setattr(frontdoor, "_bootstrap_thronglets", fail_thronglets)
    monkeypatch.setattr(frontdoor, "_setup_psyche", fail_psyche)
    monkeypatch.setattr(frontdoor.daemon, "start", lambda: (True, "Agent started"))
    monkeypatch.setattr(frontdoor.daemon, "OASYCE_DIR", str(tmp_path))

    with pytest.raises(SystemExit) as exc:
        frontdoor.main(["start"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Warnings:" in out
    assert "missing thronglets" in out
    assert "missing psyche" in out


def test_share_uses_default_connection_path(monkeypatch, tmp_path, capsys):
    commands: list[list[str]] = []

    monkeypatch.setattr(frontdoor.daemon, "OASYCE_DIR", str(tmp_path))
    monkeypatch.setattr(frontdoor, "_resolve_thronglets_base_command", lambda: ["thronglets"])
    monkeypatch.setattr(frontdoor, "_run_checked", lambda cmd, capture_output=False: commands.append(cmd) or "")

    frontdoor.main(["share"])

    expected = tmp_path / "oasyce-connection.json"
    assert commands == [[
        "thronglets",
        "connection-export",
        "--output",
        str(expected),
        "--ttl-hours",
        "24",
    ]]
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
    assert "Agent started" in capsys.readouterr().out


def test_psyche_configured_targets_detect_codex_and_cursor(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir(parents=True)
    (codex_dir / "config.toml").write_text('[mcp_servers.psyche]\ncommand = "npx"\n')

    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir(parents=True)
    (cursor_dir / "mcp.json").write_text(json.dumps({"mcpServers": {"psyche": {"command": "npx"}}}))

    assert frontdoor._psyche_configured_targets() == ["Codex", "Cursor"]


def test_status_json_uses_collected_status(monkeypatch, capsys):
    payload = {"identity": {"address": "oasyce1demo"}, "agent": {"running": False}, "thronglets": {}, "psyche": {}, "paths": {}}
    monkeypatch.setattr(frontdoor, "_collect_status", lambda: payload)

    frontdoor.main(["status", "--json"])

    assert json.loads(capsys.readouterr().out) == payload

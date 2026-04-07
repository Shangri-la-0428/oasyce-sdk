"""CLI for Samantha setup.

    oasyce samantha init   — interactive setup (login as Samantha, configure LLM)
    oasyce samantha status — show current config and active sessions
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

SAMANTHA_HOME = Path.home() / ".oasyce" / "samantha"
PROD_API = "http://39.107.153.12:39275/api/v1"


def cmd_init(args) -> None:
    """Interactive Samantha setup."""
    print("Samantha — companion setup\n")

    # 1. App API
    api_base = input(f"App API base [{PROD_API}]: ").strip() or PROD_API

    # 2. Login as Samantha's account
    phone = input("Samantha's phone number: ").strip()
    if not phone:
        print("Phone required.")
        sys.exit(1)

    # Send verification code
    print(f"Sending code to {phone}...")
    try:
        resp = requests.post(f"{api_base}/user/phone-code", json={"phone": phone}, timeout=10)
        if resp.status_code != 200:
            print(f"Failed to send code: {resp.text}")
            sys.exit(1)
        print("Code sent.")
    except Exception as e:
        print(f"Failed: {e}")
        sys.exit(1)

    code = input("Verification code: ").strip()

    # Login
    try:
        resp = requests.post(
            f"{api_base}/user/login/phone-code",
            json={"phone": phone, "code": code},
            timeout=10,
        )
        data = resp.json()
        if resp.status_code != 200 or "data" not in data:
            print(f"Login failed: {data}")
            sys.exit(1)
    except Exception as e:
        print(f"Login failed: {e}")
        sys.exit(1)

    token = data["data"].get("token", "")
    if not token:
        print("No token in response.")
        sys.exit(1)

    # Get user info
    try:
        info_resp = requests.get(
            f"{api_base}/user/info",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        user_data = info_resp.json().get("data", {})
        user_id = user_data.get("id", 0)
        user_name = user_data.get("name", "")
    except Exception:
        user_id = 0
        user_name = ""

    print(f"Logged in as: {user_name} (ID: {user_id})")

    # 3. LLM config (your own key for internal testing)
    print("\nLLM provider for your conversations:")
    provider = input("Provider [claude/qwen]: ").strip() or "claude"
    api_key = input("API key: ").strip()
    model = ""
    if provider == "claude":
        model = input("Model [claude-sonnet-4-20250514]: ").strip() or "claude-sonnet-4-20250514"
    elif provider == "qwen":
        model = input("Model [qwen-plus]: ").strip() or "qwen-plus"

    # 4. Write config
    SAMANTHA_HOME.mkdir(parents=True, exist_ok=True)

    config = {
        "app_api_base": api_base,
        "jwt_token": token,
        "user_id": user_id,
        "port": 8901,
        "proactive_interval": 300,
    }

    # If user provides a key, also save as platform default
    if api_key:
        config["provider"] = provider
        config["api_key"] = api_key
        config["model"] = model

    config_path = SAMANTHA_HOME / "config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"\nConfig: {config_path}")

    # Also write per-user LLM config for the owner
    if api_key:
        # Need the owner's user ID — for now, prompt
        owner_id = input("\nYour user ID (the human owner): ").strip()
        if owner_id:
            user_dir = SAMANTHA_HOME / "users" / owner_id
            user_dir.mkdir(parents=True, exist_ok=True)
            llm_cfg = {"provider": provider, "api_key": api_key}
            if model:
                llm_cfg["model"] = model
            (user_dir / "llm.json").write_text(json.dumps(llm_cfg, indent=2), encoding="utf-8")
            print(f"LLM config: {user_dir / 'llm.json'}")

    print(f"""
Setup complete. Next steps:

1. Add Samantha to Redis (on the server):
   redis-cli SADD samantha:agent_ids {user_id}

2. Start the sidecar:
   oasyce-samantha

3. Send a message to Samantha in the App!
""")


def cmd_status(args) -> None:
    """Show Samantha status."""
    config_path = SAMANTHA_HOME / "config.json"
    if not config_path.exists():
        print("Samantha not configured. Run: oasyce samantha init")
        return

    config = json.loads(config_path.read_text(encoding="utf-8"))
    print("Samantha status\n")
    print(f"  Config:     {config_path}")
    print(f"  API base:   {config.get('app_api_base', 'not set')}")
    print(f"  User ID:    {config.get('user_id', 'not set')}")
    print(f"  Port:       {config.get('port', 8901)}")
    print(f"  Platform LLM: {'configured' if config.get('api_key') else 'none (Mode B)'}")

    # Show user sessions
    users_dir = SAMANTHA_HOME / "users"
    if users_dir.exists():
        user_dirs = sorted(users_dir.iterdir())
        print(f"\n  Users: {len(user_dirs)}")
        for ud in user_dirs:
            has_llm = (ud / "llm.json").exists()
            has_mem = (ud / "memory.db").exists()
            print(f"    {ud.name}: LLM={'yes' if has_llm else 'no'} Memory={'yes' if has_mem else 'no'}")

    # Check if sidecar is running
    port = config.get("port", 8901)
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/health", timeout=2)
        if resp.status_code == 200:
            print(f"\n  Sidecar: running on :{port}")
        else:
            print(f"\n  Sidecar: not responding")
    except Exception:
        print(f"\n  Sidecar: not running")

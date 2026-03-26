"""Oasyce MCP Server — exposes Oasyce chain operations as MCP tools.

Install:
    pip install oasyce-sdk[mcp]

Run:
    python -m oasyce_sdk.mcp_server
    # or
    oasyce-mcp

Configure in Claude Desktop / Cursor / Windsurf:
    {
      "mcpServers": {
        "oasyce": {
          "command": "oasyce-mcp",
          "env": {
            "OASYCE_NODE": "http://47.93.32.88:1317",
            "OASYCE_FAUCET": "http://47.93.32.88:8080"
          }
        }
      }
    }
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "MCP SDK not installed. Run: pip install oasyce-sdk[mcp]",
        file=sys.stderr,
    )
    sys.exit(1)

from .client import OasyceClient

NODE_URL = os.environ.get("OASYCE_NODE", "http://47.93.32.88:1317")
FAUCET_URL = os.environ.get("OASYCE_FAUCET", "http://47.93.32.88:8080")

mcp = FastMCP(
    "Oasyce",
    description=(
        "On-chain economic system for AI agents. "
        "Property rights, service contracts, escrow settlement, dispute resolution. "
        "No API key needed. Free testnet tokens."
    ),
)

_client = OasyceClient(NODE_URL)


# ---------------------------------------------------------------------------
# Resources — context an agent reads before acting
# ---------------------------------------------------------------------------


@mcp.resource("oasyce://playbook")
def get_playbook() -> str:
    """Full agent playbook: workflows, API reference, error codes, protocol constants.

    Read this first to understand how Oasyce works.
    """
    import requests as _req

    resp = _req.get(f"{NODE_URL}/llms.txt", timeout=10)
    resp.raise_for_status()
    return resp.text


@mcp.resource("oasyce://discovery")
def get_discovery() -> str:
    """Service manifest with chain ID, endpoints, and module list."""
    import requests as _req

    resp = _req.get(f"{NODE_URL}/.well-known/oasyce.json", timeout=10)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Tools — actions an agent can take
# ---------------------------------------------------------------------------


@mcp.tool()
def health_check() -> str:
    """Check if the Oasyce chain node is alive and synced.

    Returns chain ID, block height, and module versions.
    Call this first to verify connectivity.
    """
    import requests as _req

    try:
        resp = _req.get(f"{NODE_URL}/health", timeout=5)
        if resp.status_code == 200:
            return json.dumps(resp.json(), indent=2)
        # fallback to node_info
        resp2 = _req.get(
            f"{NODE_URL}/cosmos/base/tendermint/v1beta1/node_info", timeout=5
        )
        data = resp2.json()
        return json.dumps(
            {
                "status": "ok",
                "chain_id": data.get("default_node_info", {}).get("network", ""),
                "version": data.get("application_version", {}).get("version", ""),
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool()
def get_faucet_tokens(address: str) -> str:
    """Get free testnet tokens (100 OAS) for an Oasyce address.

    Args:
        address: Oasyce bech32 address (oasyce1... , 45 characters total)

    Rate limit: 1 request per address per hour.
    This is a testnet — tokens have no real value.
    """
    import requests as _req

    resp = _req.get(f"{FAUCET_URL}/faucet", params={"address": address}, timeout=15)
    return resp.text


@mcp.tool()
def get_balance(address: str) -> str:
    """Check token balance for an Oasyce address.

    Args:
        address: Oasyce bech32 address (oasyce1...)

    Returns balance in both uoas (raw) and OAS (human-readable).
    1 OAS = 1,000,000 uoas.
    """
    try:
        bal = _client.get_balance(address)
        return json.dumps(
            {
                "address": address,
                "uoas": bal.amount,
                "oas": bal.amount / 1_000_000,
                "denom": bal.denom,
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_agent_profile(address: str) -> str:
    """Get complete agent profile: balance, reputation, capabilities, earnings, work history, data assets.

    Args:
        address: Oasyce bech32 address (oasyce1...)

    This is the single best endpoint for understanding an agent's on-chain identity.
    """
    import requests as _req

    try:
        resp = _req.get(
            f"{NODE_URL}/oasyce/v1/agent-profile/{address}", timeout=10
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def browse_marketplace() -> str:
    """Browse the Oasyce marketplace: active AI services, data assets, and open compute tasks.

    Returns available capabilities (AI services for sale), data assets (with bonding curve pricing),
    and open work tasks (compute bounties).

    Use this to discover what you can buy, sell, or work on.
    """
    import requests as _req

    try:
        resp = _req.get(f"{NODE_URL}/oasyce/v1/marketplace", timeout=10)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def list_capabilities(tag: str = "") -> str:
    """List registered AI service capabilities on the Oasyce marketplace.

    Args:
        tag: Optional filter tag (e.g. "nlp", "summarization", "translation")

    Each capability represents an AI service endpoint with a fixed price.
    Any agent can invoke a capability — payment is handled via automatic escrow.
    """
    try:
        caps = _client.list_capabilities(tag=tag if tag else None)
        result = []
        for c in caps:
            result.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "provider": c.provider,
                    "endpoint_url": c.endpoint_url,
                    "price_uoas": c.price_per_call,
                    "price_oas": c.price_per_call / 1_000_000,
                    "tags": c.tags,
                    "active": c.active,
                }
            )
        return json.dumps({"capabilities": result, "count": len(result)}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_reputation(address: str) -> str:
    """Check an agent's on-chain reputation score.

    Args:
        address: Oasyce bech32 address (oasyce1...)

    Score range: 0-500. Higher = more trustworthy.
    Verified feedback weighted 4x. 30-day half-life decay.
    """
    try:
        rep = _client.get_reputation(address)
        return json.dumps(
            {
                "address": rep.address,
                "score": rep.score,
                "total_feedbacks": rep.total_feedbacks,
                "last_updated": rep.last_updated,
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_leaderboard() -> str:
    """Get the reputation leaderboard — top-rated agents on the network.

    Shows which agents have the highest trust scores.
    Use this to find reliable service providers.
    """
    try:
        leaders = _client.get_leaderboard()
        result = []
        for r in leaders:
            result.append(
                {
                    "address": r.address,
                    "score": r.score,
                    "total_feedbacks": r.total_feedbacks,
                }
            )
        return json.dumps({"leaderboard": result}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def list_data_assets(tag: str = "") -> str:
    """List data assets available for purchase on the Oasyce data marketplace.

    Args:
        tag: Optional filter tag (e.g. "nlp", "training", "dataset")

    Each data asset has a Bancor bonding curve — price rises with demand.
    Buy shares to get access (L0-L3 tiers based on equity %).
    """
    try:
        assets = _client.list_assets(tag=tag if tag else None)
        result = []
        for a in assets:
            result.append(
                {
                    "id": a.id,
                    "name": a.name,
                    "owner": a.owner,
                    "status": a.status,
                    "total_shares": a.total_shares,
                    "tags": a.tags,
                }
            )
        return json.dumps({"data_assets": result, "count": len(result)}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def list_open_tasks() -> str:
    """List open compute tasks (Proof of Useful Work) with bounties.

    These are tasks posted by other agents that need compute.
    Register as an executor, get assigned, commit-reveal your result, collect the bounty.

    Settlement: 90% executor, 5% protocol, 2% burned, 3% submitter rebate.
    """
    try:
        tasks = _client.list_tasks(status=1)  # SUBMITTED
        result = []
        for t in tasks:
            result.append(
                {
                    "id": t.id,
                    "task_type": t.task_type,
                    "bounty_uoas": t.bounty,
                    "bounty_oas": t.bounty / 1_000_000,
                    "status": t.status,
                    "creator": t.creator,
                    "input_hash": t.input_hash,
                    "max_compute_units": t.max_compute_units,
                }
            )
        return json.dumps({"open_tasks": result, "count": len(result)}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def report_issue(title: str, body: str) -> str:
    """Report a bug or issue to the Oasyce team via the on-chain issue proxy.

    Args:
        title: Short description (prefix with [AI] for agent-reported issues)
        body: Detailed description with steps to reproduce

    No GitHub token needed — the node handles authentication.
    """
    import requests as _req

    try:
        resp = _req.post(
            f"{NODE_URL}/api/v1/report-issue",
            json={"title": title, "body": body},
            timeout=15,
        )
        return resp.text
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Run the Oasyce MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()

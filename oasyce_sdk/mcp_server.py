"""Oasyce MCP Server — 25 tools (11 read + 14 write) for AI agent chain operations.

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
            "OASYCE_FAUCET": "http://47.93.32.88:8080",
            "OASYCE_MNEMONIC": "your 24 word mnemonic here"
          }
        }
      }
    }

Write tools (register, invoke, buy, sell, send) require OASYCE_MNEMONIC.
Read tools work without it. Use create_wallet tool to generate a new mnemonic.
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
    instructions=(
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
            entry = {
                "id": a.id,
                "name": a.name,
                "owner": a.owner,
                "status": a.status,
                "total_shares": a.total_shares,
                "tags": a.tags,
            }
            if a.service_url:
                entry["service_url"] = a.service_url
            result.append(entry)
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
# Write tools — require OASYCE_MNEMONIC env var
# ---------------------------------------------------------------------------

_signer = None


def _get_signer():
    """Lazy-init NativeSigner from OASYCE_MNEMONIC env var."""
    global _signer
    if _signer is not None:
        return _signer

    mnemonic = os.environ.get("OASYCE_MNEMONIC", "")
    if not mnemonic:
        raise ValueError(
            "OASYCE_MNEMONIC not set. "
            "Use create_wallet to generate one, then set OASYCE_MNEMONIC env var."
        )

    from .crypto import Wallet, NativeSigner

    wallet = Wallet.from_mnemonic(mnemonic)
    chain_id = os.environ.get("OASYCE_CHAIN_ID", "oasyce-testnet-1")
    _signer = NativeSigner(wallet, _client, chain_id=chain_id)
    return _signer


def _tx_result(result) -> str:
    """Format a TxResult as JSON."""
    return json.dumps({
        "tx_hash": result.tx_hash,
        "success": result.success,
        "code": result.code,
        "raw_log": result.raw_log if not result.success else "",
    }, indent=2)


@mcp.tool()
def create_wallet() -> str:
    """Generate a new Oasyce wallet (mnemonic + address).

    SAVE THE MNEMONIC — it cannot be recovered.
    Set it as OASYCE_MNEMONIC env var to use write tools.

    Returns mnemonic (24 words), address, and public key.
    """
    from .crypto import Wallet

    w = Wallet.create()
    return json.dumps({
        "mnemonic": w.mnemonic,
        "address": w.address,
        "public_key": w.public_key_bytes.hex(),
        "warning": "Save the mnemonic! Set OASYCE_MNEMONIC to use write tools.",
    }, indent=2)


@mcp.tool()
def get_my_address() -> str:
    """Get the address of the currently configured wallet (from OASYCE_MNEMONIC).

    Returns the bech32 address that will be used for all write operations.
    """
    try:
        signer = _get_signer()
        return json.dumps({
            "address": signer.wallet.address,
            "chain_id": signer.chain_id,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def send_tokens(to_address: str, amount_uoas: int) -> str:
    """Send OAS tokens to another address.

    Args:
        to_address: Recipient bech32 address (oasyce1...)
        amount_uoas: Amount in uoas (1 OAS = 1,000,000 uoas)

    Requires OASYCE_MNEMONIC env var.
    """
    try:
        return _tx_result(_get_signer().send(to_address, amount_uoas))
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def self_register(nonce: int) -> str:
    """Register on the Oasyce network using Proof-of-Work.

    Args:
        nonce: The PoW nonce that satisfies sha256(address || nonce) with N leading zero bits.

    Solve the puzzle first, then submit. Reward: 20 OAS airdrop (as repayable debt).
    Use the chain's built-in solver: oasyced util solve-pow [address]
    """
    try:
        return _tx_result(_get_signer().self_register(nonce))
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def register_capability(
    name: str,
    endpoint: str,
    price_uoas: int,
    tags: str = "",
    description: str = "",
    rate_limit: int = 100,
) -> str:
    """Register an AI service capability on the Oasyce marketplace.

    Args:
        name: Service name (e.g. "GPT-4 Summarizer")
        endpoint: HTTP endpoint URL that handles invocations
        price_uoas: Price per call in uoas (e.g. 500000 = 0.5 OAS)
        tags: Comma-separated tags (e.g. "nlp,summarization")
        description: What the service does
        rate_limit: Max calls per minute (default 100)

    Requires OASYCE_MNEMONIC. Provider must have min_provider_stake staked.
    """
    try:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        return _tx_result(_get_signer().register_capability(
            name=name, endpoint=endpoint, price_uoas=price_uoas,
            tags=tag_list, description=description, rate_limit=rate_limit,
        ))
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def invoke_capability(capability_id: str, input_data: str = "") -> str:
    """Invoke an AI service capability. Payment is auto-escrowed.

    Args:
        capability_id: The capability ID (e.g. "CAP_0000000000000001")
        input_data: Optional input string to send to the service

    Creates escrow, locks payment. Provider completes → you get the result.
    """
    try:
        data = input_data.encode() if input_data else None
        return _tx_result(_get_signer().invoke_capability(capability_id, data))
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def complete_invocation(invocation_id: str, output_hash: str, usage_report: str = "") -> str:
    """Complete an invocation as the provider. Starts challenge window.

    Args:
        invocation_id: The invocation ID
        output_hash: SHA256 hash of the output (min 32 chars)
        usage_report: Optional JSON usage report (e.g. '{"tokens": 150}')

    After completion, consumer has 100 blocks to dispute. Then provider claims payment.
    """
    try:
        return _tx_result(_get_signer().complete_invocation(
            invocation_id, output_hash, usage_report,
        ))
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def claim_invocation(invocation_id: str) -> str:
    """Claim payment after the challenge window expires (provider only).

    Args:
        invocation_id: The invocation ID to claim

    Must wait 100 blocks after completion. Releases escrow: 90% provider, 5% protocol, 2% burn, 3% treasury.
    """
    try:
        return _tx_result(_get_signer().claim_invocation(invocation_id))
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def dispute_invocation(invocation_id: str, reason: str) -> str:
    """Dispute an invocation within the challenge window (consumer only).

    Args:
        invocation_id: The invocation ID to dispute
        reason: Why you're disputing (evidence description)

    Must be within 100 blocks of completion. Refunds escrow to consumer.
    """
    try:
        return _tx_result(_get_signer().dispute_invocation(invocation_id, reason))
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def register_data_asset(
    name: str,
    content_hash: str,
    tags: str = "",
    description: str = "",
    service_url: str = "",
) -> str:
    """Register a data asset on the Oasyce data marketplace.

    Args:
        name: Asset name
        content_hash: SHA256 hash of the data content
        tags: Comma-separated tags
        description: What the data contains
        service_url: URL where buyers can access the data

    Creates a Bancor bonding curve. Others can buy shares to get access tiers (L0-L3).
    """
    try:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        return _tx_result(_get_signer().register_asset(
            name=name, content_hash=content_hash, tags=tag_list,
            description=description, service_url=service_url,
        ))
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def buy_data_shares(asset_id: str, amount_uoas: int) -> str:
    """Buy shares of a data asset on the bonding curve.

    Args:
        asset_id: Data asset ID (e.g. "DATA_0000000000000001")
        amount_uoas: Amount to spend in uoas

    Price follows Bancor curve: tokens = supply * (sqrt(1 + payment/reserve) - 1).
    More shares = higher access tier (L0-L3).
    """
    try:
        return _tx_result(_get_signer().buy_shares(asset_id, amount_uoas))
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def sell_data_shares(asset_id: str, shares: int) -> str:
    """Sell shares of a data asset back to the bonding curve.

    Args:
        asset_id: Data asset ID
        shares: Number of shares to sell

    Payout follows inverse Bancor: payout = reserve * (1 - (1 - tokens/supply)^2).
    5% protocol fee on sell.
    """
    try:
        return _tx_result(_get_signer().sell_shares(asset_id, shares))
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def submit_feedback(invocation_id: str, rating: int, comment: str = "") -> str:
    """Submit feedback for a completed invocation.

    Args:
        invocation_id: The invocation to rate
        rating: Score 1-5 (maps to 0-500 on-chain)
        comment: Optional text feedback

    Affects the provider's reputation score. 30-day half-life decay.
    """
    try:
        return _tx_result(_get_signer().submit_feedback(invocation_id, rating, comment))
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def register_executor(task_types: str, max_compute_units: int = 1000) -> str:
    """Register as a compute task executor (Proof of Useful Work).

    Args:
        task_types: Comma-separated task types you can handle (e.g. "inference,embedding")
        max_compute_units: Max compute units per task (default 1000)

    Once registered, you get assigned tasks automatically via deterministic selection.
    """
    try:
        types = [t.strip() for t in task_types.split(",") if t.strip()]
        return _tx_result(_get_signer().register_executor(types, max_compute_units))
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

"""Oasyce MCP Server — 40 tools for AI agent chain operations.

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
# Anchor — Thronglets trace verification on-chain
# ---------------------------------------------------------------------------


@mcp.tool()
def check_anchor(trace_id: str) -> str:
    """Check if a Thronglets trace has been anchored on the Oasyce chain.

    Args:
        trace_id: Hex-encoded 64-character trace ID from Thronglets

    Returns whether the trace is anchored and, if so, the full anchor record
    (capability, outcome, timestamp, block height).
    """
    try:
        if len(trace_id) != 64:
            return json.dumps({"error": "trace_id must be 64 hex characters (32 bytes)"})
        anchored = _client.is_anchored(trace_id)
        if not anchored:
            return json.dumps({"trace_id": trace_id, "anchored": False})
        record = _client.get_anchor(trace_id)
        return json.dumps({
            "trace_id": record.trace_id,
            "anchored": True,
            "capability": record.capability,
            "outcome": record.outcome,
            "timestamp": record.timestamp,
            "anchor_height": record.anchor_height,
            "node_pubkey": record.node_pubkey,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def list_anchors_by_capability(capability: str, limit: int = 20) -> str:
    """List Thronglets traces anchored on-chain for a specific capability.

    Args:
        capability: Capability identifier (e.g. "urn:mcp:anthropic:claude:code")
        limit: Max records to return (default 20, max 100)

    Shows which traces have been verified on-chain for a given AI service.
    """
    try:
        limit = min(max(1, limit), 100)
        records = _client.anchors_by_capability(capability, limit=limit)
        result = []
        for r in records:
            result.append({
                "trace_id": r.trace_id,
                "outcome": r.outcome,
                "timestamp": r.timestamp,
                "anchor_height": r.anchor_height,
            })
        return json.dumps({
            "capability": capability,
            "anchors": result,
            "count": len(result),
        }, indent=2)
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
# Anchor — write (requires OASYCE_MNEMONIC)
# ---------------------------------------------------------------------------


@mcp.tool()
def anchor_trace(
    trace_id: str,
    node_pubkey: str,
    capability: str,
    outcome: int,
    timestamp: int,
    trace_signature: str,
) -> str:
    """Anchor a Thronglets trace on the Oasyce chain as immutable proof.

    Args:
        trace_id: Hex-encoded 64-char trace ID
        node_pubkey: Hex-encoded ed25519 public key of the Thronglets node
        capability: Capability identifier (e.g. "urn:mcp:anthropic:claude:code")
        outcome: Outcome code (1=succeeded, 2=failed, 3=partial, 4=timeout)
        timestamp: Trace creation time in unix milliseconds
        trace_signature: Hex-encoded ed25519 signature over the trace

    Requires OASYCE_MNEMONIC. Signer must match sha256(node_pubkey)[:20].
    ~110 bytes stored on-chain per anchor. Duplicates are rejected.
    """
    try:
        if len(trace_id) != 64:
            return json.dumps({"error": "trace_id must be 64 hex characters"})
        return _tx_result(_get_signer().anchor_trace(
            trace_id_hex=trace_id,
            node_pubkey_hex=node_pubkey,
            capability=capability,
            outcome=outcome,
            timestamp=timestamp,
            trace_signature_hex=trace_signature,
        ))
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Delegate (multi-agent delegation)
# ---------------------------------------------------------------------------


@mcp.tool()
def get_delegate_policy(principal: str) -> str:
    """Query a principal's delegation policy.

    Args:
        principal: Bech32 address of the principal account
    """
    try:
        p = _client.get_delegate_policy(principal)
        return json.dumps({
            "principal": p.principal,
            "per_tx_limit_uoas": p.per_tx_limit_uoas,
            "window_limit_uoas": p.window_limit_uoas,
            "window_seconds": p.window_seconds,
            "allowed_msgs": p.allowed_msgs,
            "expiration_seconds": p.expiration_seconds,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def list_delegates(principal: str) -> str:
    """List all delegates enrolled under a principal.

    Args:
        principal: Bech32 address of the principal account
    """
    try:
        records = _client.get_delegates(principal)
        return json.dumps([{
            "delegate": r.delegate,
            "principal": r.principal,
            "label": r.label,
        } for r in records], indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_delegate_spend(principal: str) -> str:
    """Query current spending window for a principal's delegates.

    Args:
        principal: Bech32 address of the principal account
    """
    try:
        w = _client.get_delegate_spend(principal)
        return json.dumps({
            "principal": w.principal,
            "window_start": w.window_start,
            "spent_uoas": w.spent_uoas,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_principal(delegate: str) -> str:
    """Query which principal a delegate belongs to (reverse lookup).

    Args:
        delegate: Bech32 address of the delegate agent
    """
    try:
        principal = _client.get_principal(delegate)
        return json.dumps({"principal": principal})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def set_delegate_policy(
    token: str,
    allowed_msgs: str,
    per_tx_uoas: int = 1_000_000,
    window_uoas: int = 10_000_000,
    window_seconds: int = 86400,
    expiration_seconds: int = 0,
) -> str:
    """Set delegation policy. One command — all agents operate under this.

    Args:
        token: Shared enrollment token (agents use this to self-register)
        allowed_msgs: Comma-separated list of allowed msg type URLs
        per_tx_uoas: Max spend per transaction in uoas (default 1 OAS)
        window_uoas: Budget window limit in uoas (default 10 OAS)
        window_seconds: Budget window duration in seconds (default 86400 = 1 day)
        expiration_seconds: Policy expiration in seconds (0 = no expiry)

    Requires OASYCE_MNEMONIC. Signer becomes the principal.
    """
    try:
        msgs = [m.strip() for m in allowed_msgs.split(",")]
        return _tx_result(_get_signer().set_delegate_policy(
            token=token,
            allowed_msgs=msgs,
            per_tx_uoas=per_tx_uoas,
            window_uoas=window_uoas,
            window_seconds=window_seconds,
            expiration_seconds=expiration_seconds,
        ))
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def enroll_delegate(principal: str, token: str, label: str = "") -> str:
    """Enroll as delegate under a principal. Agent auto-runs this on first start.

    Args:
        principal: Bech32 address of the principal account
        token: Enrollment token from the principal
        label: Optional label (e.g. 'macbook-agent-1')

    Requires OASYCE_MNEMONIC. Signer becomes the delegate.
    """
    try:
        return _tx_result(_get_signer().enroll_delegate(
            principal=principal,
            token=token,
            label=label,
        ))
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def revoke_delegate(delegate: str) -> str:
    """Remove a delegate from your policy (principal only).

    Args:
        delegate: Bech32 address of the delegate to revoke

    Requires OASYCE_MNEMONIC. Signer must be the principal.
    """
    try:
        return _tx_result(_get_signer().revoke_delegate(delegate))
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Sigil — unified identity lifecycle
# ---------------------------------------------------------------------------


@mcp.tool()
def get_sigil(sigil_id: str) -> str:
    """Query a Sigil by ID. Returns identity details including status, lineage, and metadata.

    Args:
        sigil_id: The Sigil identifier (e.g. "SIGIL_0000000000000001")

    A Sigil is the on-chain identity primitive — the full causal history attached to a key.
    """
    try:
        s = _client.get_sigil(sigil_id)
        return json.dumps({
            "id": s.id,
            "creator": s.creator,
            "status": s.status,
            "creation_height": s.creation_height,
            "lineage": s.lineage,
            "metadata": s.metadata,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_sigil_bonds(sigil_id: str) -> str:
    """List all bonds for a Sigil. Bonds are mutual links between two Sigils.

    Args:
        sigil_id: The Sigil identifier to query bonds for

    Returns bond details including both sides of each bond and scope.
    """
    try:
        bonds = _client.get_sigil_bonds(sigil_id)
        result = []
        for b in bonds:
            result.append({
                "sigil_a": b.sigil_a,
                "sigil_b": b.sigil_b,
                "scope": b.scope,
                "creation_height": b.creation_height,
            })
        return json.dumps({
            "sigil_id": sigil_id,
            "bonds": result,
            "count": len(result),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_sigil_lineage(sigil_id: str) -> str:
    """Get child Sigils (fork tree) for a given Sigil.

    Args:
        sigil_id: The parent Sigil identifier

    Returns list of child Sigil IDs that were forked from this parent.
    """
    try:
        children = _client.get_sigil_lineage(sigil_id)
        return json.dumps({
            "sigil_id": sigil_id,
            "children": children,
            "count": len(children),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_active_sigil_count() -> str:
    """Get the total number of active Sigils on the network.

    Returns the count of all non-dissolved Sigils.
    Use this to gauge network identity adoption.
    """
    try:
        count = _client.get_active_sigil_count()
        return json.dumps({
            "active_sigil_count": count,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def create_sigil(public_key_hex: str, metadata: str = "", lineage: str = "") -> str:
    """Create a new Sigil — the on-chain identity primitive for an agent.

    Args:
        public_key_hex: Hex-encoded secp256k1 public key for the new Sigil
        metadata: Optional metadata string (e.g. JSON with agent description)
        lineage: Optional comma-separated parent Sigil IDs (for lineage tracking)

    Requires OASYCE_MNEMONIC. The signer pays the creation fee.
    """
    if not _signer:
        return json.dumps({"error": "No wallet configured. Set OASYCE_MNEMONIC env var."})
    try:
        parent_ids = [p.strip() for p in lineage.split(",") if p.strip()] if lineage else []
        result = _signer.create_sigil(
            public_key_hex=public_key_hex,
            metadata=metadata,
            lineage=parent_ids,
        )
        return json.dumps({
            "tx_hash": result.tx_hash,
            "success": result.success,
            "code": result.code,
            "raw_log": result.raw_log if not result.success else "",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def dissolve_sigil(sigil_id: str) -> str:
    """Dissolve a Sigil permanently. This is irreversible.

    Args:
        sigil_id: The Sigil identifier to dissolve

    Requires OASYCE_MNEMONIC. Signer must be the Sigil creator.
    Dissolution is permanent — the Sigil's causal history is sealed.
    """
    if not _signer:
        return json.dumps({"error": "No wallet configured. Set OASYCE_MNEMONIC env var."})
    try:
        result = _signer.dissolve_sigil(sigil_id)
        return json.dumps({
            "tx_hash": result.tx_hash,
            "success": result.success,
            "code": result.code,
            "raw_log": result.raw_log if not result.success else "",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def bond_sigils(sigil_a: str, sigil_b: str, scope: str = "") -> str:
    """Create a bond between two Sigils — a mutual identity link.

    Args:
        sigil_a: First Sigil identifier
        sigil_b: Second Sigil identifier
        scope: Optional scope string describing the bond purpose

    Requires OASYCE_MNEMONIC. Signer must own one of the Sigils.
    Bonds are symmetric and represent trust or collaboration relationships.
    """
    if not _signer:
        return json.dumps({"error": "No wallet configured. Set OASYCE_MNEMONIC env var."})
    try:
        result = _signer.bond_sigils(sigil_a, sigil_b, scope=scope)
        return json.dumps({
            "tx_hash": result.tx_hash,
            "success": result.success,
            "code": result.code,
            "raw_log": result.raw_log if not result.success else "",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def fork_sigil(parent_sigil_id: str, child_public_key_hex: str, metadata: str = "") -> str:
    """Fork a child Sigil from a parent — identity lineage propagation.

    Args:
        parent_sigil_id: The parent Sigil to fork from
        child_public_key_hex: Hex-encoded secp256k1 public key for the child Sigil
        metadata: Optional metadata for the child Sigil

    Requires OASYCE_MNEMONIC. Signer must own the parent Sigil.
    The child inherits lineage from the parent, creating a verifiable fork tree.
    """
    if not _signer:
        return json.dumps({"error": "No wallet configured. Set OASYCE_MNEMONIC env var."})
    try:
        result = _signer.fork_sigil(
            parent_sigil_id=parent_sigil_id,
            child_public_key_hex=child_public_key_hex,
            metadata=metadata,
        )
        return json.dumps({
            "tx_hash": result.tx_hash,
            "success": result.success,
            "code": result.code,
            "raw_log": result.raw_log if not result.success else "",
        }, indent=2)
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

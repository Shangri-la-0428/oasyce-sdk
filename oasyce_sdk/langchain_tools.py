"""LangChain tool wrappers for Oasyce chain operations.

Install:
    pip install oasyce-sdk[langchain]

Usage:
    from oasyce_sdk.langchain_tools import oasyce_tools

    # Add to your agent:
    agent = create_react_agent(llm, oasyce_tools)
"""

from __future__ import annotations

import json
import os
from typing import List, Optional, Type

try:
    from langchain_core.tools import BaseTool
    from pydantic import BaseModel, Field
except ImportError:
    raise ImportError(
        "LangChain not installed. Run: pip install oasyce-sdk[langchain]"
    )

from .client import OasyceClient

NODE_URL = os.environ.get("OASYCE_NODE", "http://47.93.32.88:1317")
FAUCET_URL = os.environ.get("OASYCE_FAUCET", "http://47.93.32.88:8080")

_client = OasyceClient(NODE_URL)


# --- Input schemas ---


class AddressInput(BaseModel):
    address: str = Field(description="Oasyce bech32 address (oasyce1..., 45 chars)")


class TagInput(BaseModel):
    tag: str = Field(default="", description="Optional filter tag (e.g. 'nlp', 'summarization')")


class IssueInput(BaseModel):
    title: str = Field(description="Short description, prefix with [AI]")
    body: str = Field(description="Detailed description with reproduction steps")


# --- Tools ---


class OasyceHealthCheck(BaseTool):
    name: str = "oasyce_health_check"
    description: str = (
        "Check if the Oasyce chain node is alive. "
        "Returns chain ID and block height. Call this first."
    )

    def _run(self) -> str:
        import requests

        try:
            resp = requests.get(f"{NODE_URL}/health", timeout=5)
            if resp.status_code == 200:
                return json.dumps(resp.json())
            resp2 = requests.get(
                f"{NODE_URL}/cosmos/base/tendermint/v1beta1/node_info", timeout=5
            )
            d = resp2.json()
            return json.dumps({
                "status": "ok",
                "chain_id": d.get("default_node_info", {}).get("network", ""),
            })
        except Exception as e:
            return json.dumps({"error": str(e)})


class OasyceGetBalance(BaseTool):
    name: str = "oasyce_get_balance"
    description: str = (
        "Check token balance for an Oasyce address. "
        "1 OAS = 1,000,000 uoas."
    )
    args_schema: Type[BaseModel] = AddressInput

    def _run(self, address: str) -> str:
        try:
            bal = _client.get_balance(address)
            return json.dumps({"address": address, "uoas": bal.amount, "oas": bal.amount / 1_000_000})
        except Exception as e:
            return json.dumps({"error": str(e)})


class OasyceGetFaucetTokens(BaseTool):
    name: str = "oasyce_get_faucet_tokens"
    description: str = (
        "Get free testnet tokens (100 OAS) for an Oasyce address. "
        "Rate limit: 1/hour/address. No API key needed."
    )
    args_schema: Type[BaseModel] = AddressInput

    def _run(self, address: str) -> str:
        import requests

        resp = requests.get(f"{FAUCET_URL}/faucet", params={"address": address}, timeout=15)
        return resp.text


class OasyceGetAgentProfile(BaseTool):
    name: str = "oasyce_get_agent_profile"
    description: str = (
        "Get complete agent profile: balance, reputation, capabilities, "
        "earnings, work history, data assets. Single best endpoint for "
        "understanding an agent's on-chain identity."
    )
    args_schema: Type[BaseModel] = AddressInput

    def _run(self, address: str) -> str:
        import requests

        try:
            resp = requests.get(f"{NODE_URL}/oasyce/v1/agent-profile/{address}", timeout=10)
            return json.dumps(resp.json())
        except Exception as e:
            return json.dumps({"error": str(e)})


class OasyceBrowseMarketplace(BaseTool):
    name: str = "oasyce_browse_marketplace"
    description: str = (
        "Browse the Oasyce marketplace: AI services for sale, data assets "
        "with bonding curve pricing, and open compute tasks with bounties."
    )

    def _run(self) -> str:
        import requests

        try:
            resp = requests.get(f"{NODE_URL}/oasyce/v1/marketplace", timeout=10)
            return json.dumps(resp.json())
        except Exception as e:
            return json.dumps({"error": str(e)})


class OasyceListCapabilities(BaseTool):
    name: str = "oasyce_list_capabilities"
    description: str = (
        "List AI service capabilities on Oasyce marketplace. "
        "Filter by tag (e.g. 'nlp', 'summarization'). "
        "Each capability has a fixed price and automatic escrow."
    )
    args_schema: Type[BaseModel] = TagInput

    def _run(self, tag: str = "") -> str:
        try:
            caps = _client.list_capabilities(tag=tag if tag else None)
            result = [{"id": c.id, "name": c.name, "provider": c.provider,
                        "price_oas": c.price_per_call / 1_000_000, "tags": c.tags}
                       for c in caps]
            return json.dumps({"capabilities": result, "count": len(result)})
        except Exception as e:
            return json.dumps({"error": str(e)})


class OasyceGetReputation(BaseTool):
    name: str = "oasyce_get_reputation"
    description: str = (
        "Check an agent's on-chain reputation score (0-500). "
        "Higher = more trustworthy. 30-day decay half-life."
    )
    args_schema: Type[BaseModel] = AddressInput

    def _run(self, address: str) -> str:
        try:
            rep = _client.get_reputation(address)
            return json.dumps({"address": rep.address, "score": rep.score,
                               "total_feedbacks": rep.total_feedbacks})
        except Exception as e:
            return json.dumps({"error": str(e)})


class OasyceReportIssue(BaseTool):
    name: str = "oasyce_report_issue"
    description: str = (
        "Report a bug to the Oasyce team via on-chain issue proxy. "
        "No GitHub token needed."
    )
    args_schema: Type[BaseModel] = IssueInput

    def _run(self, title: str, body: str) -> str:
        import requests

        try:
            resp = requests.post(
                f"{NODE_URL}/api/v1/report-issue",
                json={"title": title, "body": body}, timeout=15,
            )
            return resp.text
        except Exception as e:
            return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Write tools — use the device wallet
# ---------------------------------------------------------------------------

_signer = None
_identity = None


def _get_identity():
    global _identity
    if _identity is not None:
        return _identity
    from .identity import IdentityResolver
    _identity = IdentityResolver.resolve()
    return _identity


def _get_signer():
    global _signer
    if _signer is not None:
        return _signer
    from .crypto import NativeSigner
    wallet = _get_identity().wallet
    chain_id = os.environ.get("OASYCE_CHAIN_ID", "oasyce-testnet-1")
    _signer = NativeSigner(wallet, _client, chain_id=chain_id)
    return _signer


def _tx_json(result) -> str:
    return json.dumps({
        "tx_hash": result.tx_hash, "success": result.success,
        "code": result.code, "raw_log": result.raw_log if not result.success else "",
    })


class CreateWalletInput(BaseModel):
    pass


class SendTokensInput(BaseModel):
    to_address: str = Field(description="Recipient oasyce1... address")
    amount_uoas: int = Field(description="Amount in uoas (1 OAS = 1,000,000 uoas)")


class RegisterCapabilityInput(BaseModel):
    name: str = Field(description="Service name")
    endpoint: str = Field(description="HTTP endpoint URL")
    price_uoas: int = Field(description="Price per call in uoas")
    tags: str = Field(default="", description="Comma-separated tags")
    description: str = Field(default="", description="Service description")


class InvokeCapabilityInput(BaseModel):
    capability_id: str = Field(description="Capability ID (e.g. CAP_0000000000000001)")
    input_data: str = Field(default="", description="Optional input string")


class InvocationIdInput(BaseModel):
    invocation_id: str = Field(description="Invocation ID")


class DisputeInvocationInput(BaseModel):
    invocation_id: str = Field(description="Invocation ID")
    reason: str = Field(description="Dispute reason")


class RegisterAssetInput(BaseModel):
    name: str = Field(description="Asset name")
    content_hash: str = Field(description="SHA256 hash of content")
    tags: str = Field(default="", description="Comma-separated tags")
    description: str = Field(default="", description="Asset description")
    service_url: str = Field(default="", description="Data access URL")


class AssetAmountInput(BaseModel):
    asset_id: str = Field(description="Data asset ID")
    amount_uoas: int = Field(description="Amount in uoas")


class AssetSharesInput(BaseModel):
    asset_id: str = Field(description="Data asset ID")
    shares: int = Field(description="Number of shares")


class FeedbackInput(BaseModel):
    invocation_id: str = Field(description="Invocation ID to rate")
    rating: int = Field(description="Score 1-5")
    comment: str = Field(default="", description="Optional text feedback")


class OasyceCreateWallet(BaseTool):
    name: str = "oasyce_create_wallet"
    description: str = "Generate a new Oasyce wallet. Returns mnemonic + address. SAVE THE MNEMONIC."

    def _run(self) -> str:
        from .crypto import Wallet
        w = Wallet.create()
        return json.dumps({"mnemonic": w.mnemonic, "address": w.address})


class OasyceSendTokens(BaseTool):
    name: str = "oasyce_send_tokens"
    description: str = "Send OAS tokens using the device wallet."
    args_schema: Type[BaseModel] = SendTokensInput

    def _run(self, to_address: str, amount_uoas: int) -> str:
        try:
            return _tx_json(_get_signer().send(to_address, amount_uoas))
        except Exception as e:
            return json.dumps({"error": str(e)})


class OasyceRegisterCapability(BaseTool):
    name: str = "oasyce_register_capability"
    description: str = (
        "Register an AI service on Oasyce marketplace. "
        "Uses the device wallet."
    )
    args_schema: Type[BaseModel] = RegisterCapabilityInput

    def _run(self, name: str, endpoint: str, price_uoas: int,
             tags: str = "", description: str = "") -> str:
        try:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
            return _tx_json(_get_signer().register_capability(
                name=name, endpoint=endpoint, price_uoas=price_uoas,
                tags=tag_list, description=description,
            ))
        except Exception as e:
            return json.dumps({"error": str(e)})


class OasyceInvokeCapability(BaseTool):
    name: str = "oasyce_invoke_capability"
    description: str = "Invoke an AI service. Payment auto-escrowed. Uses the device wallet."
    args_schema: Type[BaseModel] = InvokeCapabilityInput

    def _run(self, capability_id: str, input_data: str = "") -> str:
        try:
            data = input_data.encode() if input_data else None
            return _tx_json(_get_signer().invoke_capability(capability_id, data))
        except Exception as e:
            return json.dumps({"error": str(e)})


class OasyceClaimInvocation(BaseTool):
    name: str = "oasyce_claim_invocation"
    description: str = "Claim payment after challenge window (provider). Uses the device wallet."
    args_schema: Type[BaseModel] = InvocationIdInput

    def _run(self, invocation_id: str) -> str:
        try:
            return _tx_json(_get_signer().claim_invocation(invocation_id))
        except Exception as e:
            return json.dumps({"error": str(e)})


class OasyceDisputeInvocation(BaseTool):
    name: str = "oasyce_dispute_invocation"
    description: str = "Dispute an invocation within challenge window (consumer). Uses the device wallet."
    args_schema: Type[BaseModel] = DisputeInvocationInput

    def _run(self, invocation_id: str, reason: str) -> str:
        try:
            return _tx_json(_get_signer().dispute_invocation(invocation_id, reason))
        except Exception as e:
            return json.dumps({"error": str(e)})


class OasyceRegisterDataAsset(BaseTool):
    name: str = "oasyce_register_data_asset"
    description: str = "Register a data asset with Bancor bonding curve. Uses the device wallet."
    args_schema: Type[BaseModel] = RegisterAssetInput

    def _run(self, name: str, content_hash: str, tags: str = "",
             description: str = "", service_url: str = "") -> str:
        try:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
            return _tx_json(_get_signer().register_asset(
                name=name, content_hash=content_hash, tags=tag_list,
                description=description, service_url=service_url,
            ))
        except Exception as e:
            return json.dumps({"error": str(e)})


class OasyceBuyShares(BaseTool):
    name: str = "oasyce_buy_data_shares"
    description: str = "Buy shares of a data asset on bonding curve. Uses the device wallet."
    args_schema: Type[BaseModel] = AssetAmountInput

    def _run(self, asset_id: str, amount_uoas: int) -> str:
        try:
            return _tx_json(_get_signer().buy_shares(asset_id, amount_uoas))
        except Exception as e:
            return json.dumps({"error": str(e)})


class OasyceSellShares(BaseTool):
    name: str = "oasyce_sell_data_shares"
    description: str = "Sell data asset shares back to bonding curve. Uses the device wallet."
    args_schema: Type[BaseModel] = AssetSharesInput

    def _run(self, asset_id: str, shares: int) -> str:
        try:
            return _tx_json(_get_signer().sell_shares(asset_id, shares))
        except Exception as e:
            return json.dumps({"error": str(e)})


class OasyceSubmitFeedback(BaseTool):
    name: str = "oasyce_submit_feedback"
    description: str = "Rate a completed invocation (1-5). Affects provider reputation. Uses the device wallet."
    args_schema: Type[BaseModel] = FeedbackInput

    def _run(self, invocation_id: str, rating: int, comment: str = "") -> str:
        try:
            return _tx_json(_get_signer().submit_feedback(invocation_id, rating, comment))
        except Exception as e:
            return json.dumps({"error": str(e)})


# Convenience lists
oasyce_read_tools: List[BaseTool] = [
    OasyceHealthCheck(),
    OasyceGetBalance(),
    OasyceGetFaucetTokens(),
    OasyceGetAgentProfile(),
    OasyceBrowseMarketplace(),
    OasyceListCapabilities(),
    OasyceGetReputation(),
    OasyceReportIssue(),
]

oasyce_write_tools: List[BaseTool] = [
    OasyceCreateWallet(),
    OasyceSendTokens(),
    OasyceRegisterCapability(),
    OasyceInvokeCapability(),
    OasyceClaimInvocation(),
    OasyceDisputeInvocation(),
    OasyceRegisterDataAsset(),
    OasyceBuyShares(),
    OasyceSellShares(),
    OasyceSubmitFeedback(),
]

oasyce_tools: List[BaseTool] = oasyce_read_tools + oasyce_write_tools

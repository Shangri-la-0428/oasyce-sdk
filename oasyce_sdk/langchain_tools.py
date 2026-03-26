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


class OasyecBrowseMarketplace(BaseTool):
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


# Convenience list for agent setup
oasyce_tools: List[BaseTool] = [
    OasyceHealthCheck(),
    OasyceGetBalance(),
    OasyceGetFaucetTokens(),
    OasyceGetAgentProfile(),
    OasyecBrowseMarketplace(),
    OasyceListCapabilities(),
    OasyceGetReputation(),
    OasyceReportIssue(),
]

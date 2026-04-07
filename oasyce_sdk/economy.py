"""Economic perception layer for AI delegates.

Aggregates chain state into synthesized economic views that give AI models
enough context to make autonomous economic decisions.

No strategy, no autopilot — just perception.  The AI model is the brain;
this module is proprioception.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .client import OasyceClient

_UOAS = 1_000_000


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DataPosition:
    """A held position in a data asset."""
    asset_id: str
    asset_name: str
    shares: int
    total_shares: int
    equity_pct: float
    estimated_value_uoas: int


@dataclass(frozen=True)
class CapabilityIncome:
    """Income from a registered capability service."""
    capability_id: str
    name: str
    price_uoas: int
    total_earned_uoas: int
    total_calls: int
    active: bool


@dataclass(frozen=True)
class WorkOpportunity:
    """A work task matched to agent capabilities."""
    task_id: str
    task_type: str
    bounty_uoas: int
    creator: str
    redundancy: int


# ---------------------------------------------------------------------------
# EconomicSnapshot — the core perception object
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EconomicSnapshot:
    """Synthesized economic state for AI reasoning."""

    # Identity
    address: str

    # Balance sheet
    liquid_uoas: int
    locked_in_escrow_uoas: int
    data_equity_value_uoas: int
    net_worth_uoas: int

    # Positions
    capabilities: List[CapabilityIncome]
    data_positions: List[DataPosition]
    active_escrows: List[Dict[str, Any]]

    # Earnings
    total_earned_uoas: int
    total_capability_calls: int

    # Delegate budget
    has_delegate_policy: bool
    window_limit_uoas: int
    window_spent_uoas: int
    window_remaining_uoas: int
    per_tx_limit_uoas: int

    # Executor
    is_executor: bool
    executor_task_types: List[str]
    tasks_completed: int
    tasks_failed: int

    # Reputation & debt
    reputation_score: int
    debt_remaining_uoas: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": {"address": self.address},
            "balance_sheet": {
                "liquid_oas": self.liquid_uoas / _UOAS,
                "locked_in_escrow_oas": self.locked_in_escrow_uoas / _UOAS,
                "data_equity_oas": self.data_equity_value_uoas / _UOAS,
                "net_worth_oas": self.net_worth_uoas / _UOAS,
            },
            "budget": {
                "has_delegate_policy": self.has_delegate_policy,
                "window_limit_oas": self.window_limit_uoas / _UOAS,
                "window_spent_oas": self.window_spent_uoas / _UOAS,
                "window_remaining_oas": self.window_remaining_uoas / _UOAS,
                "per_tx_limit_oas": self.per_tx_limit_uoas / _UOAS,
            },
            "earnings": {
                "total_earned_oas": self.total_earned_uoas / _UOAS,
                "total_capability_calls": self.total_capability_calls,
            },
            "positions": {
                "capabilities": [
                    {
                        "id": c.capability_id,
                        "name": c.name,
                        "price_oas": c.price_uoas / _UOAS,
                        "earned_oas": c.total_earned_uoas / _UOAS,
                        "calls": c.total_calls,
                        "active": c.active,
                    }
                    for c in self.capabilities
                ],
                "data_assets": [
                    {
                        "asset_id": p.asset_id,
                        "name": p.asset_name,
                        "shares": p.shares,
                        "equity_pct": round(p.equity_pct, 2),
                        "value_oas": p.estimated_value_uoas / _UOAS,
                    }
                    for p in self.data_positions
                ],
                "escrows": self.active_escrows,
            },
            "executor": {
                "registered": self.is_executor,
                "task_types": self.executor_task_types,
                "completed": self.tasks_completed,
                "failed": self.tasks_failed,
            },
            "reputation": {"score": self.reputation_score},
            "debt": {
                "remaining_oas": self.debt_remaining_uoas / _UOAS,
            },
        }


# ---------------------------------------------------------------------------
# Builder functions — pure reads, no side effects
# ---------------------------------------------------------------------------

def _safe(fn, default=None):
    """Call *fn*; swallow exceptions and return *default*."""
    try:
        return fn()
    except Exception:
        return default


def build_snapshot(client: OasyceClient, address: str) -> EconomicSnapshot:
    """Aggregate chain queries into a single economic snapshot."""

    # Balance
    bal = _safe(lambda: client.get_balance(address))
    liquid = bal.amount_uoas if bal else 0

    # Locked escrows
    locked = 0
    escrow_list: List[Dict[str, Any]] = []
    escrows = _safe(lambda: client.list_escrows(address), [])
    for e in escrows:
        if e.status == "LOCKED":
            locked += e.amount_uoas
            escrow_list.append({
                "id": e.escrow_id,
                "amount_oas": e.amount_uoas / _UOAS,
                "provider": e.provider,
            })

    # Capabilities (income sources)
    caps_income: List[CapabilityIncome] = []
    earned = 0
    calls = 0
    caps = _safe(lambda: client.list_capabilities(provider=address), [])
    for c in caps:
        caps_income.append(CapabilityIncome(
            capability_id=c.capability_id,
            name=c.name,
            price_uoas=c.price_per_call,
            total_earned_uoas=c.total_earned,
            total_calls=c.total_calls,
            active=c.active,
        ))
        earned += c.total_earned
        calls += c.total_calls

    # Aggregate earnings may include work rewards
    agg = _safe(lambda: client.get_earnings(address))
    if agg and agg.total_earned_uoas > earned:
        earned = agg.total_earned_uoas
        calls = max(calls, agg.total_calls)

    # Data asset positions (owned assets)
    positions: List[DataPosition] = []
    equity_value = 0
    owned = _safe(lambda: client.list_assets(owner=address), [])
    for asset in owned:
        curve = _safe(lambda a=asset: client.get_bonding_curve(a.asset_id))
        shares_list = _safe(lambda a=asset: client.get_shares(a.asset_id), [])
        my_shares = 0
        for sh in shares_list:
            if sh.address == address:
                my_shares = sh.shares
                break
        total = asset.total_shares or 1
        pct = (my_shares / total * 100) if total > 0 else 0
        est = int(curve.reserve_uoas * my_shares / total) if (curve and total > 0) else 0
        positions.append(DataPosition(
            asset_id=asset.asset_id,
            asset_name=asset.name,
            shares=my_shares,
            total_shares=total,
            equity_pct=pct,
            estimated_value_uoas=est,
        ))
        equity_value += est

    # Delegate budget
    has_policy = False
    wlimit = wspent = ptx = 0
    principal = _safe(lambda: client.get_principal(address), "")
    if principal:
        policy = _safe(lambda: client.get_delegate_policy(principal))
        if policy:
            has_policy = True
            wlimit = policy.window_limit_uoas
            ptx = policy.per_tx_limit_uoas
            spend = _safe(lambda: client.get_delegate_spend(principal))
            if spend:
                wspent = spend.spent_uoas

    # Executor profile
    exe = _safe(lambda: client.get_executor(address))
    is_exe = bool(exe and exe.active)
    exe_types = exe.supported_task_types if exe else []
    completed = exe.tasks_completed if exe else 0
    failed = exe.tasks_failed if exe else 0

    # Reputation
    rep = _safe(lambda: client.get_reputation(address))
    rep_score = rep.score if rep else 0

    # Onboarding debt
    debt = _safe(lambda: client.get_debt(address))
    debt_rem = debt.remaining if debt else 0

    net_worth = liquid + locked + equity_value

    return EconomicSnapshot(
        address=address,
        liquid_uoas=liquid,
        locked_in_escrow_uoas=locked,
        data_equity_value_uoas=equity_value,
        net_worth_uoas=net_worth,
        capabilities=caps_income,
        data_positions=positions,
        active_escrows=escrow_list,
        total_earned_uoas=earned,
        total_capability_calls=calls,
        has_delegate_policy=has_policy,
        window_limit_uoas=wlimit,
        window_spent_uoas=wspent,
        window_remaining_uoas=max(0, wlimit - wspent),
        per_tx_limit_uoas=ptx,
        is_executor=is_exe,
        executor_task_types=exe_types,
        tasks_completed=completed,
        tasks_failed=failed,
        reputation_score=rep_score,
        debt_remaining_uoas=debt_rem,
    )


def find_opportunities(
    client: OasyceClient,
    address: str,
    task_types: Optional[List[str]] = None,
) -> List[WorkOpportunity]:
    """Find open tasks matching agent capabilities, sorted by bounty."""

    if task_types is None:
        exe = _safe(lambda: client.get_executor(address))
        task_types = exe.supported_task_types if exe else []

    tasks = _safe(lambda: client.list_tasks(status=1), [])
    opps = []
    for t in tasks:
        if t.creator == address:
            continue
        if task_types and t.task_type not in task_types:
            continue
        opps.append(WorkOpportunity(
            task_id=t.task_id,
            task_type=t.task_type,
            bounty_uoas=t.bounty_uoas,
            creator=t.creator,
            redundancy=t.redundancy,
        ))
    opps.sort(key=lambda o: o.bounty_uoas, reverse=True)
    return opps


def build_portfolio(client: OasyceClient, address: str) -> Dict[str, Any]:
    """Detailed portfolio: owned assets, capability services, valuations."""

    data_value = 0
    cap_revenue = 0
    assets_owned = []
    capabilities = []

    for asset in _safe(lambda: client.list_assets(owner=address), []):
        entry: Dict[str, Any] = {
            "asset_id": asset.asset_id,
            "name": asset.name,
            "tags": asset.tags,
            "total_shares": asset.total_shares,
            "status": asset.status,
            "rights_type": asset.rights_type,
        }
        curve = _safe(lambda a=asset: client.get_bonding_curve(a.asset_id))
        if curve:
            entry["reserve_oas"] = curve.reserve_uoas / _UOAS
            entry["spot_price_oas"] = curve.spot_price_uoas / _UOAS
            entry["buyer_count"] = curve.buyer_count
            data_value += curve.reserve_uoas
        else:
            entry["reserve_oas"] = 0
            entry["spot_price_oas"] = 0
        assets_owned.append(entry)

    for c in _safe(lambda: client.list_capabilities(provider=address), []):
        capabilities.append({
            "id": c.capability_id,
            "name": c.name,
            "price_oas": c.price_per_call / _UOAS,
            "earned_oas": c.total_earned / _UOAS,
            "calls": c.total_calls,
            "active": c.active,
        })
        cap_revenue += c.total_earned

    return {
        "address": address,
        "data_assets": assets_owned,
        "capabilities": capabilities,
        "summary": {
            "assets_count": len(assets_owned),
            "data_reserve_oas": data_value / _UOAS,
            "capabilities_count": len(capabilities),
            "capability_revenue_oas": cap_revenue / _UOAS,
        },
    }


def estimate_cost(
    client: OasyceClient,
    action: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Estimate cost of an economic action before executing.

    Supported actions:
        invoke_capability  — params: {capability_id}
        buy_data_shares    — params: {asset_id, amount_uoas}
        submit_task        — params: {bounty_uoas}
        anchor_trace       — params: {}
        register_capability / register_data_asset — params: {}
    """
    gas = 10_000  # standard gas estimate in uoas

    result: Dict[str, Any] = {
        "action": action,
        "gas_estimate_oas": gas / _UOAS,
    }

    if action == "invoke_capability":
        cap = _safe(lambda: client.get_capability(params.get("capability_id", "")))
        if cap:
            cost = cap.price_per_call
            result["service_cost_oas"] = cost / _UOAS
            result["total_cost_oas"] = (cost + gas) / _UOAS
            result["provider"] = cap.provider
        else:
            result["error"] = "capability not found"

    elif action == "buy_data_shares":
        amount = int(params.get("amount_uoas", 0))
        result["investment_oas"] = amount / _UOAS
        result["total_cost_oas"] = (amount + gas) / _UOAS
        curve = _safe(
            lambda: client.get_bonding_curve(params.get("asset_id", ""))
        )
        if curve and curve.spot_price_uoas > 0:
            result["estimated_shares"] = amount // curve.spot_price_uoas
            result["spot_price_oas"] = curve.spot_price_uoas / _UOAS

    elif action == "submit_task":
        bounty = int(params.get("bounty_uoas", 0))
        deposit = int(bounty * 0.10)
        result["bounty_oas"] = bounty / _UOAS
        result["deposit_oas"] = deposit / _UOAS
        result["total_cost_oas"] = (bounty + deposit + gas) / _UOAS
        result["note"] = "deposit returned on settlement; 3% rebate on success"

    elif action in ("anchor_trace", "register_capability", "register_data_asset"):
        result["total_cost_oas"] = gas / _UOAS

    else:
        result["error"] = f"unknown action: {action}"

    return result

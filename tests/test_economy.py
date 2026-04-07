"""Unit tests for the economic perception layer.

All chain queries are mocked — no running node required.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from oasyce_sdk.client import OasyceClient
from oasyce_sdk.economy import (
    CapabilityIncome,
    DataPosition,
    EconomicSnapshot,
    WorkOpportunity,
    build_portfolio,
    build_snapshot,
    estimate_cost,
    find_opportunities,
)
from oasyce_sdk.types import (
    Balance,
    BondingCurve,
    Capability,
    DataAsset,
    Debt,
    DelegatePolicy,
    Earnings,
    Escrow,
    Executor,
    Reputation,
    ShareHolder,
    SpendWindow,
    Task,
)

ADDR = "oasyce1testaddr"
PRINCIPAL = "oasyce1principal"


def _client() -> OasyceClient:
    return OasyceClient("http://testnode:1317", timeout=1)


class TestBuildSnapshot(unittest.TestCase):
    """build_snapshot aggregates multiple queries correctly."""

    def test_empty_state(self):
        """New agent with no chain presence gets a valid zero snapshot."""
        c = _client()
        c.get_balance = MagicMock(return_value=Balance(ADDR, 0, 0.0))
        c.list_escrows = MagicMock(return_value=[])
        c.list_capabilities = MagicMock(return_value=[])
        c.get_earnings = MagicMock(side_effect=Exception("not found"))
        c.list_assets = MagicMock(return_value=[])
        c.get_principal = MagicMock(return_value="")
        c.get_executor = MagicMock(side_effect=Exception("not found"))
        c.get_reputation = MagicMock(side_effect=Exception("not found"))
        c.get_debt = MagicMock(side_effect=Exception("not found"))

        snap = build_snapshot(c, ADDR)

        self.assertEqual(snap.address, ADDR)
        self.assertEqual(snap.liquid_uoas, 0)
        self.assertEqual(snap.net_worth_uoas, 0)
        self.assertFalse(snap.is_executor)
        self.assertEqual(snap.reputation_score, 0)

    def test_with_balance_and_escrows(self):
        c = _client()
        c.get_balance = MagicMock(return_value=Balance(ADDR, 50_000_000, 50.0))
        c.list_escrows = MagicMock(return_value=[
            Escrow("esc-1", ADDR, "oasyce1prov", 5_000_000, "LOCKED"),
            Escrow("esc-2", ADDR, "oasyce1prov", 3_000_000, "RELEASED"),
        ])
        c.list_capabilities = MagicMock(return_value=[])
        c.get_earnings = MagicMock(side_effect=Exception("nf"))
        c.list_assets = MagicMock(return_value=[])
        c.get_principal = MagicMock(return_value="")
        c.get_executor = MagicMock(side_effect=Exception("nf"))
        c.get_reputation = MagicMock(side_effect=Exception("nf"))
        c.get_debt = MagicMock(side_effect=Exception("nf"))

        snap = build_snapshot(c, ADDR)

        self.assertEqual(snap.liquid_uoas, 50_000_000)
        self.assertEqual(snap.locked_in_escrow_uoas, 5_000_000)  # only LOCKED
        self.assertEqual(snap.net_worth_uoas, 55_000_000)
        self.assertEqual(len(snap.active_escrows), 1)

    def test_with_capabilities_and_earnings(self):
        c = _client()
        c.get_balance = MagicMock(return_value=Balance(ADDR, 10_000_000, 10.0))
        c.list_escrows = MagicMock(return_value=[])
        c.list_capabilities = MagicMock(return_value=[
            Capability(
                capability_id="cap-1", name="code-review", provider=ADDR,
                description="", endpoint_url="", price_per_call=500_000,
                tags=[], rate_limit=100, total_calls=20,
                total_earned=10_000_000, avg_latency_ms=0,
                success_rate=9500, active=True,
            ),
        ])
        c.get_earnings = MagicMock(
            return_value=Earnings(ADDR, 15_000_000, 25)
        )
        c.list_assets = MagicMock(return_value=[])
        c.get_principal = MagicMock(return_value="")
        c.get_executor = MagicMock(side_effect=Exception("nf"))
        c.get_reputation = MagicMock(
            return_value=Reputation(ADDR, 85, 10, 5)
        )
        c.get_debt = MagicMock(return_value=Debt(ADDR, 20_000_000, 12_000_000, 8_000_000, "ACTIVE"))

        snap = build_snapshot(c, ADDR)

        self.assertEqual(len(snap.capabilities), 1)
        self.assertEqual(snap.capabilities[0].name, "code-review")
        # get_earnings returns higher, so it wins
        self.assertEqual(snap.total_earned_uoas, 15_000_000)
        self.assertEqual(snap.reputation_score, 85)
        self.assertEqual(snap.debt_remaining_uoas, 8_000_000)

    def test_with_delegate_policy(self):
        c = _client()
        c.get_balance = MagicMock(return_value=Balance(ADDR, 0, 0.0))
        c.list_escrows = MagicMock(return_value=[])
        c.list_capabilities = MagicMock(return_value=[])
        c.get_earnings = MagicMock(side_effect=Exception("nf"))
        c.list_assets = MagicMock(return_value=[])
        c.get_principal = MagicMock(return_value=PRINCIPAL)
        c.get_delegate_policy = MagicMock(
            return_value=DelegatePolicy(
                PRINCIPAL, 10_000_000, 100_000_000, 86400, [], 0, 0
            )
        )
        c.get_delegate_spend = MagicMock(
            return_value=SpendWindow(PRINCIPAL, 0, 25_000_000)
        )
        c.get_executor = MagicMock(side_effect=Exception("nf"))
        c.get_reputation = MagicMock(side_effect=Exception("nf"))
        c.get_debt = MagicMock(side_effect=Exception("nf"))

        snap = build_snapshot(c, ADDR)

        self.assertTrue(snap.has_delegate_policy)
        self.assertEqual(snap.window_limit_uoas, 100_000_000)
        self.assertEqual(snap.window_spent_uoas, 25_000_000)
        self.assertEqual(snap.window_remaining_uoas, 75_000_000)
        self.assertEqual(snap.per_tx_limit_uoas, 10_000_000)

    def test_with_data_assets(self):
        c = _client()
        c.get_balance = MagicMock(return_value=Balance(ADDR, 0, 0.0))
        c.list_escrows = MagicMock(return_value=[])
        c.list_capabilities = MagicMock(return_value=[])
        c.get_earnings = MagicMock(side_effect=Exception("nf"))
        c.list_assets = MagicMock(return_value=[
            DataAsset(
                asset_id="asset-1", name="training-data", owner=ADDR,
                description="", content_hash="", fingerprint="",
                rights_type="ORIGINAL", tags=[], total_shares=1000,
                status="ACTIVE", version=1, parent_asset_id="",
            ),
        ])
        c.get_bonding_curve = MagicMock(
            return_value=BondingCurve("asset-1", 1000, 20_000_000, 20_000, "", 5)
        )
        c.get_shares = MagicMock(return_value=[
            ShareHolder(ADDR, "asset-1", 500),
            ShareHolder("oasyce1other", "asset-1", 500),
        ])
        c.get_principal = MagicMock(return_value="")
        c.get_executor = MagicMock(side_effect=Exception("nf"))
        c.get_reputation = MagicMock(side_effect=Exception("nf"))
        c.get_debt = MagicMock(side_effect=Exception("nf"))

        snap = build_snapshot(c, ADDR)

        self.assertEqual(len(snap.data_positions), 1)
        pos = snap.data_positions[0]
        self.assertEqual(pos.shares, 500)
        self.assertAlmostEqual(pos.equity_pct, 50.0)
        # 500/1000 * 20_000_000 = 10_000_000
        self.assertEqual(pos.estimated_value_uoas, 10_000_000)
        self.assertEqual(snap.data_equity_value_uoas, 10_000_000)

    def test_to_dict_roundtrip(self):
        """to_dict returns valid JSON-serializable structure."""
        import json

        c = _client()
        c.get_balance = MagicMock(return_value=Balance(ADDR, 1_000_000, 1.0))
        c.list_escrows = MagicMock(return_value=[])
        c.list_capabilities = MagicMock(return_value=[])
        c.get_earnings = MagicMock(side_effect=Exception("nf"))
        c.list_assets = MagicMock(return_value=[])
        c.get_principal = MagicMock(return_value="")
        c.get_executor = MagicMock(side_effect=Exception("nf"))
        c.get_reputation = MagicMock(side_effect=Exception("nf"))
        c.get_debt = MagicMock(side_effect=Exception("nf"))

        snap = build_snapshot(c, ADDR)
        d = snap.to_dict()
        text = json.dumps(d)  # must not raise
        parsed = json.loads(text)
        self.assertEqual(parsed["balance_sheet"]["liquid_oas"], 1.0)

    def test_resilient_to_partial_failures(self):
        """Snapshot builds even when most queries fail."""
        c = _client()
        c.get_balance = MagicMock(side_effect=Exception("down"))
        c.list_escrows = MagicMock(side_effect=Exception("down"))
        c.list_capabilities = MagicMock(side_effect=Exception("down"))
        c.get_earnings = MagicMock(side_effect=Exception("down"))
        c.list_assets = MagicMock(side_effect=Exception("down"))
        c.get_principal = MagicMock(side_effect=Exception("down"))
        c.get_executor = MagicMock(side_effect=Exception("down"))
        c.get_reputation = MagicMock(side_effect=Exception("down"))
        c.get_debt = MagicMock(side_effect=Exception("down"))

        snap = build_snapshot(c, ADDR)
        self.assertEqual(snap.liquid_uoas, 0)
        self.assertEqual(snap.net_worth_uoas, 0)


class TestFindOpportunities(unittest.TestCase):

    def test_filters_by_task_type(self):
        c = _client()
        c.get_executor = MagicMock(
            return_value=Executor(ADDR, ["code-review"], 1000, 5, 0, True)
        )
        c.list_tasks = MagicMock(return_value=[
            Task("1", "oasyce1x", "code-review", 5_000_000, 500_000, "SUBMITTED", 3, []),
            Task("2", "oasyce1y", "data-analysis", 3_000_000, 300_000, "SUBMITTED", 3, []),
            Task("3", ADDR, "code-review", 2_000_000, 200_000, "SUBMITTED", 3, []),  # own task
        ])

        opps = find_opportunities(c, ADDR)

        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].task_id, "1")
        self.assertEqual(opps[0].bounty_uoas, 5_000_000)

    def test_explicit_task_types(self):
        c = _client()
        c.list_tasks = MagicMock(return_value=[
            Task("1", "oasyce1x", "translation", 8_000_000, 800_000, "SUBMITTED", 3, []),
            Task("2", "oasyce1y", "code-review", 3_000_000, 300_000, "SUBMITTED", 3, []),
        ])

        opps = find_opportunities(c, ADDR, task_types=["translation"])

        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].task_type, "translation")

    def test_sorted_by_bounty_desc(self):
        c = _client()
        c.list_tasks = MagicMock(return_value=[
            Task("1", "oasyce1x", "a", 1_000_000, 100_000, "SUBMITTED", 3, []),
            Task("2", "oasyce1y", "a", 9_000_000, 900_000, "SUBMITTED", 3, []),
            Task("3", "oasyce1z", "a", 5_000_000, 500_000, "SUBMITTED", 3, []),
        ])

        opps = find_opportunities(c, ADDR, task_types=["a"])

        self.assertEqual(opps[0].bounty_uoas, 9_000_000)
        self.assertEqual(opps[1].bounty_uoas, 5_000_000)
        self.assertEqual(opps[2].bounty_uoas, 1_000_000)

    def test_empty_when_no_tasks(self):
        c = _client()
        c.list_tasks = MagicMock(return_value=[])

        opps = find_opportunities(c, ADDR, task_types=["code-review"])
        self.assertEqual(opps, [])


class TestBuildPortfolio(unittest.TestCase):

    def test_portfolio_with_assets_and_capabilities(self):
        c = _client()
        c.list_assets = MagicMock(return_value=[
            DataAsset(
                "a1", "my-dataset", ADDR, "", "", "", "ORIGINAL",
                ["nlp"], 1000, "ACTIVE", 1, "",
            ),
        ])
        c.get_bonding_curve = MagicMock(
            return_value=BondingCurve("a1", 1000, 10_000_000, 10_000, "", 3)
        )
        c.list_capabilities = MagicMock(return_value=[
            Capability(
                "cap-1", "translator", ADDR, "", "", 200_000,
                ["nlp"], 100, 50, 10_000_000, 0, 9800, True,
            ),
        ])

        pf = build_portfolio(c, ADDR)

        self.assertEqual(pf["summary"]["assets_count"], 1)
        self.assertEqual(pf["summary"]["capabilities_count"], 1)
        self.assertAlmostEqual(pf["summary"]["data_reserve_oas"], 10.0)
        self.assertAlmostEqual(pf["summary"]["capability_revenue_oas"], 10.0)

    def test_empty_portfolio(self):
        c = _client()
        c.list_assets = MagicMock(return_value=[])
        c.list_capabilities = MagicMock(return_value=[])

        pf = build_portfolio(c, ADDR)
        self.assertEqual(pf["summary"]["assets_count"], 0)
        self.assertEqual(pf["summary"]["capabilities_count"], 0)


class TestEstimateCost(unittest.TestCase):

    def test_invoke_capability(self):
        c = _client()
        c.get_capability = MagicMock(
            return_value=Capability(
                "cap-1", "proxy", "oasyce1prov", "", "", 500_000,
                [], 100, 0, 0, 0, 0, True,
            )
        )
        result = estimate_cost(c, "invoke_capability", {"capability_id": "cap-1"})
        self.assertAlmostEqual(result["service_cost_oas"], 0.5)
        self.assertIn("total_cost_oas", result)
        self.assertNotIn("error", result)

    def test_submit_task(self):
        c = _client()
        result = estimate_cost(c, "submit_task", {"bounty_uoas": 5_000_000})
        self.assertAlmostEqual(result["bounty_oas"], 5.0)
        self.assertAlmostEqual(result["deposit_oas"], 0.5)
        # total = bounty + deposit + gas = 5.5 + 0.01
        self.assertGreater(result["total_cost_oas"], 5.5)

    def test_buy_data_shares(self):
        c = _client()
        c.get_bonding_curve = MagicMock(
            return_value=BondingCurve("a1", 1000, 10_000_000, 10_000, "", 3)
        )
        result = estimate_cost(c, "buy_data_shares", {
            "asset_id": "a1",
            "amount_uoas": 1_000_000,
        })
        self.assertAlmostEqual(result["investment_oas"], 1.0)
        self.assertEqual(result["estimated_shares"], 100)

    def test_anchor_trace(self):
        c = _client()
        result = estimate_cost(c, "anchor_trace", {})
        self.assertIn("total_cost_oas", result)

    def test_unknown_action(self):
        c = _client()
        result = estimate_cost(c, "fly_to_moon", {})
        self.assertIn("error", result)


class TestExecutorProfile(unittest.TestCase):

    def test_snapshot_includes_executor(self):
        c = _client()
        c.get_balance = MagicMock(return_value=Balance(ADDR, 0, 0.0))
        c.list_escrows = MagicMock(return_value=[])
        c.list_capabilities = MagicMock(return_value=[])
        c.get_earnings = MagicMock(side_effect=Exception("nf"))
        c.list_assets = MagicMock(return_value=[])
        c.get_principal = MagicMock(return_value="")
        c.get_executor = MagicMock(
            return_value=Executor(ADDR, ["code-review", "data-analysis"], 5000, 12, 1, True)
        )
        c.get_reputation = MagicMock(return_value=Reputation(ADDR, 150, 20, 15))
        c.get_debt = MagicMock(side_effect=Exception("nf"))

        snap = build_snapshot(c, ADDR)

        self.assertTrue(snap.is_executor)
        self.assertEqual(snap.executor_task_types, ["code-review", "data-analysis"])
        self.assertEqual(snap.tasks_completed, 12)
        self.assertEqual(snap.tasks_failed, 1)
        self.assertEqual(snap.reputation_score, 150)


if __name__ == "__main__":
    unittest.main()

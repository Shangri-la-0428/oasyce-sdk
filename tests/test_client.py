"""Comprehensive unit tests for OasyceClient.

All HTTP calls are mocked -- no running chain node required.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import requests

from oasyce_sdk import OasyceClient
from oasyce_sdk.errors import (
    ChainError,
    ConnectionError,
    HTTPError,
    NotFoundError,
    OasyceError,
    TimeoutError,
)
from oasyce_sdk.types import (
    Account,
    AnchorRecord,
    Balance,
    Block,
    BondingCurve,
    Capability,
    DataAsset,
    Debt,
    DelegatePolicy,
    Earnings,
    Escrow,
    Executor,
    Registration,
    Reputation,
    ShareHolder,
    Task,
    TxResult,
)


def _mock_response(status_code: int = 200, json_data: dict | None = None, text: str = ""):
    """Create a mock requests.Response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text or json.dumps(json_data or {})
    resp.json.return_value = json_data or {}
    return resp


# ---------------------------------------------------------------------------
# Capability tests
# ---------------------------------------------------------------------------

class TestCapabilities(unittest.TestCase):

    def setUp(self):
        self.client = OasyceClient("http://testnode:1317", timeout=5)

    @patch.object(requests.Session, "get")
    def test_list_capabilities(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "capabilities": [
                {
                    "id": "cap-001",
                    "name": "GPT-4 Proxy",
                    "provider": "oasyce1abc",
                    "description": "OpenAI GPT-4 proxy",
                    "endpoint_url": "https://example.com/gpt4",
                    "price_per_call": {"denom": "uoas", "amount": "5000"},
                    "tags": ["llm", "openai"],
                    "rate_limit": "100",
                    "total_calls": "42",
                    "total_earned": "210000",
                    "avg_latency_ms": "350",
                    "success_rate": "9500",
                    "is_active": True,
                },
            ]
        })
        caps = self.client.list_capabilities()
        self.assertEqual(len(caps), 1)
        self.assertIsInstance(caps[0], Capability)
        self.assertEqual(caps[0].capability_id, "cap-001")
        self.assertEqual(caps[0].name, "GPT-4 Proxy")
        self.assertEqual(caps[0].price_per_call, 5000)
        self.assertEqual(caps[0].tags, ["llm", "openai"])
        self.assertEqual(caps[0].total_calls, 42)
        self.assertEqual(caps[0].success_rate, 9500)
        self.assertTrue(caps[0].active)

    @patch.object(requests.Session, "get")
    def test_list_capabilities_with_tag(self, mock_get):
        mock_get.return_value = _mock_response(200, {"capabilities": []})
        self.client.list_capabilities(tag="llm")
        args, kwargs = mock_get.call_args
        self.assertIn("tag", kwargs.get("params", {}))
        self.assertEqual(kwargs["params"]["tag"], "llm")

    @patch.object(requests.Session, "get")
    def test_list_capabilities_by_provider(self, mock_get):
        mock_get.return_value = _mock_response(200, {"capabilities": []})
        self.client.list_capabilities(provider="oasyce1xyz")
        url = mock_get.call_args[0][0]
        self.assertIn("/capabilities/provider/oasyce1xyz", url)

    @patch.object(requests.Session, "get")
    def test_get_capability(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "capability": {
                "id": "cap-002",
                "name": "Whisper STT",
                "provider": "oasyce1def",
                "description": "Speech to text",
                "endpoint_url": "https://example.com/stt",
                "price_per_call": {"denom": "uoas", "amount": "10000"},
                "tags": ["audio"],
                "rate_limit": "50",
                "total_calls": "0",
                "total_earned": "0",
                "avg_latency_ms": "0",
                "success_rate": "0",
                "is_active": True,
            }
        })
        cap = self.client.get_capability("cap-002")
        self.assertIsInstance(cap, Capability)
        self.assertEqual(cap.capability_id, "cap-002")
        self.assertEqual(cap.price_per_call, 10000)

    @patch.object(requests.Session, "get")
    def test_get_capability_not_found(self, mock_get):
        mock_get.return_value = _mock_response(404, text="not found")
        with self.assertRaises(NotFoundError) as ctx:
            self.client.get_capability("nonexistent")
        self.assertIn("Capability", str(ctx.exception))
        self.assertIn("nonexistent", str(ctx.exception))

    @patch.object(requests.Session, "get")
    def test_get_earnings(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "total_earned": [{"denom": "uoas", "amount": "500000"}],
            "total_calls": "100",
        })
        earnings = self.client.get_earnings("oasyce1abc")
        self.assertIsInstance(earnings, Earnings)
        self.assertEqual(earnings.provider, "oasyce1abc")
        self.assertEqual(earnings.total_earned_uoas, 500000)
        self.assertEqual(earnings.total_calls, 100)


# ---------------------------------------------------------------------------
# Data asset tests
# ---------------------------------------------------------------------------

class TestDataAssets(unittest.TestCase):

    def setUp(self):
        self.client = OasyceClient("http://testnode:1317")

    @patch.object(requests.Session, "get")
    def test_list_assets(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "data_assets": [
                {
                    "id": "asset-001",
                    "name": "Training Data v1",
                    "owner": "oasyce1owner",
                    "description": "ML training dataset",
                    "content_hash": "sha256:abc123",
                    "fingerprint": "fp:xyz",
                    "rights_type": "RIGHTS_TYPE_ORIGINAL",
                    "tags": ["ml", "training"],
                    "total_shares": "1000",
                    "status": "ASSET_STATUS_ACTIVE",
                    "version": 1,
                    "parent_asset_id": "",
                    "service_url": "https://api.example.com/data/v1",
                },
            ]
        })
        assets = self.client.list_assets()
        self.assertEqual(len(assets), 1)
        self.assertIsInstance(assets[0], DataAsset)
        self.assertEqual(assets[0].asset_id, "asset-001")
        self.assertEqual(assets[0].rights_type, "ORIGINAL")
        self.assertEqual(assets[0].status, "ACTIVE")
        self.assertEqual(assets[0].total_shares, 1000)
        self.assertEqual(assets[0].service_url, "https://api.example.com/data/v1")

    @patch.object(requests.Session, "get")
    def test_list_assets_filtered(self, mock_get):
        mock_get.return_value = _mock_response(200, {"data_assets": []})
        self.client.list_assets(tag="ml", owner="oasyce1x")
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"]["tag"], "ml")
        self.assertEqual(kwargs["params"]["owner"], "oasyce1x")

    @patch.object(requests.Session, "get")
    def test_get_asset(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "data_asset": {
                "id": "asset-002",
                "name": "Photo Collection",
                "owner": "oasyce1own",
                "description": "Photos",
                "content_hash": "sha256:def",
                "fingerprint": "fp:abc",
                "rights_type": "RIGHTS_TYPE_COLLECTION",
                "tags": [],
                "total_shares": "500",
                "status": "ASSET_STATUS_SHUTTING_DOWN",
                "version": 2,
                "parent_asset_id": "asset-001",
            }
        })
        asset = self.client.get_asset("asset-002")
        self.assertEqual(asset.status, "SHUTTING_DOWN")
        self.assertEqual(asset.rights_type, "COLLECTION")
        self.assertEqual(asset.version, 2)
        self.assertEqual(asset.parent_asset_id, "asset-001")

    @patch.object(requests.Session, "get")
    def test_get_shares(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "shareholders": [
                {"address": "oasyce1a", "asset_id": "asset-001", "shares": "300"},
                {"address": "oasyce1b", "asset_id": "asset-001", "shares": "700"},
            ]
        })
        holders = self.client.get_shares("asset-001")
        self.assertEqual(len(holders), 2)
        self.assertIsInstance(holders[0], ShareHolder)
        self.assertEqual(holders[0].shares, 300)
        self.assertEqual(holders[1].shares, 700)

    @patch.object(requests.Session, "get")
    def test_get_bonding_curve(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "current_price": {"denom": "uoas", "amount": "1500"},
            "state": {
                "asset_id": "asset-001",
                "total_shares": "10000",
                "reserve": "75000000",
                "price_factor": "0.5",
                "buyer_count": 5,
            }
        })
        bc = self.client.get_bonding_curve("asset-001")
        self.assertIsInstance(bc, BondingCurve)
        self.assertEqual(bc.asset_id, "asset-001")
        self.assertEqual(bc.supply, 10000)
        self.assertEqual(bc.reserve_uoas, 75000000)
        self.assertEqual(bc.spot_price_uoas, 1500)
        self.assertEqual(bc.buyer_count, 5)


# ---------------------------------------------------------------------------
# Settlement tests
# ---------------------------------------------------------------------------

class TestSettlement(unittest.TestCase):

    def setUp(self):
        self.client = OasyceClient("http://testnode:1317")

    @patch.object(requests.Session, "get")
    def test_get_escrow(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "escrow": {
                "id": "esc-001",
                "creator": "oasyce1consumer",
                "provider": "oasyce1provider",
                "amount": {"denom": "uoas", "amount": "50000"},
                "status": "ESCROW_STATUS_LOCKED",
            }
        })
        esc = self.client.get_escrow("esc-001")
        self.assertIsInstance(esc, Escrow)
        self.assertEqual(esc.escrow_id, "esc-001")
        self.assertEqual(esc.status, "LOCKED")
        self.assertEqual(esc.amount_uoas, 50000)

    @patch.object(requests.Session, "get")
    def test_get_escrow_released(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "escrow": {
                "id": "esc-002",
                "creator": "oasyce1a",
                "provider": "oasyce1b",
                "amount": {"denom": "uoas", "amount": "100000"},
                "status": "ESCROW_STATUS_RELEASED",
            }
        })
        esc = self.client.get_escrow("esc-002")
        self.assertEqual(esc.status, "RELEASED")

    @patch.object(requests.Session, "get")
    def test_list_escrows(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "escrows": [
                {
                    "id": "esc-001",
                    "creator": "oasyce1a",
                    "provider": "oasyce1b",
                    "amount": {"denom": "uoas", "amount": "10000"},
                    "status": "ESCROW_STATUS_EXPIRED",
                },
            ]
        })
        escrows = self.client.list_escrows("oasyce1a")
        self.assertEqual(len(escrows), 1)
        self.assertEqual(escrows[0].status, "EXPIRED")


# ---------------------------------------------------------------------------
# Delegate tests
# ---------------------------------------------------------------------------

class TestDelegate(unittest.TestCase):

    def setUp(self):
        self.client = OasyceClient("http://testnode:1317")

    @patch.object(requests.Session, "get")
    def test_get_delegate_policy(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "policy": {
                "principal": "oasyce1principal",
                "per_tx_limit": {"denom": "uoas", "amount": "1000000"},
                "window_limit": {"denom": "uoas", "amount": "10000000"},
                "window_seconds": "86400",
                "allowed_msgs": ["/cosmos.bank.v1beta1.MsgSend"],
                "max_msgs_per_exec": "4",
                "expiration_seconds": "0",
                "created_at_seconds": "123",
            }
        })

        policy = self.client.get_delegate_policy("oasyce1principal")

        self.assertIsInstance(policy, DelegatePolicy)
        self.assertEqual(policy.principal, "oasyce1principal")
        self.assertEqual(policy.max_msgs_per_exec, 4)


# ---------------------------------------------------------------------------
# Reputation tests
# ---------------------------------------------------------------------------

class TestReputation(unittest.TestCase):

    def setUp(self):
        self.client = OasyceClient("http://testnode:1317")

    @patch.object(requests.Session, "get")
    def test_get_reputation(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "reputation": {
                "address": "oasyce1abc",
                "total_score": "450",
                "total_feedbacks": "10",
                "verified_feedbacks": "8",
            }
        })
        rep = self.client.get_reputation("oasyce1abc")
        self.assertIsInstance(rep, Reputation)
        self.assertEqual(rep.address, "oasyce1abc")
        self.assertEqual(rep.score, 450)
        self.assertEqual(rep.total_feedback, 10)
        self.assertEqual(rep.verified_feedback, 8)

    @patch.object(requests.Session, "get")
    def test_get_leaderboard(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "scores": [
                {"address": "oasyce1a", "total_score": "490", "total_feedbacks": "50", "verified_feedbacks": "48"},
                {"address": "oasyce1b", "total_score": "420", "total_feedbacks": "30", "verified_feedbacks": "25"},
            ]
        })
        lb = self.client.get_leaderboard()
        self.assertEqual(len(lb), 2)
        self.assertEqual(lb[0].score, 490)
        self.assertEqual(lb[1].score, 420)


# ---------------------------------------------------------------------------
# Work tests
# ---------------------------------------------------------------------------

class TestWork(unittest.TestCase):

    def setUp(self):
        self.client = OasyceClient("http://testnode:1317")

    @patch.object(requests.Session, "get")
    def test_get_task(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "task": {
                "id": "42",
                "creator": "oasyce1submit",
                "task_type": "inference",
                "bounty": {"denom": "uoas", "amount": "100000"},
                "deposit": {"denom": "uoas", "amount": "10000"},
                "status": "TASK_STATUS_SUBMITTED",
                "redundancy": 3,
                "assigned_executors": [],
                "description": "Run inference on model X",
            }
        })
        task = self.client.get_task("42")
        self.assertIsInstance(task, Task)
        self.assertEqual(task.task_id, "42")
        self.assertEqual(task.status, "SUBMITTED")
        self.assertEqual(task.bounty_uoas, 100000)
        self.assertEqual(task.deposit_uoas, 10000)
        self.assertIsNone(task.executor)

    @patch.object(requests.Session, "get")
    def test_get_task_assigned(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "task": {
                "id": "43",
                "creator": "oasyce1a",
                "task_type": "training",
                "bounty": {"denom": "uoas", "amount": "500000"},
                "deposit": {"denom": "uoas", "amount": "50000"},
                "status": "TASK_STATUS_ASSIGNED",
                "redundancy": 1,
                "assigned_executors": ["oasyce1exec1", "oasyce1exec2"],
            }
        })
        task = self.client.get_task("43")
        self.assertEqual(task.status, "ASSIGNED")
        self.assertEqual(task.executor, "oasyce1exec1")
        self.assertEqual(len(task.assigned_executors), 2)

    @patch.object(requests.Session, "get")
    def test_list_tasks(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "tasks": [
                {
                    "id": "1",
                    "creator": "oasyce1a",
                    "task_type": "inference",
                    "bounty": {"denom": "uoas", "amount": "1000"},
                    "deposit": {"denom": "uoas", "amount": "100"},
                    "status": "TASK_STATUS_SETTLED",
                    "redundancy": 1,
                    "assigned_executors": ["oasyce1e"],
                },
            ]
        })
        tasks = self.client.list_tasks(status=5)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].status, "SETTLED")
        url = mock_get.call_args[0][0]
        self.assertIn("/tasks/status/5", url)

    @patch.object(requests.Session, "get")
    def test_list_executors(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "executors": [
                {
                    "address": "oasyce1exec",
                    "supported_task_types": ["inference", "training"],
                    "max_compute_units": "1000",
                    "tasks_completed": "25",
                    "tasks_failed": "1",
                    "active": True,
                },
            ]
        })
        execs = self.client.list_executors()
        self.assertEqual(len(execs), 1)
        self.assertIsInstance(execs[0], Executor)
        self.assertEqual(execs[0].tasks_completed, 25)
        self.assertTrue(execs[0].active)


# ---------------------------------------------------------------------------
# Onboarding tests
# ---------------------------------------------------------------------------

class TestOnboarding(unittest.TestCase):

    def setUp(self):
        self.client = OasyceClient("http://testnode:1317")

    @patch.object(requests.Session, "get")
    def test_get_registration(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "registration": {
                "address": "oasyce1new",
                "airdrop_amount": "20000000",
                "repaid_amount": "5000000",
                "status": "REGISTRATION_STATUS_ACTIVE",
            }
        })
        reg = self.client.get_registration("oasyce1new")
        self.assertIsInstance(reg, Registration)
        self.assertEqual(reg.address, "oasyce1new")
        self.assertEqual(reg.airdrop_amount, 20000000)
        self.assertEqual(reg.repaid_amount, 5000000)
        self.assertEqual(reg.status, "ACTIVE")

    @patch.object(requests.Session, "get")
    def test_get_debt(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "registration": {
                "address": "oasyce1debt",
                "airdrop_amount": "20000000",
                "repaid_amount": "12000000",
                "status": "REGISTRATION_STATUS_ACTIVE",
            }
        })
        debt = self.client.get_debt("oasyce1debt")
        self.assertIsInstance(debt, Debt)
        self.assertEqual(debt.total_debt, 20000000)
        self.assertEqual(debt.repaid, 12000000)
        self.assertEqual(debt.remaining, 8000000)
        self.assertEqual(debt.status, "ACTIVE")

    @patch.object(requests.Session, "get")
    def test_get_debt_fully_repaid(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "registration": {
                "address": "oasyce1done",
                "airdrop_amount": "20000000",
                "repaid_amount": "20000000",
                "status": "REGISTRATION_STATUS_REPAID",
            }
        })
        debt = self.client.get_debt("oasyce1done")
        self.assertEqual(debt.remaining, 0)
        self.assertEqual(debt.status, "REPAID")


# ---------------------------------------------------------------------------
# Bank / Auth / Tendermint tests
# ---------------------------------------------------------------------------

class TestCosmos(unittest.TestCase):

    def setUp(self):
        self.client = OasyceClient("http://testnode:1317")

    @patch.object(requests.Session, "get")
    def test_get_balance(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "balances": [
                {"denom": "uoas", "amount": "5000000"},
                {"denom": "stake", "amount": "100"},
            ]
        })
        bal = self.client.get_balance("oasyce1rich")
        self.assertIsInstance(bal, Balance)
        self.assertEqual(bal.address, "oasyce1rich")
        self.assertEqual(bal.amount_uoas, 5000000)
        self.assertAlmostEqual(bal.amount_oas, 5.0)

    @patch.object(requests.Session, "get")
    def test_get_balance_empty(self, mock_get):
        mock_get.return_value = _mock_response(200, {"balances": []})
        bal = self.client.get_balance("oasyce1empty")
        self.assertEqual(bal.amount_uoas, 0)
        self.assertAlmostEqual(bal.amount_oas, 0.0)

    @patch.object(requests.Session, "get")
    def test_get_account(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "account": {
                "@type": "/cosmos.auth.v1beta1.BaseAccount",
                "address": "oasyce1abc",
                "account_number": "5",
                "sequence": "12",
            }
        })
        acct = self.client.get_account("oasyce1abc")
        self.assertIsInstance(acct, Account)
        self.assertEqual(acct.account_number, 5)
        self.assertEqual(acct.sequence, 12)

    @patch.object(requests.Session, "get")
    def test_get_account_nested(self, mock_get):
        """Test account parsing when base_account is nested (e.g. vesting accounts)."""
        mock_get.return_value = _mock_response(200, {
            "account": {
                "@type": "/cosmos.vesting.v1beta1.ContinuousVestingAccount",
                "base_account": {
                    "address": "oasyce1vest",
                    "account_number": "10",
                    "sequence": "3",
                },
            }
        })
        acct = self.client.get_account("oasyce1vest")
        self.assertEqual(acct.account_number, 10)
        self.assertEqual(acct.sequence, 3)

    @patch.object(requests.Session, "get")
    def test_get_latest_block(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "block_id": {},
            "block": {
                "header": {
                    "height": "12345",
                    "time": "2026-03-24T10:00:00Z",
                    "chain_id": "oasyce-local-1",
                    "proposer_address": "ABCDEF",
                },
                "data": {
                    "txs": ["tx1", "tx2"],
                },
            },
        })
        block = self.client.get_latest_block()
        self.assertIsInstance(block, Block)
        self.assertEqual(block.height, 12345)
        self.assertEqual(block.chain_id, "oasyce-local-1")
        self.assertEqual(block.num_txs, 2)


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------

class TestErrorHandling(unittest.TestCase):

    def setUp(self):
        self.client = OasyceClient("http://testnode:1317")

    @patch.object(requests.Session, "get")
    def test_404_raises_not_found(self, mock_get):
        mock_get.return_value = _mock_response(404, text="not found")
        with self.assertRaises(NotFoundError):
            self.client.get_capability("does-not-exist")

    @patch.object(requests.Session, "get")
    def test_grpc_not_found_message(self, mock_get):
        """gRPC-gateway wraps NOT_FOUND errors with code + message."""
        mock_get.return_value = _mock_response(200, {
            "code": 5,
            "message": "capability not found: xyz",
        })
        with self.assertRaises(NotFoundError):
            self.client.get_capability("xyz")

    @patch.object(requests.Session, "get")
    def test_500_raises_http_error(self, mock_get):
        mock_get.return_value = _mock_response(500, text="internal server error")
        with self.assertRaises(HTTPError) as ctx:
            self.client.list_capabilities()
        self.assertEqual(ctx.exception.status_code, 500)

    @patch.object(requests.Session, "get")
    def test_connection_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")
        with self.assertRaises(ConnectionError):
            self.client.list_capabilities()

    @patch.object(requests.Session, "get")
    def test_timeout_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout("timed out")
        with self.assertRaises(TimeoutError):
            self.client.list_capabilities()

    @patch.object(requests.Session, "get")
    def test_all_errors_inherit_from_oasyce_error(self, mock_get):
        """All custom exceptions should be catchable via OasyceError."""
        mock_get.return_value = _mock_response(404, text="not found")
        with self.assertRaises(OasyceError):
            self.client.get_capability("missing")


# ---------------------------------------------------------------------------
# Unit conversion tests
# ---------------------------------------------------------------------------

class TestUnitConversion(unittest.TestCase):

    def test_oas_to_uoas(self):
        self.assertEqual(OasyceClient.oas_to_uoas(1.0), 1_000_000)
        self.assertEqual(OasyceClient.oas_to_uoas(0.5), 500_000)
        self.assertEqual(OasyceClient.oas_to_uoas(0.0), 0)
        self.assertEqual(OasyceClient.oas_to_uoas(100.0), 100_000_000)

    def test_uoas_to_oas(self):
        self.assertAlmostEqual(OasyceClient.uoas_to_oas(1_000_000), 1.0)
        self.assertAlmostEqual(OasyceClient.uoas_to_oas(500_000), 0.5)
        self.assertAlmostEqual(OasyceClient.uoas_to_oas(0), 0.0)
        self.assertAlmostEqual(OasyceClient.uoas_to_oas(2_500_000), 2.5)

    def test_roundtrip(self):
        for oas in [0.1, 1.0, 10.5, 100.0, 0.000001]:
            uoas = OasyceClient.oas_to_uoas(oas)
            back = OasyceClient.uoas_to_oas(uoas)
            self.assertAlmostEqual(back, oas, places=6)


# ---------------------------------------------------------------------------
# Health check tests
# ---------------------------------------------------------------------------

class TestHealth(unittest.TestCase):

    def setUp(self):
        self.client = OasyceClient("http://testnode:1317")

    @patch.object(requests.Session, "get")
    def test_health_ok(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "block": {
                "header": {"height": "100", "time": "2026-01-01T00:00:00Z", "chain_id": "oasyce-1", "proposer_address": ""},
                "data": {"txs": []},
            }
        })
        self.assertTrue(self.client.health())

    @patch.object(requests.Session, "get")
    def test_health_unreachable(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")
        self.assertFalse(self.client.health())

    @patch.object(requests.Session, "get")
    def test_health_timeout(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout()
        self.assertFalse(self.client.health())


# ---------------------------------------------------------------------------
# Transaction builder tests
# ---------------------------------------------------------------------------

class TestTxBuilders(unittest.TestCase):

    def setUp(self):
        self.client = OasyceClient("http://testnode:1317")

    def test_build_register_capability(self):
        tx = self.client.build_register_capability(
            sender="oasyce1sender",
            name="My LLM",
            endpoint="https://api.example.com/llm",
            price_uoas=5000,
            tags=["llm", "gpt"],
            description="A fine LLM",
        )
        self.assertIn("body", tx)
        msgs = tx["body"]["messages"]
        self.assertEqual(len(msgs), 1)
        msg = msgs[0]
        self.assertEqual(msg["@type"], "/oasyce.capability.v1.MsgRegisterCapability")
        self.assertEqual(msg["creator"], "oasyce1sender")
        self.assertEqual(msg["name"], "My LLM")
        self.assertEqual(msg["price_per_call"]["amount"], "5000")
        self.assertEqual(msg["price_per_call"]["denom"], "uoas")
        self.assertEqual(msg["tags"], ["llm", "gpt"])

    def test_build_invoke_capability(self):
        tx = self.client.build_invoke_capability(
            sender="oasyce1consumer",
            capability_id="cap-001",
            input_data=b"hello world",
        )
        msg = tx["body"]["messages"][0]
        self.assertEqual(msg["@type"], "/oasyce.capability.v1.MsgInvokeCapability")
        self.assertEqual(msg["capability_id"], "cap-001")
        # input should be base64 encoded
        import base64
        decoded = base64.b64decode(msg["input"])
        self.assertEqual(decoded, b"hello world")

    def test_build_invoke_capability_no_input(self):
        tx = self.client.build_invoke_capability(
            sender="oasyce1x",
            capability_id="cap-002",
        )
        msg = tx["body"]["messages"][0]
        # empty input is base64 of b""
        import base64
        decoded = base64.b64decode(msg["input"])
        self.assertEqual(decoded, b"")

    def test_build_register_asset(self):
        tx = self.client.build_register_asset(
            sender="oasyce1owner",
            name="Dataset Alpha",
            content_hash="sha256:abc123def",
            tags=["ml", "nlp"],
            description="NLP training data",
            service_url="https://data.example.com/v1",
        )
        msg = tx["body"]["messages"][0]
        self.assertEqual(msg["@type"], "/oasyce.datarights.v1.MsgRegisterDataAsset")
        self.assertEqual(msg["content_hash"], "sha256:abc123def")
        self.assertEqual(msg["tags"], ["ml", "nlp"])
        self.assertEqual(msg["service_url"], "https://data.example.com/v1")

    def test_build_register_asset_no_service_url(self):
        tx = self.client.build_register_asset(
            sender="oasyce1owner",
            name="Dataset",
            content_hash="sha256:xyz",
        )
        msg = tx["body"]["messages"][0]
        self.assertEqual(msg["service_url"], "")

    def test_build_update_service_url(self):
        tx = self.client.build_update_service_url(
            sender="oasyce1owner",
            asset_id="asset-001",
            service_url="https://new-endpoint.com/data",
        )
        msg = tx["body"]["messages"][0]
        self.assertEqual(msg["@type"], "/oasyce.datarights.v1.MsgUpdateServiceUrl")
        self.assertEqual(msg["creator"], "oasyce1owner")
        self.assertEqual(msg["asset_id"], "asset-001")
        self.assertEqual(msg["service_url"], "https://new-endpoint.com/data")

    def test_build_update_service_url_clear(self):
        tx = self.client.build_update_service_url(
            sender="oasyce1owner",
            asset_id="asset-001",
            service_url="",
        )
        msg = tx["body"]["messages"][0]
        self.assertEqual(msg["service_url"], "")

    def test_build_buy_shares(self):
        tx = self.client.build_buy_shares(
            sender="oasyce1buyer",
            asset_id="asset-001",
            amount_uoas=100000,
        )
        msg = tx["body"]["messages"][0]
        self.assertEqual(msg["@type"], "/oasyce.datarights.v1.MsgBuyShares")
        self.assertEqual(msg["asset_id"], "asset-001")
        self.assertEqual(msg["amount"]["amount"], "100000")

    def test_build_sell_shares(self):
        tx = self.client.build_sell_shares(
            sender="oasyce1seller",
            asset_id="asset-001",
            shares=500,
        )
        msg = tx["body"]["messages"][0]
        self.assertEqual(msg["@type"], "/oasyce.datarights.v1.MsgSellShares")
        self.assertEqual(msg["shares"], "500")

    def test_tx_structure_has_required_keys(self):
        """All builders should return body, auth_info, signatures."""
        tx = self.client.build_register_capability(
            sender="oasyce1x", name="X", endpoint="http://x", price_uoas=1,
        )
        self.assertIn("body", tx)
        self.assertIn("auth_info", tx)
        self.assertIn("signatures", tx)
        self.assertIn("messages", tx["body"])
        self.assertIn("memo", tx["body"])


# ---------------------------------------------------------------------------
# Broadcast TX test
# ---------------------------------------------------------------------------

class TestBroadcastTx(unittest.TestCase):

    def setUp(self):
        self.client = OasyceClient("http://testnode:1317")

    @patch.object(requests.Session, "post")
    def test_broadcast_success(self, mock_post):
        mock_post.return_value = _mock_response(200, {
            "tx_response": {
                "txhash": "AABBCCDD",
                "code": 0,
                "raw_log": "[]",
            }
        })
        result = self.client.broadcast_tx({
            "tx_bytes": "c2lnbmVkZGF0YQ==",
            "mode": "BROADCAST_MODE_SYNC",
        })
        self.assertIsInstance(result, TxResult)
        self.assertEqual(result.tx_hash, "AABBCCDD")
        self.assertEqual(result.code, 0)
        self.assertTrue(result.success)

    @patch.object(requests.Session, "post")
    def test_broadcast_failure(self, mock_post):
        mock_post.return_value = _mock_response(200, {
            "tx_response": {
                "txhash": "EEFF0011",
                "code": 5,
                "raw_log": "insufficient funds",
            }
        })
        result = self.client.broadcast_tx({
            "tx_bytes": "c2lnbmVk",
            "mode": "BROADCAST_MODE_SYNC",
        })
        self.assertFalse(result.success)
        self.assertEqual(result.code, 5)
        self.assertIn("insufficient funds", result.raw_log)

    @patch.object(requests.Session, "post")
    def test_broadcast_from_builder_output(self, mock_post):
        """broadcast_tx should handle the dict output from build_* methods."""
        mock_post.return_value = _mock_response(200, {
            "tx_response": {
                "txhash": "AABB",
                "code": 0,
                "raw_log": "",
            }
        })
        tx = self.client.build_register_capability(
            sender="oasyce1x", name="X", endpoint="http://x", price_uoas=1,
        )
        result = self.client.broadcast_tx(tx)
        self.assertTrue(result.success)
        # Verify post was called with tx_bytes
        call_body = mock_post.call_args[1]["json"]
        self.assertIn("tx_bytes", call_body)
        self.assertEqual(call_body["mode"], "BROADCAST_MODE_SYNC")


# ---------------------------------------------------------------------------
# Client repr / construction
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Anchor tests
# ---------------------------------------------------------------------------

# A fake 32-byte trace ID (hex)
_TRACE_ID_HEX = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"
# Matching base64 of those bytes
_TRACE_ID_B64 = "obLD1OX2p7jJ0OHyo7TF1uf4qbDB0uP0pbbH2On wouy"  # placeholder

import base64 as _b64
_TRACE_ID_B64 = _b64.b64encode(bytes.fromhex(_TRACE_ID_HEX)).decode()
_NODE_PUBKEY_HEX = "d4a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1"
_NODE_PUBKEY_B64 = _b64.b64encode(bytes.fromhex(_NODE_PUBKEY_HEX)).decode()
_SIG_HEX = "00" * 64
_SIG_B64 = _b64.b64encode(bytes.fromhex(_SIG_HEX)).decode()


class TestAnchor(unittest.TestCase):

    def setUp(self):
        self.client = OasyceClient("http://testnode:1317", timeout=5)

    @patch.object(requests.Session, "get")
    def test_get_anchor(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "anchor": {
                "trace_id": _TRACE_ID_B64,
                "node_pubkey": _NODE_PUBKEY_B64,
                "capability": "tool-summarize",
                "outcome": "1",
                "timestamp": "1711929600000",
                "anchor_height": "42",
                "trace_signature": _SIG_B64,
            }
        })
        record = self.client.get_anchor(_TRACE_ID_HEX)
        self.assertIsInstance(record, AnchorRecord)
        self.assertEqual(record.trace_id, _TRACE_ID_HEX)
        self.assertEqual(record.capability, "tool-summarize")
        self.assertEqual(record.outcome, 1)
        self.assertEqual(record.timestamp, 1711929600000)
        self.assertEqual(record.anchor_height, 42)

    @patch.object(requests.Session, "get")
    def test_is_anchored_true(self, mock_get):
        mock_get.return_value = _mock_response(200, {"anchored": True})
        self.assertTrue(self.client.is_anchored(_TRACE_ID_HEX))

    @patch.object(requests.Session, "get")
    def test_is_anchored_false(self, mock_get):
        mock_get.return_value = _mock_response(200, {"anchored": False})
        self.assertFalse(self.client.is_anchored(_TRACE_ID_HEX))

    @patch.object(requests.Session, "get")
    def test_is_anchored_404(self, mock_get):
        mock_get.return_value = _mock_response(404, None, text="not found")
        self.assertFalse(self.client.is_anchored(_TRACE_ID_HEX))

    @patch.object(requests.Session, "get")
    def test_anchors_by_capability(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "anchors": [
                {
                    "trace_id": _TRACE_ID_B64,
                    "node_pubkey": _NODE_PUBKEY_B64,
                    "capability": "tool-summarize",
                    "outcome": "1",
                    "timestamp": "1711929600000",
                    "anchor_height": "100",
                    "trace_signature": _SIG_B64,
                },
            ],
            "pagination": {"total": "1"},
        })
        records = self.client.anchors_by_capability("tool-summarize", limit=10)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].capability, "tool-summarize")

    @patch.object(requests.Session, "get")
    def test_anchors_by_node(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "anchors": [],
            "pagination": {"total": "0"},
        })
        records = self.client.anchors_by_node(_NODE_PUBKEY_HEX)
        self.assertEqual(len(records), 0)

    def test_build_anchor_trace(self):
        tx = self.client.build_anchor_trace(
            sender="oasyce1abc",
            trace_id_hex=_TRACE_ID_HEX,
            node_pubkey_hex=_NODE_PUBKEY_HEX,
            capability="tool-summarize",
            outcome=1,
            timestamp=1711929600000,
            trace_signature_hex=_SIG_HEX,
        )
        msgs = tx["body"]["messages"]
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["@type"], "/oasyce.anchor.v1.MsgAnchorTrace")
        self.assertEqual(msgs[0]["signer"], "oasyce1abc")
        self.assertEqual(msgs[0]["capability"], "tool-summarize")

    def test_build_anchor_batch(self):
        traces = [
            {
                "trace_id_hex": _TRACE_ID_HEX,
                "node_pubkey_hex": _NODE_PUBKEY_HEX,
                "capability": f"tool-{i}",
                "outcome": 1,
                "timestamp": 1711929600000 + i,
                "trace_signature_hex": _SIG_HEX,
            }
            for i in range(3)
        ]
        tx = self.client.build_anchor_batch("oasyce1abc", traces)
        msgs = tx["body"]["messages"]
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["@type"], "/oasyce.anchor.v1.MsgAnchorBatch")
        self.assertEqual(len(msgs[0]["anchors"]), 3)

    def test_bytes_from_b64_or_hex(self):
        # base64 input
        hex_out = OasyceClient._bytes_from_b64_or_hex(_TRACE_ID_B64)
        self.assertEqual(hex_out, _TRACE_ID_HEX)
        # empty
        self.assertEqual(OasyceClient._bytes_from_b64_or_hex(""), "")

    def test_anchor_record_frozen(self):
        r = AnchorRecord(
            trace_id=_TRACE_ID_HEX,
            node_pubkey=_NODE_PUBKEY_HEX,
            capability="test",
            outcome=1,
            timestamp=0,
            anchor_height=0,
            trace_signature=_SIG_HEX,
        )
        with self.assertRaises(AttributeError):
            r.outcome = 2  # frozen


class TestClientConstruction(unittest.TestCase):

    def test_default_construction(self):
        client = OasyceClient()
        self.assertIn("localhost:1317", repr(client))

    def test_custom_url(self):
        client = OasyceClient("https://rpc.oasyce.io:1317")
        self.assertIn("rpc.oasyce.io", repr(client))

    def test_trailing_slash_stripped(self):
        client = OasyceClient("http://localhost:1317/")
        self.assertNotIn("//", repr(client).split("localhost:1317")[1])


if __name__ == "__main__":
    unittest.main()

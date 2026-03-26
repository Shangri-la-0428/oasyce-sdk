"""Parametrized tests for v0.2.0 additions.

Covers all 22 new TX builders, 14 new query methods, and PoW solver
using pytest.mark.parametrize for compact coverage.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from oasyce_sdk import OasyceClient
from oasyce_sdk.types import (
    AccessLevel,
    DataAsset,
    Dispute,
    EpochStats,
    Executor,
    Invocation,
    MigrationPath,
    PowResult,
    Task,
)


def _mock_response(status_code: int = 200, json_data: dict | None = None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = json.dumps(json_data or {})
    resp.json.return_value = json_data or {}
    return resp


@pytest.fixture
def client():
    return OasyceClient("http://testnode:1317", timeout=5)


# ============================================================================
# TX Builder tests — parametrized
# ============================================================================

TX_BUILDER_CASES = [
    # (method_name, kwargs, expected_type_url, expected_fields)
    (
        "build_complete_invocation",
        {"sender": "oasyce1p", "invocation_id": "INV_001", "output_hash": "abc123" * 6, "usage_report": '{"t":1}'},
        "/oasyce.capability.v1.MsgCompleteInvocation",
        {"creator": "oasyce1p", "invocation_id": "INV_001", "output_hash": "abc123" * 6},
    ),
    (
        "build_fail_invocation",
        {"sender": "oasyce1p", "invocation_id": "INV_001"},
        "/oasyce.capability.v1.MsgFailInvocation",
        {"creator": "oasyce1p", "invocation_id": "INV_001"},
    ),
    (
        "build_claim_invocation",
        {"sender": "oasyce1p", "invocation_id": "INV_001"},
        "/oasyce.capability.v1.MsgClaimInvocation",
        {"creator": "oasyce1p", "invocation_id": "INV_001"},
    ),
    (
        "build_dispute_invocation",
        {"sender": "oasyce1c", "invocation_id": "INV_001", "reason": "bad output"},
        "/oasyce.capability.v1.MsgDisputeInvocation",
        {"creator": "oasyce1c", "reason": "bad output"},
    ),
    (
        "build_submit_feedback",
        {"sender": "oasyce1c", "invocation_id": "INV_001", "rating": 450, "comment": "great"},
        "/oasyce.reputation.v1.MsgSubmitFeedback",
        {"creator": "oasyce1c", "rating": 450, "comment": "great"},
    ),
    (
        "build_report_misbehavior",
        {"sender": "oasyce1c", "target": "oasyce1bad", "evidence_type": "spam"},
        "/oasyce.reputation.v1.MsgReportMisbehavior",
        {"creator": "oasyce1c", "target": "oasyce1bad", "evidence_type": "spam"},
    ),
    (
        "build_register_executor",
        {"sender": "oasyce1e", "task_types": ["inference"], "max_compute_units": 1000},
        "/oasyce.work.v1.MsgRegisterExecutor",
        {"executor": "oasyce1e", "supported_task_types": ["inference"], "max_compute_units": "1000"},
    ),
    (
        "build_update_executor",
        {"sender": "oasyce1e", "task_types": ["training"], "max_compute_units": 2000, "active": False},
        "/oasyce.work.v1.MsgUpdateExecutor",
        {"executor": "oasyce1e", "active": False},
    ),
    (
        "build_submit_task",
        {"sender": "oasyce1s", "task_type": "inference", "input_hash": b"\x01\x02", "input_uri": "https://x", "max_compute_units": 100, "bounty_uoas": 5000},
        "/oasyce.work.v1.MsgSubmitTask",
        {"creator": "oasyce1s", "task_type": "inference"},
    ),
    (
        "build_commit_result",
        {"sender": "oasyce1e", "task_id": 42, "commit_hash": b"\xab\xcd"},
        "/oasyce.work.v1.MsgCommitResult",
        {"executor": "oasyce1e", "task_id": "42"},
    ),
    (
        "build_reveal_result",
        {"sender": "oasyce1e", "task_id": 42, "output_hash": b"\xef", "output_uri": "https://y", "compute_units_used": 50, "salt": b"\x00"},
        "/oasyce.work.v1.MsgRevealResult",
        {"executor": "oasyce1e", "task_id": "42"},
    ),
    (
        "build_dispute_result",
        {"sender": "oasyce1d", "task_id": 42, "reason": "wrong", "bond_uoas": 1000},
        "/oasyce.work.v1.MsgDisputeResult",
        {"challenger": "oasyce1d", "task_id": "42", "reason": "wrong"},
    ),
    (
        "build_create_escrow",
        {"sender": "oasyce1c", "amount_uoas": 50000, "asset_id": "DATA_001"},
        "/oasyce.settlement.v1.MsgCreateEscrow",
        {"creator": "oasyce1c", "asset_id": "DATA_001"},
    ),
    (
        "build_release_escrow",
        {"sender": "oasyce1p", "escrow_id": "ESC_001"},
        "/oasyce.settlement.v1.MsgReleaseEscrow",
        {"creator": "oasyce1p", "escrow_id": "ESC_001"},
    ),
    (
        "build_refund_escrow",
        {"sender": "oasyce1c", "escrow_id": "ESC_001"},
        "/oasyce.settlement.v1.MsgRefundEscrow",
        {"creator": "oasyce1c", "escrow_id": "ESC_001"},
    ),
    (
        "build_self_register",
        {"sender": "oasyce1new", "nonce": 123456789},
        "/oasyce.onboarding.v1.MsgSelfRegister",
        {"creator": "oasyce1new", "nonce": "123456789"},
    ),
    (
        "build_repay_debt",
        {"sender": "oasyce1new", "amount_uoas": 10000000},
        "/oasyce.onboarding.v1.MsgRepayDebt",
        {"creator": "oasyce1new", "amount": "10000000"},
    ),
    (
        "build_file_dispute",
        {"sender": "oasyce1d", "asset_id": "DATA_001", "reason": "plagiarism"},
        "/oasyce.datarights.v1.MsgFileDispute",
        {"creator": "oasyce1d", "asset_id": "DATA_001", "reason": "plagiarism"},
    ),
    (
        "build_initiate_shutdown",
        {"sender": "oasyce1o", "asset_id": "DATA_001"},
        "/oasyce.datarights.v1.MsgInitiateShutdown",
        {"creator": "oasyce1o", "asset_id": "DATA_001"},
    ),
    (
        "build_claim_settlement",
        {"sender": "oasyce1h", "asset_id": "DATA_001"},
        "/oasyce.datarights.v1.MsgClaimSettlement",
        {"creator": "oasyce1h", "asset_id": "DATA_001"},
    ),
    (
        "build_create_migration",
        {"sender": "oasyce1t", "source_asset_id": "DATA_001", "target_asset_id": "DATA_002", "exchange_rate_bps": 10000, "max_migrated_shares": 5000},
        "/oasyce.datarights.v1.MsgCreateMigrationPath",
        {"creator": "oasyce1t", "source_asset_id": "DATA_001", "target_asset_id": "DATA_002"},
    ),
    (
        "build_migrate",
        {"sender": "oasyce1m", "source_asset_id": "DATA_001", "target_asset_id": "DATA_002", "shares": 100},
        "/oasyce.datarights.v1.MsgMigrate",
        {"creator": "oasyce1m", "shares": "100"},
    ),
]


@pytest.mark.parametrize("method,kwargs,type_url,fields", TX_BUILDER_CASES, ids=[c[0] for c in TX_BUILDER_CASES])
def test_tx_builder_structure(client, method, kwargs, type_url, fields):
    """Every TX builder returns correct structure with correct @type and fields."""
    fn = getattr(client, method)
    tx = fn(**kwargs)

    # Structure
    assert "body" in tx
    assert "auth_info" in tx
    assert "signatures" in tx
    assert "messages" in tx["body"]
    assert len(tx["body"]["messages"]) == 1

    # Message
    msg = tx["body"]["messages"][0]
    assert msg["@type"] == type_url

    # Fields
    for k, v in fields.items():
        assert msg[k] == v, f"{method}: {k} expected {v!r}, got {msg.get(k)!r}"


# ============================================================================
# Query tests — parametrized
# ============================================================================

QUERY_CASES = [
    # (method_name, args, mock_response, result_type_or_check)
    (
        "get_invocation", ("INV_001",),
        {"invocation": {"id": "INV_001", "capability_id": "CAP_001", "consumer": "oasyce1c", "provider": "oasyce1p", "status": "INVOCATION_STATUS_COMPLETED", "output_hash": "abc", "completed_height": "100", "usage_report": "{}"}},
        Invocation,
    ),
    (
        "get_capability_params", (),
        {"params": {"min_provider_stake": {"denom": "uoas", "amount": "0"}, "challenge_window": "100", "max_tags": "10"}},
        dict,
    ),
    (
        "get_access_level", ("DATA_001", "oasyce1b"),
        {"access_level": "L2", "equity_bps": "500", "shares": "50", "total_shares": "1000"},
        AccessLevel,
    ),
    (
        "get_dispute", ("DISP_001",),
        {"dispute": {"id": "DISP_001", "asset_id": "DATA_001", "creator": "oasyce1d", "reason": "stolen", "status": "DISPUTE_STATUS_OPEN", "requested_remedy": "DISPUTE_REMEDY_DELIST"}},
        Dispute,
    ),
    (
        "list_disputes", (),
        {"disputes": [{"id": "DISP_001", "asset_id": "DATA_001", "creator": "oasyce1d", "reason": "x", "status": "DISPUTE_STATUS_OPEN", "requested_remedy": "DISPUTE_REMEDY_DELIST"}]},
        list,
    ),
    (
        "get_migration_path", ("DATA_001", "DATA_002"),
        {"migration_path": {"source_asset_id": "DATA_001", "target_asset_id": "DATA_002", "creator": "oasyce1t", "exchange_rate_bps": "10000", "max_migrated_shares": "5000", "migrated_shares": "0", "enabled": True}},
        MigrationPath,
    ),
    (
        "get_asset_children", ("DATA_001",),
        {"data_assets": [{"id": "DATA_002", "name": "Fork", "owner": "oasyce1f", "description": "", "content_hash": "x", "fingerprint": "", "rights_type": "RIGHTS_TYPE_ORIGINAL", "tags": [], "total_shares": "0", "status": "ASSET_STATUS_ACTIVE", "version": 2, "parent_asset_id": "DATA_001"}]},
        list,
    ),
    (
        "get_datarights_params", (),
        {"params": {"dispute_deposit": {"denom": "uoas", "amount": "10000000"}, "shutdown_cooldown": "604800s", "max_tags": "10", "min_shares_for_dispute": "1"}},
        dict,
    ),
    (
        "get_settlement_params", (),
        {"params": {"protocol_fee_rate": "0.05", "reserve_solvency_cap": "0.95"}},
        dict,
    ),
    (
        "get_reputation_params", (),
        {"params": {"max_score": "500", "decay_half_life": "2592000s", "feedback_cooldown": "3600s", "min_feedback_for_leaderboard": "1", "report_deposit": {"denom": "uoas", "amount": "100000"}}},
        dict,
    ),
    (
        "get_executor", ("oasyce1e",),
        {"executor": {"address": "oasyce1e", "supported_task_types": ["inference"], "max_compute_units": "1000", "tasks_completed": "10", "tasks_failed": "1", "active": True}},
        Executor,
    ),
    (
        "get_work_params", (),
        {"params": {"min_bounty": {"denom": "uoas", "amount": "100"}}},
        dict,
    ),
    (
        "get_epoch_stats", (1,),
        {"stats": {"epoch": "1", "tasks_submitted": "100", "tasks_settled": "90", "total_bounty": "5000000", "total_burned": "100000"}},
        EpochStats,
    ),
    (
        "get_onboarding_params", (),
        {"params": {"pow_difficulty": "16", "airdrop_amount": "20000000", "repayment_deadline": "7776000s"}},
        dict,
    ),
]


@pytest.mark.parametrize("method,args,response_data,expected_type", QUERY_CASES, ids=[c[0] for c in QUERY_CASES])
def test_query_returns_correct_type(client, method, args, response_data, expected_type):
    """Every new query method parses mocked response into the correct type."""
    with patch.object(requests.Session, "get") as mock_get:
        mock_get.return_value = _mock_response(200, response_data)
        fn = getattr(client, method)
        result = fn(*args)
        assert isinstance(result, expected_type), f"{method} returned {type(result)}, expected {expected_type}"


# ============================================================================
# PoW solver tests
# ============================================================================

class TestPowSolver:

    def test_solve_pow_returns_pow_result(self):
        result = OasyceClient.solve_pow("oasyce1test", difficulty=8)
        assert isinstance(result, PowResult)
        assert result.address == "oasyce1test"
        assert result.difficulty == 8
        assert result.nonce >= 0
        assert len(result.hash_hex) == 64

    def test_solve_pow_hash_has_leading_zeros(self):
        result = OasyceClient.solve_pow("oasyce1abc", difficulty=8)
        h = bytes.fromhex(result.hash_hex)
        # First byte must be 0 for 8+ leading zero bits
        assert h[0] == 0

    def test_solve_pow_hash_is_reproducible(self):
        """Verifying the same nonce produces the same hash."""
        import hashlib
        import struct
        result = OasyceClient.solve_pow("oasyce1verify", difficulty=8)
        data = b"oasyce1verify" + struct.pack("<Q", result.nonce)
        h = hashlib.sha256(data).hexdigest()
        assert h == result.hash_hex

    def test_solve_pow_difficulty_16(self):
        result = OasyceClient.solve_pow("oasyce1hard", difficulty=16)
        h = bytes.fromhex(result.hash_hex)
        # First two bytes must be 0 for 16+ leading zero bits
        assert h[0] == 0
        assert h[1] == 0


# ============================================================================
# Invocation status mapping
# ============================================================================

class TestInvocationParsing:

    def test_invocation_status_mapping(self, client):
        with patch.object(requests.Session, "get") as mock_get:
            for proto_status, expected in [
                ("INVOCATION_STATUS_PENDING", "PENDING"),
                ("INVOCATION_STATUS_COMPLETED", "COMPLETED"),
                ("INVOCATION_STATUS_SUCCESS", "SUCCESS"),
                ("INVOCATION_STATUS_FAILED", "FAILED"),
                ("INVOCATION_STATUS_DISPUTED", "DISPUTED"),
            ]:
                mock_get.return_value = _mock_response(200, {
                    "invocation": {"id": "INV_X", "capability_id": "C", "consumer": "a", "provider": "b", "status": proto_status}
                })
                inv = client.get_invocation("INV_X")
                assert inv.status == expected, f"{proto_status} -> {inv.status}, expected {expected}"


# ============================================================================
# Access level field parsing
# ============================================================================

class TestAccessLevelFields:

    def test_access_level_fields(self, client):
        with patch.object(requests.Session, "get") as mock_get:
            mock_get.return_value = _mock_response(200, {
                "access_level": "L2", "equity_bps": "500", "shares": "50", "total_shares": "1000"
            })
            al = client.get_access_level("DATA_001", "oasyce1x")
            assert al.level == "L2"
            assert al.equity_bps == 500
            assert al.shares == 50
            assert al.total_shares == 1000
            assert al.asset_id == "DATA_001"
            assert al.address == "oasyce1x"

"""Auto-generated protobuf message schemas — DO NOT EDIT.

Regenerate with::

    python -m oasyce_sdk.crypto._gen_schemas ~/Desktop/oasyce-chain

Source of truth: ``oasyce-chain/x/<module>/types/*pb.go`` struct tags.

``MSG_SCHEMAS`` maps a protobuf type URL to a list of
``(field_name, field_number, kind)`` tuples.  ``NESTED_SCHEMAS`` is
keyed by fully-qualified proto name (no leading slash) and stores the
same tuple shape for non-``Msg`` structs referenced by ``nested:<fqn>``
or ``repeated_nested:<fqn>`` kinds.  ``kind`` values match the ``F_*``
constants in :mod:`oasyce_sdk.crypto.protobuf`.
"""

from typing import Dict, List, Tuple

MSG_SCHEMAS: Dict[str, List[Tuple[str, int, str]]] = {
    "/oasyce.anchor.v1.MsgAnchorTrace": [
        ("signer", 1, "string"),
        ("trace_id", 2, "bytes"),
        ("node_pubkey", 3, "bytes"),
        ("capability", 4, "string"),
        ("outcome", 5, "uint32"),
        ("timestamp", 6, "uint64"),
        ("trace_signature", 7, "bytes"),
        ("sigil_id", 8, "string"),
    ],
    "/oasyce.capability.v1.MsgClaimInvocation": [
        ("creator", 1, "string"),
        ("invocation_id", 2, "string"),
    ],
    "/oasyce.capability.v1.MsgCompleteInvocation": [
        ("creator", 1, "string"),
        ("invocation_id", 2, "string"),
        ("output_hash", 3, "string"),
        ("usage_report", 4, "string"),
    ],
    "/oasyce.capability.v1.MsgDeactivateCapability": [
        ("creator", 1, "string"),
        ("capability_id", 2, "string"),
    ],
    "/oasyce.capability.v1.MsgDisputeInvocation": [
        ("creator", 1, "string"),
        ("invocation_id", 2, "string"),
        ("reason", 3, "string"),
    ],
    "/oasyce.capability.v1.MsgFailInvocation": [
        ("creator", 1, "string"),
        ("invocation_id", 2, "string"),
    ],
    "/oasyce.capability.v1.MsgInvokeCapability": [
        ("creator", 1, "string"),
        ("capability_id", 2, "string"),
        ("input", 3, "bytes"),
    ],
    "/oasyce.capability.v1.MsgRegisterCapability": [
        ("creator", 1, "string"),
        ("name", 2, "string"),
        ("description", 3, "string"),
        ("endpoint_url", 4, "string"),
        ("price_per_call", 5, "coin"),
        ("tags", 6, "repeated_string"),
        ("rate_limit", 7, "uint64"),
    ],
    "/oasyce.capability.v1.MsgUpdateCapability": [
        ("creator", 1, "string"),
        ("capability_id", 2, "string"),
        ("endpoint_url", 3, "string"),
        ("price_per_call", 4, "coin"),
        ("rate_limit", 5, "uint64"),
        ("description", 6, "string"),
    ],
    "/oasyce.datarights.v1.MsgBuyShares": [
        ("creator", 1, "string"),
        ("asset_id", 2, "string"),
        ("amount", 3, "coin"),
        ("min_shares_out", 4, "string"),
    ],
    "/oasyce.datarights.v1.MsgClaimSettlement": [
        ("creator", 1, "string"),
        ("asset_id", 2, "string"),
    ],
    "/oasyce.datarights.v1.MsgCreateMigrationPath": [
        ("creator", 1, "string"),
        ("source_asset_id", 2, "string"),
        ("target_asset_id", 3, "string"),
        ("exchange_rate_bps", 4, "uint32"),
        ("max_migrated_shares", 5, "string"),
    ],
    "/oasyce.datarights.v1.MsgDelistAsset": [
        ("creator", 1, "string"),
        ("asset_id", 2, "string"),
    ],
    "/oasyce.datarights.v1.MsgDisableMigration": [
        ("creator", 1, "string"),
        ("source_asset_id", 2, "string"),
        ("target_asset_id", 3, "string"),
    ],
    "/oasyce.datarights.v1.MsgFileDispute": [
        ("creator", 1, "string"),
        ("asset_id", 2, "string"),
        ("reason", 3, "string"),
        ("evidence", 4, "bytes"),
        ("requested_remedy", 5, "enum"),
    ],
    "/oasyce.datarights.v1.MsgInitiateShutdown": [
        ("creator", 1, "string"),
        ("asset_id", 2, "string"),
    ],
    "/oasyce.datarights.v1.MsgMigrate": [
        ("creator", 1, "string"),
        ("source_asset_id", 2, "string"),
        ("target_asset_id", 3, "string"),
        ("shares", 4, "string"),
    ],
    "/oasyce.datarights.v1.MsgRegisterDataAsset": [
        ("creator", 1, "string"),
        ("name", 2, "string"),
        ("description", 3, "string"),
        ("content_hash", 4, "string"),
        ("rights_type", 5, "enum"),
        ("tags", 6, "repeated_string"),
        ("co_creators", 7, "repeated_nested:oasyce.datarights.v1.CoCreator"),
        ("parent_asset_id", 8, "string"),
        ("service_url", 9, "string"),
    ],
    "/oasyce.datarights.v1.MsgResolveDispute": [
        ("creator", 1, "string"),
        ("dispute_id", 2, "string"),
        ("remedy", 3, "enum"),
        ("details", 4, "bytes"),
    ],
    "/oasyce.datarights.v1.MsgSellShares": [
        ("creator", 1, "string"),
        ("asset_id", 2, "string"),
        ("shares", 3, "string"),
        ("min_payout_out", 4, "string"),
    ],
    "/oasyce.datarights.v1.MsgUpdateServiceUrl": [
        ("creator", 1, "string"),
        ("asset_id", 2, "string"),
        ("service_url", 3, "string"),
    ],
    "/oasyce.delegate.v1.MsgEnroll": [
        ("delegate", 1, "string"),
        ("principal", 2, "string"),
        ("token", 3, "string"),
        ("label", 4, "string"),
    ],
    "/oasyce.delegate.v1.MsgRevoke": [
        ("principal", 1, "string"),
        ("delegate", 2, "string"),
    ],
    "/oasyce.delegate.v1.MsgSetPolicy": [
        ("principal", 1, "string"),
        ("per_tx_limit", 2, "coin"),
        ("window_limit", 3, "coin"),
        ("window_seconds", 4, "uint64"),
        ("allowed_msgs", 5, "repeated_string"),
        ("enrollment_token", 6, "string"),
        ("expiration_seconds", 7, "uint64"),
    ],
    "/oasyce.onboarding.v1.MsgRepayDebt": [
        ("creator", 1, "string"),
        ("amount", 2, "string"),
    ],
    "/oasyce.onboarding.v1.MsgSelfRegister": [
        ("creator", 1, "string"),
        ("nonce", 2, "uint64"),
    ],
    "/oasyce.reputation.v1.MsgReportMisbehavior": [
        ("creator", 1, "string"),
        ("target", 2, "string"),
        ("evidence_type", 3, "string"),
        ("evidence", 4, "bytes"),
    ],
    "/oasyce.reputation.v1.MsgSubmitFeedback": [
        ("creator", 1, "string"),
        ("invocation_id", 2, "string"),
        ("rating", 3, "uint32"),
        ("comment", 4, "string"),
    ],
    "/oasyce.settlement.v1.MsgCreateEscrow": [
        ("creator", 1, "string"),
        ("capability_id", 2, "string"),
        ("asset_id", 3, "string"),
        ("amount", 4, "coin"),
    ],
    "/oasyce.settlement.v1.MsgRefundEscrow": [
        ("creator", 1, "string"),
        ("escrow_id", 2, "string"),
    ],
    "/oasyce.settlement.v1.MsgReleaseEscrow": [
        ("creator", 1, "string"),
        ("escrow_id", 2, "string"),
    ],
    "/oasyce.sigil.v1.MsgBond": [
        ("signer", 1, "string"),
        ("sigil_a", 2, "string"),
        ("sigil_b", 3, "string"),
        ("terms_hash", 4, "bytes"),
        ("scope", 5, "string"),
    ],
    "/oasyce.sigil.v1.MsgDissolve": [
        ("signer", 1, "string"),
        ("sigil_id", 2, "string"),
    ],
    "/oasyce.sigil.v1.MsgFork": [
        ("signer", 1, "string"),
        ("parent_sigil_id", 2, "string"),
        ("public_key", 3, "bytes"),
        ("fork_mode", 4, "uint32"),
        ("mutation", 5, "string"),
        ("metadata", 6, "string"),
    ],
    "/oasyce.sigil.v1.MsgGenesis": [
        ("signer", 1, "string"),
        ("public_key", 2, "bytes"),
        ("lineage", 3, "repeated_string"),
        ("state_root", 4, "bytes"),
        ("metadata", 5, "string"),
    ],
    "/oasyce.sigil.v1.MsgMerge": [
        ("signer", 1, "string"),
        ("sigil_a", 2, "string"),
        ("sigil_b", 3, "string"),
        ("merge_mode", 4, "uint32"),
        ("metadata", 5, "string"),
    ],
    "/oasyce.sigil.v1.MsgPulse": [
        ("signer", 1, "string"),
        ("sigil_id", 2, "string"),
        ("dimensions", 3, "map_string_uint64"),
    ],
    "/oasyce.sigil.v1.MsgUnbond": [
        ("signer", 1, "string"),
        ("bond_id", 2, "string"),
    ],
    "/oasyce.sigil.v1.MsgUpdateParams": [
        ("authority", 1, "string"),
        ("params", 2, "nested:oasyce.sigil.v1.Params"),
    ],
    "/oasyce.work.v1.MsgCommitResult": [
        ("executor", 1, "string"),
        ("task_id", 2, "uint64"),
        ("commit_hash", 3, "bytes"),
    ],
    "/oasyce.work.v1.MsgDisputeResult": [
        ("challenger", 1, "string"),
        ("task_id", 2, "uint64"),
        ("reason", 3, "string"),
        ("bond", 4, "coin"),
    ],
    "/oasyce.work.v1.MsgRegisterExecutor": [
        ("executor", 1, "string"),
        ("supported_task_types", 2, "repeated_string"),
        ("max_compute_units", 3, "uint64"),
    ],
    "/oasyce.work.v1.MsgRevealResult": [
        ("executor", 1, "string"),
        ("task_id", 2, "uint64"),
        ("output_hash", 3, "bytes"),
        ("output_uri", 4, "string"),
        ("compute_units_used", 5, "uint64"),
        ("salt", 6, "bytes"),
        ("unavailable", 7, "bool"),
    ],
    "/oasyce.work.v1.MsgSubmitTask": [
        ("creator", 1, "string"),
        ("task_type", 2, "string"),
        ("input_hash", 3, "bytes"),
        ("input_uri", 4, "string"),
        ("max_compute_units", 5, "uint64"),
        ("bounty", 6, "coin"),
        ("redundancy", 7, "uint32"),
        ("timeout_blocks", 8, "uint64"),
    ],
    "/oasyce.work.v1.MsgUpdateExecutor": [
        ("executor", 1, "string"),
        ("supported_task_types", 2, "repeated_string"),
        ("max_compute_units", 3, "uint64"),
        ("active", 4, "bool"),
    ],
}

NESTED_SCHEMAS: Dict[str, List[Tuple[str, int, str]]] = {
    "oasyce.datarights.v1.CoCreator": [
        ("address", 1, "string"),
        ("share_bps", 2, "uint32"),
    ],
    "oasyce.sigil.v1.Params": [
        ("dormant_threshold", 1, "uint64"),
        ("dissolve_threshold", 2, "uint64"),
        ("submit_window", 3, "uint64"),
    ],
}

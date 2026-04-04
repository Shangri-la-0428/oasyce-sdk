import base64
from pathlib import Path
from types import SimpleNamespace

from oasyce_sdk.crypto.protobuf import MSG_SCHEMAS, encode_msg
from oasyce_sdk.crypto.signer import NativeSigner, TxResult


def test_all_signer_messages_have_protobuf_support():
    signer_source = Path(
        "/Users/wutongcheng/Desktop/oasyce-sdk/oasyce_sdk/crypto/signer.py"
    ).read_text()
    type_urls = {
        token
        for token in signer_source.split('"')
        if token.startswith("/") and ".Msg" in token
    }
    special_cases = {
        "/cosmos.bank.v1beta1.MsgSend",
        "/oasyce.delegate.v1.MsgExec",
        "/oasyce.anchor.v1.MsgAnchorBatch",
    }
    missing = sorted(type_urls - set(MSG_SCHEMAS) - special_cases)
    assert missing == []


def test_encode_delegate_policy_message():
    encoded = encode_msg(
        "/oasyce.delegate.v1.MsgSetPolicy",
        {
            "principal": "oasyce1principal",
            "per_tx_limit": {"denom": "uoas", "amount": "1000000"},
            "window_limit": {"denom": "uoas", "amount": "10000000"},
            "window_seconds": "86400",
            "allowed_msgs": ["/cosmos.bank.v1beta1.MsgSend"],
            "enrollment_token": "shared-secret",
            "expiration_seconds": "0",
        },
    )
    assert b"oasyce1principal" in encoded
    assert b"/cosmos.bank.v1beta1.MsgSend" in encoded
    assert b"shared-secret" in encoded
    assert b"uoas" in encoded


def test_encode_delegate_exec_message_with_inner_any():
    encoded = encode_msg(
        "/oasyce.delegate.v1.MsgExec",
        {
            "delegate": "oasyce1delegate",
            "msgs": [
                {
                    "@type": "/cosmos.bank.v1beta1.MsgSend",
                    "from_address": "oasyce1principal",
                    "to_address": "oasyce1target",
                    "amount": {"denom": "uoas", "amount": "42"},
                }
            ],
        },
    )
    assert b"oasyce1delegate" in encoded
    assert b"/cosmos.bank.v1beta1.MsgSend" in encoded
    assert b"oasyce1target" in encoded
    assert b"uoas" in encoded


def test_encode_anchor_trace_and_batch_messages():
    trace = {
        "signer": "oasyce1principal",
        "trace_id": "AQID",
        "node_pubkey": "BAUG",
        "capability": "trace.capability",
        "outcome": 7,
        "timestamp": "123456789",
        "trace_signature": "BwgJ",
    }
    single = encode_msg("/oasyce.anchor.v1.MsgAnchorTrace", trace)
    batch = encode_msg(
        "/oasyce.anchor.v1.MsgAnchorBatch",
        {
            "signer": "oasyce1principal",
            "anchors": [
                trace,
                {
                    **trace,
                    "capability": "trace.capability.2",
                    "trace_id": "CgsM",
                },
            ],
        },
    )
    assert b"trace.capability" in single
    assert b"oasyce1principal" in batch
    assert b"trace.capability" in batch
    assert b"trace.capability.2" in batch


class RecordingSigner(NativeSigner):
    def __init__(self, address: str = "oasyce1delegate", principal: str | None = None):
        super().__init__(
            wallet=SimpleNamespace(address=address),
            client=object(),
            principal=principal,
        )
        self.recorded = None

    def sign_and_broadcast(self, messages, memo=None, gas_limit=None, fee=None):
        self.recorded = messages
        return TxResult("tx", True, 0, "")


def test_delegate_helper_methods_build_expected_messages():
    signer = RecordingSigner()

    signer.set_delegate_policy(
        token="shared-secret",
        allowed_msgs=["/cosmos.bank.v1beta1.MsgSend"],
        per_tx_uoas=5,
        window_uoas=9,
        window_seconds=60,
    )
    assert signer.recorded == [
        (
            "/oasyce.delegate.v1.MsgSetPolicy",
            {
                "principal": "oasyce1delegate",
                "per_tx_limit": {"denom": "uoas", "amount": "5"},
                "window_limit": {"denom": "uoas", "amount": "9"},
                "window_seconds": "60",
                "allowed_msgs": ["/cosmos.bank.v1beta1.MsgSend"],
                "enrollment_token": "shared-secret",
                "expiration_seconds": "0",
            },
        )
    ]

    signer.enroll_delegate("oasyce1principal", "shared-secret", label="mbp")
    assert signer.recorded == [
        (
            "/oasyce.delegate.v1.MsgEnroll",
            {
                "delegate": "oasyce1delegate",
                "principal": "oasyce1principal",
                "token": "shared-secret",
                "label": "mbp",
            },
        )
    ]

    signer.revoke_delegate("oasyce1other")
    assert signer.recorded == [
        (
            "/oasyce.delegate.v1.MsgRevoke",
            {"principal": "oasyce1delegate", "delegate": "oasyce1other"},
        )
    ]

    signer.delegate_exec(
        [
            {
                "type_url": "/cosmos.bank.v1beta1.MsgSend",
                "value": {
                    "from_address": "oasyce1principal",
                    "to_address": "oasyce1target",
                    "amount": {"denom": "uoas", "amount": "42"},
                },
            }
        ]
    )
    assert signer.recorded == [
        (
            "/oasyce.delegate.v1.MsgExec",
            {
                "delegate": "oasyce1delegate",
                "msgs": [
                    {
                        "@type": "/cosmos.bank.v1beta1.MsgSend",
                        "from_address": "oasyce1principal",
                        "to_address": "oasyce1target",
                        "amount": {"denom": "uoas", "amount": "42"},
                    }
                ],
            },
        )
    ]


def test_anchor_batch_helper_builds_expected_message():
    signer = RecordingSigner("oasyce1principal")
    signer.anchor_batch(
        [
            {
                "trace_id_hex": "010203",
                "node_pubkey_hex": "040506",
                "capability": "trace.capability",
                "outcome": 7,
                "timestamp": 123,
                "trace_signature_hex": "070809",
            }
        ]
    )
    assert signer.recorded == [
        (
            "/oasyce.anchor.v1.MsgAnchorBatch",
            {
                "signer": "oasyce1principal",
                "anchors": [
                    {
                        "signer": "oasyce1principal",
                        "trace_id": "AQID",
                        "node_pubkey": "BAUG",
                        "capability": "trace.capability",
                        "outcome": 7,
                        "timestamp": "123",
                        "trace_signature": "BwgJ",
                    }
                ],
            },
        )
    ]


def test_delegated_signer_wraps_business_messages_as_msg_exec():
    signer = RecordingSigner("oasyce1delegate", principal="oasyce1principal")
    signer.register_asset("demo.txt", "sha256:abc")
    assert signer.recorded == [
        (
            "/oasyce.delegate.v1.MsgExec",
            {
                "delegate": "oasyce1delegate",
                "msgs": [
                    {
                        "@type": "/oasyce.datarights.v1.MsgRegisterDataAsset",
                        "creator": "oasyce1principal",
                        "name": "demo.txt",
                        "description": "",
                        "content_hash": "sha256:abc",
                        "rights_type": "RIGHTS_TYPE_ORIGINAL",
                        "tags": [],
                        "parent_asset_id": "",
                        "service_url": "",
                    }
                ],
            },
        )
    ]

    signer.send("oasyce1target", 42)
    assert signer.recorded == [
        (
            "/oasyce.delegate.v1.MsgExec",
            {
                "delegate": "oasyce1delegate",
                "msgs": [
                    {
                        "@type": "/cosmos.bank.v1beta1.MsgSend",
                        "from_address": "oasyce1principal",
                        "to_address": "oasyce1target",
                        "amount": [{"denom": "uoas", "amount": "42"}],
                    }
                ],
            },
        )
    ]


def test_delegated_signer_keeps_identity_and_delegate_control_messages_direct():
    signer = RecordingSigner("oasyce1delegate", principal="oasyce1principal")
    public_key_hex = "02" + "11" * 32
    signer.create_sigil(public_key_hex)
    assert signer.recorded == [
        (
            "/oasyce.sigil.v1.MsgGenesis",
            {
                "signer": "oasyce1delegate",
                "public_key": base64.b64encode(bytes.fromhex(public_key_hex)).decode(),
            },
        )
    ]

    signer.enroll_delegate("oasyce1principal", "shared-secret")
    assert signer.recorded == [
        (
            "/oasyce.delegate.v1.MsgEnroll",
            {
                "delegate": "oasyce1delegate",
                "principal": "oasyce1principal",
                "token": "shared-secret",
                "label": "",
            },
        )
    ]

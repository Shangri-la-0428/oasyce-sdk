import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from oasyce_sdk.crypto.protobuf import MSG_SCHEMAS, NESTED_SCHEMAS, encode_msg
from oasyce_sdk.crypto.protobuf import (
    _encode_from_schema,
    _encode_map,
    _parse_map_kind,
)
from oasyce_sdk.crypto.signer import NativeSigner, TxResult


def _varint(value: int) -> bytes:
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value & 0x7F)
    return bytes(out)


def _tag(field_number: int, wire_type: int) -> bytes:
    return _varint((field_number << 3) | wire_type)


def test_all_signer_messages_have_protobuf_support():
    signer_source = (
        Path(__file__).resolve().parents[1] / "oasyce_sdk" / "crypto" / "signer.py"
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


def test_msg_genesis_lineage_round_trips_with_chain_canonical_field_numbers():
    """Regression guard for the MSG_SCHEMAS drift that put lineage and
    state_root under each other's field numbers.  Chain canonical layout:

        signer     = 1  (string)
        public_key = 2  (bytes)
        lineage    = 3  (repeated string)
        state_root = 4  (bytes)
        metadata   = 5  (string)
    """
    parent_sigil = "SIG_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    pubkey = bytes.fromhex("02" + "11" * 32)  # 33-byte compressed secp256k1
    state_root = bytes.fromhex("ab" * 32)
    encoded = encode_msg(
        "/oasyce.sigil.v1.MsgGenesis",
        {
            "signer": "oasyce1signer",
            "public_key": base64.b64encode(pubkey).decode(),
            "lineage": [parent_sigil],
            "state_root": base64.b64encode(state_root).decode(),
            "metadata": '{"name":"Joi"}',
        },
    )

    # Manually construct the expected wire bytes in canonical order:
    signer_bytes = b"oasyce1signer"
    lineage_bytes = parent_sigil.encode()
    metadata_bytes = b'{"name":"Joi"}'
    expected = (
        _tag(1, 2) + _varint(len(signer_bytes)) + signer_bytes
        + _tag(2, 2) + _varint(len(pubkey)) + pubkey
        + _tag(3, 2) + _varint(len(lineage_bytes)) + lineage_bytes
        + _tag(4, 2) + _varint(len(state_root)) + state_root
        + _tag(5, 2) + _varint(len(metadata_bytes)) + metadata_bytes
    )
    assert encoded == expected, (
        f"MsgGenesis wire bytes drift — regenerate msg_schemas.py from chain."
        f"\n  got:      {encoded.hex()}"
        f"\n  expected: {expected.hex()}"
    )

    # Sanity: the parent Sigil ID must appear under field 3 (lineage), NOT
    # under field 4 (state_root) where the buggy schema placed it.
    lineage_tag = _tag(3, 2)
    state_root_tag = _tag(4, 2)
    # The parent Sigil ID starts right after `lineage_tag + varint(len)`.
    lineage_prefix = lineage_tag + _varint(len(lineage_bytes))
    assert lineage_prefix + lineage_bytes in encoded
    # It must not appear under field 4.
    assert state_root_tag + _varint(len(lineage_bytes)) + lineage_bytes not in encoded


def test_msg_fork_uses_chain_canonical_field_names():
    """MsgFork.public_key (not child_public_key) and mutation as string."""
    child_pubkey = bytes.fromhex("03" + "22" * 32)
    encoded = encode_msg(
        "/oasyce.sigil.v1.MsgFork",
        {
            "signer": "oasyce1parent",
            "parent_sigil_id": "SIG_parent",
            "public_key": base64.b64encode(child_pubkey).decode(),
            "mutation": '{"trait":"curious"}',
        },
    )
    # Field 3 is the child pubkey (bytes)
    assert _tag(3, 2) + _varint(len(child_pubkey)) + child_pubkey in encoded
    # Field 5 is mutation encoded verbatim as string bytes (no base64 wrapper)
    mutation_bytes = b'{"trait":"curious"}'
    assert _tag(5, 2) + _varint(len(mutation_bytes)) + mutation_bytes in encoded


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


# ---------------------------------------------------------------------------
# Map-field support — MsgPulse.dimensions (map<string, int64>)
# ---------------------------------------------------------------------------


def _map_entry(key: str, value: int) -> bytes:
    """Build the inner ``<Name>Entry`` bytes for a string→int map entry.

    Mirrors the gogoproto layout: key is field 1 (bytes wire), value is
    field 2 (varint wire) and is omitted when zero.
    """
    kb = key.encode("utf-8")
    entry = _tag(1, 2) + _varint(len(kb)) + kb
    if value != 0:
        entry += _tag(2, 0) + _varint(value)
    return entry


def _map_field(field_number: int, entries: list[tuple[str, int]]) -> bytes:
    """Build the full wire bytes for a map field given its sorted entries."""
    out = b""
    for k, v in entries:
        e = _map_entry(k, v)
        out += _tag(field_number, 2) + _varint(len(e)) + e
    return out


def test_msg_pulse_schema_entry_is_generated_from_chain_proto():
    """``MsgPulse.dimensions`` must be classified as a map kind, not skipped.

    Regression guard for the ``# SKIP`` comment that the generator used to
    emit for ``map[string]int64`` fields.  If the classifier regresses, the
    schema entry will either go missing or be listed with fewer fields.
    """
    schema = MSG_SCHEMAS["/oasyce.sigil.v1.MsgPulse"]
    assert ("signer", 1, "string") in schema
    assert ("sigil_id", 2, "string") in schema
    # map value is classified as uint64 (int64 and uint64 share the varint
    # wire representation — see _MAP_SCALAR_KIND in _gen_schemas.py).
    assert ("dimensions", 3, "map_string_uint64") in schema


def test_encode_msg_pulse_with_dimensions_matches_chain_wire_format():
    """Wire-byte equality check for MsgPulse with a populated dimensions map.

    Entries must be sorted lexicographically by their UTF-8 key bytes so that
    the SDK's output matches Cosmos SDK v0.50's deterministic sign-mode
    marshal on the chain side — otherwise signatures would not verify.
    """
    signer_bytes = b"oasyce1pulser"
    sigil_bytes = b"SIG_pulsepulsepulsepulsepulsepul"

    encoded = encode_msg(
        "/oasyce.sigil.v1.MsgPulse",
        {
            "signer": signer_bytes.decode(),
            "sigil_id": sigil_bytes.decode(),
            # Intentionally out of order — encoder must sort.
            "dimensions": {"thronglets": 5, "psyche": 3, "economy": 7},
        },
    )

    expected = (
        _tag(1, 2) + _varint(len(signer_bytes)) + signer_bytes
        + _tag(2, 2) + _varint(len(sigil_bytes)) + sigil_bytes
        + _map_field(3, [("economy", 7), ("psyche", 3), ("thronglets", 5)])
    )
    assert encoded == expected, (
        "MsgPulse wire bytes drift."
        f"\n  got:      {encoded.hex()}"
        f"\n  expected: {expected.hex()}"
    )


def test_encode_msg_pulse_dimensions_sort_is_insertion_order_independent():
    """Two dicts with the same entries must encode to byte-identical bytes."""
    base_fields = {"signer": "oasyce1a", "sigil_id": "SIG_x"}
    a = encode_msg(
        "/oasyce.sigil.v1.MsgPulse",
        {**base_fields, "dimensions": {"c": 3, "a": 1, "b": 2}},
    )
    b = encode_msg(
        "/oasyce.sigil.v1.MsgPulse",
        {**base_fields, "dimensions": {"a": 1, "b": 2, "c": 3}},
    )
    assert a == b


def test_encode_msg_pulse_dimension_with_zero_value_omits_value_but_writes_key():
    """Gogoproto Marshal writes the key unconditionally but omits value=0.

    The SDK encoder must match this exactly or the wire bytes diverge from
    what the chain's verifier would re-serialize for signature checking.
    """
    encoded = encode_msg(
        "/oasyce.sigil.v1.MsgPulse",
        {
            "signer": "oasyce1a",
            "sigil_id": "SIG_x",
            "dimensions": {"idle": 0},
        },
    )
    # Entry is key-only: tag(1,2) + len("idle")=4 + b"idle"
    key_bytes = b"idle"
    expected_entry = _tag(1, 2) + _varint(len(key_bytes)) + key_bytes
    expected_field = _tag(3, 2) + _varint(len(expected_entry)) + expected_entry
    assert expected_field in encoded
    # And the value tag 0x10 must NOT appear in the dimensions portion.
    dims_start = encoded.index(_tag(3, 2))
    assert b"\x10" not in encoded[dims_start:]


def test_encode_msg_pulse_omits_dimensions_field_when_empty():
    """An empty dimensions map produces zero bytes for field 3."""
    encoded = encode_msg(
        "/oasyce.sigil.v1.MsgPulse",
        {"signer": "oasyce1a", "sigil_id": "SIG_x", "dimensions": {}},
    )
    assert _tag(3, 2) not in encoded


def test_encode_msg_pulse_omits_dimensions_field_when_missing():
    """A missing dimensions key behaves the same as an empty map."""
    encoded = encode_msg(
        "/oasyce.sigil.v1.MsgPulse",
        {"signer": "oasyce1a", "sigil_id": "SIG_x"},
    )
    assert _tag(3, 2) not in encoded


def test_encode_msg_pulse_rejects_non_mapping_dimensions():
    """Passing a list where a map is expected must fail loudly, not silently."""
    with pytest.raises(TypeError, match="map"):
        encode_msg(
            "/oasyce.sigil.v1.MsgPulse",
            {
                "signer": "oasyce1a",
                "sigil_id": "SIG_x",
                "dimensions": [("psyche", 1)],
            },
        )


def test_parse_map_kind_accepts_valid_forms_and_rejects_garbage():
    assert _parse_map_kind("map_string_uint64") == ("string", "uint64")
    assert _parse_map_kind("map_string_int64") == ("string", "int64")
    assert _parse_map_kind("map_uint32_string") == ("uint32", "string")
    for bad in ("map_", "map_string", "mapstringstring", "map__string"):
        with pytest.raises(ValueError, match="malformed map kind"):
            _parse_map_kind(bad)


def test_encode_map_helper_sorts_by_key_bytes_not_python_ordering():
    """Keys with non-ASCII bytes must sort by UTF-8 byte order to match Go."""
    # "é" in UTF-8 is 0xc3 0xa9, which is > any ASCII letter byte.
    # So sorted order is: "a", "z", "é" — not Python's default unicode sort
    # (which also happens to agree here, but we want to pin the contract).
    encoded = _encode_map(
        field_number=3,
        entries={"é": 3, "a": 1, "z": 2},
        key_kind="string",
        value_kind="uint64",
    )
    expected = _map_field(
        3, [("a", 1), ("z", 2), ("é", 3)]
    )
    assert encoded == expected


def test_pulse_sigil_signer_method_builds_expected_message():
    signer = RecordingSigner("oasyce1pulser")
    signer.pulse_sigil(
        "SIG_abcabcabcabcabcabcabcabcabcabcab",
        {"psyche": 42, "thronglets": 99},
    )
    assert signer.recorded == [
        (
            "/oasyce.sigil.v1.MsgPulse",
            {
                "signer": "oasyce1pulser",
                "sigil_id": "SIG_abcabcabcabcabcabcabcabcabcabcab",
                "dimensions": {"psyche": 42, "thronglets": 99},
            },
        )
    ]


def test_pulse_sigil_signer_method_elides_empty_dimensions():
    signer = RecordingSigner("oasyce1pulser")
    signer.pulse_sigil("SIG_x")
    assert signer.recorded == [
        (
            "/oasyce.sigil.v1.MsgPulse",
            {"signer": "oasyce1pulser", "sigil_id": "SIG_x"},
        )
    ]


# ---------------------------------------------------------------------------
# Nested-message support — MsgRegisterDataAsset.co_creators (repeated),
#                         MsgUpdateParams.params (single nested)
# ---------------------------------------------------------------------------


def _len_prefixed(field_number: int, inner: bytes) -> bytes:
    """Wrap ``inner`` as a length-delimited field — shared by all nested tests."""
    return _tag(field_number, 2) + _varint(len(inner)) + inner


def _co_creator_bytes(address: str, share_bps: int) -> bytes:
    """Construct the CoCreator submessage body the chain would marshal.

    Matches the gogoproto output from ``oasyce-chain/x/datarights/types/
    types.pb.go:CoCreator.MarshalToSizedBuffer``: field 1 is ``address``
    (string, bytes wire), field 2 is ``share_bps`` (varint, omitted when 0).
    """
    ab = address.encode("utf-8")
    body = b""
    if ab:
        body += _tag(1, 2) + _varint(len(ab)) + ab
    if share_bps:
        body += _tag(2, 0) + _varint(share_bps)
    return body


def test_msg_register_data_asset_schema_entry_uses_repeated_nested_co_creator():
    """``co_creators`` must be classified, not emitted as a ``# SKIP`` comment.

    Regression guard for the long-standing gap where the generator dropped
    ``[]CoCreator`` because it had no handler for repeated nested messages.
    """
    schema = MSG_SCHEMAS["/oasyce.datarights.v1.MsgRegisterDataAsset"]
    assert (
        "co_creators",
        7,
        "repeated_nested:oasyce.datarights.v1.CoCreator",
    ) in schema


def test_nested_schemas_registers_co_creator_with_chain_field_numbers():
    """Field numbers and kinds must mirror the chain's CoCreator struct tags."""
    assert NESTED_SCHEMAS["oasyce.datarights.v1.CoCreator"] == [
        ("address", 1, "string"),
        ("share_bps", 2, "uint32"),
    ]


def test_encode_msg_register_data_asset_with_co_creators_matches_wire_format():
    """Byte-exact check: a populated co_creators list must encode the same
    bytes the chain would produce, so signature verification holds under
    SIGN_MODE_DIRECT where the client's bytes are canonical.
    """
    creator = "oasyce1creator"
    name = "test asset"
    description = "desc"
    content_hash = "hash"
    tags = ["a", "b"]
    co1 = _co_creator_bytes("oasyce1co1", 3000)
    co2 = _co_creator_bytes("oasyce1co2", 7000)
    service_url = "https://svc"

    encoded = encode_msg(
        "/oasyce.datarights.v1.MsgRegisterDataAsset",
        {
            "creator": creator,
            "name": name,
            "description": description,
            "content_hash": content_hash,
            "rights_type": 1,
            "tags": tags,
            "co_creators": [
                {"address": "oasyce1co1", "share_bps": 3000},
                {"address": "oasyce1co2", "share_bps": 7000},
            ],
            "service_url": service_url,
        },
    )

    expected = (
        _tag(1, 2) + _varint(len(creator)) + creator.encode()
        + _tag(2, 2) + _varint(len(name)) + name.encode()
        + _tag(3, 2) + _varint(len(description)) + description.encode()
        + _tag(4, 2) + _varint(len(content_hash)) + content_hash.encode()
        + _tag(5, 0) + _varint(1)
        + _tag(6, 2) + _varint(1) + b"a"
        + _tag(6, 2) + _varint(1) + b"b"
        + _len_prefixed(7, co1)
        + _len_prefixed(7, co2)
        + _tag(9, 2) + _varint(len(service_url)) + service_url.encode()
    )
    assert encoded == expected, (
        "MsgRegisterDataAsset wire bytes drift."
        f"\n  got:      {encoded.hex()}"
        f"\n  expected: {expected.hex()}"
    )


def test_encode_msg_register_data_asset_co_creator_list_order_is_preserved():
    """The chain walks the slice in the same order it was built — the SDK
    must not sort ``co_creators`` because shares bind to specific addresses.
    """
    order_a = [
        {"address": "oasyce1first", "share_bps": 5000},
        {"address": "oasyce1second", "share_bps": 5000},
    ]
    order_b = list(reversed(order_a))

    a = encode_msg(
        "/oasyce.datarights.v1.MsgRegisterDataAsset",
        {"creator": "c", "name": "n", "co_creators": order_a},
    )
    b = encode_msg(
        "/oasyce.datarights.v1.MsgRegisterDataAsset",
        {"creator": "c", "name": "n", "co_creators": order_b},
    )
    assert a != b
    assert a.index(b"oasyce1first") < a.index(b"oasyce1second")
    assert b.index(b"oasyce1second") < b.index(b"oasyce1first")


def test_encode_msg_register_data_asset_empty_co_creators_omits_field():
    """An empty list must produce zero bytes for field 7, matching gogoproto."""
    encoded = encode_msg(
        "/oasyce.datarights.v1.MsgRegisterDataAsset",
        {"creator": "c", "name": "n", "co_creators": []},
    )
    assert _tag(7, 2) not in encoded


def test_encode_msg_register_data_asset_missing_co_creators_omits_field():
    """A missing key behaves exactly the same as an empty list."""
    encoded = encode_msg(
        "/oasyce.datarights.v1.MsgRegisterDataAsset",
        {"creator": "c", "name": "n"},
    )
    assert _tag(7, 2) not in encoded


def test_encode_msg_register_data_asset_rejects_non_list_co_creators():
    """Passing a dict where a list is expected must fail loudly, not silently."""
    with pytest.raises(TypeError, match="repeated nested"):
        encode_msg(
            "/oasyce.datarights.v1.MsgRegisterDataAsset",
            {"creator": "c", "name": "n", "co_creators": {"addr": "x"}},
        )


def test_encode_msg_register_data_asset_rejects_non_mapping_list_item():
    """Each slot in the list must be a mapping — tuple/str inputs are a bug."""
    with pytest.raises(TypeError, match="must be a mapping"):
        encode_msg(
            "/oasyce.datarights.v1.MsgRegisterDataAsset",
            {
                "creator": "c",
                "name": "n",
                "co_creators": [("oasyce1co1", 3000)],
            },
        )


def test_msg_update_params_schema_entry_is_nested_sigil_params():
    """``params`` must be classified as a single nested message, not SKIPped."""
    schema = MSG_SCHEMAS["/oasyce.sigil.v1.MsgUpdateParams"]
    assert ("params", 2, "nested:oasyce.sigil.v1.Params") in schema


def test_nested_schemas_registers_sigil_params_with_three_threshold_fields():
    assert NESTED_SCHEMAS["oasyce.sigil.v1.Params"] == [
        ("dormant_threshold", 1, "uint64"),
        ("dissolve_threshold", 2, "uint64"),
        ("submit_window", 3, "uint64"),
    ]


def test_encode_msg_update_params_with_full_params_matches_wire_format():
    """Byte-exact check for a single (non-repeated) nested message field."""
    authority = "oasyce1auth"

    encoded = encode_msg(
        "/oasyce.sigil.v1.MsgUpdateParams",
        {
            "authority": authority,
            "params": {
                "dormant_threshold": 100,
                "dissolve_threshold": 200,
                "submit_window": 50,
            },
        },
    )

    inner = (
        _tag(1, 0) + _varint(100)
        + _tag(2, 0) + _varint(200)
        + _tag(3, 0) + _varint(50)
    )
    expected = (
        _tag(1, 2) + _varint(len(authority)) + authority.encode()
        + _len_prefixed(2, inner)
    )
    assert encoded == expected, (
        "MsgUpdateParams wire bytes drift."
        f"\n  got:      {encoded.hex()}"
        f"\n  expected: {expected.hex()}"
    )


def test_encode_msg_update_params_with_empty_params_emits_length_zero_submsg():
    """Gogoproto nullable=false emits an empty submsg even when the struct is
    all zero values.  The SDK must do the same when the caller passes ``{}``
    so that a SIGN_MODE_DIRECT client can produce bytes the chain re-parses
    into an identical ``Params{}`` struct for signature checking.
    """
    encoded = encode_msg(
        "/oasyce.sigil.v1.MsgUpdateParams",
        {"authority": "a", "params": {}},
    )
    # authority + tag(2,2) + varint(0)
    assert encoded.endswith(_tag(2, 2) + _varint(0))


def test_encode_msg_update_params_missing_params_key_omits_field():
    """When the caller supplies no ``params`` key at all, field 2 is absent."""
    encoded = encode_msg(
        "/oasyce.sigil.v1.MsgUpdateParams",
        {"authority": "a"},
    )
    assert _tag(2, 2) not in encoded


def test_encode_msg_update_params_rejects_non_mapping_params():
    """Passing a list where a mapping is expected must fail loudly."""
    with pytest.raises(TypeError, match="nested"):
        encode_msg(
            "/oasyce.sigil.v1.MsgUpdateParams",
            {"authority": "a", "params": [("dormant_threshold", 1)]},
        )


def test_encode_from_schema_raises_on_unknown_nested_fqn():
    """Using a kind that points at a nested FQN missing from NESTED_SCHEMAS
    must fail immediately with a clear pointer to the drifted generator,
    not silently produce a zero-length field.
    """
    bogus_schema = [("child", 1, "nested:oasyce.nonexistent.v1.Ghost")]
    with pytest.raises(ValueError, match="unknown nested schema"):
        _encode_from_schema(bogus_schema, {"child": {}}, "/fake.TypeUrl")


def test_encode_from_schema_raises_on_unknown_repeated_nested_fqn():
    bogus_schema = [("kids", 2, "repeated_nested:oasyce.nonexistent.v1.Ghost")]
    with pytest.raises(ValueError, match="unknown nested schema"):
        _encode_from_schema(bogus_schema, {"kids": [{}]}, "/fake.TypeUrl")

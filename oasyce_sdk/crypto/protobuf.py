"""Hand-rolled Protobuf wire encoder for Cosmos SDK transactions.

No generated stubs, no protobuf library dependency.  Data-driven schema
registry: adding a new message type = adding a dict entry.

Only encodes — decoding is handled by the chain's REST/gRPC responses
which come back as JSON.

Wire format reference: https://protobuf.dev/programming-guides/encoding/
"""

import base64
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Protobuf wire types
# ---------------------------------------------------------------------------
VARINT = 0
FIXED64 = 1
LENGTH_DELIMITED = 2
FIXED32 = 5

# ---------------------------------------------------------------------------
# Low-level wire encoding
# ---------------------------------------------------------------------------


def _encode_varint(value: int) -> bytes:
    """Encode an unsigned integer as a protobuf varint."""
    if value < 0:
        # Protobuf uses two's complement for negative varints (10 bytes)
        value = value + (1 << 64)
    parts = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value & 0x7F)
    return bytes(parts)


def _encode_tag(field_number: int, wire_type: int) -> bytes:
    """Encode a protobuf field tag."""
    return _encode_varint((field_number << 3) | wire_type)


def _encode_bytes(field_number: int, data: bytes) -> bytes:
    """Encode a length-delimited bytes field."""
    if not data:
        return b""
    return _encode_tag(field_number, LENGTH_DELIMITED) + _encode_varint(len(data)) + data


def _encode_string(field_number: int, value: str) -> bytes:
    """Encode a string field."""
    if not value:
        return b""
    data = value.encode("utf-8")
    return _encode_tag(field_number, LENGTH_DELIMITED) + _encode_varint(len(data)) + data


def _encode_uint64(field_number: int, value: int) -> bytes:
    """Encode a uint64 varint field."""
    if not value:
        return b""
    return _encode_tag(field_number, VARINT) + _encode_varint(value)


def _encode_uint32(field_number: int, value: int) -> bytes:
    """Encode a uint32 varint field."""
    return _encode_uint64(field_number, value)


def _encode_int64(field_number: int, value: int) -> bytes:
    """Encode an int64 varint field."""
    return _encode_uint64(field_number, value)


def _encode_bool(field_number: int, value: bool) -> bytes:
    """Encode a bool field."""
    if not value:
        return b""
    return _encode_tag(field_number, VARINT) + _encode_varint(1)


def _encode_enum(field_number: int, value: int) -> bytes:
    """Encode an enum field (varint)."""
    if not value:
        return b""
    return _encode_tag(field_number, VARINT) + _encode_varint(value)


def _encode_message(field_number: int, data: bytes) -> bytes:
    """Encode a nested message field."""
    if not data:
        return b""
    return _encode_tag(field_number, LENGTH_DELIMITED) + _encode_varint(len(data)) + data


def _encode_repeated_string(field_number: int, values: List[str]) -> bytes:
    """Encode repeated string fields."""
    result = b""
    for v in values:
        if v:
            data = v.encode("utf-8")
            result += _encode_tag(field_number, LENGTH_DELIMITED) + _encode_varint(len(data)) + data
    return result


def _encode_repeated_bytes(field_number: int, values: List[bytes]) -> bytes:
    """Encode repeated bytes fields."""
    result = b""
    for v in values:
        result += _encode_tag(field_number, LENGTH_DELIMITED) + _encode_varint(len(v)) + v
    return result


def _encode_repeated_message(field_number: int, messages: List[bytes]) -> bytes:
    """Encode repeated message fields (each pre-encoded)."""
    result = b""
    for m in messages:
        result += _encode_tag(field_number, LENGTH_DELIMITED) + _encode_varint(len(m)) + m
    return result


# ---------------------------------------------------------------------------
# Cosmos SDK types
# ---------------------------------------------------------------------------

# Sign mode: SIGN_MODE_DIRECT = 1
SIGN_MODE_DIRECT = 1


def encode_coin(denom: str, amount: str) -> bytes:
    """Encode cosmos.base.v1beta1.Coin."""
    return _encode_string(1, denom) + _encode_string(2, amount)


def encode_any(type_url: str, value: bytes) -> bytes:
    """Encode google.protobuf.Any."""
    return _encode_string(1, type_url) + _encode_bytes(2, value)


def encode_pubkey(pubkey_bytes: bytes) -> bytes:
    """Encode cosmos.crypto.secp256k1.PubKey wrapped in Any."""
    # Inner: cosmos.crypto.secp256k1.PubKey { key: 1 (bytes) }
    inner = _encode_bytes(1, pubkey_bytes)
    return encode_any("/cosmos.crypto.secp256k1.PubKey", inner)


def encode_mode_info_single() -> bytes:
    """Encode ModeInfo with Single { mode: SIGN_MODE_DIRECT }."""
    # ModeInfo.Single { mode: 1 (enum) }
    single = _encode_enum(1, SIGN_MODE_DIRECT)
    # ModeInfo { single: 1 (message) }
    return _encode_message(1, single)


def encode_signer_info(pubkey_bytes: bytes, sequence: int) -> bytes:
    """Encode SignerInfo."""
    pubkey_any = encode_pubkey(pubkey_bytes)
    mode_info = encode_mode_info_single()
    return (
        _encode_message(1, pubkey_any)
        + _encode_message(2, mode_info)
        + _encode_uint64(3, sequence)
    )


def encode_fee(amount_uoas: int, gas_limit: int, denom: str = "uoas") -> bytes:
    """Encode Fee."""
    result = b""
    if amount_uoas > 0:
        coin = encode_coin(denom, str(amount_uoas))
        result += _encode_repeated_message(1, [coin])
    result += _encode_uint64(2, gas_limit)
    return result


def encode_auth_info(pubkey_bytes: bytes, sequence: int, fee_amount: int, gas_limit: int) -> bytes:
    """Encode AuthInfo."""
    signer_info = encode_signer_info(pubkey_bytes, sequence)
    fee = encode_fee(fee_amount, gas_limit)
    return _encode_repeated_message(1, [signer_info]) + _encode_message(2, fee)


def encode_tx_body(messages: List[bytes], memo: str = "") -> bytes:
    """Encode TxBody. Each message should already be encoded as Any."""
    result = _encode_repeated_message(1, messages)
    if memo:
        result += _encode_string(2, memo)
    return result


def encode_sign_doc(body_bytes: bytes, auth_info_bytes: bytes, chain_id: str, account_number: int) -> bytes:
    """Encode SignDoc for SIGN_MODE_DIRECT."""
    return (
        _encode_bytes(1, body_bytes)
        + _encode_bytes(2, auth_info_bytes)
        + _encode_string(3, chain_id)
        + _encode_uint64(4, account_number)
    )


def encode_tx_raw(body_bytes: bytes, auth_info_bytes: bytes, signatures: List[bytes]) -> bytes:
    """Encode TxRaw — the final broadcast format."""
    return (
        _encode_bytes(1, body_bytes)
        + _encode_bytes(2, auth_info_bytes)
        + _encode_repeated_bytes(3, signatures)
    )


# ---------------------------------------------------------------------------
# Message encoder — data-driven from schema registry
# ---------------------------------------------------------------------------

# Field type constants for the schema registry
F_STRING = "string"
F_BYTES = "bytes"
F_UINT64 = "uint64"
F_UINT32 = "uint32"
F_INT64 = "int64"
F_BOOL = "bool"
F_ENUM = "enum"
F_COIN = "coin"           # shorthand for nested Coin message
F_REPEATED_STRING = "repeated_string"
F_REPEATED_BYTES = "repeated_bytes"

# Schema registry: single source of truth is the chain's own .pb.go structs.
# ``msg_schemas.MSG_SCHEMAS`` is auto-generated by ``_gen_schemas.py`` from
# ``oasyce-chain/x/*/types/*pb.go``.  Regenerate after any chain proto change:
#
#     python -m oasyce_sdk.crypto._gen_schemas ~/Desktop/oasyce-chain
#
# Imperatively-encoded messages (repeated Coin/Any/nested Msg) live directly
# in this file as ``_encode_msg_*`` helpers — see ``encode_msg`` below.
from .msg_schemas import MSG_SCHEMAS  # re-exported for callers

# Enum mappings for fields that use F_ENUM
ENUM_VALUES = {
    "rights_type": {
        "RIGHTS_TYPE_UNSPECIFIED": 0,
        "RIGHTS_TYPE_ORIGINAL": 1,
        "RIGHTS_TYPE_DERIVATIVE": 2,
        "RIGHTS_TYPE_LICENSE": 3,
    },
    "requested_remedy": {
        "DISPUTE_REMEDY_UNSPECIFIED": 0,
        "DISPUTE_REMEDY_REFUND": 1,
        "DISPUTE_REMEDY_DELIST": 2,
        "DISPUTE_REMEDY_COMPENSATION": 3,
    },
    "remedy": {
        "DISPUTE_REMEDY_UNSPECIFIED": 0,
        "DISPUTE_REMEDY_REFUND": 1,
        "DISPUTE_REMEDY_DELIST": 2,
        "DISPUTE_REMEDY_COMPENSATION": 3,
    },
}


# ---------------------------------------------------------------------------
# Generic message encoder
# ---------------------------------------------------------------------------

def encode_msg(type_url: str, fields: Dict[str, Any]) -> bytes:
    """Encode a message body from its type_url and field dict.

    The field dict uses the same JSON keys as the build_*() methods in
    client.py, so callers can pass them directly.

    Returns the encoded message body (NOT wrapped in Any yet).
    """
    # Special case: MsgSend has repeated Coin for amount
    if type_url == "/cosmos.bank.v1beta1.MsgSend":
        return _encode_msg_send(fields)
    if type_url == "/oasyce.delegate.v1.MsgExec":
        return _encode_msg_exec(fields)
    if type_url == "/oasyce.anchor.v1.MsgAnchorBatch":
        return _encode_msg_anchor_batch(fields)

    schema = MSG_SCHEMAS.get(type_url)
    if schema is None:
        raise ValueError(f"Unknown message type: {type_url}")

    result = b""
    for json_key, field_num, field_type in schema:
        value = fields.get(json_key)
        if value is None:
            continue

        if field_type == F_STRING:
            result += _encode_string(field_num, str(value))
        elif field_type == F_BYTES:
            if isinstance(value, str):
                # Accept base64-encoded bytes (from client.py build methods)
                value = base64.b64decode(value)
            result += _encode_bytes(field_num, value)
        elif field_type == F_UINT64:
            result += _encode_uint64(field_num, int(value))
        elif field_type == F_UINT32:
            result += _encode_uint32(field_num, int(value))
        elif field_type == F_INT64:
            result += _encode_int64(field_num, int(value))
        elif field_type == F_BOOL:
            result += _encode_bool(field_num, bool(value))
        elif field_type == F_ENUM:
            if isinstance(value, str):
                enum_map = ENUM_VALUES.get(json_key, {})
                value = enum_map.get(value, 0)
            result += _encode_enum(field_num, int(value))
        elif field_type == F_COIN:
            coin_data = _encode_coin_from_dict(value)
            result += _encode_message(field_num, coin_data)
        elif field_type == F_REPEATED_STRING:
            if isinstance(value, list):
                result += _encode_repeated_string(field_num, value)
        elif field_type == F_REPEATED_BYTES:
            if isinstance(value, list):
                result += _encode_repeated_bytes(field_num, value)

    return result


def _encode_coin_from_dict(coin: Dict[str, str]) -> bytes:
    """Encode a Coin from {"denom": "uoas", "amount": "1000"}."""
    return encode_coin(coin.get("denom", "uoas"), str(coin.get("amount", "0")))


def _encode_msg_send(fields: Dict[str, Any]) -> bytes:
    """Special encoder for cosmos.bank.v1beta1.MsgSend (repeated Coin)."""
    result = b""
    result += _encode_string(1, fields.get("from_address", ""))
    result += _encode_string(2, fields.get("to_address", ""))
    # amount: field 3, repeated Coin
    amount = fields.get("amount", [])
    if isinstance(amount, dict):
        amount = [amount]
    for coin in amount:
        coin_bytes = _encode_coin_from_dict(coin)
        result += _encode_message(3, coin_bytes)
    return result


def _split_any_input(msg: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Normalize Any-like dicts into (type_url, value_fields)."""
    if not isinstance(msg, dict):
        raise TypeError("Any message input must be a dict")

    type_url = msg.get("@type") or msg.get("type_url")
    if not type_url:
        raise ValueError("Any message input must include '@type' or 'type_url'")

    if "value" in msg:
        value = msg["value"]
        if not isinstance(value, dict):
            raise TypeError("Any message 'value' must be a dict")
        return str(type_url), value

    value = {k: v for k, v in msg.items() if k not in {"@type", "type_url"}}
    return str(type_url), value


def _encode_msg_exec(fields: Dict[str, Any]) -> bytes:
    """Special encoder for delegate MsgExec with repeated Any inner msgs."""
    result = b""
    result += _encode_string(1, fields.get("delegate", ""))
    for msg in fields.get("msgs", []) or []:
        type_url, value = _split_any_input(msg)
        result += _encode_message(2, encode_msg_as_any(type_url, value))
    return result


def _encode_msg_anchor_batch(fields: Dict[str, Any]) -> bytes:
    """Special encoder for anchor MsgAnchorBatch with repeated MsgAnchorTrace."""
    result = b""
    result += _encode_string(1, fields.get("signer", ""))
    for anchor in fields.get("anchors", []) or []:
        result += _encode_message(2, encode_msg("/oasyce.anchor.v1.MsgAnchorTrace", anchor))
    return result


def encode_msg_as_any(type_url: str, fields: Dict[str, Any]) -> bytes:
    """Encode a message and wrap it in google.protobuf.Any."""
    body = encode_msg(type_url, fields)
    return encode_any(type_url, body)


# ---------------------------------------------------------------------------
# Convenience: build complete transaction bytes
# ---------------------------------------------------------------------------

def build_tx_bytes(
    messages: List[Tuple[str, Dict[str, Any]]],
    pubkey_bytes: bytes,
    sequence: int,
    account_number: int,
    chain_id: str,
    fee_amount: int = 10000,
    gas_limit: int = 200000,
    memo: str = "",
    sign_fn=None,
) -> bytes:
    """Build complete signed TxRaw bytes ready for broadcast.

    Args:
        messages: List of (type_url, fields) tuples.
        pubkey_bytes: 33-byte compressed secp256k1 public key.
        sequence: Account sequence number.
        account_number: Account number on chain.
        chain_id: Chain ID string.
        fee_amount: Fee in uoas.
        gas_limit: Gas limit.
        memo: Optional memo string.
        sign_fn: Callable(digest: bytes) -> bytes that signs a 32-byte SHA256 hash.

    Returns:
        Encoded TxRaw bytes (ready to base64-encode and broadcast).
    """
    import hashlib

    # 1. Encode messages as Any
    any_messages = [encode_msg_as_any(url, fields) for url, fields in messages]

    # 2. Encode TxBody and AuthInfo
    body_bytes = encode_tx_body(any_messages, memo)
    auth_info_bytes = encode_auth_info(pubkey_bytes, sequence, fee_amount, gas_limit)

    # 3. Encode SignDoc and compute digest
    sign_doc = encode_sign_doc(body_bytes, auth_info_bytes, chain_id, account_number)
    digest = hashlib.sha256(sign_doc).digest()

    # 4. Sign
    if sign_fn is None:
        raise ValueError("sign_fn is required")
    signature = sign_fn(digest)

    # 5. Encode TxRaw
    return encode_tx_raw(body_bytes, auth_info_bytes, [signature])

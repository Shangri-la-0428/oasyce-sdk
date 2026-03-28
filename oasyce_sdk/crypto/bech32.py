"""Bech32 encoding for Cosmos SDK addresses.

Reference: BIP173 (https://github.com/bitcoin/bips/blob/master/bip-0173.mediawiki)
Cosmos uses bech32 with a 20-byte payload (SHA256(pubkey)[:20]).
"""

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values):
    """Internal function that computes the Bech32 checksum."""
    GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            chk ^= GEN[i] if ((b >> i) & 1) else 0
    return chk


def _bech32_hrp_expand(hrp):
    """Expand the HRP into values for checksum computation."""
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_create_checksum(hrp, data):
    """Compute the checksum values given HRP and data."""
    values = _bech32_hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def _bech32_verify_checksum(hrp, data):
    """Verify a checksum given HRP and converted data characters."""
    return _bech32_polymod(_bech32_hrp_expand(hrp) + data) == 1


def convertbits(data, frombits, tobits, pad=True):
    """General power-of-2 base conversion."""
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def bech32_encode(hrp: str, data_bytes: bytes) -> str:
    """Encode bytes as a bech32 string with the given human-readable prefix.

    Args:
        hrp: Human-readable prefix (e.g., "oasyce")
        data_bytes: Raw bytes (typically 20 bytes for a Cosmos address)

    Returns:
        Bech32-encoded string (e.g., "oasyce1...")
    """
    data_5bit = convertbits(list(data_bytes), 8, 5)
    if data_5bit is None:
        raise ValueError("Invalid data for bech32 encoding")
    checksum = _bech32_create_checksum(hrp, data_5bit)
    return hrp + "1" + "".join(CHARSET[d] for d in data_5bit + checksum)


def bech32_decode(bech: str):
    """Decode a bech32 string.

    Returns:
        (hrp, data_bytes) tuple, or (None, None) on error.
    """
    if any(ord(x) < 33 or ord(x) > 126 for x in bech):
        return None, None
    if bech.lower() != bech and bech.upper() != bech:
        return None, None
    bech = bech.lower()
    pos = bech.rfind("1")
    if pos < 1 or pos + 7 > len(bech) or len(bech) > 90:
        return None, None
    if not all(x in CHARSET for x in bech[pos + 1:]):
        return None, None
    hrp = bech[:pos]
    data = [CHARSET.find(x) for x in bech[pos + 1:]]
    if not _bech32_verify_checksum(hrp, data):
        return None, None
    decoded = convertbits(data[:-6], 5, 8, False)
    if decoded is None or len(decoded) < 2 or len(decoded) > 40:
        return None, None
    return hrp, bytes(decoded)

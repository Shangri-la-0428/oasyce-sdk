"""Generate oasyce_sdk/crypto/msg_schemas.py from chain .pb.go files.

This tool parses every ``Msg*`` struct declared in
``oasyce-chain/x/<module>/types/*pb.go``, extracts protobuf field numbers,
wire types, and gogoproto customtypes from the Go struct tags, and emits a
Python data module that is the single source of truth for the hand-rolled
protobuf encoder in :mod:`oasyce_sdk.crypto.protobuf`.

The generator refuses to silently drop fields: any field it cannot classify
becomes an explicit ``# SKIP`` comment in the output, so drift between chain
and SDK is always visible in ``git diff``.

Usage::

    python -m oasyce_sdk.crypto._gen_schemas [CHAIN_ROOT]

``CHAIN_ROOT`` defaults to ``~/Desktop/oasyce-chain``.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# These messages are encoded imperatively in protobuf.py because they contain
# repeated Coin / repeated Any / repeated nested Msg fields that the generic
# schema-driven encoder does not handle.  The generator must not emit them.
IMPERATIVE_MESSAGES = {
    "/cosmos.bank.v1beta1.MsgSend",  # repeated Coin — MsgSend is not on chain
    "/oasyce.delegate.v1.MsgExec",  # repeated google.protobuf.Any
    "/oasyce.anchor.v1.MsgAnchorBatch",  # repeated MsgAnchorTrace
}

# gogoproto customtypes whose wire representation is a plain string even
# though the Go type is cosmossdk.io/math.{Int,Dec,LegacyDec}.
STRING_ON_WIRE_CUSTOMTYPES = {
    "cosmossdk.io/math.Int",
    "cosmossdk.io/math.Dec",
    "cosmossdk.io/math.LegacyDec",
}

# ---------------------------------------------------------------------------
# Regexes that walk the pb.go text
# ---------------------------------------------------------------------------

_RE_STRUCT = re.compile(r"^type (Msg\w+) struct \{$", re.MULTILINE)

_RE_REGISTER = re.compile(
    r'proto\.RegisterType\(\(\*(Msg\w+)\)\(nil\),\s*"([^"]+)"\)',
    re.MULTILINE,
)

_RE_FIELD = re.compile(
    r"^\s+(\w+)\s+([\w\.\[\]\*]+)\s+`protobuf:\"([^\"]+)\"",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FieldSpec:
    name: str  # snake_case name from the ``name=`` tag attribute
    number: int
    kind: Optional[str]  # matches protobuf.py F_* constants, or None if skipped
    reason: Optional[str] = None  # explanation when kind is None


@dataclass
class MsgSpec:
    go_type: str
    type_url: str
    fields: List[FieldSpec] = dc_field(default_factory=list)


# ---------------------------------------------------------------------------
# Tag parsing + field classification
# ---------------------------------------------------------------------------


def parse_tag(tag: str) -> Dict[str, object]:
    """Parse a protobuf struct tag into a dict of attributes.

    Example input : ``'bytes,3,rep,name=lineage,proto3'``
    Example output: ``{'wire': 'bytes', 'number': 3, 'label': 'rep',
                       'name': 'lineage'}``
    """
    parts = tag.split(",")
    out: Dict[str, object] = {
        "wire": parts[0],
        "number": int(parts[1]),
        "label": parts[2],
    }
    for p in parts[3:]:
        if "=" in p:
            key, _, value = p.partition("=")
            out[key] = value
    return out


def classify_field(
    go_type: str, tag: Dict[str, object]
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(kind, reason)`` for a single field.

    ``kind`` is the ``F_*`` constant name (without the ``F_`` prefix) used in
    protobuf.py.  When ``kind`` is ``None``, ``reason`` explains why the field
    was skipped so the generated output documents the gap.
    """
    wire = str(tag["wire"])
    label = str(tag["label"])
    customtype = tag.get("customtype")
    enum_name = tag.get("enum")

    # gogoproto customtypes whose wire representation is a plain string
    if customtype in STRING_ON_WIRE_CUSTOMTYPES:
        if label == "rep":
            return None, f"repeated {customtype} not supported by generic encoder"
        return "string", None

    # Pointer prefix is a Go detail only — strip it before classification.
    if go_type.startswith("*"):
        go_type = go_type[1:]

    # Repeated fields
    if label == "rep":
        if go_type == "[]string":
            return "repeated_string", None
        if go_type == "[][]byte":
            return "repeated_bytes", None
        return (
            None,
            f"repeated Go type {go_type!r} not supported by generic encoder",
        )

    # Explicit enum annotation in the tag (``enum=pkg.Name``)
    if enum_name is not None:
        return "enum", None

    # Scalar varint wire type
    if wire == "varint":
        if go_type == "bool":
            return "bool", None
        if go_type in ("int32", "uint32"):
            return "uint32", None
        if go_type in ("int64", "uint64"):
            return "uint64", None
        return None, f"unknown varint Go type {go_type!r}"

    # Scalar bytes wire type
    if wire == "bytes":
        if go_type == "string":
            return "string", None
        if go_type == "[]byte":
            return "bytes", None
        if go_type == "Coin" or go_type.endswith(".Coin"):
            return "coin", None
        return None, f"nested message Go type {go_type!r} not supported"

    return None, f"unsupported wire type {wire!r}"


# ---------------------------------------------------------------------------
# pb.go parser
# ---------------------------------------------------------------------------


def parse_pb_go(path: Path) -> List[MsgSpec]:
    """Extract all ``Msg*`` specs from a single pb.go file."""
    text = path.read_text()

    # type URL registry from ``proto.RegisterType((*MsgFoo)(nil), "pkg.MsgFoo")``
    type_urls: Dict[str, str] = {}
    for m in _RE_REGISTER.finditer(text):
        go_name = m.group(1)
        url = m.group(2)
        if go_name.endswith("Response"):
            continue
        type_urls[go_name] = "/" + url

    # Walk struct declarations in file order
    struct_starts = [(m.start(), m.group(1)) for m in _RE_STRUCT.finditer(text)]
    struct_starts.append((len(text), None))

    specs: List[MsgSpec] = []
    for i in range(len(struct_starts) - 1):
        start, name = struct_starts[i]
        end = struct_starts[i + 1][0]
        if name is None or name.endswith("Response") or name not in type_urls:
            continue

        # Restrict matching to the body of THIS struct by cutting at the
        # first line that is exactly ``}`` (the closing brace of the struct).
        block = text[start:end]
        close_idx = block.find("\n}\n")
        if close_idx >= 0:
            block = block[: close_idx + 3]

        spec = MsgSpec(go_type=name, type_url=type_urls[name])
        for fm in _RE_FIELD.finditer(block):
            go_field = fm.group(1)
            go_field_type = fm.group(2)
            tag_str = fm.group(3)
            tag = parse_tag(tag_str)
            field_name = str(tag.get("name", go_field.lower()))
            kind, reason = classify_field(go_field_type, tag)
            spec.fields.append(
                FieldSpec(
                    name=field_name,
                    number=int(tag["number"]),
                    kind=kind,
                    reason=reason,
                )
            )
        specs.append(spec)

    return specs


# ---------------------------------------------------------------------------
# Source emission
# ---------------------------------------------------------------------------


def generate(chain_root: Path) -> str:
    """Scan ``chain_root`` for pb.go files and return the Python module source."""
    files = sorted(chain_root.glob("x/*/types/*pb.go"))
    if not files:
        raise SystemExit(f"no pb.go files found under {chain_root / 'x'}")

    all_specs: List[MsgSpec] = []
    for path in files:
        all_specs.extend(parse_pb_go(path))

    # Drop messages encoded imperatively — they must not appear in the
    # schema-driven dispatch table.
    all_specs = [s for s in all_specs if s.type_url not in IMPERATIVE_MESSAGES]

    # Stable order for git-diff friendly output.
    all_specs.sort(key=lambda s: s.type_url)

    lines: List[str] = [
        '"""Auto-generated protobuf message schemas — DO NOT EDIT.',
        "",
        "Regenerate with::",
        "",
        "    python -m oasyce_sdk.crypto._gen_schemas ~/Desktop/oasyce-chain",
        "",
        "Source of truth: ``oasyce-chain/x/<module>/types/*pb.go`` struct tags.",
        "",
        "Each entry maps a protobuf type URL to a list of",
        "``(field_name, field_number, kind)`` tuples, where ``kind`` matches",
        "the ``F_*`` constants in :mod:`oasyce_sdk.crypto.protobuf`.",
        '"""',
        "",
        "from typing import Dict, List, Tuple",
        "",
        "MSG_SCHEMAS: Dict[str, List[Tuple[str, int, str]]] = {",
    ]

    for spec in all_specs:
        lines.append(f'    "{spec.type_url}": [')
        for f in spec.fields:
            if f.kind is None:
                lines.append(
                    f"        # SKIP name={f.name!r} number={f.number}"
                    f" — {f.reason}"
                )
                continue
            lines.append(f'        ("{f.name}", {f.number}, "{f.kind}"),')
        lines.append("    ],")

    lines.append("}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: List[str]) -> int:
    if len(argv) >= 2:
        chain_root = Path(argv[1]).expanduser().resolve()
    else:
        chain_root = Path("~/Desktop/oasyce-chain").expanduser().resolve()
    if not chain_root.is_dir():
        print(f"error: chain root not found: {chain_root}", file=sys.stderr)
        return 1

    out_path = Path(__file__).with_name("msg_schemas.py")
    out_path.write_text(generate(chain_root))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

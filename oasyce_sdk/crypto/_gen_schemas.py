"""Generate oasyce_sdk/crypto/msg_schemas.py from chain .pb.go files.

This tool parses every ``Msg*`` struct declared in
``oasyce-chain/x/<module>/types/*pb.go``, extracts protobuf field numbers,
wire types, and gogoproto customtypes from the Go struct tags, and emits a
Python data module that is the single source of truth for the hand-rolled
protobuf encoder in :mod:`oasyce_sdk.crypto.protobuf`.

The generator also picks up non-``Msg*`` structs registered via
``proto.RegisterType`` in the same module when they are referenced as nested
fields (single or repeated) by any ``Msg*``.  Their schemas are emitted into
a separate ``NESTED_SCHEMAS`` dict keyed by fully-qualified proto name, which
the encoder dispatches to recursively via the ``nested:<fqn>`` and
``repeated_nested:<fqn>`` kind strings.

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
from typing import Dict, List, Optional, Set, Tuple

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

# Go scalar types that the generic map encoder supports as a key or value.
# Wire-compatible with the corresponding F_* kinds in protobuf.py: int32 and
# uint32 share "uint32"; int64 and uint64 share "uint64" (proto varint is
# unsigned, negative ints are two's-complement-extended by the varint helper).
_MAP_SCALAR_KIND: Dict[str, str] = {
    "string": "string",
    "bool": "bool",
    "int32": "uint32",
    "uint32": "uint32",
    "int64": "uint64",
    "uint64": "uint64",
}

# ---------------------------------------------------------------------------
# Regexes that walk the pb.go text
# ---------------------------------------------------------------------------

_RE_STRUCT = re.compile(r"^type (\w+) struct \{$", re.MULTILINE)

_RE_REGISTER = re.compile(
    r'proto\.RegisterType\(\(\*(\w+)\)\(nil\),\s*"([^"]+)"\)',
    re.MULTILINE,
)

_RE_FIELD = re.compile(
    r"^\s+(\w+)\s+([\w\.\[\]\*]+)\s+`protobuf:\"([^\"]+)\"",
    re.MULTILINE,
)

# Go map type: ``map[KEY]VALUE`` where both are scalar identifiers.
_RE_MAP_GO_TYPE = re.compile(r"^map\[(\w+)\]([\w\.\*]+)$")

# Go slice of identifier: ``[]Name`` or ``[]*Name``.
_RE_SLICE_GO_TYPE = re.compile(r"^\[\]\*?(\w+)$")


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
    type_url: str  # with leading slash: "/pkg.MsgFoo"
    fields: List[FieldSpec] = dc_field(default_factory=list)


@dataclass
class NestedSpec:
    go_type: str  # bare Go struct name in its module
    fqn: str  # fully-qualified proto name, no leading slash: "pkg.Foo"
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
    go_type: str,
    tag: Dict[str, object],
    local_nested_fqns: Dict[str, str],
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(kind, reason)`` for a single field.

    ``kind`` is the ``F_*`` constant name (without the ``F_`` prefix) used in
    protobuf.py.  When ``kind`` is ``None``, ``reason`` explains why the field
    was skipped so the generated output documents the gap.

    ``local_nested_fqns`` is a ``Go name -> fully-qualified proto name`` map
    of non-``Msg`` structs registered in the SAME module as the struct being
    classified.  Bare Go struct field types are always in-package, so this
    scope matches how the Go compiler resolves them.
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

    # Repeated fields (including proto maps, which are rep entries of a
    # synthetic ``<Name>Entry`` message in wire format).
    if label == "rep":
        if go_type == "[]string":
            return "repeated_string", None
        if go_type == "[][]byte":
            return "repeated_bytes", None
        map_match = _RE_MAP_GO_TYPE.match(go_type)
        if map_match is not None:
            key_go = map_match.group(1)
            val_go = map_match.group(2)
            key_kind = _MAP_SCALAR_KIND.get(key_go)
            val_kind = _MAP_SCALAR_KIND.get(val_go)
            if key_kind is None:
                return None, f"map key Go type {key_go!r} not supported"
            if val_kind is None:
                return None, f"map value Go type {val_go!r} not supported"
            return f"map_{key_kind}_{val_kind}", None
        slice_match = _RE_SLICE_GO_TYPE.match(go_type)
        if slice_match is not None:
            inner = slice_match.group(1)
            if inner in local_nested_fqns:
                return f"repeated_nested:{local_nested_fqns[inner]}", None
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
        if go_type in local_nested_fqns:
            return f"nested:{local_nested_fqns[go_type]}", None
        return None, f"nested message Go type {go_type!r} not supported"

    return None, f"unsupported wire type {wire!r}"


# ---------------------------------------------------------------------------
# pb.go parser
# ---------------------------------------------------------------------------


def parse_pb_module(module_dir: Path) -> Tuple[List[MsgSpec], List[NestedSpec]]:
    """Extract all Msg and referenced nested specs from one module's pb.go files.

    Per-module scoping matches Go's package semantics: bare struct references
    in a field's type always resolve to the same Go package, which corresponds
    to ``<chain>/x/<module>/types``.
    """
    # Matches both ``*.pb.go`` (protoc-generated) and ``*_pb.go`` (hand-written
    # challenge-window messages in x/capability) — same pattern the top-level
    # walker in ``generate()`` uses.
    pb_files = sorted(module_dir.glob("*pb.go"))
    if not pb_files:
        return [], []

    # Pass 1: collect every ``proto.RegisterType`` in the module.
    # Msg-prefixed registrations become top-level type URLs; everything else
    # that isn't a Response is a candidate nested message.
    msg_type_urls: Dict[str, str] = {}
    nested_fqns: Dict[str, str] = {}
    for pb in pb_files:
        text = pb.read_text()
        for m in _RE_REGISTER.finditer(text):
            go_name = m.group(1)
            fqn = m.group(2)
            if go_name.endswith("Response"):
                continue
            if go_name.startswith("Msg"):
                msg_type_urls[go_name] = "/" + fqn
            else:
                nested_fqns[go_name] = fqn

    # Pass 2: parse struct bodies.
    msg_specs: List[MsgSpec] = []
    nested_specs: List[NestedSpec] = []

    for pb in pb_files:
        text = pb.read_text()
        struct_starts = [(m.start(), m.group(1)) for m in _RE_STRUCT.finditer(text)]
        struct_starts.append((len(text), None))

        for i in range(len(struct_starts) - 1):
            start, name = struct_starts[i]
            end = struct_starts[i + 1][0]
            if name is None:
                continue

            is_msg = name in msg_type_urls
            is_nested = not is_msg and name in nested_fqns
            if not is_msg and not is_nested:
                continue

            # Restrict matching to the body of THIS struct by cutting at the
            # first line that is exactly ``}`` (the closing brace of the
            # struct).
            block = text[start:end]
            close_idx = block.find("\n}\n")
            if close_idx >= 0:
                block = block[: close_idx + 3]

            fields: List[FieldSpec] = []
            for fm in _RE_FIELD.finditer(block):
                go_field = fm.group(1)
                go_field_type = fm.group(2)
                tag_str = fm.group(3)
                tag = parse_tag(tag_str)
                field_name = str(tag.get("name", go_field.lower()))
                kind, reason = classify_field(go_field_type, tag, nested_fqns)
                fields.append(
                    FieldSpec(
                        name=field_name,
                        number=int(tag["number"]),
                        kind=kind,
                        reason=reason,
                    )
                )

            if is_msg:
                msg_specs.append(
                    MsgSpec(
                        go_type=name,
                        type_url=msg_type_urls[name],
                        fields=fields,
                    )
                )
            else:
                nested_specs.append(
                    NestedSpec(
                        go_type=name,
                        fqn=nested_fqns[name],
                        fields=fields,
                    )
                )

    return msg_specs, nested_specs


def _reachable_nested_fqns(
    msg_specs: List[MsgSpec],
    nested_by_fqn: Dict[str, NestedSpec],
) -> Set[str]:
    """Return the transitive set of nested FQNs referenced from any Msg."""
    reachable: Set[str] = set()
    worklist: List[str] = []

    def _visit(kind: Optional[str]) -> None:
        if not kind:
            return
        if kind.startswith("nested:"):
            fqn = kind[len("nested:") :]
        elif kind.startswith("repeated_nested:"):
            fqn = kind[len("repeated_nested:") :]
        else:
            return
        if fqn not in reachable:
            reachable.add(fqn)
            worklist.append(fqn)

    for msg in msg_specs:
        for f in msg.fields:
            _visit(f.kind)

    while worklist:
        fqn = worklist.pop()
        spec = nested_by_fqn.get(fqn)
        if spec is None:
            continue
        for f in spec.fields:
            _visit(f.kind)

    return reachable


# ---------------------------------------------------------------------------
# Source emission
# ---------------------------------------------------------------------------


def generate(chain_root: Path) -> str:
    """Scan ``chain_root`` for pb.go files and return the Python module source."""
    module_dirs = sorted(
        {p.parent for p in chain_root.glob("x/*/types/*pb.go")}
    )
    if not module_dirs:
        raise SystemExit(f"no pb.go files found under {chain_root / 'x'}")

    all_msgs: List[MsgSpec] = []
    nested_by_fqn: Dict[str, NestedSpec] = {}
    for module_dir in module_dirs:
        msgs, nested = parse_pb_module(module_dir)
        all_msgs.extend(msgs)
        for ns in nested:
            # Per-module scoping guarantees FQNs are globally unique, so a
            # collision here would indicate a real duplicate proto definition.
            if ns.fqn in nested_by_fqn:
                existing = nested_by_fqn[ns.fqn]
                raise SystemExit(
                    f"duplicate nested registration {ns.fqn!r}: "
                    f"{existing.go_type} vs {ns.go_type}"
                )
            nested_by_fqn[ns.fqn] = ns

    # Drop messages encoded imperatively — they must not appear in the
    # schema-driven dispatch table.
    all_msgs = [s for s in all_msgs if s.type_url not in IMPERATIVE_MESSAGES]

    # Only emit nested schemas that are actually reachable from a Msg.  This
    # keeps the generated file focused on the SDK's broadcast surface rather
    # than every proto type the chain happens to register.
    reachable = _reachable_nested_fqns(all_msgs, nested_by_fqn)
    filtered_nested = sorted(
        (nested_by_fqn[fqn] for fqn in reachable if fqn in nested_by_fqn),
        key=lambda s: s.fqn,
    )

    # Stable order for git-diff friendly output.
    all_msgs.sort(key=lambda s: s.type_url)

    lines: List[str] = [
        '"""Auto-generated protobuf message schemas — DO NOT EDIT.',
        "",
        "Regenerate with::",
        "",
        "    python -m oasyce_sdk.crypto._gen_schemas ~/Desktop/oasyce-chain",
        "",
        "Source of truth: ``oasyce-chain/x/<module>/types/*pb.go`` struct tags.",
        "",
        "``MSG_SCHEMAS`` maps a protobuf type URL to a list of",
        "``(field_name, field_number, kind)`` tuples.  ``NESTED_SCHEMAS`` is",
        "keyed by fully-qualified proto name (no leading slash) and stores the",
        "same tuple shape for non-``Msg`` structs referenced by ``nested:<fqn>``",
        "or ``repeated_nested:<fqn>`` kinds.  ``kind`` values match the ``F_*``",
        "constants in :mod:`oasyce_sdk.crypto.protobuf`.",
        '"""',
        "",
        "from typing import Dict, List, Tuple",
        "",
        "MSG_SCHEMAS: Dict[str, List[Tuple[str, int, str]]] = {",
    ]

    def _emit_entries(key: str, fields: List[FieldSpec]) -> None:
        lines.append(f'    "{key}": [')
        for f in fields:
            if f.kind is None:
                lines.append(
                    f"        # SKIP name={f.name!r} number={f.number}"
                    f" — {f.reason}"
                )
                continue
            lines.append(f'        ("{f.name}", {f.number}, "{f.kind}"),')
        lines.append("    ],")

    for spec in all_msgs:
        _emit_entries(spec.type_url, spec.fields)

    lines.append("}")
    lines.append("")
    lines.append("NESTED_SCHEMAS: Dict[str, List[Tuple[str, int, str]]] = {")
    for nspec in filtered_nested:
        _emit_entries(nspec.fqn, nspec.fields)
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

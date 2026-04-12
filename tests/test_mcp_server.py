from __future__ import annotations

import importlib
import json
import sys
import types
from types import SimpleNamespace

from oasyce_sdk.crypto.signer import TxResult


def _load_mcp_server():
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")

    class FakeFastMCP:
        def __init__(self, *args, **kwargs):
            pass

        def tool(self, *args, **kwargs):
            return lambda fn: fn

        def resource(self, *args, **kwargs):
            return lambda fn: fn

    fastmcp_module.FastMCP = FakeFastMCP
    sys.modules["mcp"] = types.ModuleType("mcp")
    sys.modules["mcp.server"] = types.ModuleType("mcp.server")
    sys.modules["mcp.server.fastmcp"] = fastmcp_module
    sys.modules.pop("oasyce_sdk.mcp_server", None)
    module = importlib.import_module("oasyce_sdk.mcp_server")
    return importlib.reload(module)


def test_get_delegate_policy_exposes_max_msgs_per_exec(monkeypatch):
    module = _load_mcp_server()
    module._client = SimpleNamespace(
        get_delegate_policy=lambda principal: SimpleNamespace(
            principal=principal,
            per_tx_limit_uoas=1_000_000,
            window_limit_uoas=10_000_000,
            window_seconds=86400,
            allowed_msgs=["/cosmos.bank.v1beta1.MsgSend"],
            max_msgs_per_exec=4,
            expiration_seconds=0,
        )
    )

    payload = json.loads(module.get_delegate_policy("oasyce1principal"))

    assert payload["principal"] == "oasyce1principal"
    assert payload["max_msgs_per_exec"] == 4


def test_set_delegate_policy_threads_max_msgs_per_exec(monkeypatch, tmp_path):
    module = _load_mcp_server()
    identity = SimpleNamespace(wallet=SimpleNamespace(address="oasyce1principal"), account="")
    calls: list[dict] = []

    class StubSigner:
        def set_delegate_policy(self, **kwargs):
            calls.append(kwargs)
            return TxResult("txhash", True, 0, "")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OASYCE_DIR", str(tmp_path / ".oasyce"))
    monkeypatch.setattr(module, "_get_identity", lambda: identity)
    monkeypatch.setattr(module, "_get_signer", lambda: StubSigner())

    from oasyce_sdk import delegate_policy as delegate_policy_mod
    from oasyce_sdk import identity as identity_mod

    monkeypatch.setattr(delegate_policy_mod.LocalDelegatePolicy, "save", lambda self: "saved")
    monkeypatch.setattr(identity_mod.IdentityResolver, "ensure_local_binding", lambda *a, **k: None)
    monkeypatch.setattr(identity_mod.IdentityResolver, "resolve", lambda wallet=None: identity)

    result = json.loads(
        module.set_delegate_policy(
            token="shared-secret",
            allowed_msgs="/cosmos.bank.v1beta1.MsgSend",
            max_msgs_per_exec=5,
        )
    )

    assert result["success"] is True
    assert calls[0]["max_msgs_per_exec"] == 5

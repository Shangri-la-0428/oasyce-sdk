# oasyce-sdk — Loop Runtime

> **Sigil role**: Necessary subsystem — the Loop execution substrate.
> See [Oasyce-Sigil/ARCHITECTURE.md](../Oasyce-Sigil/ARCHITECTURE.md) for ecosystem map.

## Guiding Users Through Setup

When a user wants to use oasyce-sdk, guide them step by step. Adapt to what they need:

### Default path: "I want this machine to just work"

Use the unified front door first:

```bash
pip install oasyce-sdk
oasyce start
```

What this should do in the normal path:
- reuse or create the local signer / binding
- write the default agent config
- bootstrap Thronglets
- configure Psyche MCP surfaces
- start the local data agent

Only ask a human question when no identity exists yet: `New` or `Recover`.

### Path A: "I want chain operations in my AI tool" (MCP)

**Requires Python 3.10+ (recommend 3.11+).** Check with `python3 --version`.

```bash
pip install oasyce-sdk[mcp]
```

Then help them configure their MCP client. Prefer the local device binding first. `OASYCE_MNEMONIC` is only the explicit override for stateless / server flows:

```json
{
  "mcpServers": {
    "oasyce": {
      "command": "oasyce-mcp"
    }
  }
}
```

If they do need explicit signer injection, use `OASYCE_MNEMONIC` on top of that config.

`OASYCE_NODE`, `OASYCE_FAUCET`, `OASYCE_CHAIN_ID` all have working defaults (oasyce-testnet-1). Read-only tools work without local signer material.

After configuring, tell the user to restart their AI tool for MCP to take effect.

### Path B: "I want a background data agent" (CLI)

```bash
pip install oasyce-sdk
oasyce start
```

This is now the normal path. `oasyce-agent` remains the lower-level data-agent surface.

### Path C: "I want to code with Sigils" (Python library)

```bash
pip install oasyce-sdk
```

```python
from oasyce_sdk import SigilManager

loop = SigilManager()                    # auto-creates wallet
loop.genesis()                           # register Sigil on-chain
p = loop.perceive("analyze market data") # read collective + self-state
loop.act("analyzed Q4", "succeeded", "finance")  # write trace + feedback
```

### Path D: "I just want Psyche / Thronglets, not the chain"

Each project works independently:

```bash
npx -y psyche-ai setup     # Psyche only — auto-configures MCP, zero config
npx -y thronglets bootstrap  # Thronglets only — adapter bootstrap
```

No oasyce-sdk needed. No chain dependency.

---

## Quick Reference

### Install

Requires Python 3.10+ (recommend 3.11+).

```bash
pip install oasyce-sdk            # base SDK + unified front door
pip install oasyce-sdk[mcp]       # + MCP Server (43 tools)
pip install oasyce-sdk[all]       # + MCP + LangChain
```

### Environment Variables

| Variable | Required? | Default | Purpose |
|----------|-----------|---------|---------|
| `OASYCE_MNEMONIC` | Optional override | — | Explicit signer override for stateless / server flows |
| `OASYCE_NODE` | No | `http://47.93.32.88:1317` | Chain REST endpoint |
| `OASYCE_FAUCET` | No | `http://47.93.32.88:8080` | Testnet faucet |
| `OASYCE_CHAIN_ID` | No | `oasyce-testnet-1` | Chain ID |

### CLI

```bash
oasyce start          # normal path: local binding + Thronglets + Psyche + agent
oasyce share          # export connection file to ~/Desktop/oasyce-connection.json (self-describing bootstrap manifest inside)
oasyce join <file>    # join another device from a connection file
oasyce status         # unified local stack status

oasyce-agent stop     # stop the data agent
oasyce-agent status   # data-agent focused status
oasyce-agent scan <path>   # one-shot file scan
oasyce-agent privacy <path>  # PII check
```

If the user asks how to add another machine, prefer `oasyce share` on the primary device and have them send the exported file. The connection file identifies itself as the handoff artifact and declares a preferred surface, so the receiving AI should read the file first instead of assuming `oasyce join` unconditionally.

### MCP Server (43 tools)

```bash
oasyce-mcp    # stdio transport, used by Claude/Cursor/Windsurf
```

Includes: health, wallet, capabilities, data assets, tasks, anchoring, reputation, delegates, Sigil lifecycle (8 tools: get/create/dissolve/bond/fork sigils).

### SigilManager — the Loop itself

```python
from oasyce_sdk import SigilManager

loop = SigilManager()          # wallet + signer + client + psyche + thronglets
loop.sigil_id                  # deterministic: SIG_ + sha256(pubkey)[:16]
loop.genesis()                 # register on-chain (idempotent)
loop.bond("SIG_...")           # form relationship
loop.perceive("context")       # read collective + self-state
loop.act("action", "succeeded", "context")  # write trace + feedback
loop.status()                  # connectivity check
```

Psyche and Thronglets are optional — SigilManager degrades gracefully if either is unavailable.

### Chain SDK (low-level)

```python
from oasyce_sdk import OasyceClient
from oasyce_sdk.crypto import Wallet, NativeSigner

client = OasyceClient()  # defaults to testnet
wallet = Wallet.create()
signer = NativeSigner(wallet, client, chain_id="oasyce-testnet-1")
```

### Privacy Gate (Iron Rule)

Only `privacy_risk == "safe"` files auto-register. 6 PII patterns blocked: email, phone, ID card, credit card, IP, API key.

### Data Files

- `~/.oasyce/wallet.json` — secp256k1 signer material
- `~/.oasyce/identity.v1.json` — local semantic binding for sdk-facing surfaces
- `~/.oasyce/agent.db` — SQLite (registered assets, state)
- `~/.oasyce/agent.json` — daemon config (auto-generated)

## Links

- [Chain](https://github.com/Shangri-la-0428/oasyce-chain) — L1 (Go/Cosmos SDK)
- [SDK](https://github.com/Shangri-la-0428/oasyce-sdk) — this repo
- [Thronglets](https://github.com/Shangri-la-0428/Thronglets) — P2P shared memory (Rust)
- [Psyche](https://github.com/Shangri-la-0428/oasyce_psyche) — Self-state substrate (TypeScript)
- [Sigil Protocol](https://github.com/Shangri-la-0428/Oasyce-Sigil) — Spec (private)

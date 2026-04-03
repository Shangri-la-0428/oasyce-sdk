# oasyce-sdk — Loop Runtime

> **Sigil role**: Necessary subsystem — the Loop execution substrate.
> See [Oasyce-Sigil/ARCHITECTURE.md](../Oasyce-Sigil/ARCHITECTURE.md) for ecosystem map.

## Guiding Users Through Setup

When a user wants to use oasyce-sdk, guide them step by step. Adapt to what they need:

### Path A: "I want chain operations in my AI tool" (MCP)

**Requires Python 3.10+ (recommend 3.11+).** Check with `python3 --version`.

```bash
pip install oasyce-sdk[mcp]
```

Then help them configure their MCP client. They need a wallet mnemonic for write operations:

```python
# Generate one for them:
python3 -c "from oasyce_sdk.crypto import Wallet; w = Wallet.create(); print(w.mnemonic)"
```

Then add to their MCP config (Claude Code: `~/.claude/.mcp.json`, Cursor: `~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "oasyce": {
      "command": "oasyce-mcp",
      "env": {
        "OASYCE_MNEMONIC": "<the 24 words from above>"
      }
    }
  }
}
```

That's it. `OASYCE_NODE`, `OASYCE_FAUCET`, `OASYCE_CHAIN_ID` all have working defaults (oasyce-testnet-1). Read-only tools work without a mnemonic.

After configuring, tell the user to restart their AI tool for MCP to take effect.

### Path B: "I want a background data agent" (CLI)

```bash
pip install oasyce-sdk
oasyce-agent start
```

Auto-onboarding: creates wallet, solves PoW (~1 min), registers on chain, gets 20 OAS airdrop. Scans ~/Documents, ~/Desktop, ~/Downloads, ~/Pictures hourly.

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
npx -y thronglets start  # Thronglets only — auto-detects AI tools, installs hooks
```

No oasyce-sdk needed. No chain dependency.

---

## Quick Reference

### Install

Requires Python 3.10+ (recommend 3.11+).

```bash
pip install oasyce-sdk            # base SDK + CLI agent
pip install oasyce-sdk[mcp]       # + MCP Server (43 tools)
pip install oasyce-sdk[all]       # + MCP + LangChain
```

### Environment Variables

| Variable | Required? | Default | Purpose |
|----------|-----------|---------|---------|
| `OASYCE_MNEMONIC` | For write ops | — | 24-word BIP39 mnemonic |
| `OASYCE_NODE` | No | `http://47.93.32.88:1317` | Chain REST endpoint |
| `OASYCE_FAUCET` | No | `http://47.93.32.88:8080` | Testnet faucet |
| `OASYCE_CHAIN_ID` | No | `oasyce-testnet-1` | Chain ID |

### CLI

```bash
oasyce-agent start    # daemon: auto wallet + PoW + Sigil + scan + register
oasyce-agent stop     # stop daemon
oasyce-agent status   # show wallet, assets, connectivity
oasyce-agent scan <path>   # one-shot file scan
oasyce-agent privacy <path>  # PII check
```

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

- `~/.oasyce/wallet.json` — BIP39 wallet (secp256k1)
- `~/.oasyce/agent.db` — SQLite (registered assets, state)
- `~/.oasyce/agent.json` — daemon config (auto-generated)

## Links

- [Chain](https://github.com/Shangri-la-0428/oasyce-chain) — L1 (Go/Cosmos SDK)
- [SDK](https://github.com/Shangri-la-0428/oasyce-sdk) — this repo
- [Thronglets](https://github.com/Shangri-la-0428/Thronglets) — P2P shared memory (Rust)
- [Psyche](https://github.com/Shangri-la-0428/oasyce_psyche) — Self-state substrate (TypeScript)
- [Sigil Protocol](https://github.com/Shangri-la-0428/Oasyce-Sigil) — Spec (private)

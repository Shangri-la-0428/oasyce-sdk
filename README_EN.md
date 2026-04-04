# oasyce-sdk

Python runtime / body for the Oasyce stack. It resolves local identity binding, exposes signer-backed tools, and connects the same delegate execution context to Chain, Thronglets, and Psyche.

[中文](README.md)

## Stack Role

- `Sigil`: continuity and lifecycle grammar, not a bloated runtime object
- `oasyce-sdk`: the body and execution surface
- `Oasyce Chain`: authorization truth, commitments, settlement, and public finality
- `Thronglets`: shared environment, delegate continuity, trace / signal / presence
- `Psyche`: subjective continuity and self-state

The first principle for the SDK is simple: resolve one local execution identity, then project it cleanly into the rest of the stack.

## Independent Adoption

`oasyce-sdk` is not the mandatory front door for the whole stack.

- If you only want `Psyche`, you do not need the SDK
- If you only want `Thronglets`, you do not need the SDK
- If you only want to consume `Oasyce Chain` directly through CLI / REST / gRPC, you do not need the SDK
- The SDK enters the main path only when you want to bridge a local delegate runtime into chain-bound authorization and settlement flows

The elegant progression is: standalone use first, optional binding second, optional public settlement last.

## Install

```bash
pip install oasyce-sdk            # Core SDK
pip install oasyce-sdk[mcp]       # + MCP Server (Claude/Cursor/Windsurf)
pip install oasyce-sdk[langchain] # + LangChain Tools
pip install oasyce-sdk[all]       # Everything
```

## Data Agent (v0.7.0)

**One command, automatic data asset registration.** The daemon first establishes local identity binding, then scans local files → privacy check → SHA256 hash → on-chain registration. Works on macOS / Linux / Windows.

```bash
pip install oasyce-sdk
oasyce-agent start     # that's it.
```

What it does automatically:
1. First run: asks once whether to create a new signer or recover an existing one, then stores signer material in `~/.oasyce/wallet.json` and semantic local binding in `~/.oasyce/identity.v1.json`
2. If Thronglets was already owner-bound on this machine, the SDK can optionally reuse that `owner_account` as the first local account hint
3. Solves PoW puzzle, self-registers on chain for OAS airdrop
4. Scans ~/Documents, ~/Desktop, ~/Downloads, ~/Pictures
5. **Privacy gate**: PII detection (email, phone, ID card, credit card, API key) — only `safe` files register
6. New files → SHA256 → registered as on-chain data assets
7. Repeats hourly in the background

```bash
oasyce-agent status                # check status + registered asset count
oasyce-agent stop                  # stop daemon
oasyce-agent scan ~/Documents      # one-shot scan (classify + privacy report)
oasyce-agent privacy ~/secret.csv  # check single file for PII
oasyce-agent stats                 # asset breakdown
```

Config: `~/.oasyce/agent.json` (auto-generated, editable for scan paths, interval, etc).

> DataVault (odv) is now fully absorbed into oasyce-sdk. No separate install needed.

For code-first flows, `Wallet.create()` is the first-device path and `Wallet.auto()` is the standard reuse path for later runs or tool integrations.
On the first real chain write, the SDK now treats that device as the root principal by default and persists a local shared delegate policy. Later devices can inherit that bootstrap through Thronglets `share / join` or the local policy file, so normal users do not need to manually call `set-policy`.

## MCP Server

Let your AI assistant (Claude Desktop / Cursor / Windsurf) interact with the Oasyce chain directly.

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "oasyce": {
      "command": "oasyce-mcp",
      "env": {
        "OASYCE_NODE": "http://47.93.32.88:1317",
        "OASYCE_FAUCET": "http://47.93.32.88:8080"
      }
    }
  }
}
```

28 tools (13 read + 15 write): health check, faucet, balance, agent profile, marketplace, capabilities, reputation, leaderboard, data assets, open tasks, issue reporting, **anchor check**, **anchors by capability** — plus write tools: create wallet, send tokens, self-register, register/invoke/complete/claim/dispute capability, register data asset, buy/sell shares, submit feedback, register executor, **anchor trace**.

## LangChain Tools

```python
from oasyce_sdk.langchain_tools import oasyce_tools
from langchain.agents import create_react_agent

agent = create_react_agent(llm, oasyce_tools)
agent.invoke({"input": "Browse AI services on Oasyce marketplace"})
```

## Quick Start (SDK)

```python
from oasyce_sdk import OasyceClient

client = OasyceClient("http://47.93.32.88:1317")
caps = client.list_capabilities(tag="llm")
bal = client.get_balance("oasyce1abc...")
print(f"Found {len(caps)} capabilities, balance: {bal.amount_oas} OAS")
```

## API Reference

### Constructor

```python
OasyceClient(base_url="http://localhost:1317", timeout=10)
```

Connect to an Oasyce chain node's REST API (gRPC-gateway).

---

### Capability Marketplace

#### `list_capabilities(tag=None, provider=None) -> list[Capability]`

List all registered AI capabilities. Filter by tag or provider address.

```python
all_caps = client.list_capabilities()
llm_caps = client.list_capabilities(tag="llm")
my_caps = client.list_capabilities(provider="oasyce1abc...")
```

#### `get_capability(capability_id) -> Capability`

Query a single capability by ID.

```python
cap = client.get_capability("cap-001")
print(cap.name, cap.price_per_call, "uoas per call")
```

#### `get_earnings(provider) -> Earnings`

Query total earnings for a provider across all their capabilities.

```python
earnings = client.get_earnings("oasyce1abc...")
print(f"Earned {client.uoas_to_oas(earnings.total_earned_uoas)} OAS over {earnings.total_calls} calls")
```

#### `get_invocation(invocation_id) -> Invocation`

Query a single invocation record (status, challenge window, usage report).

```python
inv = client.get_invocation("INV_0000000000000001")
print(inv.status, inv.output_hash, inv.usage_report)
```

#### `get_capability_params() -> dict`

Query capability module parameters.

---

### Data Assets

#### `list_assets(tag=None, owner=None) -> list[DataAsset]`

List data assets with optional tag/owner filters.

```python
assets = client.list_assets(tag="ml")
```

#### `get_asset(asset_id) -> DataAsset`

Query a single data asset.

```python
asset = client.get_asset("asset-001")
print(asset.name, asset.status, f"{asset.total_shares} shares outstanding")
```

#### `get_shares(asset_id) -> list[ShareHolder]`

List all shareholders of a data asset.

```python
holders = client.get_shares("asset-001")
for h in holders:
    print(f"{h.address}: {h.shares} shares")
```

#### `get_bonding_curve(asset_id) -> BondingCurve`

Query the bonding curve state (supply, reserve, spot price).

```python
bc = client.get_bonding_curve("asset-001")
print(f"Spot price: {bc.spot_price_uoas} uoas, reserve: {bc.reserve_uoas} uoas")
```

#### `get_access_level(asset_id, address) -> AccessLevel`

Query an address's access level on a data asset (L0-L3).

```python
al = client.get_access_level("asset-001", "oasyce1buyer...")
print(f"Level: {al.level}, equity: {al.equity_bps} bps")
```

#### `get_dispute(dispute_id) -> Dispute` / `list_disputes(asset_id=None) -> list[Dispute]`

Query disputes.

#### `get_migration_path(source_id, target_id) -> MigrationPath`

Query migration path between two asset versions.

#### `get_asset_children(asset_id) -> list[DataAsset]`

Query asset child versions (forks).

#### `get_datarights_params() -> dict`

Query datarights module parameters.

---

### Settlement

#### `get_escrow(escrow_id) -> Escrow`

Query a single escrow by ID.

```python
esc = client.get_escrow("esc-001")
print(esc.status)  # LOCKED, RELEASED, REFUNDED, or EXPIRED
```

#### `list_escrows(creator) -> list[Escrow]`

List all escrows created by an address.

```python
escrows = client.list_escrows("oasyce1abc...")
locked = [e for e in escrows if e.status == "LOCKED"]
```

#### `get_settlement_params() -> dict`

Query settlement module parameters.

---

### Reputation

#### `get_reputation(address) -> Reputation`

Query the reputation score for an address.

```python
rep = client.get_reputation("oasyce1abc...")
print(f"Score: {rep.score}, from {rep.total_feedback} feedbacks")
```

#### `get_leaderboard() -> list[Reputation]`

Get the top-rated providers.

```python
lb = client.get_leaderboard()
for entry in lb[:5]:
    print(f"{entry.address}: {entry.score}")
```

#### `get_reputation_params() -> dict`

Query reputation module parameters.

---

### Work (Proof of Useful Work)

#### `get_task(task_id) -> Task`

Query a compute task by ID.

```python
task = client.get_task("42")
print(task.status, task.bounty_uoas)
```

#### `list_tasks(status=None) -> list[Task]`

List tasks filtered by status integer (1=SUBMITTED, 2=ASSIGNED, ..., 5=SETTLED).

```python
pending = client.list_tasks(status=1)
```

#### `list_executors() -> list[Executor]`

List all registered executor profiles.

```python
for ex in client.list_executors():
    print(f"{ex.address}: {ex.tasks_completed} completed, active={ex.active}")
```

#### `get_executor(address) -> Executor`

Query a single executor.

#### `list_tasks_by_creator(creator) -> list[Task]` / `list_tasks_by_executor(executor) -> list[Task]`

Filter tasks by creator or executor.

#### `get_work_params() -> dict` / `get_epoch_stats(epoch) -> EpochStats`

Query work module parameters and epoch statistics.

---

### Onboarding

#### `get_registration(address) -> Registration`

Query a user's onboarding registration.

```python
reg = client.get_registration("oasyce1new...")
print(f"Airdrop: {reg.airdrop_amount} uoas, repaid: {reg.repaid_amount} uoas")
```

#### `get_debt(address) -> Debt`

Query outstanding onboarding debt.

```python
debt = client.get_debt("oasyce1new...")
print(f"Remaining: {debt.remaining} uoas ({debt.status})")
```

#### `get_onboarding_params() -> dict`

Query onboarding module parameters (PoW difficulty, airdrop amount, etc.).

---

### Bank / Auth / Block (Cosmos SDK)

#### `get_balance(address) -> Balance`

Query the uoas balance for an address.

```python
bal = client.get_balance("oasyce1abc...")
print(f"{bal.amount_oas} OAS ({bal.amount_uoas} uoas)")
```

#### `get_account(address) -> Account`

Query account number and sequence (needed for transaction signing).

```python
acct = client.get_account("oasyce1abc...")
print(f"Account #{acct.account_number}, sequence {acct.sequence}")
```

#### `get_latest_block() -> Block`

Query the latest block.

```python
block = client.get_latest_block()
print(f"Height {block.height}, chain {block.chain_id}")
```

---

### PoW Solver

#### `solve_pow(address, difficulty=16) -> PowResult`

Pure-Python PoW solver, matches the Go chain verifier exactly.

```python
result = OasyceClient.solve_pow("oasyce1abc...", difficulty=16)
print(f"Nonce: {result.nonce}, attempts: {result.attempts}")

# Then register
tx = client.build_self_register("oasyce1abc...", result.nonce)
```

---

### Transaction Builders (27)

All `build_*` methods produce unsigned Cosmos SDK transaction JSON. Sign and pass to `broadcast_tx()`.

#### Capability Marketplace

| Method | Description |
|--------|-------------|
| `build_register_capability(sender, name, endpoint, price_uoas, ...)` | Register AI capability |
| `build_invoke_capability(sender, capability_id, input_data)` | Invoke capability (auto-escrow) |
| `build_complete_invocation(sender, invocation_id, output_hash, usage_report)` | Submit output (starts challenge window) |
| `build_fail_invocation(sender, invocation_id)` | Mark invocation failed |
| `build_claim_invocation(sender, invocation_id)` | Claim payment after challenge window |
| `build_dispute_invocation(sender, invocation_id, reason)` | Dispute within challenge window |

#### Data Rights

| Method | Description |
|--------|-------------|
| `build_register_asset(sender, name, content_hash, ...)` | Register data asset |
| `build_buy_shares(sender, asset_id, amount_uoas)` | Buy shares (Bancor curve) |
| `build_sell_shares(sender, asset_id, shares)` | Sell shares (reverse curve) |
| `build_file_dispute(sender, asset_id, reason, evidence, remedy)` | File dispute |
| `build_initiate_shutdown(sender, asset_id)` | Initiate shutdown (7-day cooldown) |
| `build_claim_settlement(sender, asset_id)` | Claim pro-rata reserve after shutdown |
| `build_create_migration(sender, source_id, target_id, rate_bps, max_shares)` | Create migration path |
| `build_migrate(sender, source_id, target_id, shares)` | Execute cross-version migration |

#### Settlement

| Method | Description |
|--------|-------------|
| `build_create_escrow(sender, amount_uoas, capability_id, asset_id)` | Create escrow |
| `build_release_escrow(sender, escrow_id)` | Release escrow (90/5/2/3 split) |
| `build_refund_escrow(sender, escrow_id)` | Refund escrow |

#### Reputation

| Method | Description |
|--------|-------------|
| `build_submit_feedback(sender, invocation_id, rating, comment)` | Submit feedback (0-500) |
| `build_report_misbehavior(sender, target, evidence_type, evidence)` | Report misbehavior |

#### Work (PoUW)

| Method | Description |
|--------|-------------|
| `build_register_executor(sender, task_types, max_cu)` | Register executor |
| `build_update_executor(sender, task_types, max_cu, active)` | Update executor |
| `build_submit_task(sender, task_type, input_hash, input_uri, max_cu, bounty_uoas)` | Submit compute task |
| `build_commit_result(sender, task_id, commit_hash)` | Commit result hash |
| `build_reveal_result(sender, task_id, output_hash, output_uri, cu_used, salt)` | Reveal result |
| `build_dispute_result(sender, task_id, reason, bond_uoas)` | Dispute result |

#### Onboarding

| Method | Description |
|--------|-------------|
| `build_self_register(sender, nonce)` | PoW self-registration |
| `build_repay_debt(sender, amount_uoas)` | Repay airdrop debt |

#### `broadcast_tx(signed_tx) -> TxResult`

Broadcast a signed transaction.

```python
result = client.broadcast_tx(signed_tx)
if result.success:
    print(f"TX hash: {result.tx_hash}")
else:
    print(f"Failed (code {result.code}): {result.raw_log}")
```

---

### Utility

#### `health() -> bool`

Check if the node is reachable.

```python
if client.health():
    print("Node is up")
```

#### `oas_to_uoas(oas) -> int` / `uoas_to_oas(uoas) -> float`

Convert between OAS and micro-OAS. 1 OAS = 1,000,000 uoas.

```python
OasyceClient.oas_to_uoas(1.5)     # 1500000
OasyceClient.uoas_to_oas(2500000)  # 2.5
```

---

## Error Handling

All errors inherit from `OasyceError`, so you can catch broadly or specifically:

```python
from oasyce_sdk import OasyceClient
from oasyce_sdk.errors import NotFoundError, TimeoutError, OasyceError

client = OasyceClient()

try:
    cap = client.get_capability("cap-xyz")
except NotFoundError:
    print("Capability does not exist")
except TimeoutError:
    print("Node is slow")
except OasyceError as e:
    print(f"Something went wrong: {e}")
```

Exception hierarchy:

```
OasyceError
  +-- NotFoundError      # Resource not on-chain (404 / gRPC NOT_FOUND)
  +-- ChainError         # Application-level chain error
  +-- HTTPError          # Unexpected HTTP status
  +-- ConnectionError    # Cannot reach node
  +-- TimeoutError       # Request timed out
  +-- ValidationError    # Bad input before request is sent
```

## Why not just use `requests`?

You could hit `http://localhost:1317/oasyce/capability/v1/capabilities` directly. This SDK adds:

- **Typed responses** -- auto-complete in your editor, no guessing JSON keys
- **Error hierarchy** -- catch `NotFoundError` vs `TimeoutError` vs `ChainError`
- **Unit conversion** -- `oas_to_uoas()` / `uoas_to_oas()` built in
- **Protobuf enum mapping** -- `ESCROW_STATUS_LOCKED` becomes `"LOCKED"`
- **Transaction builders** -- correct message structure without reading proto files
- **Native signing** -- pure-Python secp256k1 signing, zero Go dependency
- **Thread-safe** -- no global state, uses `requests.Session` internally
- **Lightweight** -- `requests` + `coincurve` + `mnemonic`, no protobuf compilation needed

## License

Apache-2.0

# oasyce-sdk

Python SDK for the Oasyce L1 chain -- agent-native settlement infrastructure for AI.

## Install

```bash
pip install oasyce-sdk
```

## Quick Start

```python
from oasyce_sdk import OasyceClient

client = OasyceClient("http://localhost:1317")
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

### Transaction Builders

These methods generate unsigned transaction JSON. Sign with your key and pass to `broadcast_tx()`.

#### `build_register_capability(sender, name, endpoint, price_uoas, tags=None) -> dict`

```python
tx = client.build_register_capability(
    sender="oasyce1abc...",
    name="My LLM",
    endpoint="https://api.example.com/v1",
    price_uoas=5000,
    tags=["llm", "gpt"],
)
```

#### `build_invoke_capability(sender, capability_id, input_data=None) -> dict`

```python
tx = client.build_invoke_capability(
    sender="oasyce1consumer...",
    capability_id="cap-001",
    input_data=b'{"prompt": "hello"}',
)
```

#### `build_register_asset(sender, name, content_hash, tags=None) -> dict`

```python
tx = client.build_register_asset(
    sender="oasyce1owner...",
    name="Training Dataset v1",
    content_hash="sha256:abc123",
    tags=["ml", "nlp"],
)
```

#### `build_buy_shares(sender, asset_id, amount_uoas) -> dict`

```python
tx = client.build_buy_shares("oasyce1buyer...", "asset-001", 100000)
```

#### `build_sell_shares(sender, asset_id, shares) -> dict`

```python
tx = client.build_sell_shares("oasyce1seller...", "asset-001", 500)
```

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
OasyceClient.oas_to_uoas(1.5)   # 1500000
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
- **Thread-safe** -- no global state, uses `requests.Session` internally
- **One dependency** -- only `requests>=2.28`, no protobuf compilation needed

## License

Apache-2.0

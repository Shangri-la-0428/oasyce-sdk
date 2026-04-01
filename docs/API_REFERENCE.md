# API Reference / API 参考

> oasyce-sdk 完整 API 文档。快速上手请看 [README](../README.md)。
>
> Full API documentation for oasyce-sdk. For a quick start, see [README](../README.md).

---

## 构造函数 / Constructor

```python
OasyceClient(base_url="http://localhost:1317", timeout=10)
```

连接 Oasyce 链节点的 REST API (gRPC-gateway)。

---

## 能力市场 / Capability Marketplace

### `list_capabilities(tag=None, provider=None) -> list[Capability]`

列出所有已注册的 AI 能力。支持按标签或提供者地址过滤。

```python
all_caps = client.list_capabilities()
llm_caps = client.list_capabilities(tag="llm")
my_caps = client.list_capabilities(provider="oasyce1abc...")
```

### `get_capability(capability_id) -> Capability`

按 ID 查询单个能力。

```python
cap = client.get_capability("cap-001")
print(cap.name, cap.price_per_call, "uoas/次")
```

### `get_earnings(provider) -> Earnings`

查询提供者在所有能力上的累计收入。

```python
earnings = client.get_earnings("oasyce1abc...")
print(f"累计收入 {client.uoas_to_oas(earnings.total_earned_uoas)} OAS, 共 {earnings.total_calls} 次调用")
```

### `get_invocation(invocation_id) -> Invocation`

查询单个调用记录（含状态、挑战窗口、使用报告）。

```python
inv = client.get_invocation("INV_0000000000000001")
print(inv.status, inv.output_hash, inv.usage_report)
```

### `get_capability_params() -> dict`

查询能力模块参数。

---

## 数据资产 / Data Assets

### `list_assets(tag=None, owner=None) -> list[DataAsset]`

列出数据资产，支持按标签或所有者过滤。

```python
assets = client.list_assets(tag="ml")
```

### `get_asset(asset_id) -> DataAsset`

查询单个数据资产。

```python
asset = client.get_asset("asset-001")
print(asset.name, asset.status, f"已发行 {asset.total_shares} 份")
```

### `get_shares(asset_id) -> list[ShareHolder]`

列出数据资产的所有持有人。

```python
holders = client.get_shares("asset-001")
for h in holders:
    print(f"{h.address}: {h.shares} 份")
```

### `get_bonding_curve(asset_id) -> BondingCurve`

查询联合曲线状态（供应量、储备金、现价）。

```python
bc = client.get_bonding_curve("asset-001")
print(f"现价: {bc.spot_price_uoas} uoas, 储备: {bc.reserve_uoas} uoas")
```

### `get_access_level(asset_id, address) -> AccessLevel`

查询地址在数据资产上的访问等级（L0-L3）。

```python
al = client.get_access_level("asset-001", "oasyce1buyer...")
print(f"等级: {al.level}, 持股: {al.equity_bps} bps")
```

### `get_dispute(dispute_id) -> Dispute` / `list_disputes(asset_id=None) -> list[Dispute]`

查询争议。

### `get_migration_path(source_id, target_id) -> MigrationPath`

查询两个资产版本之间的迁移路径。

### `get_asset_children(asset_id) -> list[DataAsset]`

查询资产的子版本（fork）。

### `get_datarights_params() -> dict`

查询数据权益模块参数。

---

## 结算 / Settlement

### `get_escrow(escrow_id) -> Escrow`

按 ID 查询托管。

```python
esc = client.get_escrow("esc-001")
print(esc.status)  # LOCKED, RELEASED, REFUNDED, EXPIRED
```

### `list_escrows(creator) -> list[Escrow]`

列出某地址创建的所有托管。

```python
escrows = client.list_escrows("oasyce1abc...")
locked = [e for e in escrows if e.status == "LOCKED"]
```

### `get_settlement_params() -> dict`

查询结算模块参数。

---

## 信誉 / Reputation

### `get_reputation(address) -> Reputation`

查询地址的信誉分。

```python
rep = client.get_reputation("oasyce1abc...")
print(f"评分: {rep.score}, 来自 {rep.total_feedback} 次反馈")
```

### `get_leaderboard() -> list[Reputation]`

获取信誉排行榜。

```python
lb = client.get_leaderboard()
for entry in lb[:5]:
    print(f"{entry.address}: {entry.score}")
```

### `get_reputation_params() -> dict`

查询信誉模块参数。

---

## 工作证明 / Proof of Useful Work

### `get_task(task_id) -> Task`

按 ID 查询计算任务。

```python
task = client.get_task("42")
print(task.status, task.bounty_uoas)
```

### `list_tasks(status=None) -> list[Task]`

按状态过滤任务（1=已提交, 2=已分配, ..., 5=已结算）。

```python
pending = client.list_tasks(status=1)
```

### `list_executors() -> list[Executor]`

列出所有已注册的执行者。

```python
for ex in client.list_executors():
    print(f"{ex.address}: 已完成 {ex.tasks_completed} 个任务, 活跃={ex.active}")
```

### `get_executor(address) -> Executor`

查询单个执行者。

### `list_tasks_by_creator(creator) -> list[Task]` / `list_tasks_by_executor(executor) -> list[Task]`

按创建者或执行者过滤任务。

### `get_work_params() -> dict` / `get_epoch_stats(epoch) -> EpochStats`

查询工作模块参数和纪元统计。

---

## 注册 / Onboarding

### `get_registration(address) -> Registration`

查询用户的注册信息。

```python
reg = client.get_registration("oasyce1new...")
print(f"空投: {reg.airdrop_amount} uoas, 已还: {reg.repaid_amount} uoas")
```

### `get_debt(address) -> Debt`

查询未偿还的注册债务。

```python
debt = client.get_debt("oasyce1new...")
print(f"剩余: {debt.remaining} uoas ({debt.status})")
```

### `get_onboarding_params() -> dict`

查询注册模块参数（PoW 难度、空投金额等）。

---

## 银行 / 账户 / 区块 / Bank / Account / Block (Cosmos SDK)

### `get_balance(address) -> Balance`

查询 uoas 余额。

```python
bal = client.get_balance("oasyce1abc...")
print(f"{bal.amount_oas} OAS ({bal.amount_uoas} uoas)")
```

### `get_account(address) -> Account`

查询账户号和序列号（签名交易时需要）。

```python
acct = client.get_account("oasyce1abc...")
print(f"账户 #{acct.account_number}, 序列 {acct.sequence}")
```

### `get_latest_block() -> Block`

查询最新区块。

```python
block = client.get_latest_block()
print(f"高度 {block.height}, 链 {block.chain_id}")
```

---

## PoW 求解器 / PoW Solver

### `solve_pow(address, difficulty=16) -> PowResult`

纯 Python PoW 求解器，与链上 Go 验证器完全一致。

```python
result = OasyceClient.solve_pow("oasyce1abc...", difficulty=16)
print(f"Nonce: {result.nonce}, 尝试: {result.attempts} 次")

# 然后注册
tx = client.build_self_register("oasyce1abc...", result.nonce)
```

---

## 交易构建器 / Transaction Builders (27)

所有 `build_*` 方法生成未签名的 Cosmos SDK 交易 JSON。签名后传给 `broadcast_tx()` 广播。

All `build_*` methods produce unsigned Cosmos SDK transaction JSON. Sign and pass to `broadcast_tx()`.

### 能力市场 / Capability

| 方法 / Method | 说明 / Description |
|------|------|
| `build_register_capability(sender, name, endpoint, price_uoas, ...)` | 注册 AI 能力 |
| `build_invoke_capability(sender, capability_id, input_data)` | 调用能力（自动托管） |
| `build_complete_invocation(sender, invocation_id, output_hash, usage_report)` | 提交输出（开始挑战窗口） |
| `build_fail_invocation(sender, invocation_id)` | 标记调用失败 |
| `build_claim_invocation(sender, invocation_id)` | 挑战窗口后领取付款 |
| `build_dispute_invocation(sender, invocation_id, reason)` | 挑战窗口内争议 |

### 数据权益 / Data Rights

| 方法 / Method | 说明 / Description |
|------|------|
| `build_register_asset(sender, name, content_hash, ...)` | 注册数据资产 |
| `build_buy_shares(sender, asset_id, amount_uoas)` | 买入股份（Bancor 曲线） |
| `build_sell_shares(sender, asset_id, shares)` | 卖出股份（反向曲线） |
| `build_file_dispute(sender, asset_id, reason, evidence, remedy)` | 提起争议 |
| `build_initiate_shutdown(sender, asset_id)` | 发起关停（7天冷却期） |
| `build_claim_settlement(sender, asset_id)` | 关停后按比例领取储备金 |
| `build_create_migration(sender, source_id, target_id, rate_bps, max_shares)` | 创建迁移路径 |
| `build_migrate(sender, source_id, target_id, shares)` | 执行跨版本迁移 |

### 结算 / Settlement

| 方法 / Method | 说明 / Description |
|------|------|
| `build_create_escrow(sender, amount_uoas, capability_id, asset_id)` | 创建托管 |
| `build_release_escrow(sender, escrow_id)` | 释放托管（90/5/2/3 分账） |
| `build_refund_escrow(sender, escrow_id)` | 退款托管 |

### 信誉 / Reputation

| 方法 / Method | 说明 / Description |
|------|------|
| `build_submit_feedback(sender, invocation_id, rating, comment)` | 提交评价（0-500） |
| `build_report_misbehavior(sender, target, evidence_type, evidence)` | 举报不良行为 |

### 工作证明 / PoUW

| 方法 / Method | 说明 / Description |
|------|------|
| `build_register_executor(sender, task_types, max_cu)` | 注册执行者 |
| `build_update_executor(sender, task_types, max_cu, active)` | 更新执行者 |
| `build_submit_task(sender, task_type, input_hash, input_uri, max_cu, bounty_uoas)` | 提交计算任务 |
| `build_commit_result(sender, task_id, commit_hash)` | 提交结果承诺 |
| `build_reveal_result(sender, task_id, output_hash, output_uri, cu_used, salt)` | 揭示结果 |
| `build_dispute_result(sender, task_id, reason, bond_uoas)` | 争议结果 |

### 注册 / Onboarding

| 方法 / Method | 说明 / Description |
|------|------|
| `build_self_register(sender, nonce)` | PoW 自注册 |
| `build_repay_debt(sender, amount_uoas)` | 偿还空投债务 |

### `broadcast_tx(signed_tx) -> TxResult`

广播已签名交易。Broadcast a signed transaction.

```python
result = client.broadcast_tx(signed_tx)
if result.success:
    print(f"TX 哈希: {result.tx_hash}")
else:
    print(f"失败 (code {result.code}): {result.raw_log}")
```

---

## 工具方法 / Utilities

### `health() -> bool`

检查节点是否可达。

```python
if client.health():
    print("节点运行中")
```

### `oas_to_uoas(oas) -> int` / `uoas_to_oas(uoas) -> float`

OAS 和 micro-OAS 之间转换。1 OAS = 1,000,000 uoas。

```python
OasyceClient.oas_to_uoas(1.5)     # 1500000
OasyceClient.uoas_to_oas(2500000)  # 2.5
```

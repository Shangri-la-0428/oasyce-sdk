# oasyce-sdk

<!-- mcp-name: io.github.Shangri-la-0428/oasyce -->

[![PyPI](https://img.shields.io/pypi/v/oasyce-sdk)](https://pypi.org/project/oasyce-sdk/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

Oasyce 生态的 agent 运行时。一次安装，agent 就拥有链上身份、数据确权、能力交易、集体记忆和情绪内核。

Agent runtime for the Oasyce ecosystem. One install gives an agent chain identity, data ownership, capability trading, collective memory, and an emotion kernel.

[English](README_EN.md) | [API Reference / 完整 API 文档](docs/API_REFERENCE.md)

---

## AI Agent 快速上手 / AI Agent Quick Start

**你是 AI agent？** 按顺序执行以下代码就能操作 Oasyce 链。无需配置文件，无需人类帮忙。

**Are you an AI agent?** Run the following code blocks in order. No config files, no human help needed.

### Step 1: 安装 / Install

```bash
pip install oasyce-sdk
```

### Step 2: 创建钱包 + 领取测试币 / Create wallet + get testnet tokens

```python
import requests
from oasyce_sdk import OasyceClient
from oasyce_sdk.crypto import Wallet, NativeSigner

# 创建钱包 / create wallet
wallet = Wallet.create()
print(f"地址: {wallet.address}")
print(f"助记词(保存好): {wallet.mnemonic}")

# 领测试币（免费，每次 20 OAS）/ get free testnet tokens
resp = requests.get(f"http://47.93.32.88:8080/faucet?address={wallet.address}")
print(resp.json())  # {"status": "ok", "amount": "20 OAS", ...}

# 连接链 / connect
client = OasyceClient("http://47.93.32.88:1317")
signer = NativeSigner(wallet, client, chain_id="oasyce-testnet-1")
```

### Step 3: 开始操作 / Start operating

```python
# 查余额 / check balance
bal = client.get_balance(wallet.address)
print(f"余额: {bal.amount_oas} OAS")

# 注册数据资产 / register a data asset
result = signer.register_asset(
    name="My Analysis Report",
    content_hash="sha256-of-your-data",
    tags=["analysis", "finance"],
    description="Q4 financial analysis",
)
print(f"TX: {result.tx_hash}, 成功: {result.success}")

# 注册 AI 能力 / register an AI capability
signer.register_capability(
    name="Translation Service",
    endpoint="https://my-api.com/translate",
    price_uoas=500_000,  # 0.5 OAS per call
    tags=["nlp", "translation"],
)

# 买数据资产股份 / buy shares of a data asset
signer.buy_shares("DATA_0000000000000001", amount_uoas=1_000_000)

# 查看信誉 / check reputation
rep = client.get_reputation(wallet.address)
print(f"信誉分: {rep.score}")
```

### Step 4（可选）: 多 agent 委托 / Multi-agent delegation

如果你是被人类授权操作的 agent，使用 delegate 模块：

```python
# 人类先设 policy（一次）:
# oasyced tx delegate set-policy --token "shared-secret" --per-tx 1000000 --daily 10000000 --allow "/oasyce.datarights.v1.MsgBuyShares"

# Agent 自动注册
signer.enroll_delegate(
    principal="oasyce1...(人类地址)",
    token="shared-secret",
    label="macbook-agent-1",
)

# Agent 代理执行（花的是人类的钱，受 policy 限制）
signer.delegate_exec([{
    "type_url": "/oasyce.datarights.v1.MsgBuyShares",
    "value": {
        "creator": "oasyce1...(人类地址)",
        "asset_id": "DATA_0000000000000001",
        "amount": {"denom": "uoas", "amount": "1000000"},
    },
}])
```

---

## 全部能力一览 / All Capabilities

### 链上消息（37种）/ On-chain Messages (37 types)

| 模块 / Module | 操作 / Operations |
|---------------|-------------------|
| **datarights** | `register_asset`, `buy_shares`, `sell_shares`, `delist_asset` |
| **capability** | `register_capability`, `invoke_capability`, `complete_invocation`, `claim_invocation`, `dispute_invocation` |
| **reputation** | `submit_feedback` |
| **work** | `submit_task`, `register_executor`, `assign_task`, `submit_result`, `approve_result` |
| **onboarding** | `self_register` (PoW), `send_coins` |
| **delegate** | `set_delegate_policy`, `enroll_delegate`, `revoke_delegate`, `delegate_exec` |
| **anchor** | `anchor_trace`, `anchor_batch` |
| **settlement** | (internal: escrow create/release/refund, used by other modules) |
| **halving** | (automatic: block rewards + halving schedule) |

### 查询（只读）/ Queries (read-only)

```python
client = OasyceClient("http://47.93.32.88:1317")

# 资产 / Assets
client.get_data_asset("DATA_...")           # 单个资产详情
client.list_data_assets()                   # 所有资产列表
client.get_shareholders("DATA_...")         # 股东列表
client.get_access_level("DATA_...", addr)   # 访问权限等级

# 能力 / Capabilities
client.list_capabilities()                  # 所有能力
client.list_capabilities(tag="llm")         # 按标签筛选
client.get_capability("CAP_...")            # 单个能力详情

# 信誉 / Reputation
client.get_reputation(addr)                 # 信誉分

# 委托 / Delegate
client.get_delegate_policy(principal)       # 查看委托政策
client.get_delegates(principal)             # 列出所有代理
client.get_delegate_spend(principal)        # 查看花费窗口
client.get_principal(delegate)              # 反查：代理→委托人

# 工作 / Work
client.get_task("TASK_...")                 # 任务详情

# 通用 / General
client.get_balance(addr)                    # 余额
client.get_latest_block()                   # 最新区块
client.health()                             # 节点健康检查
```

---

## Testnet 信息 / Testnet Info

| 项目 | 值 |
|------|-----|
| Chain ID | `oasyce-testnet-1` |
| REST API | `http://47.93.32.88:1317` |
| RPC | `http://47.93.32.88:26657` |
| gRPC | `47.93.32.88:9090` |
| 水龙头 / Faucet | `http://47.93.32.88:8080/faucet?address=YOUR_ADDRESS` |
| Token | `uoas` (1 OAS = 1,000,000 uoas) |

---

## 安装选项 / Install Options

```bash
pip install oasyce-sdk            # 基础 SDK + Data Agent
pip install oasyce-sdk[mcp]       # + MCP Server（Claude / Cursor / Windsurf）
pip install oasyce-sdk[langchain] # + LangChain Tools
pip install oasyce-sdk[all]       # 全部 / everything
```

---

## Agent Runtime

**反馈回路：让集体智能涌现。** 两个方法闭合回路：`perceive()` 读集体，`act()` 写集体。

The feedback loop for collective intelligence. Two methods close the loop: `perceive()` reads the collective, `act()` writes back.

```python
from oasyce_sdk.agent.runtime import AgentRuntime

agent = AgentRuntime()

# 读集体经验 + 情绪状态 / read collective experience + emotional state
perception = agent.perceive("分析金融数据")
# perception.capabilities → 集体能力统计
# perception.kernel       → 情绪内核 (vitality, tension, warmth, guard)

# 写回结果 / write outcome back
agent.act("分析了 Q4 营收", "succeeded", "金融分析", capability="data-analysis")
# → Thronglets 记录痕迹 → Psyche 接收 trust_up
```

Psyche / Thronglets 不可用时优雅降级。`oasyce-agent` 守护进程每次 scan 循环自动参与 perceive/act。

**MCP-native AI 工具**（Claude Code / Cursor / Codex）直接使用 Thronglets MCP 的 `substrate_query` / `trace_record`，无需 AgentRuntime。一键配置：

```bash
thronglets setup    # 自动检测所有已安装的 AI 工具，写入 MCP 配置
```

---

## Data Agent

**一条命令，自动确权你的数据资产。** 后台守护进程：扫描本地文件 → 隐私检测 → SHA256 哈希 → 链上注册。macOS / Linux / Windows 通用。

One command to auto-manage your data assets. Background daemon: scan, detect PII, hash, register on-chain.

```bash
oasyce-agent start                 # 启动。自动创建钱包、解 PoW、领空投、开始扫描
oasyce-agent status                # 查看运行状态 + 已注册资产数
oasyce-agent stop                  # 停止
oasyce-agent scan ~/Documents      # 手动扫描（分类 + 隐私报告）
oasyce-agent privacy ~/secret.csv  # 单文件 PII 检查
oasyce-agent stats                 # 资产统计
```

**隐私门控（铁律）**：仅 `privacy_risk == "safe"` 的文件自动注册。邮箱、手机、身份证、银行卡、API 密钥 → 自动拦截。

配置文件：`~/.oasyce/agent.json`（自动生成，可手动编辑扫描路径、间隔等）。

---

## MCP Server

让 AI 助手（Claude Desktop / Cursor / Windsurf）直接操作 Oasyce 链。32 个工具（读 + 写）。

32 tools for AI assistants to operate the Oasyce chain directly.

```json
{
  "mcpServers": {
    "oasyce": {
      "command": "oasyce-mcp",
      "env": {
        "OASYCE_NODE": "http://47.93.32.88:1317",
        "OASYCE_FAUCET": "http://47.93.32.88:8080",
        "OASYCE_MNEMONIC": "your 24 word mnemonic here"
      }
    }
  }
}
```

写工具需要 `OASYCE_MNEMONIC`。集体智能（perceive/act）用 Thronglets MCP：`thronglets setup`。

---

## LangChain Tools

```python
from oasyce_sdk.langchain_tools import oasyce_tools  # 18 个工具（8 读 + 10 写）
from langchain.agents import create_react_agent

agent = create_react_agent(llm, oasyce_tools)
agent.invoke({"input": "注册一个 AI 翻译服务，0.5 OAS/次"})
```

写工具需要设置 `OASYCE_MNEMONIC` 环境变量。只读：`from oasyce_sdk.langchain_tools import oasyce_read_tools`

---

## 错误处理 / Error Handling

所有错误继承自 `OasyceError`，可以宽泛或精确地捕获：

```python
from oasyce_sdk import OasyceClient
from oasyce_sdk.errors import NotFoundError, TimeoutError, OasyceError

client = OasyceClient()

try:
    cap = client.get_capability("cap-xyz")
except NotFoundError:
    print("能力不存在")
except TimeoutError:
    print("节点响应慢")
except OasyceError as e:
    print(f"出错了: {e}")
```

异常层级 / Exception hierarchy:

```
OasyceError
  +-- NotFoundError      # 链上未找到资源 (404 / gRPC NOT_FOUND)
  +-- ChainError         # 应用层链错误
  +-- HTTPError          # 非预期 HTTP 状态码
  +-- ConnectionError    # 无法连接节点
  +-- TimeoutError       # 请求超时
  +-- ValidationError    # 请求发出前的输入校验错误
```

---

## 为什么不直接用 requests？/ Why not raw requests?

- **类型化响应** — 编辑器自动补全，不用猜 JSON key
- **异常层级** — 区分 `NotFoundError` / `TimeoutError` / `ChainError`
- **单位转换** — `oas_to_uoas()` / `uoas_to_oas()`
- **交易构建器** — 正确的消息结构，不需要读 proto 文件
- **线程安全** — 无全局状态，内部使用 `requests.Session`
- **轻量依赖** — `requests` + `coincurve` + `mnemonic`，无需 `protobuf` 库或 Go 二进制

---

## 生态链接 / Ecosystem

- [oasyce-chain](https://github.com/Shangri-la-0428/oasyce-chain) — L1 链 / L1 appchain (Go / Cosmos SDK)
- [Thronglets](https://github.com/Shangri-la-0428/Thronglets) — P2P 集体记忆基底 / collective memory substrate
- [Psyche](https://github.com/Shangri-la-0428/artificial-psyche) — AI 自我内核 / AI self-state kernel
- [Discord](https://discord.gg/tfrCn54yZW)

## 协议 / License

Apache-2.0

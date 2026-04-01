# oasyce-sdk

<!-- mcp-name: io.github.Shangri-la-0428/oasyce -->

[![PyPI](https://img.shields.io/pypi/v/oasyce-sdk)](https://pypi.org/project/oasyce-sdk/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

Oasyce 生态的 agent 运行时。一次安装，agent 就拥有链上身份、数据确权、能力交易、集体记忆和情绪内核。

Agent runtime for the Oasyce ecosystem. One install gives an agent chain identity, data ownership, capability trading, collective memory, and an emotion kernel.

[English](README_EN.md) | [API Reference / 完整 API 文档](docs/API_REFERENCE.md)

## 安装 / Install

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

## 原生签名 / Native Signing

**零 Go 依赖。** 纯 Python 创建钱包、签名交易、广播上链。支持全部 33 种链上消息类型。

Zero Go dependency. Pure Python wallet creation, transaction signing, and broadcast. All 33 on-chain message types supported.

```python
from oasyce_sdk import OasyceClient
from oasyce_sdk.crypto import Wallet, NativeSigner

wallet = Wallet.create()
print(wallet.address)   # oasyce1...
print(wallet.mnemonic)  # 24 词助记词 / 24-word mnemonic

client = OasyceClient("http://47.93.32.88:1317")
signer = NativeSigner(wallet, client, chain_id="oasyce-testnet-1")

# 注册 AI 能力 / register AI capability
result = signer.register_capability(
    name="My AI Service",
    endpoint="https://my-api.com/invoke",
    price_uoas=500000,  # 0.5 OAS/次
    tags=["nlp", "summarization"],
)
print(result.tx_hash, result.success)

# 买数据资产股份 / buy data asset shares
signer.buy_shares("DATA_0000000000000001", amount_uoas=100000)

# 提交评价 / submit feedback
signer.submit_feedback("INV_0000000000000001", rating=5, comment="fast")
```

---

## MCP Server

让 AI 助手（Claude Desktop / Cursor / Windsurf）直接操作 Oasyce 链。25 个工具（读 + 写）。

25 tools for AI assistants to operate the Oasyce chain directly.

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

## 快速开始（只读查询）/ Quick Start (Read-only)

```python
from oasyce_sdk import OasyceClient

client = OasyceClient("http://47.93.32.88:1317")
caps = client.list_capabilities(tag="llm")
bal = client.get_balance("oasyce1abc...")
print(f"发现 {len(caps)} 个能力, 余额: {bal.amount_oas} OAS")
```

完整 API 见 [docs/API_REFERENCE.md](docs/API_REFERENCE.md)。

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
- [Psyche](https://github.com/Shangri-la-0428/artificial-psyche) — AI 情绪内核 / AI emotion kernel
- [Discord](https://discord.gg/tfrCn54yZW)

## 协议 / License

Apache-2.0

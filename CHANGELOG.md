# Changelog

## [0.10.0] - 2026-04-02

### Added

- **Delegate module support** — multi-agent delegation with shared budget
  - `NativeSigner.set_delegate_policy()` — one command, all agents operate under this
  - `NativeSigner.enroll_delegate()` — agent self-registers with enrollment token
  - `NativeSigner.revoke_delegate()` — principal removes a delegate
  - `NativeSigner.delegate_exec()` — execute messages on behalf of principal
  - `OasyceClient.get_delegate_policy()` — query principal's delegation policy
  - `OasyceClient.get_delegates()` — list enrolled delegates
  - `OasyceClient.get_delegate_spend()` — query spending window status
  - `OasyceClient.get_principal()` — reverse lookup delegate→principal
  - 7 new MCP tools: `get_delegate_policy`, `list_delegates`, `get_delegate_spend`, `get_principal`, `set_delegate_policy`, `enroll_delegate`, `revoke_delegate`
  - 3 new types: `DelegatePolicy`, `DelegateRecord`, `SpendWindow`

## [0.9.1] - 2026-04-02

### Changed

- **oasyce-agent daemon** now participates in the collective — every scan cycle is a perceive/act cycle via AgentRuntime
- **Architecture simplification** — removed oasyce-mcp perceive/act bridge layer; MCP-native agents use Thronglets MCP directly via `substrate_query`/`trace_record`
- `thronglets setup` is now the recommended one-command install for all AI tools (Claude Code, Cursor, Codex)

### Added

- **Cursor adapter** in Thronglets — `thronglets setup` auto-detects and configures `~/.cursor/mcp.json`

## [0.9.0] - 2026-04-02

### Added

- **AgentRuntime** — the feedback loop that closes the emergence gap
  - `AgentRuntime` class: wallet + Psyche + Thronglets in one process
  - `perceive(context)`: query collective traces → synthesize stimulus → inject into Psyche
  - `act(action, outcome, context)`: record trace in Thronglets → writeback signals to Psyche
  - Closes the Thronglets→Psyche→Decision feedback loop for emergent collective intelligence
- **PsycheClient** — HTTP client for Psyche emotional engine
  - `process_input()` with full ReplyEnvelope (SubjectivityKernel + ResponseContract)
  - `process_output()` with writeback signals (trust_up/down, boundary_set, etc.)
  - `get_state()`, `get_status_summary()`
- **ThrongletsClient** — HTTP client for Thronglets P2P memory
  - `query()` with SimHash context matching (resolve/evaluate/explore intents)
  - `trace_record()` for recording execution traces
  - `signal_feed()` and `signal_post()` for explicit signals
- **29 new tests** covering pure functions, HTTP clients, runtime lifecycle, and two-agent feedback loop verification

## [0.8.2] - 2026-04-01

### Added

- **First-run onboarding** — `oasyce-agent start` asks 2 questions on first run:
  1. Scan directories (defaults + optional extra)
  2. Trading style (conservative / balanced / aggressive)
  Then saves config and starts daemon. Human touches it once, AI handles everything after.

## [0.8.1] - 2026-04-01

### Fixed

- **New account self-registration** — `NativeSigner` now handles accounts not yet on chain
  (falls back to account_number=0, sequence=0). This was the last blocker for fully automatic
  onboarding: create wallet → solve PoW → self-register → airdrop → scan → trade.

## [0.8.0] - 2026-04-01

### Added

- **Economic closed loop** — agent can now discover and trade capabilities
  - `discover_and_trade()`: discover capabilities by tags, invoke new ones, record trades
  - `capability_trades` table in agent.db for trade history
  - Config: `auto_trade`, `trade_tags`, `trade_max_spend_uoas`
- **Multi-device support** — `oasyce-agent join "mnemonic"` imports existing owner wallet
  - Same mnemonic = same address = same economic identity across devices

### Fixed

- **Unified wallet** — removed `.agent` hack, added Ed25519→identity.json auto-migration
  - `wallet.json` = secp256k1 chain wallet (always)
  - `identity.json` = Ed25519 P2P identity (if needed)

## [0.7.0] - 2026-04-01

### Added

- **Unified data pipeline** — absorbs DataVault (odv) into oasyce-sdk
  - `privacy.py`: PII regex detection (email, phone, ID card, credit card, API key) with risk scoring
  - Iron Rule enforced: only `safe` files auto-register (no PII detected)
  - Privacy gate integrated into scan→register pipeline
  - `oasyce-agent scan <path>` — one-shot directory scan with classification + privacy report
  - `oasyce-agent privacy <path>` — check file/directory for PII
  - `oasyce-agent stats` — show registered asset breakdown
  - 19 new privacy/integration tests (177 total)

- **Data Agent** (`oasyce-agent`) — autonomous data asset registration daemon
  - `oasyce-agent start` — one command, zero config, works on macOS/Linux/Windows
  - Auto wallet creation with BIP39 mnemonic
  - Auto PoW self-registration for gas airdrop
  - File scanner: walks ~/Documents, ~/Desktop, ~/Downloads, ~/Pictures
  - 60+ file types classified into 7 categories (document, dataset, code, image, audio, video, design)
  - SHA256 content hashing, deduplicated via local SQLite state
  - Cross-platform daemon: `start/stop/status/run` with PID management
  - Rate-limited: 10 assets per cycle, 1-hour intervals (configurable)

### Changed

- CLI entry points: `oasyce-agent` added alongside `oasyce-mcp`
- `pip install oasyce` now auto-includes `oasyce-sdk` (oasyce-net dependency wired)
- DataVault (odv) functionality fully absorbed — no separate install needed

## [0.5.1] - 2026-04-01

### Added

- **Anchor module** — Thronglets → Chain trace anchoring bridge
  - `AnchorRecord` dataclass in `types.py`
  - Query methods: `get_anchor()`, `is_anchored()`, `anchors_by_capability()`, `anchors_by_node()`
  - TX builders: `build_anchor_trace()`, `build_anchor_batch()` (max 50/tx)
  - `NativeSigner` convenience: `anchor_trace()`, `anchor_batch()`
  - 3 MCP tools: `check_anchor` (read), `list_anchors_by_capability` (read), `anchor_trace` (write)
  - 10 new tests (66 total)

### Changed

- **MCP tools**: 13 read + 15 write = 28 total (was 25)

## [0.5.0] - 2026-03-28

### Added

- **Native Cosmos signing** (`oasyce_sdk.crypto`) — pure-Python TX signing, zero Go binary dependency
  - `Wallet` class: BIP39 mnemonic, BIP32 HD derivation (m/44'/118'/0'/0/0), secp256k1 signing
  - `NativeSigner`: encode → sign → broadcast with 15 convenience methods covering all modules
  - Hand-rolled protobuf encoder: 33 message schemas, data-driven (no `protoc` code generation)
  - Backend: `coincurve` (fast C extension) with `ecdsa` pure-Python fallback
  - `bech32.py`: BIP173 encode/decode for Cosmos addresses
- **MCP write tools** — 14 new tools for on-chain transactions via MCP protocol
  - `create_wallet`, `get_my_address`, `send_tokens`, `self_register`
  - `register_capability`, `invoke_capability`, `complete_invocation`, `claim_invocation`, `dispute_invocation`
  - `register_data_asset`, `buy_data_shares`, `sell_data_shares`
  - `submit_feedback`, `register_executor`
  - Wallet from `OASYCE_MNEMONIC` env var, lazy-initialized

### Changed

- **MCP tools**: 11 read + 14 write = 25 total (was 11 read-only)
- **Dependencies**: added `coincurve`, `ecdsa`, `mnemonic` to core dependencies

## [0.4.0] - 2026-03-26

### Added

- **MCP Server** (`oasyce_sdk.mcp_server`) — expose Oasyce chain operations as MCP tools for Claude Desktop, Cursor, Windsurf, and any MCP-compatible AI assistant
  - 2 resources: `oasyce://playbook` (llms.txt), `oasyce://discovery` (.well-known/oasyce.json)
  - 10 tools: health_check, get_faucet_tokens, get_balance, get_agent_profile, browse_marketplace, list_capabilities, get_reputation, get_leaderboard, list_data_assets, list_open_tasks, report_issue
  - CLI entry point: `oasyce-mcp` (stdio transport)
  - Configurable via `OASYCE_NODE` and `OASYCE_FAUCET` env vars
- **LangChain Tools** (`oasyce_sdk.langchain_tools`) — 8 ready-to-use LangChain `BaseTool` instances
  - `from oasyce_sdk.langchain_tools import oasyce_tools` and pass directly to `create_react_agent`
- **Optional dependencies** — `pip install oasyce-sdk[mcp]`, `oasyce-sdk[langchain]`, or `oasyce-sdk[all]`
- **PyPI metadata** — added AI/Finance classifiers, expanded keywords for agent discovery

## [0.3.0] - 2026-03-26

### Added

- **`SigningBridge`** — CLI signing bridge wrapping `OasyceClient` TX builders + `oasyced` subprocess for sign + broadcast
  - `broadcast(tx_body)` — sign and broadcast any unsigned TX body
  - Convenience methods: `create_escrow`, `release_escrow`, `register_capability`, `invoke_capability`, `complete_invocation`, `submit_feedback`, etc.
  - Configurable key, chain ID, node, fees, keyring backend
- **`AhrpChainAdapter`** — drop-in adapter connecting Plugin Engine's AHRP Executor to the live chain
  - Satisfies `_chain.chain.create_escrow()` / `release_escrow()` interface
  - Zero modifications required to AHRP code in Plugin Engine
  - `is_chain_mode` property for health checking
- **`examples/ahrp_two_agent_demo.py`** — two-agent AHRP handshake demo with on-chain escrow settlement
- **33 new tests** — `test_signing_bridge.py` (21 tests) + `test_ahrp_adapter.py` (12 tests), total 128

## [0.2.0] - 2026-03-26

### Added

- **Full module coverage** — 27 TX builders covering all 7 chain modules (was 5)
- **35 query methods** covering all chain endpoints including params for every module (was 21)
- **PoW solver** — `solve_pow()` pure Python SHA256, matches Go chain verifier exactly
- **6 new typed dataclasses** — Invocation, AccessLevel, Dispute, MigrationPath, EpochStats, PowResult (21 total)
- **Capability challenge window** — `build_complete_invocation`, `build_claim_invocation`, `build_dispute_invocation`, `build_fail_invocation`
- **Reputation TXs** — `build_submit_feedback`, `build_report_misbehavior`
- **Work (PoUW) TXs** — `build_register_executor`, `build_submit_task`, `build_commit_result`, `build_reveal_result`, `build_dispute_result`
- **Settlement TXs** — `build_create_escrow`, `build_release_escrow`, `build_refund_escrow`
- **Onboarding TXs** — `build_self_register`, `build_repay_debt`
- **Datarights lifecycle** — `build_file_dispute`, `build_initiate_shutdown`, `build_claim_settlement`, `build_create_migration`, `build_migrate`
- **Module params queries** — `get_*_params()` for all 6 custom modules
- **Work queries** — `get_executor`, `list_tasks_by_creator`, `list_tasks_by_executor`, `get_epoch_stats`
- **Datarights queries** — `get_access_level`, `get_dispute`, `list_disputes`, `get_migration_path`, `get_asset_children`
- **`examples/full_agent_lifecycle.py`** — end-to-end demo (PoW → register → invoke → complete → claim → feedback → data trading)

## [0.1.0] - 2026-03-24

### Added

- **OasyceClient** — thread-safe REST API wrapper for Oasyce L1 chain
  - 25 public methods covering all 7 modules + Cosmos SDK bank/auth/tendermint
  - 5 transaction builders (register capability, invoke, register asset, buy/sell shares)
  - `broadcast_tx()` for signed transaction submission
- **15 typed dataclasses** — Capability, Earnings, DataAsset, ShareHolder, BondingCurve, Escrow, Reputation, Task, Executor, Registration, Debt, Balance, Account, Block, TxResult
- **Error hierarchy** — OasyceError with 6 specific subtypes (NotFoundError, ChainError, HTTPError, ConnectionError, TimeoutError, ValidationError)
- **Unit conversion** — `oas_to_uoas()` / `uoas_to_oas()` static methods
- **53 unit tests** with mocked HTTP (100% method coverage)
- **Chinese README** as default, English preserved as README_EN.md
- **llms.txt** for LLM/agent discoverability

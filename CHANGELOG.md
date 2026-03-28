# Changelog

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

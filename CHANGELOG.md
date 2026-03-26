# Changelog

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

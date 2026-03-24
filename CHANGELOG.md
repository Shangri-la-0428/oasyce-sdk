# Changelog

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
